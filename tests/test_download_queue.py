from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import threading

import pytest

from signriver_app.application import DownloadQueue
from signriver_app.domain import DownloadSnapshot, DownloadSpec, DownloadState
from signriver_app.infrastructure.downloads import DownloadManager
from signriver_app.infrastructure.persistence import Database, DownloadTaskRepository


DATA = b"queue-data" * 100


def make_spec(task_id: str = "queue-1") -> DownloadSpec:
    return DownloadSpec(
        task_id, "https://example.test/dlc.zip", "dlc.zip",
        len(DATA), hashlib.sha256(DATA).hexdigest(),
    )


def test_queue_is_intentionally_single_threaded(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))
    with pytest.raises(ValueError, match="single-threaded"):
        DownloadQueue(manager, max_concurrent=2)


def test_queue_runs_and_persists_task(tmp_path: Path) -> None:
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    manager = DownloadManager(tmp_path / "cache", opener=lambda *_args: io.BytesIO(DATA))
    events = []
    queue = DownloadQueue(manager, repository=repository, on_change=events.append)
    result = queue.enqueue(make_spec()).result(timeout=5)
    queue.shutdown()
    assert result.state is DownloadState.READY
    assert repository.list_all()[0].state is DownloadState.READY
    assert events[-1].state is DownloadState.READY


def test_progress_snapshots_notify_every_time_but_persist_only_state_changes() -> None:
    class RecordingRepository:
        def __init__(self) -> None:
            self.saved = []

        def save(self, snapshot) -> None:
            self.saved.append(snapshot)

    repository = RecordingRepository()
    events = []
    queue = DownloadQueue(
        object(), repository=repository, on_change=events.append
    )
    spec = make_spec()

    queue._record(DownloadSnapshot(spec, DownloadState.QUEUED))
    for index in range(1, 1_001):
        queue._record(DownloadSnapshot(
            spec,
            DownloadState.DOWNLOADING,
            bytes_downloaded=index,
            total_bytes=1_000,
        ))
    queue._record(DownloadSnapshot(
        spec,
        DownloadState.VERIFYING,
        bytes_downloaded=1_000,
        total_bytes=1_000,
    ))
    ready = DownloadSnapshot(
        spec,
        DownloadState.READY,
        bytes_downloaded=1_000,
        total_bytes=1_000,
        result_path=Path("dlc.zip"),
        sha256="a" * 64,
    )
    queue._record(ready)
    queue.shutdown()

    assert len(events) == 1_003
    assert [item.state for item in repository.saved] == [
        DownloadState.QUEUED,
        DownloadState.DOWNLOADING,
        DownloadState.VERIFYING,
        DownloadState.READY,
    ]
    assert repository.saved[-1] is ready


def test_repository_save_runs_without_holding_the_queue_lock() -> None:
    queue_holder = {}
    lock_was_available = []

    class ProbingRepository:
        def save(self, _snapshot) -> None:
            completed = threading.Event()

            def read_queue() -> None:
                queue_holder["queue"].snapshots()
                completed.set()

            probe = threading.Thread(target=read_queue)
            probe.start()
            lock_was_available.append(completed.wait(1))
            probe.join(timeout=1)

    queue = DownloadQueue(object(), repository=ProbingRepository())
    queue_holder["queue"] = queue
    queue._record(DownloadSnapshot(make_spec(), DownloadState.QUEUED))
    queue.shutdown()

    assert lock_was_available == [True]


def test_restore_normalizes_interrupted_task_to_paused(tmp_path: Path) -> None:
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    repository.save(DownloadSnapshot(make_spec(), DownloadState.DOWNLOADING, 20, len(DATA), 1))
    queue = DownloadQueue(
        DownloadManager(tmp_path / "cache", opener=lambda *_args: io.BytesIO(DATA)),
        repository=repository,
    )
    restored = queue.restore()
    queue.shutdown()
    assert restored[0].state is DownloadState.PAUSED
    assert "手动继续" in (restored[0].error or "")
    assert repository.list_all()[0].state is DownloadState.PAUSED


def test_restore_keeps_ready_task_when_cached_package_exists(tmp_path: Path) -> None:
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    package = tmp_path / "cache" / "packages" / ("a" * 64) / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    ready = DownloadSnapshot(
        make_spec(), DownloadState.READY, len(DATA), len(DATA), 1,
        result_path=package, sha256=hashlib.sha256(DATA).hexdigest(),
    )
    repository.save(ready)
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"), repository=repository)

    restored = queue.restore()
    queue.shutdown()

    assert restored[0].state is DownloadState.READY
    assert restored[0].result_path == package


