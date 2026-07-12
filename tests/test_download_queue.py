from __future__ import annotations

import hashlib
import io
from pathlib import Path

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
