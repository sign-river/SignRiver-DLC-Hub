from __future__ import annotations

from pathlib import Path

from signriver_publisher import main as publisher_main


def test_default_workspace_uses_cwd_in_source_mode(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(publisher_main.sys, "frozen", raising=False)

    assert publisher_main.default_workspace_path() == (
        tmp_path / "publisher-workspace"
    )


def test_default_workspace_uses_executable_directory_when_frozen(
    tmp_path: Path, monkeypatch,
) -> None:
    executable = tmp_path / "portable" / "SignRiver-Publisher.exe"
    monkeypatch.setattr(publisher_main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(publisher_main.sys, "executable", str(executable))
    monkeypatch.chdir(tmp_path)

    assert publisher_main.default_workspace_path() == (
        executable.parent / "publisher-workspace"
    )
