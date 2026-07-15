"""Safe discovery and removal of cartridge-managed DLC directories."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ...domain import resolve_game_directory

_DLC_DIRECTORY = re.compile(r"^(dlc\d{3,})_[a-z0-9_]+$", re.I)


def discover_numbered_dlc(
    game_root: Path, dlc_relative_dir: str
) -> dict[str, Path]:
    try:
        dlc_root = resolve_game_directory(
            game_root, dlc_relative_dir,
            field_name="DLC install directory", strict_root=False,
        )
        children = tuple(dlc_root.iterdir())
    except (OSError, ValueError):
        return {}
    installed: dict[str, Path] = {}
    for path in children:
        match = _DLC_DIRECTORY.fullmatch(path.name)
        if match is not None and path.is_dir():
            installed[match.group(1).casefold()] = path
    return installed


def remove_numbered_dlc(
    game_root: Path, dlc_id: str, dlc_relative_dir: str
) -> Path:
    if not re.fullmatch(r"dlc\d{3,}", dlc_id, re.I):
        raise ValueError("invalid DLC ID")
    root = Path(game_root).resolve(strict=True)
    dlc_root = resolve_game_directory(
        root, dlc_relative_dir, field_name="DLC install directory"
    ).resolve(strict=True)
    target = discover_numbered_dlc(root, dlc_relative_dir).get(dlc_id.casefold())
    if target is None:
        raise FileNotFoundError(f"installed DLC directory not found: {dlc_id}")
    resolved = target.resolve(strict=True)
    if resolved.parent != dlc_root or _DLC_DIRECTORY.fullmatch(resolved.name) is None:
        raise ValueError("refusing to remove an unsafe DLC directory")
    shutil.rmtree(resolved)
    return resolved


__all__ = ["discover_numbered_dlc", "remove_numbered_dlc"]
