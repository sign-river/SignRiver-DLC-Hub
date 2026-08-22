"""Export client-facing cartridge documents from publisher game profiles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import PublisherCartridge

HUB_RELEASE_TAG = "hub"
INDEX_ASSET_NAME = "cartridges_index.json"
CARTRIDGE_DOCUMENT_SCHEMA = 1
CARTRIDGE_INDEX_SCHEMA = 1


def client_cartridge_asset_name(game_id: str) -> str:
    return f"cartridge_{game_id}.json"


def build_client_cartridge_document(
    profile: PublisherCartridge,
    *,
    freshness: dict[str, object] | None = None,
) -> dict[str, object]:
    """Convert a publisher disk cartridge into the client remote document."""
    executable = profile.executable_relative_path.strip()
    if not executable:
        raise ValueError(f"{profile.game_id} 缺少 executable_relative_path，无法导出客户端卡带")
    inspector = profile.package_inspector.strip() or "directory"
    payload: dict[str, object] = {
        "schema_version": CARTRIDGE_DOCUMENT_SCHEMA,
        "engine": "steam_configured_v1",
        "game_id": profile.game_id,
        "display_name": profile.display_name,
        "store_app_id": profile.steam_app_id,
        "release_tag": profile.release_tag,
        "executable_relative_path": executable,
        "dlc_relative_dir": profile.dlc_relative_dir,
        "dlc_delivery_mode": profile.dlc_delivery_mode,
        "package_inspector": inspector,
        "install_directory_from_slug": bool(profile.install_directory_from_slug),
        "dlc_group_search_roots": list(profile.dlc_group_search_roots),
        "repository": {
            "owner": "signriver",
            "repository": "signriver-dlc-assets",
        },
        "repositories": {
            "gitlink": {
                "owner": "signriver",
                "repository": "signriver-dlc-assets",
            },
            "github": {
                "owner": "sign-river",
                "repository": "signriver-dlc-assets",
            },
        },
        "patch": {
            "unlocker_dll_name": profile.patch_unlocker_name,
            "runtime_original_library_name": profile.patch_runtime_original_name,
            "appinfo_asset_name": profile.appinfo_name,
            "install_relative_dir": profile.patch_relative_dir,
            "additional_install_relative_dirs": list(
                profile.patch_additional_relative_dirs
            ),
            "ini_target_name": profile.ini_target_name,
            "language": profile.patch_language,
            "unlock_all": bool(profile.patch_unlock_all),
            "extra_protection": bool(profile.patch_extra_protection),
            "force_offline": bool(profile.patch_force_offline),
            "platforms": {
                platform: dict(spec)
                for platform, spec in sorted(profile.patch_platforms.items())
            },
        },
    }
    if freshness:
        payload["freshness"] = freshness
    return payload


def write_client_cartridge_document(
    profile: PublisherCartridge,
    directory: Path,
    *,
    freshness: dict[str, object] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / client_cartridge_asset_name(profile.game_id)
    payload = build_client_cartridge_document(profile, freshness=freshness)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def build_client_cartridge_index(
    profiles: tuple[PublisherCartridge, ...],
    *,
    documents: dict[str, Path],
    default_game_id: str | None = None,
    resource_availability_by_game: dict[str, dict[str, dict[str, bool]]] | None = None,
) -> dict[str, object]:
    if not profiles:
        raise ValueError("至少需要一张游戏卡带才能生成主表")
    default_id = default_game_id or profiles[0].game_id
    cartridges = []
    availability_by_game = resource_availability_by_game or {}
    for profile in profiles:
        path = documents[profile.game_id]
        payload = path.read_bytes()
        # Callers that have inspected the published game release may supply an
        # exact resource map.  During local export we retain a useful default:
        # every configured patch platform has a patch, and downloadable DLC is
        # game-wide rather than duplicated per platform.  ``built_in`` games
        # (for example Civilization VII) intentionally remain patch-only.
        supplied = availability_by_game.get(profile.game_id)
        if supplied is None:
            patch_platforms = {"windows", *profile.patch_platforms}
            dlc_available = profile.dlc_delivery_mode != "built_in"
            supplied = {
                platform: {"patch": True, "dlc": dlc_available}
                for platform in patch_platforms
            }
        platform_resources = {
            str(platform).split("-", 1)[0]: {
                "patch": bool(values.get("patch")),
                "dlc": bool(values.get("dlc")),
            }
            for platform, values in supplied.items()
        }
        cartridges.append({
            "game_id": profile.game_id,
            "display_name": profile.display_name,
            "asset_name": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "platform_resources": platform_resources,
        })
    return {
        "schema_version": CARTRIDGE_INDEX_SCHEMA,
        "default_game_id": default_id,
        "release_tag": HUB_RELEASE_TAG,
        "repository": {
            "owner": "signriver",
            "repository": "signriver-dlc-assets",
        },
        "cartridges": cartridges,
    }


def export_hub_cartridges(
    profiles: tuple[PublisherCartridge, ...],
    output_dir: Path,
    *,
    default_game_id: str | None = None,
    announcement_path: Path | None = None,
    freshness_by_game: dict[str, dict[str, object]] | None = None,
    resource_availability_by_game: dict[str, dict[str, dict[str, bool]]] | None = None,
) -> tuple[Path, ...]:
    """Write every client cartridge plus the hub index into ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    documents: dict[str, Path] = {}
    written: list[Path] = []
    freshness_map = freshness_by_game or {}
    for profile in profiles:
        path = write_client_cartridge_document(
            profile,
            output_dir,
            freshness=freshness_map.get(profile.game_id),
        )
        documents[profile.game_id] = path
        written.append(path)
    index = build_client_cartridge_index(
        profiles,
        documents=documents,
        default_game_id=default_game_id,
        resource_availability_by_game=resource_availability_by_game,
    )
    index_path = output_dir / INDEX_ASSET_NAME
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    written.append(index_path)
    if announcement_path is not None and announcement_path.is_file():
        target = output_dir / "announcement.json"
        payload = json.loads(announcement_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("announcement.json root must be an object")
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(target)
    expected = {path.name.casefold() for path in written}
    for stale in output_dir.iterdir():
        folded = stale.name.casefold()
        managed_document = folded.startswith("cartridge_") and folded.endswith(
            ".json"
        )
        managed_announcement = folded == "announcement.json"
        if (
            stale.is_file()
            and folded not in expected
            and (managed_document or managed_announcement)
        ):
            stale.unlink()
    return tuple(written)


__all__ = [
    "CARTRIDGE_DOCUMENT_SCHEMA",
    "CARTRIDGE_INDEX_SCHEMA",
    "HUB_RELEASE_TAG",
    "INDEX_ASSET_NAME",
    "build_client_cartridge_document",
    "build_client_cartridge_index",
    "client_cartridge_asset_name",
    "export_hub_cartridges",
    "write_client_cartridge_document",
]
