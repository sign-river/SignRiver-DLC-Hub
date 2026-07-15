from __future__ import annotations

import re


MANUAL_PREFIXED = "manual_prefixed"
AUTO_PREFIX = "auto_prefix"
VALID_DLC_IMPORT_NAMING_MODES = frozenset({MANUAL_PREFIXED, AUTO_PREFIX})
SINGLE_DIRECTORY = "single_directory"
CHILDREN_IF_ROOT = "children_if_root"
VALID_DLC_IMPORT_LAYOUT_MODES = frozenset({SINGLE_DIRECTORY, CHILDREN_IF_ROOT})

_MANAGED_FOLDER = re.compile(
    r"^(dlc(?P<number>\d{3,}))_(?P<install_name>[A-Za-z0-9][A-Za-z0-9_-]*)$",
    re.I,
)
_INSTALL_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def parse_managed_folder(name: str) -> tuple[str, str, int] | None:
    """Return the stable DLC id, install directory and numeric id."""
    match = _MANAGED_FOLDER.fullmatch(name)
    if match is None:
        return None
    return (
        match.group(1).lower(),
        match.group("install_name"),
        int(match.group("number")),
    )


def auto_managed_folder(source_name: str, number: int) -> str:
    """Add a publisher-only stable id while preserving the install directory."""
    if not _INSTALL_FOLDER.fullmatch(source_name):
        raise ValueError(
            "自动编号模式要求原始 DLC 目录仅包含英文字母、数字、下划线或短横线"
        )
    if number < 1:
        raise ValueError("DLC 编号必须大于 0")
    return f"dlc{number:03d}_{source_name}"


__all__ = [
    "AUTO_PREFIX",
    "CHILDREN_IF_ROOT",
    "MANUAL_PREFIXED",
    "SINGLE_DIRECTORY",
    "VALID_DLC_IMPORT_LAYOUT_MODES",
    "VALID_DLC_IMPORT_NAMING_MODES",
    "auto_managed_folder",
    "parse_managed_folder",
]
