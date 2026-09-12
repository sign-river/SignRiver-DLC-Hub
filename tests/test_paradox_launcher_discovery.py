from __future__ import annotations

from pathlib import Path

from signriver_app.infrastructure.paradox_launcher import find_latest_complete_version


def _complete_launcher(root: Path, version: str) -> Path:
    directory = root / f"launcher-v2.2026.{version}"
    for relative in (
        Path("Paradox Launcher.exe"),
        Path("resources") / "app.asar",
        Path("resources") / "app.asar.unpacked" / "node_modules" / "greenworks" / "lib" / "steam_api64.dll",
    ):
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    return directory


def test_selects_newest_complete_launcher_with_numeric_version_order(tmp_path: Path) -> None:
    _complete_launcher(tmp_path, "8.1")
    _complete_launcher(tmp_path, "10")
    newest = _complete_launcher(tmp_path, "11.1")

    assert find_latest_complete_version(tmp_path) == newest


def test_ignores_cpatch_only_staging_directory(tmp_path: Path) -> None:
    complete = _complete_launcher(tmp_path, "10")
    (tmp_path / "launcher-v2.2026.11.1" / ".cpatch").mkdir(parents=True)

    assert find_latest_complete_version(tmp_path) == complete
