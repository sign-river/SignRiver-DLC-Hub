from pathlib import Path

import pytest

import signriver_launcher.jsonio as jsonio


class _WindowsOSError(OSError):
    def __init__(self, winerror: int) -> None:
        super().__init__(winerror, "sharing violation")
        self.winerror = winerror


def test_atomic_write_retries_transient_windows_sharing_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    real_replace = jsonio.os.replace
    attempts = 0

    def replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _WindowsOSError(5)
        real_replace(source, destination)

    monkeypatch.setattr(jsonio.os, "name", "nt")
    monkeypatch.setattr(jsonio.os, "replace", replace)
    monkeypatch.setattr(jsonio.time, "sleep", lambda _delay: None)

    jsonio.atomic_write_json(target, {"ok": True})

    assert attempts == 3
    assert jsonio.read_json(target) == {"ok": True}


def test_atomic_write_stops_after_bounded_windows_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    attempts = 0

    def replace(_source, _destination):
        nonlocal attempts
        attempts += 1
        raise _WindowsOSError(32)

    monkeypatch.setattr(jsonio.os, "name", "nt")
    monkeypatch.setattr(jsonio.os, "replace", replace)
    monkeypatch.setattr(jsonio.time, "sleep", lambda _delay: None)

    with pytest.raises(_WindowsOSError):
        jsonio.atomic_write_json(target, {"ok": False})

    assert attempts == 6
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_atomic_write_does_not_retry_non_windows_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    attempts = 0

    def replace(_source, _destination):
        nonlocal attempts
        attempts += 1
        raise _WindowsOSError(5)

    monkeypatch.setattr(jsonio.os, "name", "posix")
    monkeypatch.setattr(jsonio.os, "replace", replace)

    with pytest.raises(_WindowsOSError):
        jsonio.atomic_write_json(target, {"ok": False})

    assert attempts == 1
