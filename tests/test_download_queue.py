from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from signriver_app.application import DownloadQueue
from signriver_app.domain import DownloadSnapshot, DownloadSpec, DownloadState
from signriver_app.infrastructure.downloads import DownloadManager, DownloadPolicy
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
        verifier_for=lambda _spec: lambda path: path.stat(),
    )

    recovered = queue.reconcile_cached((make_spec(),))
    queue.shutdown()

    assert recovered[0].state is DownloadState.READY
    assert recovered[0].result_path == package
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