def test_restore_marks_ready_task_failed_when_cache_is_missing(tmp_path: Path) -> None:
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    missing = tmp_path / "cache" / "packages" / ("a" * 64) / "dlc.zip"
    repository.save(DownloadSnapshot(
        make_spec(), DownloadState.READY, len(DATA), len(DATA), 1,
        result_path=missing, sha256=hashlib.sha256(DATA).hexdigest(),
    ))
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"), repository=repository)

    restored = queue.restore()
    queue.shutdown()

    assert restored[0].state is DownloadState.FAILED
    assert "缓存文件已丢失" in (restored[0].error or "")


def test_reconcile_cached_recovers_orphan_package(tmp_path: Path) -> None:
    digest = hashlib.sha256(DATA).hexdigest()
    package = tmp_path / "cache" / "packages" / digest / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    queue = DownloadQueue(
        DownloadManager(tmp_path / "cache"),
        repository=repository,
        verifier_for=lambda _spec: lambda path, _sha256: path.stat(),
    )

    recovered = queue.reconcile_cached((make_spec(),))
    queue.shutdown()

    assert recovered[0].state is DownloadState.READY
    assert recovered[0].result_path == package
    assert repository.list_all()[0].state is DownloadState.READY


def test_reconcile_cached_memoizes_stable_orphan_package_hash(
    tmp_path: Path, monkeypatch,
) -> None:
    digest = hashlib.sha256(DATA).hexdigest()
    package = tmp_path / "cache" / "packages" / digest / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    queue = DownloadQueue(
        DownloadManager(tmp_path / "cache"),
        verifier_for=lambda _spec: lambda path, _sha256: path.stat(),
    )
    original = queue._file_sha256
    hashed = []

    def counted(path: Path) -> str:
        hashed.append(path)
        return original(path)

    monkeypatch.setattr(queue, "_file_sha256", counted)
    assert queue.reconcile_cached((make_spec(),))
    queue.forget(("queue-1",))
    assert queue.reconcile_cached((make_spec(),))
    queue.shutdown()

    assert hashed == [package]


def test_reconcile_cached_hash_memo_invalidates_when_file_changes(
    tmp_path: Path, monkeypatch,
) -> None:
    digest = hashlib.sha256(DATA).hexdigest()
    package = tmp_path / "cache" / "packages" / digest / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"))
    original = queue._file_sha256
    hashed = []

    def counted(path: Path) -> str:
        hashed.append(path)
        return original(path)

    monkeypatch.setattr(queue, "_file_sha256", counted)
    assert queue.reconcile_cached((make_spec(),))
    queue.forget(("queue-1",))

    previous = package.stat()
    changed = b"changed---" * 100
    assert len(changed) == len(DATA)
    package.write_bytes(changed)
    os.utime(package, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))

    assert queue.reconcile_cached((make_spec(),)) == ()
    queue.shutdown()
    assert hashed == [package, package]


def test_concurrent_cache_hash_requests_share_one_inflight_read(
    tmp_path: Path, monkeypatch,
) -> None:
    package = tmp_path / "large.zip"
    package.write_bytes(DATA)
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"))
    original = queue._file_sha256
    hashing_started = threading.Event()
    release_hash = threading.Event()
    start_together = threading.Barrier(3)
    hashed = []
    results = []

    def slow_hash(path: Path) -> str:
        hashed.append(path)
        hashing_started.set()
        assert release_hash.wait(5)
        return original(path)

    def read_hash() -> None:
        start_together.wait()
        results.append(queue._cached_file_sha256(package))

    monkeypatch.setattr(queue, "_file_sha256", slow_hash)
    readers = [threading.Thread(target=read_hash) for _ in range(2)]
    for reader in readers:
        reader.start()
    start_together.wait()
    assert hashing_started.wait(5)
    release_hash.set()
    for reader in readers:
        reader.join(timeout=5)
        assert not reader.is_alive()
    queue.shutdown()

    assert results == [hashlib.sha256(DATA).hexdigest()] * 2
    assert hashed == [package]


