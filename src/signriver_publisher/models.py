from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GameProfile:
    game_id: str
    display_name: str
    release_tag: str
    appinfo_name: str
    steam_app_id: str = ""

    @classmethod
    def create(cls, game_id: str, display_name: str, steam_app_id: str = "") -> "GameProfile":
        """Create a game profile using the shared AppInfo naming convention."""
        return cls(game_id, display_name, game_id, f"{game_id}_appinfo.json", steam_app_id)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "GameProfile":
        game_id = str(value["game_id"])
        legacy_steam_ids = {"stellaris": "281990"}
        return cls(
            game_id=game_id,
            display_name=str(value["display_name"]),
            release_tag=str(value["release_tag"]),
            appinfo_name=str(value.get("appinfo_name") or f"{game_id}_appinfo.json"),
            steam_app_id=str(value.get("steam_app_id") or legacy_steam_ids.get(game_id, "")),
        )


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
