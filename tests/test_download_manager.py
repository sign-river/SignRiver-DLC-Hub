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


def test_multipart_download_joins_release_parts_into_original_package(tmp_path: Path) -> None:
    chunks = {
        "https://www.gitlink.org.cn/part1": DATA[:5000],
        "https://www.gitlink.org.cn/part2": DATA[5000:12000],
        "https://www.gitlink.org.cn/part3": DATA[12000:],
    }
    urls = tuple(chunks)
    manager = DownloadManager(tmp_path, opener=lambda url, _timeout: io.BytesIO(chunks[url]))

    result = manager.run(spec(url=urls[0], part_urls=urls))

    assert result.state is DownloadState.READY
    assert result.result_path is not None
    assert result.result_path.read_bytes() == DATA


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
    assert result.error is None
    assert not partial.exists()


def test_cancel_closes_partial_before_unlinking(tmp_path: Path, monkeypatch) -> None:
    control = DownloadControl()
    part = tmp_path / "downloads" / "stellaris-dlc001.part"
    active = False
    original_open = Path.open
    original_unlink = Path.unlink

    class TrackedOutput:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            nonlocal active
            active = True
            return self.handle

        def __exit__(self, *args):
            nonlocal active
            active = False
            return self.handle.__exit__(*args)

    def tracked_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path == part and args and args[0] == "wb":
            return TrackedOutput(handle)
        return handle

    def guarded_unlink(path, *args, **kwargs):
        if path == part and active:
            raise PermissionError(32, "file is still open", str(path))
        return original_unlink(path, *args, **kwargs)

    class CancelDuringRead(io.BytesIO):
        def read(self, size=-1):
            block = super().read(size)
            control.cancel()
            return block

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    manager = DownloadManager(
        tmp_path,
        policy=DownloadPolicy(chunk_size=len(DATA)),
        opener=lambda *_args: CancelDuringRead(DATA),
    )

    result = manager.run(spec(), control)

    assert result.state is DownloadState.CANCELLED
    assert result.error is None
    assert not part.exists()


def test_pause_closes_and_discards_partial_before_returning(tmp_path: Path, monkeypatch) -> None:
    control = DownloadControl()
    part = tmp_path / "downloads" / "stellaris-dlc001.part"
    active = False
    original_open = Path.open
    original_unlink = Path.unlink

    class TrackedOutput:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            nonlocal active
            active = True
            return self.handle

        def __exit__(self, *args):
            nonlocal active
            active = False
            return self.handle.__exit__(*args)

    def tracked_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path == part and args and args[0] == "wb":
            return TrackedOutput(handle)
        return handle

    def guarded_unlink(path, *args, **kwargs):
        if path == part and active:
            raise PermissionError(32, "file is still open", str(path))
        return original_unlink(path, *args, **kwargs)

    class PauseDuringRead(io.BytesIO):
        def read(self, size=-1):
            block = super().read(size)
            control.pause()
            return block

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    manager = DownloadManager(
        tmp_path,
        policy=DownloadPolicy(chunk_size=len(DATA)),
        opener=lambda *_args: PauseDuringRead(DATA),
    )

    result = manager.run(spec(), control)

    assert result.state is DownloadState.PAUSED
    assert result.bytes_downloaded == 0
    assert result.error is None
    assert not part.exists()


def test_pause_wins_over_a_simultaneous_network_error(tmp_path: Path) -> None:
    control = DownloadControl()

    class PauseThenFail(io.BytesIO):
        def read(self, size=-1):
            control.pause()
            raise OSError("connection reset while pausing")

    manager = DownloadManager(
        tmp_path,
        policy=DownloadPolicy(attempts=3, retry_delay=0),
        opener=lambda *_args: PauseThenFail(DATA),
    )

    result = manager.run(spec(), control)

    assert result.state is DownloadState.PAUSED
    assert result.error is None
    assert result.bytes_downloaded == 0