def test_hash_owner_failure_wakes_waiter_for_a_fresh_attempt(
    tmp_path: Path, monkeypatch,
) -> None:
    package = tmp_path / "large.zip"
    package.write_bytes(DATA)
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"))
    original = queue._file_sha256
    first_started = threading.Event()
    release_first = threading.Event()
    call_lock = threading.Lock()
    call_count = 0
    results = []
    errors = []

    def flaky_hash(path: Path) -> str:
        nonlocal call_count
        with call_lock:
            call_count += 1
            call = call_count
        if call == 1:
            first_started.set()
            assert release_first.wait(5)
            raise OSError("simulated read failure")
        return original(path)

    def read_hash() -> None:
        try:
            results.append(queue._cached_file_sha256(package))
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(queue, "_file_sha256", flaky_hash)
    owner = threading.Thread(target=read_hash)
    owner.start()
    assert first_started.wait(5)
    waiter = threading.Thread(target=read_hash)
    waiter.start()
    release_first.set()
    for reader in (owner, waiter):
        reader.join(timeout=5)
        assert not reader.is_alive()
    queue.shutdown()

    assert results == [hashlib.sha256(DATA).hexdigest()]
    assert len(errors) == 1
    assert isinstance(errors[0], OSError)
    assert call_count == 2
    assert queue._cached_hash_inflight == {}


def test_hash_memo_detects_atomic_replacement_with_same_size_and_mtime(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package.zip"
    package.write_bytes(DATA)
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"))
    original_digest = queue._cached_file_sha256(package)
    original_stat = package.stat()
    changed = b"changed---" * 100
    assert len(changed) == len(DATA)
    replacement = tmp_path / "replacement.zip"
    replacement.write_bytes(changed)
    os.utime(
        replacement,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    os.replace(replacement, package)

    changed_digest = queue._cached_file_sha256(package)
    queue.shutdown()

    assert package.stat().st_size == original_stat.st_size
    assert package.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert changed_digest == hashlib.sha256(changed).hexdigest()
    assert changed_digest != original_digest


def test_invalidate_hashes_forgets_descendant_package_memos(
    tmp_path: Path, monkeypatch,
) -> None:
    package_root = tmp_path / "cache" / "packages" / ("a" * 64)
    package = package_root / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"))
    original = queue._file_sha256
    hashed = []

    def counted(path: Path) -> str:
        hashed.append(path)
        return original(path)

    monkeypatch.setattr(queue, "_file_sha256", counted)
    queue._cached_file_sha256(package)
    queue.invalidate_hashes((package_root,))
    queue._cached_file_sha256(package)
    queue.shutdown()

    assert hashed == [package, package]


def test_invalidate_hashes_fences_an_inflight_memo_write(
    tmp_path: Path, monkeypatch,
) -> None:
    package = tmp_path / "cache" / "packages" / ("a" * 64) / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    queue = DownloadQueue(DownloadManager(tmp_path / "cache"))
    generation_checked = threading.Event()
    release_generation_check = threading.Event()
    original_same_generation = queue._same_hash_generation
    errors = []

    def blocked_same_generation(before, after) -> bool:
        generation_checked.set()
        assert release_generation_check.wait(5)
        return original_same_generation(before, after)

    def read_hash() -> None:
        try:
            queue._cached_file_sha256(package)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(queue, "_same_hash_generation", blocked_same_generation)
    reader = threading.Thread(target=read_hash)
    reader.start()
    assert generation_checked.wait(5)
    package.unlink()
    queue.invalidate_hashes((package,))
    release_generation_check.set()
    reader.join(timeout=5)
    queue.shutdown()

    assert not reader.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], OSError)
    assert queue._cached_hash_memo == {}
    assert queue._cached_hash_inflight == {}


