from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PublisherCartridge:
    """One server-side game cartridge and its complete release contract."""

    game_id: str
    display_name: str
    release_tag: str
    appinfo_name: str
    steam_app_id: str = ""
    patch_unlocker_name: str = "steam_api64.dll"
    patch_original_backup_name: str = "steam_api64_o.dll"
    dlc_relative_dir: str = "dlc"
    patch_relative_dir: str = "."
    dlc_archive_root_mode: str = "source"
    dlc_import_naming_mode: str = "manual_prefixed"
    dlc_import_layout_mode: str = "single_directory"
    # Client-facing fields exported into the remote hub cartridge documents.
    executable_relative_path: str = ""
    package_inspector: str = "directory"
    install_directory_from_slug: bool = False
    ini_target_name: str = "cream_api.ini"
    patch_language: str = "schinese"
    patch_unlock_all: bool = True
    patch_extra_protection: bool = False
    patch_force_offline: bool = False

    @classmethod
    def create(cls, game_id: str, display_name: str, steam_app_id: str = "") -> "PublisherCartridge":
        """Create a cartridge using the shared release naming convention."""
        return cls(game_id, display_name, game_id, f"{game_id}_appinfo.json", steam_app_id)

    @property
    def patch_asset_names(self) -> tuple[str, str]:
        return self.patch_unlocker_name, self.patch_original_backup_name

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PublisherCartridge":
        game_id = str(value["game_id"])
        auto_prefix_games = {"civilization_6", "cities_skylines", "rimworld"}
        legacy_steam_ids = {
            "stellaris": "281990",
            "civilization_6": "289070",
            "hearts_of_iron_4": "394360",
            "cities_skylines": "255710",
            "rimworld": "294100",
        }
        builtin_naming_modes = {gid: "auto_prefix" for gid in auto_prefix_games}
        builtin_layout_modes = {gid: "children_if_root" for gid in auto_prefix_games}
        builtin_archive_modes = {gid: "strip_id_prefix" for gid in auto_prefix_games}
        builtin_dlc_dirs = {
            "civilization_6": "DLC",
            "cities_skylines": "Files",
            "rimworld": "Data",
        }
        builtin_patch_dirs = {
            "civilization_6": "Base/Binaries/Win64Steam",
        }
        builtin_executables = {
            "stellaris": "stellaris.exe",
            "civilization_6": "Base/Binaries/Win64Steam/CivilizationVI.exe",
            "hearts_of_iron_4": "hoi4.exe",
            "cities_skylines": "Cities.exe",
            "rimworld": "RimWorldWin64.exe",
        }
        builtin_inspectors = {"stellaris": "stellaris_zip"}
        return cls(
            game_id=game_id,
            display_name=str(value["display_name"]),
            release_tag=str(value["release_tag"]),
            appinfo_name=str(value.get("appinfo_name") or f"{game_id}_appinfo.json"),
            steam_app_id=str(value.get("steam_app_id") or legacy_steam_ids.get(game_id, "")),
            patch_unlocker_name=str(value.get("patch_unlocker_name") or "steam_api64.dll"),
            patch_original_backup_name=str(
                value.get("patch_original_backup_name") or "steam_api64_o.dll"
            ),
            dlc_relative_dir=str(
                value.get("dlc_relative_dir") or builtin_dlc_dirs.get(game_id, "dlc")
            ),
            patch_relative_dir=str(
                value.get("patch_relative_dir") or builtin_patch_dirs.get(game_id, ".")
            ),
            dlc_archive_root_mode=str(
                value.get("dlc_archive_root_mode")
                or builtin_archive_modes.get(game_id, "source")
            ),
            dlc_import_naming_mode=str(
                value.get("dlc_import_naming_mode")
                or builtin_naming_modes.get(game_id, "manual_prefixed")
            ),
            dlc_import_layout_mode=str(
                value.get("dlc_import_layout_mode")
                or builtin_layout_modes.get(game_id, "single_directory")
            ),
            executable_relative_path=str(
                value.get("executable_relative_path")
                or builtin_executables.get(game_id, "")
            ),
            package_inspector=str(
                value.get("package_inspector")
                or builtin_inspectors.get(game_id, "directory")
            ),
            install_directory_from_slug=bool(
                value.get(
                    "install_directory_from_slug",
                    game_id in auto_prefix_games,
                )
            ),
            ini_target_name=str(value.get("ini_target_name") or "cream_api.ini"),
            patch_language=str(value.get("patch_language") or "schinese"),
            patch_unlock_all=bool(value.get("patch_unlock_all", True)),
            patch_extra_protection=bool(value.get("patch_extra_protection", False)),
            patch_force_offline=bool(value.get("patch_force_offline", False)),
        )


# Backwards-compatible import name for older modules. New server code and
# documentation use PublisherCartridge to match the client cartridge model.
GameProfile = PublisherCartridge


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    kind: str
    resource_id: str
    display_name: str
    asset_name: str
    source_path: Path
    output_path: Path
    size_bytes: int
    sha256: str

    def manifest_dict(self) -> dict[str, object]:
        return {
            "id": self.resource_id,
            "name": self.display_name,
            "asset_name": self.asset_name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PublishAsset:
    path: Path
    name: str
    size_bytes: int
    sha256: str
