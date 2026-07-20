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


def build_client_cartridge_document(profile: PublisherCartridge) -> dict[str, object]:
    """Convert a publisher disk cartridge into the client remote document."""
    executable = profile.executable_relative_path.strip()
    if not executable:
        raise ValueError(f"{profile.game_id} 缺少 executable_relative_path，无法导出客户端卡带")
    inspector = profile.package_inspector.strip() or "directory"
    return {
        "schema_version": CARTRIDGE_DOCUMENT_SCHEMA,
        "engine": "steam_configured_v1",
        "game_id": profile.game_id,
        "display_name": profile.display_name,
        "store_app_id": profile.steam_app_id,
        "release_tag": profile.release_tag,
        "executable_relative_path": executable,
        "dlc_relative_dir": profile.dlc_relative_dir,
        "package_inspector": inspector,
        "install_directory_from_slug": bool(profile.install_directory_from_slug),
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
            "original_backup_dll_name": profile.patch_original_backup_name,
            "appinfo_asset_name": profile.appinfo_name,
            "install_relative_dir": profile.patch_relative_dir,
            "ini_target_name": profile.ini_target_name,
            "language": profile.patch_language,
            "unlock_all": bool(profile.patch_unlock_all),
            "extra_protection": bool(profile.patch_extra_protection),
            "force_offline": bool(profile.patch_force_offline),
        },
    }


def write_client_cartridge_document(
    profile: PublisherCartridge, directory: Path
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / client_cartridge_asset_name(profile.game_id)
    payload = build_client_cartridge_document(profile)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def build_client_cartridge_index(
    profiles: tuple[PublisherCartridge, ...],
    *,
    documents: dict[str, Path],
    default_game_id: str | None = None,
) -> dict[str, object]:
    if not profiles:
        raise ValueError("至少需要一张游戏卡带才能生成主表")
    default_id = default_game_id or profiles[0].game_id
    cartridges = []
    for profile in profiles:
        path = documents[profile.game_id]
        payload = path.read_bytes()
        cartridges.append({
            "game_id": profile.game_id,
            "display_name": profile.display_name,
            "asset_name": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
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
) -> tuple[Path, ...]:
    """Write every client cartridge plus the hub index into ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    documents: dict[str, Path] = {}
    written: list[Path] = []
    for profile in profiles:
        path = write_client_cartridge_document(profile, output_dir)
        documents[profile.game_id] = path
        written.append(path)
    index = build_client_cartridge_index(
        profiles, documents=documents, default_game_id=default_game_id,
    )
    index_path = output_dir / INDEX_ASSET_NAME
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    written.append(index_path)
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
