from __future__ import annotations

import logging
from pathlib import Path

import pytest

from signriver_launcher.api import HostContext, PublicPaths


def test_frozen_restart_launches_independent_pyinstaller_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.api as api_module

    install = tmp_path / "install"
    install.mkdir()
    executable = install / "launcher.exe"
    calls: list[tuple[list[str], dict[str, object]]] = []
    exits: list[int] = []
    context = HostContext(
        app_version="0.2.0",
        launcher_version="0.1.2",
        api_version=1,
        paths=PublicPaths(
            root=install,
            data=tmp_path / "data",
            cache=tmp_path / "cache",
            install=install,
        ),
        updates=object(),  # type: ignore[arg-type]
        logger=logging.getLogger("test-frozen-restart"),
    )

    monkeypatch.setattr(api_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(api_module.sys, "executable", str(executable))
    monkeypatch.setattr(
        api_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    def exit_process(code: int) -> None:
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(api_module.os, "_exit", exit_process)

    with pytest.raises(SystemExit, match="0"):
        context.restart()

    assert exits == [0]
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [str(executable)]
    assert kwargs["cwd"] == install
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
