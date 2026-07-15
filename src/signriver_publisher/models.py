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

    @classmethod
    def create(cls, game_id: str, display_name: str, steam_app_id: str = "") -> "PublisherCartridge":
        """Create a cartridge using the shared release naming convention."""
        return cls(game_id, display_name, game_id, f"{game_id}_appinfo.json", steam_app_id)

    @property
    def patch_asset_names(self) -> tuple[str, str]:
        return self.patch_unlocker_name, self.patch_original_backup_name

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PublisherCartridge":
        game_id = str(value["game_id"])
        legacy_steam_ids = {"stellaris": "281990"}
        builtin_naming_modes = {"civilization_6": "auto_prefix"}
        builtin_layout_modes = {"civilization_6": "children_if_root"}
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
            dlc_relative_dir=str(value.get("dlc_relative_dir") or "dlc"),
            patch_relative_dir=str(value.get("patch_relative_dir") or "."),
            dlc_archive_root_mode=str(value.get("dlc_archive_root_mode") or "source"),
            dlc_import_naming_mode=str(
                value.get("dlc_import_naming_mode")
                or builtin_naming_modes.get(game_id, "manual_prefixed")
            ),
            dlc_import_layout_mode=str(
                value.get("dlc_import_layout_mode")
                or builtin_layout_modes.get(game_id, "single_directory")
            ),
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
