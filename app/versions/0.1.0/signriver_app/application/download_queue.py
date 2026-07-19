"""Threaded download queue coordinating controls, persistence and events."""

from __future__ import annotations

import threading
import logging
import hashlib
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from ..domain import DownloadSnapshot, DownloadSpec, DownloadState
from ..infrastructure.downloads import DownloadControl, DownloadManager


LOGGER = logging.getLogger(__name__)


_RECONCILE_ACTIVE_STATES = frozenset({
    DownloadState.QUEUED,
    DownloadState.DOWNLOADING,
    DownloadState.PAUSING,
    DownloadState.RETRYING,
    DownloadState.VERIFYING,
})

_HashGeneration = tuple[str, int, int, int, int]


class DownloadQueue:
    def __init__(
        self,
        manager: DownloadManager,
        *,
        repository=None,
        max_concurrent: int = 1,
        on_change: Callable[[DownloadSnapshot], None] | None = None,
        verifier_for: Callable[
            [DownloadSpec], Callable[[Path, str], object] | None
        ] | None = None,
    ) -> None:
        if max_concurrent != 1:
            raise ValueError("downloads are intentionally single-threaded")
        self.manager = manager
        self.repository = repository
        self.on_change = on_change or (lambda _snapshot: None)
        self.verifier_for = verifier_for or (lambda _spec: None)
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="dlc-download")
        self._lock = threading.RLock()
        self._snapshots: dict[str, DownloadSnapshot] = {}
        self._controls: dict[str, DownloadControl] = {}
        self._futures: dict[str, Future] = {}
        # Catalog reconciliation can encounter large orphan packages which no
        # longer have a database task row.  Hashing those files on every
        # catalog refresh made a 10+ GiB cache look as if the UI had frozen.
        # This memo is deliberately process-local: installation still performs
        # its authoritative digest check before touching the game directory.
        self._cached_hash_memo: dict[_HashGeneration, str] = {}
        self._cached_hash_memo_lock = threading.Lock()
        self._cached_hash_inflight: dict[_HashGeneration, threading.Event] = {}
        # Every explicit invalidation advances this revision.  Hash owners
        # capture it before reading and refuse to publish a digest if cache
        # maintenance ran after their final filesystem stat but before the
        # memo write.  Without this small fence a deleted package could be
        # reintroduced into the memo by an already-running hash operation.
        self._cached_hash_revision = 0

    def restore(self) -> tuple[DownloadSnapshot, ...]:
        if self.repository is None:
            return ()
        restored = []
        active = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        for snapshot in self.repository.list_all():
            if snapshot.state in active:
                snapshot = snapshot.evolve(
                    state=DownloadState.PAUSED,
                    bytes_downloaded=0,
                    error="程序上次退出时任务未完成；请手动继续",
                    speed_bytes_per_second=None,
                    eta_seconds=None,
                )
                self.repository.save(snapshot)
            elif snapshot.state is DownloadState.READY and (
                snapshot.result_path is None or not snapshot.result_path.is_file()
            ):
                snapshot = snapshot.evolve(
                    state=DownloadState.FAILED,
                    bytes_downloaded=0,
                    result_path=None,
                    sha256=None,
                    error="下载缓存文件已丢失，请重新下载",
                    speed_bytes_per_second=None,
                    eta_seconds=None,
                )
                self.repository.save(snapshot)
            self._snapshots[snapshot.spec.task_id] = snapshot
            restored.append(snapshot)
        return tuple(restored)

    def reconcile_cached(
        self,
        specs,
        *,
        verifier_for: Callable[
            [DownloadSpec], Callable[[Path, str], object] | None
        ] | None = None,
    ) -> tuple[DownloadSnapshot, ...]:
        """Recover structurally valid packages that lost their task record."""
        packages = self.manager.cache_root / "packages"
        if not packages.is_dir():
            return ()
        verifier_factory = verifier_for or self.verifier_for
        recovered = []
        for spec in specs:
            if self._is_reconcile_ignored(spec.task_id):
                continue
            with self._lock:
                may_reconcile = self._may_reconcile_locked(spec.task_id)
            if not may_reconcile:
                continue
            snapshot = self._cached_snapshot(
                spec, verifier_factory(spec)
            )
            if snapshot is not None and self._record_reconciled(snapshot):
                recovered.append(snapshot)
        return tuple(recovered)

    def reconcile_quarantined(
        self,
        specs,
        *,
        verifier_for: Callable[
            [DownloadSpec], Callable[[Path, str], object] | None
        ] | None = None,
    ) -> tuple[DownloadSnapshot, ...]:
        """Recover files quarantined by an older or overly strict verifier.

        A file is restored only after the current cartridge verifier accepts
        its full structure.  Genuine bad packages remain isolated.
        """
        quarantine = self.manager.cache_root / "quarantine"
        if not quarantine.is_dir():
            return ()
        verifier_factory = verifier_for or self.verifier_for
        recovered = []
        for spec in specs:
            if self._is_reconcile_ignored(spec.task_id):
                continue
            with self._lock:
                may_reconcile = self._may_reconcile_locked(spec.task_id)
            if not may_reconcile:
                continue
            prefix = f"{spec.task_id}-"
            candidates = sorted(
                (
                    path for path in quarantine.iterdir()
                    if path.is_file()
                    and path.name.startswith(prefix)
                    and path.suffix.casefold() == ".bad"
                ),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            for candidate in candidates:
                with self._lock:
                    if not self._may_reconcile_locked(spec.task_id):
                        break
                try:
                    size = candidate.stat().st_size
                    if spec.expected_size is not None and size != spec.expected_size:
                        continue
                    digest = self._cached_file_sha256(candidate)
                    if (
                        spec.expected_sha256
                        and digest.casefold() != spec.expected_sha256.casefold()
                    ):
                        continue
                    verifier = verifier_factory(spec)
                    if verifier is not None:
                        verifier(candidate, digest)
                    target_dir = self.manager.cache_root / "packages" / digest
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / spec.filename
                    # Validate an existing content-addressed target before
                    # taking the queue lock.  The second call below is normally
                    # a memo hit, but catches a replacement between validation
                    # and commit without holding the queue lock during a large
                    # file read.
                    if (
                        target.is_file()
                        and self._cached_file_sha256(target) != digest
                    ):
                        continue
                    with self._lock:
                        if not self._may_reconcile_locked(spec.task_id):
                            break
                        if target.is_file():
                            if self._cached_file_sha256(target) != digest:
                                continue
                            candidate.unlink()
                            self._drop_cached_hash(candidate)
                        elif target.exists():
                            continue
                        else:
                            candidate.replace(target)
                            self._move_cached_hash(candidate, target, digest)
                        snapshot = DownloadSnapshot(
                            spec=spec,
                            state=DownloadState.READY,
                            bytes_downloaded=size,
                            total_bytes=spec.expected_size or size,
                            result_path=target,
                            sha256=digest,
                        )
                        if not self._record_reconciled_locked(snapshot):
                            # The queue lock prevents a task transition between
                            # the preceding CAS and this commit.  Keep this
                            # fail-closed branch for future callers that may
                            # change the admission rules.
                            break
                    recovered.append(snapshot)
                    break
                except Exception:
                    LOGGER.exception(
                        "Quarantined package is still invalid: %s", candidate
                    )
        return tuple(recovered)

    def enqueue(self, spec: DownloadSpec) -> Future:
        with self._lock:
            current = self._futures.get(spec.task_id)
            if current is not None and not current.done():
                raise ValueError(f"download task is already active: {spec.task_id}")
            # Capture the verifier when the task is submitted.  A queued task
            # must keep using the cartridge that created it even if the shell
            # changes its current selection before this worker slot opens.
            verifier = self.verifier_for(spec)
            # An explicit download request supersedes a previous "clear task
            # history" choice, so this task may be recorded and recovered
            # normally again.
            self._clear_reconcile_ignored(spec.task_id)
            control = DownloadControl()
            self._controls[spec.task_id] = control
            queued = DownloadSnapshot(spec=spec)
            self._record(queued)
            future = self._executor.submit(self._run, spec, control, verifier)
            self._futures[spec.task_id] = future
            return future

    def resume(self, task_id: str) -> Future:
        with self._lock:
            snapshot = self._require(task_id)
            if snapshot.state not in {DownloadState.PAUSED, DownloadState.FAILED}:
                raise ValueError(f"task cannot be resumed from {snapshot.state}")
            return self.enqueue(snapshot.spec)

    def pause(self, task_id: str) -> None:
        with self._lock:
            snapshot = self._require(task_id)
            if snapshot.state in {DownloadState.PAUSED, DownloadState.PAUSING}:
                return
            if snapshot.state in {
                DownloadState.READY, DownloadState.CANCELLED,
                DownloadState.FAILED, DownloadState.CORRUPT,
            }:
                return
            control = self._controls.get(task_id)
            if control is None:
                raise ValueError("download task is not active")
            control.pause()
            self._record(snapshot.evolve(
                state=DownloadState.PAUSING,
                error=None,
                speed_bytes_per_second=None,
                eta_seconds=None,
            ))

    def pause_many(self, task_ids) -> int:
        paused = 0
        for task_id in task_ids:
            try:
                before = self._require(task_id)
                self.pause(task_id)
                if before.state in {
                    DownloadState.QUEUED, DownloadState.DOWNLOADING,
                    DownloadState.RETRYING, DownloadState.VERIFYING,
                }:
                    paused += 1
            except (KeyError, ValueError):
                # A task may finish between the UI snapshot and this request.
                # Finishing is a valid batch-pause outcome, not a user error.
                continue
        return paused

    def cancel(self, task_id: str) -> None:
        with self._lock:
            snapshot = self._require(task_id)
            control = self._controls.get(task_id)
            if control is not None:
                control.cancel()
            elif snapshot.state is DownloadState.PAUSED:
                self._record(snapshot.evolve(state=DownloadState.CANCELLED, error=None))
            else:
                raise ValueError("download task is not cancellable")

    def cancel_many(self, task_ids) -> int:
        cancelled = 0
        for task_id in task_ids:
            try:
                before = self._require(task_id)
                self.cancel(task_id)
                if before.state in {
                    DownloadState.QUEUED, DownloadState.DOWNLOADING,
                    DownloadState.PAUSING, DownloadState.PAUSED,
                    DownloadState.RETRYING, DownloadState.VERIFYING,
                }:
                    cancelled += 1
            except (KeyError, ValueError):
                continue
        return cancelled

    def snapshots(self) -> tuple[DownloadSnapshot, ...]:
        with self._lock:
            return tuple(self._snapshots.values())

    def is_active(self, task_id: str) -> bool:
        with self._lock:
            future = self._futures.get(task_id)
            return future is not None and not future.done()

    def clear_terminal(self) -> int:
        terminal = {
            DownloadState.CANCELLED, DownloadState.FAILED, DownloadState.CORRUPT,
        }
        with self._lock:
            removable = [
                task_id for task_id, snapshot in self._snapshots.items()
                if snapshot.state in terminal
            ]
            self._mark_reconcile_ignored(removable)
            if self.repository is not None:
                self.repository.delete_terminal()
            for task_id in removable:
                self._snapshots.pop(task_id, None)
                self._futures.pop(task_id, None)
                self._controls.pop(task_id, None)
            return len(removable)

    def clear_all(self) -> int:
        with self._lock:
            active = [
                task_id for task_id, future in self._futures.items()
                if not future.done()
            ]
            if active:
                raise ValueError("active download tasks must be cancelled or paused first")
            count = len(self._snapshots)
            self._mark_reconcile_ignored(self._snapshots)
            if self.repository is not None:
                self.repository.delete_all()
            self._snapshots.clear()
            self._futures.clear()
            self._controls.clear()
            return count

    def forget(
        self,
        task_ids,
        *,
        delete_cached_packages: bool = False,
    ) -> tuple[str, ...]:
        """Drop task snapshots so subsequent ``enqueue`` starts from scratch.

        This is intended for repair-style flows that intentionally want to
        re-download everything.  Actively running tasks are refused because
        their worker still holds file handles for the cached package.
        """
        with self._lock:
            for task_id in task_ids:
                future = self._futures.get(task_id)
                if future is not None and not future.done():
                    raise ValueError(
                        f"cannot forget an active download task: {task_id}"
                    )
            removed: list[str] = []
            for task_id in list(task_ids):
                snapshot = self._snapshots.pop(task_id, None)
                self._futures.pop(task_id, None)
                self._controls.pop(task_id, None)
                if self.repository is not None:
                    try:
                        self.repository.delete(task_id)
                    except Exception:
                        LOGGER.exception(
                            "Unable to delete download task record: %s", task_id
                        )
                if delete_cached_packages and snapshot is not None:
                    path = snapshot.result_path
                    if path is not None and path.is_file():
                        try:
                            path.unlink()
                            self._drop_cached_hash(path)
                            parent = path.parent
                            if parent.is_dir() and not any(parent.iterdir()):
                                parent.rmdir()
                        except OSError:
                            LOGGER.exception(
                                "Unable to delete cached package for %s", task_id
                            )
                if snapshot is not None:
                    removed.append(task_id)
            return tuple(removed)

    def invalidate_cached(self, task_id: str, *, reason: str) -> Path | None:
        """Quarantine one READY package and make its task retryable.

        This is used when the installer detects that a previously verified
        cache file was removed or changed by external software.  It never
        touches paths outside the content-addressed package directory.
        """
        with self._lock:
            snapshot = self._require(task_id)
            future = self._futures.get(task_id)
            if future is not None and not future.done():
                raise ValueError(f"cannot invalidate an active task: {task_id}")
            if snapshot.state is not DownloadState.READY:
                raise ValueError(f"task cache is not ready: {task_id}")
            cached_path = snapshot.result_path

        isolated = None
        if cached_path is not None and cached_path.exists():
            cache_root = Path(self.manager.cache_root).resolve(strict=False)
            packages = (cache_root / "packages").resolve(strict=False)
            resolved = cached_path.resolve(strict=True)
            try:
                resolved.relative_to(packages)
            except ValueError as error:
                raise ValueError("cached package escaped the package directory") from error
            quarantine = cache_root / "quarantine"
            quarantine.mkdir(parents=True, exist_ok=True)
            isolated = quarantine / f"{task_id}-{time.time_ns()}.bad"
            resolved.replace(isolated)
            self._drop_cached_hash(resolved)
            try:
                parent = resolved.parent
                if parent != packages and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass

        failed = snapshot.evolve(
            state=DownloadState.FAILED,
            bytes_downloaded=0,
            result_path=None,
            sha256=None,
            error=reason,
            speed_bytes_per_second=None,
            eta_seconds=None,
        )
        self._record(failed)
        return isolated

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            for control in self._controls.values():
                control.pause()
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run(
        self,
        spec: DownloadSpec,
        control: DownloadControl,
        verifier: Callable[[Path, str], object] | None,
    ) -> DownloadSnapshot:
        try:
            return self.manager.run(
                spec, control, self._record, verifier=verifier
            )
        except Exception as error:
            LOGGER.exception("Download worker crashed: task=%s", spec.task_id)
            with self._lock:
                current = self._snapshots.get(spec.task_id, DownloadSnapshot(spec=spec))
            failed = current.evolve(
                state=DownloadState.FAILED,
                error=str(error) or error.__class__.__name__,
                speed_bytes_per_second=None,
                eta_seconds=None,
            )
            self._record(failed)
            return failed
        finally:
            with self._lock:
                if self._controls.get(spec.task_id) is control:
                    self._controls.pop(spec.task_id, None)

    def _record(self, snapshot: DownloadSnapshot) -> None:
        repository = None
        with self._lock:
            previous = self._snapshots.get(snapshot.spec.task_id)
            self._snapshots[snapshot.spec.task_id] = snapshot
            if self.repository is not None and (
                previous is None or previous.state != snapshot.state
            ):
                repository = self.repository
        # Progress events can arrive for every downloaded chunk.  Persisting
        # each one both adds needless SQLite churn (partial files are not
        # resumable) and used to keep the queue lock held during disk I/O.
        # State transitions remain restart-safe, while in-memory observers
        # still receive every progress snapshot below.
        if repository is not None:
            repository.save(snapshot)
        try:
            self.on_change(snapshot)
        except Exception:
            # Observers (especially GUI adapters) must never be able to abort
            # the underlying download worker.
            LOGGER.exception("Download snapshot observer failed")

    def _may_reconcile_locked(self, task_id: str) -> bool:
        """Return whether cache discovery may claim ``task_id`` right now.

        Callers must hold ``self._lock``.  A future is authoritative even if a
        delayed state callback has not yet published its active state, while
        the state check fails closed for restored or adapter-provided queues
        that do not have an in-process future.
        """
        future = self._futures.get(task_id)
        if future is not None and not future.done():
            return False
        current = self._snapshots.get(task_id)
        if current is None:
            return True
        if current.state in _RECONCILE_ACTIVE_STATES:
            return False
        if (
            current.state is DownloadState.READY
            and current.result_path is not None
            and current.result_path.is_file()
        ):
            return False
        return True

    def _may_reconcile(self, task_id: str) -> bool:
        with self._lock:
            return self._may_reconcile_locked(task_id)

    def _record_reconciled(self, snapshot: DownloadSnapshot) -> bool:
        with self._lock:
            return self._record_reconciled_locked(snapshot)

    def _record_reconciled_locked(self, snapshot: DownloadSnapshot) -> bool:
        """CAS a discovered READY package without overtaking a live task.

        The repository write and observer notification intentionally remain
        inside the queue's re-entrant lock for this rare recovery path.  That
        preserves READY-before-QUEUED ordering if the user starts a download
        at the exact reconciliation boundary.  Normal progress writes still
        use ``_record`` and keep disk I/O outside the lock.
        """
        if not self._may_reconcile_locked(snapshot.spec.task_id):
            return False
        if self.repository is not None:
            self.repository.save(snapshot)
        self._snapshots[snapshot.spec.task_id] = snapshot
        try:
            self.on_change(snapshot)
        except Exception:
            LOGGER.exception("Download snapshot observer failed")
        return True

    def _require(self, task_id: str) -> DownloadSnapshot:
        try:
            return self._snapshots[task_id]
        except KeyError as error:
            raise KeyError(f"unknown download task: {task_id}") from error

    def _reconcile_marker_root(self) -> Path | None:
        cache_root = getattr(self.manager, "cache_root", None)
        if cache_root is None:
            return None
        return Path(cache_root) / "ignored-task-records"

    def _reconcile_marker(self, task_id: str) -> Path | None:
        root = self._reconcile_marker_root()
        if root is None:
            return None
        name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".ignored"
        return root / name

    def _mark_reconcile_ignored(self, task_ids) -> None:
        root = self._reconcile_marker_root()
        task_ids = tuple(task_ids)
        if root is None or not task_ids:
            return
        root.mkdir(parents=True, exist_ok=True)
        for task_id in task_ids:
            marker = self._reconcile_marker(task_id)
            assert marker is not None
            marker.write_text(task_id, encoding="utf-8")

    def _is_reconcile_ignored(self, task_id: str) -> bool:
        marker = self._reconcile_marker(task_id)
        return marker is not None and marker.is_file()

    def _clear_reconcile_ignored(self, task_id: str) -> None:
        marker = self._reconcile_marker(task_id)
        if marker is not None:
            marker.unlink(missing_ok=True)

    def _cached_snapshot(
        self,
        spec: DownloadSpec,
        verifier: Callable[[Path, str], object] | None,
    ) -> DownloadSnapshot | None:
        cache_root = getattr(self.manager, "cache_root", None)
        if cache_root is None:
            return None
        packages = Path(cache_root) / "packages"
        if not packages.is_dir():
            return None
        for candidate in packages.glob(f"*/{spec.filename}"):
            if not self._may_reconcile(spec.task_id):
                return None
            if not candidate.is_file():
                continue
            try:
                initial_stat = candidate.stat()
                if (
                    spec.expected_size is not None
                    and initial_stat.st_size != spec.expected_size
                ):
                    continue
                digest = self._cached_file_sha256(candidate)
                if candidate.parent.name.casefold() != digest.casefold():
                    continue
                if (
                    spec.expected_sha256
                    and digest.casefold() != spec.expected_sha256.casefold()
                ):
                    continue
                if verifier is not None:
                    verifier(candidate, digest)
                final_stat = candidate.stat()
                if not self._same_hash_generation(initial_stat, final_stat):
                    raise OSError("cached package changed while it was inspected")
                size = final_stat.st_size
            except Exception:
                LOGGER.exception("Ignoring invalid cached package: %s", candidate)
                continue
            return DownloadSnapshot(
                spec=spec,
                state=DownloadState.READY,
                bytes_downloaded=size,
                total_bytes=spec.expected_size or size,
                result_path=candidate,
                sha256=digest,
            )
        return None

    def _cached_file_sha256(self, path: Path) -> str:
        """Hash a cache candidate once per stable filesystem generation.

        The metadata is checked both before and after reading.  If another
        process changes the file while hashing, that digest is never memoized
        or accepted.  The key intentionally includes the resolved path, size
        and nanosecond mtime so normal replacement/truncation invalidates it.
        """
        resolved = path.resolve(strict=True)
        changed_attempts = 0
        while changed_attempts < 2:
            before = resolved.stat()
            key = self._hash_generation(resolved, before)
            with self._cached_hash_memo_lock:
                cached = self._cached_hash_memo.get(key)
                inflight = self._cached_hash_inflight.get(key)
                if cached is not None:
                    return cached
                if inflight is None:
                    inflight = threading.Event()
                    self._cached_hash_inflight[key] = inflight
                    owns_hash = True
                    hash_revision = self._cached_hash_revision
                else:
                    owns_hash = False
            if not owns_hash:
                inflight.wait()
                # The owner may have observed a concurrent file change or an
                # I/O error.  Re-stat instead of trusting its generation.
                continue

            try:
                digest = self._file_sha256(resolved)
                after = resolved.stat()
                if not self._same_hash_generation(before, after):
                    changed_attempts += 1
                    continue

                with self._cached_hash_memo_lock:
                    if hash_revision != self._cached_hash_revision:
                        changed_attempts += 1
                        continue
                    # Drop older generations of the same path.  Besides
                    # bounding memory, this makes invalidation explicit.
                    for existing in tuple(self._cached_hash_memo):
                        if existing[0] == key[0] and existing != key:
                            self._cached_hash_memo.pop(existing, None)
                    self._cached_hash_memo[key] = digest
                    if len(self._cached_hash_memo) > 1024:
                        oldest = next(iter(self._cached_hash_memo))
                        self._cached_hash_memo.pop(oldest, None)
                return digest
            finally:
                with self._cached_hash_memo_lock:
                    completed = self._cached_hash_inflight.pop(key, None)
                    if completed is not None:
                        completed.set()
        raise OSError("cached package changed while it was being hashed")

    def _drop_cached_hash(self, path: Path) -> None:
        resolved = self._normalized_hash_path(path)
        with self._cached_hash_memo_lock:
            self._cached_hash_revision += 1
            for key in tuple(self._cached_hash_memo):
                if key[0] == resolved:
                    self._cached_hash_memo.pop(key, None)

    def _move_cached_hash(self, source: Path, target: Path, digest: str) -> None:
        self._drop_cached_hash(source)
        with self._cached_hash_memo_lock:
            try:
                stat = target.stat()
            except OSError:
                return
            key = self._hash_generation(target, stat)
            self._cached_hash_memo[key] = digest

    def invalidate_hashes(self, paths) -> None:
        """Forget memoized hashes for files or directory trees after mutation.

        Cache-maintenance callers should invoke this after deleting or moving
        the supplied paths.  Descendant entries are removed as well, allowing
        a cleanup plan to invalidate a whole content-addressed package folder
        without knowing which files were memoized.
        """
        roots = tuple(
            self._normalized_hash_path(Path(path)) for path in paths
        )
        if not roots:
            return
        with self._cached_hash_memo_lock:
            self._cached_hash_revision += 1
            for key in tuple(self._cached_hash_memo):
                if any(self._normalized_path_is_within(key[0], root) for root in roots):
                    self._cached_hash_memo.pop(key, None)

    @staticmethod
    def _normalized_hash_path(path: Path) -> str:
        resolved = str(Path(path).resolve(strict=False))
        return os.path.normcase(resolved) if os.name == "nt" else resolved

    @classmethod
    def _hash_generation(cls, path: Path, details) -> _HashGeneration:
        return (
            cls._normalized_hash_path(path),
            int(details.st_size),
            int(details.st_mtime_ns),
            int(getattr(details, "st_ctime_ns", 0)),
            int(getattr(details, "st_ino", 0)),
        )

    @staticmethod
    def _same_hash_generation(before, after) -> bool:
        return (
            before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            and getattr(before, "st_ctime_ns", 0)
            == getattr(after, "st_ctime_ns", 0)
            and getattr(before, "st_ino", 0) == getattr(after, "st_ino", 0)
        )

    @staticmethod
    def _normalized_path_is_within(candidate: str, root: str) -> bool:
        try:
            return os.path.commonpath((candidate, root)) == root
        except ValueError:
            # Different Windows drives have no common path.
            return False

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