@pytest.mark.parametrize("cache_kind", ("packages", "quarantine"))
def test_reconcile_cannot_overwrite_task_started_during_hash_validation(
    tmp_path: Path, monkeypatch, cache_kind: str,
) -> None:
    digest = hashlib.sha256(DATA).hexdigest()
    cache_root = tmp_path / "cache"
    if cache_kind == "packages":
        candidate = cache_root / "packages" / digest / "dlc.zip"
        reconcile_name = "reconcile_cached"
    else:
        candidate = cache_root / "quarantine" / "queue-1-old.bad"
        reconcile_name = "reconcile_quarantined"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(DATA)

    hash_started = threading.Event()
    release_hash = threading.Event()
    download_read_started = threading.Event()
    release_download = threading.Event()

    class BlockingReader(io.BytesIO):
        def read(self, *args, **kwargs):
            download_read_started.set()
            assert release_download.wait(5)
            return super().read(*args, **kwargs)

    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    queue = DownloadQueue(
        DownloadManager(
            cache_root,
            opener=lambda *_args: BlockingReader(DATA),
        ),
        repository=repository,
    )
    original_hash = queue._cached_file_sha256

    def blocked_hash(path: Path) -> str:
        hash_started.set()
        assert release_hash.wait(5)
        return original_hash(path)

    monkeypatch.setattr(queue, "_cached_file_sha256", blocked_hash)
    recovered = []
    reconcile_errors = []

    def reconcile() -> None:
        try:
            recovered.extend(getattr(queue, reconcile_name)((make_spec(),)))
        except Exception as error:
            reconcile_errors.append(error)

    reconcile_thread = threading.Thread(target=reconcile)
    reconcile_thread.start()
    future = None
    try:
        assert hash_started.wait(5)
        future = queue.enqueue(make_spec())
        assert download_read_started.wait(5)
        release_hash.set()
        reconcile_thread.join(timeout=5)
        assert not reconcile_thread.is_alive()

        assert reconcile_errors == []
        assert recovered == []
        assert queue.snapshots()[0].state is DownloadState.DOWNLOADING
        assert repository.list_all()[0].state is DownloadState.DOWNLOADING
        if cache_kind == "quarantine":
            assert candidate.is_file()
    finally:
        release_hash.set()
        release_download.set()
        reconcile_thread.join(timeout=5)
        if future is not None:
            future.result(timeout=5)
        queue.shutdown(wait=True)


