"""Discover complete Paradox Launcher installations on Windows."""

from __future__ import annotations

import re
from pathlib import Path


_VERSION_DIRECTORY_PREFIX = "launcher-"
_REQUIRED_FILES = (
    Path("Paradox Launcher.exe"),
    Path("resources") / "app.asar",
    Path("resources") / "app.asar.unpacked" / "node_modules" / "greenworks" / "lib" / "steam_api64.dll",
)


def find_latest_complete_version(root: Path) -> Path | None:
    """Return the numerically newest complete launcher directory below *root*.

    The launcher updater can leave a version-named directory containing only
    ``.cpatch`` staging data.  A version is usable only when its executable,
    Electron archive, and the DLL that this tool repairs are all present.
    """
    candidates = (
        path
        for path in root.glob(f"{_VERSION_DIRECTORY_PREFIX}*")
        if path.is_dir() and all((path / relative).is_file() for relative in _REQUIRED_FILES)
    )
    return max(candidates, key=_version_sort_key, default=None)


def _version_sort_key(path: Path) -> tuple[int, ...]:
    """Compare all numeric components, not the directory names as text."""
    return tuple(int(component) for component in re.findall(r"\d+", path.name))
