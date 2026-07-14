"""Threaded download queue coordinating controls, persistence and events."""

from __future__ import annotations

import threading
import logging
import hashlib
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from ..domain import DownloadSnapshot, DownloadSpec, DownloadState
from ..infrastructure.downloads import DownloadControl, DownloadManager


LOGGER = logging.getLogger(__name__)


class DownloadQueue:
    def __init__(
        self,
        manager: DownloadManager,
        *,
        repository=None,
        max_concurrent: int = 1,
        on_change: Callable[[DownloadSnapshot], None] | None = None,
        verifier_for: Callable[[DownloadSpec], Callable[[Path], object] | None] | None = None,
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

    def reconcile_cached(self, specs) -> tuple[DownloadSnapshot, ...]:
        """Recover structurally valid packages that lost their task record."""
        packages = self.manager.cache_root / "packages"
        if not packages.is_dir():
            return ()
        recovered = []
        for spec in specs:
            with self._lock:
                current = self._snapshots.get(spec.task_id)
            if (
                current is not None
                and current.state is DownloadState.READY
                and current.result_path is not None
                and current.result_path.is_file()
            ):
                continue
            for candidate in packages.glob(f"*/{spec.filename}"):
                if not candidate.is_file():
                    continue
                digest = self._file_sha256(candidate)
                if candidate.parent.name.casefold() != digest.casefold():
                    continue
                if spec.expected_sha256 and digest.casefold() != spec.expected_sha256.casefold():
                    continue
                try:
                    verifier = self.verifier_for(spec)
                    if verifier is not None:
                        verifier(candidate)
                except Exception:
                    LOGGER.exception("Ignoring invalid cached package: %s", candidate)
                    continue
                size = candidate.stat().st_size
                snapshot = DownloadSnapshot(
                    spec=spec,
                    state=DownloadState.READY,
                    bytes_downloaded=size,
                    total_bytes=spec.expected_size or size,
                    result_path=candidate,
                    sha256=digest,
                )
                self._record(snapshot)
                recovered.append(snapshot)
                break
        return tuple(recovered)

    def enqueue(self, spec: DownloadSpec) -> Future:
        with self._lock:
            current = self._futures.get(spec.task_id)
            if current is not None and not current.done():
                raise ValueError(f"download task is already active: {spec.task_id}")
            control = DownloadControl()
            self._controls[spec.task_id] = control
            queued = DownloadSnapshot(spec=spec)
            self._record(queued)
            future = self._executor.submit(self._run, spec, control)
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

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            for control in self._controls.values():
                control.pause()
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run(self, spec: DownloadSpec, control: DownloadControl) -> DownloadSnapshot:
        try:
            return self.manager.run(
                spec, control, self._record, verifier=self.verifier_for(spec)
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
        with self._lock:
            self._snapshots[snapshot.spec.task_id] = snapshot
            if self.repository is not None:
                self.repository.save(snapshot)
        try:
            self.on_change(snapshot)
        except Exception:
            # Observers (especially GUI adapters) must never be able to abort
            # the underlying download worker.
            LOGGER.exception("Download snapshot observer failed")

    def _require(self, task_id: str) -> DownloadSnapshot:
        try:
            return self._snapshots[task_id]
        except KeyError as error:
            raise KeyError(f"unknown download task: {task_id}") from error

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