def test_clear_all_keeps_cache_without_recreating_cleared_history(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    digest = hashlib.sha256(DATA).hexdigest()
    package = cache / "packages" / digest / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    queue = DownloadQueue(
        DownloadManager(cache),
        repository=repository,
        verifier_for=lambda _spec: lambda path, _sha256: path.stat(),
    )
    queue._record(DownloadSnapshot(
        make_spec(), DownloadState.READY, len(DATA), len(DATA), 1,
        result_path=package, sha256=digest,
    ))

    assert queue.clear_all() == 1
    queue.shutdown()

    restarted = DownloadQueue(
        DownloadManager(cache),
        repository=repository,
        verifier_for=lambda _spec: lambda path, _sha256: path.stat(),
    )
    assert restarted.restore() == ()
    assert restarted.reconcile_cached((make_spec(),)) == ()
    assert restarted.snapshots() == ()
    assert package.read_bytes() == DATA
    restarted.shutdown()


def test_explicit_enqueue_allows_a_cleared_task_to_be_recorded_again(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    manager = DownloadManager(cache, opener=lambda *_args: io.BytesIO(DATA))
    queue = DownloadQueue(manager)
    queue._record(DownloadSnapshot(make_spec(), DownloadState.READY))
    queue.clear_all()
    assert queue._is_reconcile_ignored("queue-1")

    result = queue.enqueue(make_spec()).result(timeout=5)

    assert result.state is DownloadState.READY
    assert not queue._is_reconcile_ignored("queue-1")
    queue.shutdown()


def test_reconcile_quarantined_recovers_file_accepted_by_current_verifier(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    quarantine = cache / "quarantine"
    quarantine.mkdir(parents=True)
    isolated = quarantine / "queue-1-123.bad"
    isolated.write_bytes(DATA)
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    corrupt = DownloadSnapshot(
        make_spec(), DownloadState.CORRUPT, len(DATA), len(DATA), 1,
        error="legacy verifier rejected temporary filename",
    )
    repository.save(corrupt)
    queue = DownloadQueue(
        DownloadManager(cache),
        repository=repository,
        verifier_for=lambda _spec: lambda path, _sha256: path.stat(),
    )
    queue.restore()

    recovered = queue.reconcile_quarantined((make_spec(),))
    queue.shutdown()

    digest = hashlib.sha256(DATA).hexdigest()
    expected = cache / "packages" / digest / "dlc.zip"
    assert recovered[0].state is DownloadState.READY
    assert recovered[0].result_path == expected
    assert expected.read_bytes() == DATA
    assert not isolated.exists()
    assert repository.list_all()[0].state is DownloadState.READY


def test_resume_restarts_paused_non_range_task(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))
    queue = DownloadQueue(manager)
    paused = DownloadSnapshot(make_spec(), DownloadState.PAUSED, 50, len(DATA), 1)
    queue._record(paused)
    result = queue.resume(paused.spec.task_id).result(timeout=5)
    queue.shutdown()
    assert result.state is DownloadState.READY
    assert result.bytes_downloaded == len(DATA)


def test_cancel_restored_paused_task_without_worker(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))
    queue = DownloadQueue(manager)
    paused = DownloadSnapshot(make_spec(), DownloadState.PAUSED, 50, len(DATA), 1)
    queue._record(paused)
    queue.cancel(paused.spec.task_id)
    assert queue.snapshots()[0].state is DownloadState.CANCELLED
    queue.shutdown()


def test_cancel_many_cancels_paused_and_active_tasks(tmp_path: Path) -> None:
    class BlockingManager:
        def run(self, spec, control, callback, verifier=None):
            callback(DownloadSnapshot(spec, DownloadState.DOWNLOADING))
            while not control.cancel_requested:
                control._cancel.wait(0.01)
            result = DownloadSnapshot(spec, DownloadState.CANCELLED)
            callback(result)
            return result

    queue = DownloadQueue(BlockingManager())
    active = queue.enqueue(make_spec("active"))
    paused = DownloadSnapshot(make_spec("paused"), DownloadState.PAUSED)
    queue._record(paused)

    assert queue.cancel_many(("active", "paused")) == 2
    assert active.result(timeout=5).state is DownloadState.CANCELLED
    assert all(item.state is DownloadState.CANCELLED for item in queue.snapshots())
    queue.shutdown()


def test_queue_rejects_duplicate_active_task(tmp_path: Path) -> None:
    class BlockingManager:
        def run(self, spec, control, callback, verifier=None):
            callback(DownloadSnapshot(spec, DownloadState.DOWNLOADING))
            while not control.pause_requested:
                control._pause.wait(0.01)
            result = DownloadSnapshot(spec, DownloadState.PAUSED)
            callback(result)
            return result

    queue = DownloadQueue(BlockingManager())
    future = queue.enqueue(make_spec())
    try:
        queue.enqueue(make_spec())
    except ValueError as error:
        assert "already active" in str(error)
    else:
        raise AssertionError("duplicate task was accepted")
    queue.pause("queue-1")
    assert future.result(timeout=5).state is DownloadState.PAUSED
    queue.shutdown()


def test_pause_many_handles_running_and_queued_tasks_without_errors(tmp_path: Path) -> None:
    class BlockingManager:
        def run(self, spec, control, callback, verifier=None):
            callback(DownloadSnapshot(spec, DownloadState.DOWNLOADING))
            while not control.pause_requested:
                control._pause.wait(0.01)
            result = DownloadSnapshot(spec, DownloadState.PAUSED)
            callback(result)
            return result

    queue = DownloadQueue(BlockingManager(), max_concurrent=1)
    first = queue.enqueue(make_spec("batch-1"))
    second = queue.enqueue(make_spec("batch-2"))

    assert queue.pause_many(("batch-1", "batch-2")) == 2
    assert first.result(timeout=5).state is DownloadState.PAUSED
    assert second.result(timeout=5).state is DownloadState.PAUSED
    assert all(item.state is DownloadState.PAUSED for item in queue.snapshots())
    queue.shutdown()


def test_observer_error_does_not_abort_download(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))

    def broken_observer(_snapshot) -> None:
        raise RuntimeError("UI is busy")

    queue = DownloadQueue(manager, on_change=broken_observer)
    result = queue.enqueue(make_spec()).result(timeout=5)
    queue.shutdown()

    assert result.state is DownloadState.READY


