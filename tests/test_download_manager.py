from __future__ import annotations

import hashlib
import io
from pathlib import Path

from signriver_app.domain import DownloadSpec, DownloadState
from signriver_app.infrastructure.downloads import DownloadControl, DownloadManager, DownloadPolicy


DATA = b"stellaris-package" * 1000


def spec(**changes) -> DownloadSpec:
    values = dict(
        task_id="stellaris-dlc001",
        url="https://www.gitlink.org.cn/file.zip",
        filename="dlc001.zip",
        expected_size=len(DATA),
        expected_sha256=hashlib.sha256(DATA).hexdigest(),
    )
    values.update(changes)
    return DownloadSpec(**values)


def test_download_verifies_and_moves_to_content_addressed_cache(tmp_path: Path) -> None:
    states = []
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))
    result = manager.run(spec(), on_change=lambda item: states.append(item.state))
    assert result.state is DownloadState.READY
    assert result.result_path is not None and result.result_path.read_bytes() == DATA
    assert result.result_path.parent.name == hashlib.sha256(DATA).hexdigest()
    assert DownloadState.DOWNLOADING in states
    assert DownloadState.VERIFYING in states


def test_download_reports_speed_and_eta(tmp_path: Path) -> None:
    ticks = iter((0.0, 2.0))
    events = []
    manager = DownloadManager(
        tmp_path,
        policy=DownloadPolicy(chunk_size=len(DATA)),
        opener=lambda *_args: io.BytesIO(DATA),
        clock=lambda: next(ticks),
    )
    manager.run(spec(), on_change=events.append)
    progress = next(item for item in events if item.speed_bytes_per_second)
    assert progress.speed_bytes_per_second == len(DATA) / 2
    assert progress.eta_seconds == 0


def test_download_policy_applies_bandwidth_limit(tmp_path: Path) -> None:
    delays = []
    manager = DownloadManager(
        tmp_path,
        policy=DownloadPolicy(
            chunk_size=len(DATA), max_bytes_per_second=len(DATA) // 2
        ),
        opener=lambda *_args: io.BytesIO(DATA),
        clock=lambda: 0.0,
        sleep=delays.append,
    )
    result = manager.run(spec())
    assert result.state is DownloadState.READY
    assert delays == [2.0]


def test_hash_mismatch_is_quarantined(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))
    result = manager.run(spec(expected_sha256="0" * 64))
    assert result.state is DownloadState.CORRUPT
    assert "SHA-256" in (result.error or "")
    assert len(list((tmp_path / "quarantine").glob("*.bad"))) == 1
    assert not list((tmp_path / "packages").rglob("*.zip"))


def test_network_failure_retries_then_succeeds(tmp_path: Path) -> None:
    attempts = 0
    states = []

    def flaky(*_args):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("connection reset")
        return io.BytesIO(DATA)

    manager = DownloadManager(tmp_path, policy=DownloadPolicy(attempts=3, retry_delay=0), opener=flaky)
    result = manager.run(spec(), on_change=lambda item: states.append(item.state))
    assert result.state is DownloadState.READY
    assert attempts == 3
    assert states.count(DownloadState.RETRYING) == 2


def test_pre_requested_pause_does_not_open_network(tmp_path: Path) -> None:
    control = DownloadControl()
    control.pause()
    manager = DownloadManager(tmp_path, opener=lambda *_args: (_ for _ in ()).throw(AssertionError()))
    result = manager.run(spec(), control)
    assert result.state is DownloadState.PAUSED


def test_cancel_removes_partial_file(tmp_path: Path) -> None:
    control = DownloadControl()
    control.cancel()
    partial = tmp_path / "downloads" / "stellaris-dlc001.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"old")
    result = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA)).run(spec(), control)
    assert result.state is DownloadState.CANCELLED
    assert not partial.exists()


def test_package_verifier_failure_is_quarantined(tmp_path: Path) -> None:
    def reject(_path: Path) -> None:
        raise ValueError("unsafe package")

    result = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA)).run(spec(), verifier=reject)
    assert result.state is DownloadState.CORRUPT
    assert result.error == "unsafe package"


def test_rejects_unsafe_url_and_filename(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))
    for invalid in (spec(url="http://example.test/a"), spec(filename="../bad.zip")):
        try:
            manager.run(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe spec was accepted")
