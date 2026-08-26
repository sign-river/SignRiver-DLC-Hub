"""Domain models describing per-game unlock patches (CreamAPI-style)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .catalog import ReleaseAsset
from .paths import normalize_game_relative_directory, normalize_game_relative_file


class PatchAssetRole(StrEnum):
    """Semantic role of a patch asset published by the resource repository."""

    UNLOCKER_DLL = "unlocker_dll"
    ORIGINAL_DLL = "original_dll"
    APPINFO_JSON = "appinfo_json"


class PatchPlatform(StrEnum):
    """Host/target operating system for a CreamAPI/SmokeAPI-style patch."""

    WINDOWS = "windows"
    STEAMOS = "steamos"
    MACOS = "macos"


class PatchConfigFormat(StrEnum):
    """How the per-game unlock configuration file is rendered."""

    CREAM_INI = "cream_ini"
    SMOKEAPI_JSON = "smokeapi_json"


def host_patch_platform() -> PatchPlatform:
    """Return the platform the running app should patch by default."""
    import sys

    if sys.platform == "linux":
        return PatchPlatform.STEAMOS
    if sys.platform == "darwin":
        return PatchPlatform.MACOS
    return PatchPlatform.WINDOWS


class PatchHealth(StrEnum):
    """Current state of a game directory relative to our expected patch layout."""

    HEALTHY = "healthy"
    ORIGINAL = "original"
    MODIFIED = "modified"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PatchTemplate:
    """Rendering parameters for the CreamAPI/SmokeAPI-style config file."""

    ini_target_name: str
    language: str = "schinese"
    unlock_all: bool = True
    extra_protection: bool = False
    force_offline: bool = False
    config_format: PatchConfigFormat = PatchConfigFormat.CREAM_INI

    def __post_init__(self) -> None:
        if not self.ini_target_name or "/" in self.ini_target_name or "\\" in self.ini_target_name:
            raise ValueError("ini target name must be a plain filename")
        language = self.language.strip()
        if not language or any(character in language for character in "\r\n="):
            raise ValueError("language must be a single-line, non-empty token")
        if not isinstance(self.config_format, PatchConfigFormat):
            object.__setattr__(self, "config_format", PatchConfigFormat(self.config_format))


@dataclass(frozen=True, slots=True)
class PatchProfile:
    """Per-game description of the CreamAPI-style patch layout.

    Every field is declarative so that the patch engine never hard-codes
    Stellaris-specific IDs.  New games simply publish their own profile.
    """

    unlocker_dll_name: str
    runtime_original_library_name: str
    appinfo_asset_name: str
    template: PatchTemplate
    install_relative_dir: str = "."
    platform: PatchPlatform = PatchPlatform.WINDOWS
    additional_install_relative_dirs: tuple[str, ...] = ()
    interference_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.unlocker_dll_name or "/" in self.unlocker_dll_name or "\\" in self.unlocker_dll_name:
            raise ValueError("unlocker DLL name must be a plain filename")
        if (
            not self.runtime_original_library_name
            or "/" in self.runtime_original_library_name
            or "\\" in self.runtime_original_library_name
        ):
            raise ValueError("runtime original library name must be a plain filename")
        if self.unlocker_dll_name.casefold() == self.runtime_original_library_name.casefold():
            raise ValueError("unlocker and runtime original library names must differ")
        if not self.appinfo_asset_name.endswith(".json"):
            raise ValueError("appinfo asset name must reference a .json file")
        if self.appinfo_asset_name.casefold() == self.template.ini_target_name.casefold():
            raise ValueError("appinfo asset name must differ from ini target name")
        object.__setattr__(
            self,
            "install_relative_dir",
            normalize_game_relative_directory(
                self.install_relative_dir,
                field_name="patch install directory",
            ),
        )
        additional_dirs = tuple(
            normalize_game_relative_directory(
                directory,
                field_name="additional patch install directory",
            )
            for directory in self.additional_install_relative_dirs
        )
        all_dirs = (self.install_relative_dir, *additional_dirs)
        if len({directory.casefold() for directory in all_dirs}) != len(all_dirs):
            raise ValueError("patch install directories must not repeat")
        object.__setattr__(self, "additional_install_relative_dirs", additional_dirs)
        interference = tuple(
            normalize_game_relative_file(path, field_name="patch interference file")
            for path in self.interference_files
        )
        if len({path.casefold() for path in interference}) != len(interference):
            raise ValueError("patch interference files must not repeat")
        object.__setattr__(self, "interference_files", interference)

    @property
    def install_relative_dirs(self) -> tuple[str, ...]:
        """All game-relative directories that receive the complete patch."""
        return (self.install_relative_dir, *self.additional_install_relative_dirs)

    @property
    def patch_file_names(self) -> tuple[str, ...]:
        """Plain filenames installed together in the configured patch directory."""
        return (
            self.unlocker_dll_name,
            self.runtime_original_library_name,
            self.template.ini_target_name,
        )

    def relative_file_path(self, filename: str) -> str:
        prefix = "" if self.install_relative_dir == "." else f"{self.install_relative_dir}/"
        return f"{prefix}{filename}"

    def relative_file_paths(self, filename: str) -> tuple[str, ...]:
        return tuple(
            f"{'' if directory == '.' else f'{directory}/'}{filename}"
            for directory in self.install_relative_dirs
        )

    @property
    def patch_file_paths(self) -> tuple[str, ...]:
        return tuple(
            path
            for name in self.patch_file_names
            for path in self.relative_file_paths(name)
        )


@dataclass(frozen=True, slots=True)
class PatchBundle:
    """Release-side view of the complete, deterministic patch payload."""

    profile: PatchProfile
    unlocker_dll: ReleaseAsset
    original_dll: ReleaseAsset
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
    runtime_original_library_size: int
    ini_bytes: int
    backup_created: bool
    replaced_files: tuple[str, ...] = ()
    unlocker_sha256: str = ""
    runtime_original_sha256: str = ""
    ini_sha256: str = ""
    original_library_cache_key: str = ""
    original_library_source: str = "unknown"

    @property
    def backup_origin(self) -> str:
        """Compatibility alias for callers that still display the old label."""
        return self.original_library_source

    def __post_init__(self) -> None:
        object.__setattr__(self, "replaced_files", tuple(self.replaced_files))


__all__ = [
    "PatchAssetRole",
    "PatchAudit",
    "PatchBundle",
    "PatchConfigFormat",
    "PatchHealth",
    "PatchPlatform",
    "PatchProfile",
    "PatchReceipt",
    "PatchTemplate",
    "host_patch_platform",
]