def test_queued_task_keeps_verifier_captured_at_submission(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    generation = {"value": "old-cartridge"}
    observed = []

    class BlockingManager:
        cache_root = tmp_path

        def run(self, spec, _control, callback, verifier=None):
            callback(DownloadSnapshot(spec, DownloadState.DOWNLOADING))
            if spec.task_id == "first":
                started.set()
                assert release.wait(5)
            assert verifier is not None
            verifier(tmp_path / spec.filename, "a" * 64)
            result = DownloadSnapshot(spec, DownloadState.READY, sha256="a" * 64)
            callback(result)
            return result

    def verifier_for(_spec):
        captured = generation["value"]
        return lambda _path, _digest: observed.append(captured)

    queue = DownloadQueue(BlockingManager(), verifier_for=verifier_for)
    first = queue.enqueue(make_spec("first"))
    assert started.wait(5)
    second = queue.enqueue(make_spec("second"))
    generation["value"] = "new-cartridge"
    release.set()

    assert first.result(timeout=5).state is DownloadState.READY
    assert second.result(timeout=5).state is DownloadState.READY
    queue.shutdown()
    assert observed == ["old-cartridge", "old-cartridge"]


def test_worker_crash_is_recorded_as_failed_instead_of_stale_queued(tmp_path: Path) -> None:
    class CrashingManager:
        def run(self, *_args, **_kwargs):
            raise RuntimeError("unexpected worker failure")

    queue = DownloadQueue(CrashingManager())
    result = queue.enqueue(make_spec()).result(timeout=5)
    queue.shutdown()

    assert result.state is DownloadState.FAILED
    assert result.error == "unexpected worker failure"
    assert queue.snapshots()[0].state is DownloadState.FAILED


def test_clear_all_removes_ready_and_paused_history() -> None:
    queue = DownloadQueue(object())
    queue._record(DownloadSnapshot(make_spec("ready"), DownloadState.READY))
    queue._record(DownloadSnapshot(make_spec("paused"), DownloadState.PAUSED))

    assert queue.clear_all() == 2
    assert queue.snapshots() == ()
    queue.shutdown()


def test_clear_all_rejects_active_download() -> None:
    class BlockingClearManager:
        def run(self, spec, control, callback, verifier=None):
            callback(DownloadSnapshot(spec, DownloadState.DOWNLOADING))
            while not control.cancel_requested:
                control._cancel.wait(0.01)
            result = DownloadSnapshot(spec, DownloadState.CANCELLED)
            callback(result)
            return result

    queue = DownloadQueue(BlockingClearManager())
    future = queue.enqueue(make_spec("active-clear"))
    with pytest.raises(ValueError, match="active download"):
        queue.clear_all()
    queue.cancel("active-clear")
    assert future.result(timeout=5).state is DownloadState.CANCELLED
    queue.shutdown()


def test_forget_drops_snapshot_and_optionally_removes_cached_package(tmp_path: Path) -> None:
    """The repair flow needs a clean slate before re-downloading assets."""
    digest = hashlib.sha256(DATA).hexdigest()
    package = tmp_path / "cache" / "packages" / digest / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(DATA)
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    queue = DownloadQueue(
        DownloadManager(tmp_path / "cache"),
        repository=repository,
    )
    ready = DownloadSnapshot(
        make_spec(), DownloadState.READY, len(DATA), len(DATA), 1,
        result_path=package, sha256=digest,
    )
    queue._record(ready)

    removed = queue.forget(("queue-1",), delete_cached_packages=True)
    queue.shutdown()

    assert removed == ("queue-1",)
    assert queue.snapshots() == ()
    assert repository.list_all() == ()
    assert not package.exists()
    assert not package.parent.exists()


def test_forget_refuses_active_tasks(tmp_path: Path) -> None:
    class BlockingManager:
        def run(self, spec, control, callback, verifier=None):
            callback(DownloadSnapshot(spec, DownloadState.DOWNLOADING))
            while not control.cancel_requested:
                control._cancel.wait(0.01)
            result = DownloadSnapshot(spec, DownloadState.CANCELLED)
            callback(result)
            return result

    queue = DownloadQueue(BlockingManager())
    future = queue.enqueue(make_spec("active-forget"))
    with pytest.raises(ValueError, match="active"):
        queue.forget(("active-forget",))
    queue.cancel("active-forget")
    assert future.result(timeout=5).state is DownloadState.CANCELLED
    queue.shutdown()


def test_invalidate_cached_quarantines_package_and_allows_redownload(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    digest = hashlib.sha256(DATA).hexdigest()
    package = cache / "packages" / digest / "dlc.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"externally changed")
    queue = DownloadQueue(
        DownloadManager(cache, opener=lambda *_args: io.BytesIO(DATA))
    )
    queue._record(DownloadSnapshot(
        make_spec(), DownloadState.READY,
        result_path=package, sha256=digest,
    ))

    isolated = queue.invalidate_cached("queue-1", reason="digest changed")
    result = queue.resume("queue-1").result(timeout=5)

    queue.shutdown()
    assert isolated is not None and isolated.is_file()
    assert isolated.parent == cache / "quarantine"
    assert result.state is DownloadState.READY
    assert result.result_path is not None
    assert result.result_path.read_bytes() == DATA
