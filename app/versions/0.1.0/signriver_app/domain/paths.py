"""Safe cartridge-owned paths below a game installation root."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def normalize_game_relative_directory(value: str, *, field_name: str) -> str:
    """Normalize a cartridge directory and reject absolute/traversal paths."""
    raw = str(value).strip().replace("\\", "/")
    if raw in {"", "."}:
        return "."
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "\x00" in raw:
        raise ValueError(f"{field_name} must stay below the game root")
    if any(":" in part or part in {"", "."} for part in path.parts):
        raise ValueError(f"{field_name} is not a safe relative directory")
    return path.as_posix()


def game_relative_path(value: str, *, field_name: str) -> Path:
    normalized = normalize_game_relative_directory(value, field_name=field_name)
    if normalized == ".":
        return Path()
    return Path(*PurePosixPath(normalized).parts)


def resolve_game_directory(
    game_root: Path,
    value: str,
    *,
    field_name: str,
    strict_root: bool = True,
) -> Path:
    root = Path(game_root).resolve(strict=strict_root)
    target = (root / game_relative_path(value, field_name=field_name)).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{field_name} escapes the game root") from error
    return target


__all__ = [
    "game_relative_path",
    "normalize_game_relative_directory",
    "resolve_game_directory",
]