def test_package_verifier_failure_is_quarantined(tmp_path: Path) -> None:
    def reject(_path: Path, _sha256: str) -> None:
        raise ValueError("unsafe package")

    result = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA)).run(spec(), verifier=reject)
    assert result.state is DownloadState.CORRUPT
    assert result.error == "unsafe package"


def test_package_verifier_reuses_streamed_sha256(tmp_path: Path) -> None:
    observed = []

    def verify(path: Path, actual_sha256: str) -> None:
        observed.append((path.name, actual_sha256))

    result = DownloadManager(
        tmp_path, opener=lambda *_args: io.BytesIO(DATA)
    ).run(spec(), verifier=verify)

    assert result.state is DownloadState.READY
    assert observed == [("stellaris-dlc001.part", hashlib.sha256(DATA).hexdigest())]


def test_cancel_requested_by_verifier_does_not_commit_package(tmp_path: Path) -> None:
    control = DownloadControl()
    states = []

    def verify(_path: Path, _actual_sha256: str) -> None:
        control.cancel()

    result = DownloadManager(
        tmp_path, opener=lambda *_args: io.BytesIO(DATA)
    ).run(spec(), control, states.append, verifier=verify)

    assert result.state is DownloadState.CANCELLED
    assert result.error is None
    assert DownloadState.VERIFYING in [item.state for item in states]
    assert DownloadState.READY not in [item.state for item in states]
    assert not (tmp_path / "downloads" / "stellaris-dlc001.part").exists()
    assert not list((tmp_path / "packages").rglob("*.zip"))


def test_pause_requested_by_verifier_does_not_commit_package(tmp_path: Path) -> None:
    control = DownloadControl()
    states = []

    def verify(_path: Path, _actual_sha256: str) -> None:
        control.pause()

    result = DownloadManager(
        tmp_path, opener=lambda *_args: io.BytesIO(DATA)
    ).run(spec(), control, states.append, verifier=verify)

    assert result.state is DownloadState.PAUSED
    assert result.bytes_downloaded == 0
    assert result.error is None
    assert DownloadState.VERIFYING in [item.state for item in states]
    assert DownloadState.READY not in [item.state for item in states]
    assert not (tmp_path / "downloads" / "stellaris-dlc001.part").exists()
    assert not list((tmp_path / "packages").rglob("*.zip"))


def test_cancel_requested_at_eof_does_not_enter_verification(tmp_path: Path) -> None:
    control = DownloadControl()
    states = []

    class CancelAtEof(io.BytesIO):
        def read(self, size=-1):
            block = super().read(size)
            if not block:
                control.cancel()
            return block

    result = DownloadManager(
        tmp_path,
        policy=DownloadPolicy(chunk_size=len(DATA)),
        opener=lambda *_args: CancelAtEof(DATA),
    ).run(spec(), control, states.append)

    assert result.state is DownloadState.CANCELLED
    assert DownloadState.VERIFYING not in [item.state for item in states]
    assert DownloadState.READY not in [item.state for item in states]
    assert not (tmp_path / "downloads" / "stellaris-dlc001.part").exists()
    assert not list((tmp_path / "packages").rglob("*.zip"))


def test_transient_package_verification_failure_redownloads(tmp_path: Path) -> None:
    inspections = 0
    opens = 0

    def opener(*_args):
        nonlocal opens
        opens += 1
        return io.BytesIO(DATA)

    def verify(_path: Path, _actual_sha256: str) -> None:
        nonlocal inspections
        inspections += 1
        if inspections == 1:
            raise ValueError("temporary broken package")

    result = DownloadManager(
        tmp_path,
        policy=DownloadPolicy(attempts=3, retry_delay=0),
        opener=opener,
    ).run(spec(), verifier=verify)

    assert result.state is DownloadState.READY
    assert opens == inspections == 2


def test_rejects_unsafe_url_and_filename(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path, opener=lambda *_args: io.BytesIO(DATA))
    for invalid in (spec(url="http://example.test/a"), spec(filename="../bad.zip")):
        try:
            manager.run(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe spec was accepted")
