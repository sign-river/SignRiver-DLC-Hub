from pathlib import Path

from signriver_app.domain import DownloadSnapshot, DownloadSpec, DownloadState
from signriver_app.infrastructure.persistence import Database, DownloadTaskRepository


def test_download_snapshot_round_trip_and_recovery(tmp_path: Path) -> None:
    repository = DownloadTaskRepository(Database(tmp_path / "hub.db"))
    spec = DownloadSpec("task-1", "https://example.test/a.zip", "a.zip", 12, "a" * 64)
    paused = DownloadSnapshot(spec, DownloadState.PAUSED, 5, 12, 2, sha256=None, error="offline")
    repository.save(paused)
    assert repository.list_all() == (paused,)
    assert repository.recoverable() == (paused,)

    ready = paused.evolve(state=DownloadState.READY, bytes_downloaded=12, result_path=tmp_path / "a.zip", sha256="a" * 64, error=None)
    repository.save(ready)
    assert repository.list_all() == (ready,)
    assert repository.recoverable() == ()
