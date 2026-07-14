"""Domain models describing per-game unlock patches (CreamAPI-style)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .catalog import ReleaseAsset


class PatchAssetRole(StrEnum):
    """Semantic role of a patch asset published by the resource repository."""

    UNLOCKER_DLL = "unlocker_dll"
    ORIGINAL_BACKUP_DLL = "original_backup_dll"
    APPINFO_JSON = "appinfo_json"


class PatchHealth(StrEnum):
    """Current state of a game directory relative to our expected patch layout."""

    HEALTHY = "healthy"
    ORIGINAL = "original"
    MODIFIED = "modified"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PatchTemplate:
    """Rendering parameters for the CreamAPI-style ini file."""

    ini_target_name: str
    language: str = "schinese"
    unlock_all: bool = True
    extra_protection: bool = False
    force_offline: bool = False

    def __post_init__(self) -> None:
        if not self.ini_target_name or "/" in self.ini_target_name or "\\" in self.ini_target_name:
            raise ValueError("ini target name must be a plain filename")
        language = self.language.strip()
        if not language or any(character in language for character in "\r\n="):
            raise ValueError("language must be a single-line, non-empty token")


@dataclass(frozen=True, slots=True)
class PatchProfile:
    """Per-game description of the CreamAPI-style patch layout.

    Every field is declarative so that the patch engine never hard-codes
    Stellaris-specific IDs.  New games simply publish their own profile.
    """

    unlocker_dll_name: str
    original_backup_dll_name: str
    appinfo_asset_name: str
    template: PatchTemplate

    def __post_init__(self) -> None:
        if not self.unlocker_dll_name or "/" in self.unlocker_dll_name or "\\" in self.unlocker_dll_name:
            raise ValueError("unlocker DLL name must be a plain filename")
        if (
            not self.original_backup_dll_name
            or "/" in self.original_backup_dll_name
            or "\\" in self.original_backup_dll_name
        ):
            raise ValueError("original backup DLL name must be a plain filename")
        if self.unlocker_dll_name.casefold() == self.original_backup_dll_name.casefold():
            raise ValueError("unlocker and original backup names must differ")
        if not self.appinfo_asset_name.endswith(".json"):
            raise ValueError("appinfo asset name must reference a .json file")
        if self.appinfo_asset_name.casefold() == self.template.ini_target_name.casefold():
            raise ValueError("appinfo asset name must differ from ini target name")

    @property
    def patch_file_names(self) -> tuple[str, ...]:
        """Files that live under the game root after a successful apply."""
        return (
            self.unlocker_dll_name,
            self.original_backup_dll_name,
            self.template.ini_target_name,
        )


@dataclass(frozen=True, slots=True)
class PatchBundle:
    """Release-side view of the three patch assets shipped for a game."""

    profile: PatchProfile
    unlocker_dll: ReleaseAsset
    original_backup_dll: ReleaseAsset
    appinfo_json: ReleaseAsset
    release_tag: str


@dataclass(frozen=True, slots=True)
class PatchAudit:
    """Comparison between an installed patch and the bundle we would apply."""

    health: PatchHealth
    missing: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    matching: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing", tuple(self.missing))
        object.__setattr__(self, "modified", tuple(self.modified))
        object.__setattr__(self, "matching", tuple(self.matching))


@dataclass(frozen=True, slots=True)
class PatchReceipt:
    """Record of a successfully applied patch operation."""

    game_id: str
    unlocker_dll_size: int
    original_backup_dll_size: int
    ini_bytes: int
    backup_created: bool
    replaced_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "replaced_files", tuple(self.replaced_files))


__all__ = [
    "PatchAssetRole",
    "PatchAudit",
    "PatchBundle",
    "PatchHealth",
    "PatchProfile",
    "PatchReceipt",
    "PatchTemplate",
]
