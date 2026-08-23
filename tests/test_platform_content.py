from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_app.application.cartridge_catalog import (
    CartridgeCatalogError,
    CartridgeCatalogService,
)
from signriver_app.application.guides import GuideCatalogError, GuideCatalogService, GuideTool
from signriver_app.domain import CartridgeIndexEntry, INDEX_ASSET_NAME
from signriver_publisher.client_cartridges import build_client_cartridge_index
from signriver_publisher.models import PublisherCartridge
from signriver_publisher.workspace import PublisherWorkspace

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "config" / "cartridges"
GUIDES = ROOT / "config" / "guides"


def test_patch_only_platform_resource_keeps_cartridge_available() -> None:
    entry = CartridgeIndexEntry.from_dict({
        "game_id": "civilization_7",
        "display_name": "文明7",
        "asset_name": "cartridge_civilization_7.json",
        "sha256": "a" * 64,
        "platform_resources": {"windows-x64": {"patch": True, "dlc": False}},
    })

    assert entry.is_available_on("windows")
    assert entry.resource_availability("windows-x64") == {
        "patch": True, "dlc": False,
    }
    assert not entry.is_available_on("steamos")


def test_catalog_hides_platform_without_published_resource(tmp_path: Path) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    for path in BOOTSTRAP.glob("*.json"):
        (bootstrap / path.name).write_bytes(path.read_bytes())
    index_path = bootstrap / INDEX_ASSET_NAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for entry in index["cartridges"]:
        entry["platform_resources"] = {"windows": {"patch": True, "dlc": True}}
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    service = CartridgeCatalogService(
        tmp_path / "cache", bootstrap_dir=bootstrap, source=object(),
        platform="steamos",
    )
    service.refresh_index(allow_network=False)

    assert service.selection_records() == ()
    with pytest.raises(CartridgeCatalogError, match="暂无已发布的 DLC 或补丁资源"):
        service.load_cartridge("stellaris", allow_network=False)


def test_publisher_index_keeps_built_in_dlc_game_patch_only(tmp_path: Path) -> None:
    profile = PublisherCartridge.from_dict({
        "game_id": "civilization_7",
        "display_name": "文明7",
        "store_app_id": "1295660",
        "release_tag": "civilization_7",
        "executable_relative_path": "game.exe",
        "dlc_relative_dir": "DLC",
        "dlc_delivery_mode": "built_in",
        "package_inspector": "directory",
        "patch_unlocker_name": "steam_api64.dll",
        "patch_runtime_original_name": "steam_api64_o.dll",
        "appinfo_name": "civilization_7_appinfo.json",
    })
    document = tmp_path / "cartridge_civilization_7.json"
    document.write_text("{}", encoding="utf-8")

    index = build_client_cartridge_index(
        (profile,), documents={profile.game_id: document},
    )

    availability = index["cartridges"][0]["platform_resources"]
    assert availability == {"windows": {"patch": True, "dlc": False}}


def test_direct_publisher_index_fallback_does_not_assume_declared_native_assets(
    tmp_path: Path,
) -> None:
    profile = PublisherCartridge.from_dict({
        "game_id": "test_game",
        "display_name": "测试游戏",
        "release_tag": "test_game",
        "appinfo_name": "test_game_appinfo.json",
        "executable_relative_path": "game.exe",
        "dlc_relative_dir": "DLC",
        "patch_platforms": {"steamos": {"executable_relative_path": "game"}},
    })
    document = tmp_path / "cartridge_test_game.json"
    document.write_text("{}", encoding="utf-8")

    index = build_client_cartridge_index(
        (profile,), documents={profile.game_id: document},
    )

    assert index["cartridges"][0]["platform_resources"] == {
        "windows": {"patch": True, "dlc": True}
    }


def test_guide_catalog_filters_platforms_and_keeps_tools_on_demand(tmp_path: Path) -> None:
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=GUIDES, platform="steamos", opener=object(),
    )
    entries = service.refresh_index(allow_network=False)

    assert [entry.guide_id for entry in entries] == [
        "network-basics", "game-directory-missing", "disk-space", "patch-state",
        "patch-assets-missing", "update-module-basics",
    ]
    document = service.load_guide(entries[0], allow_network=False)
    assert document.blocks
    windows_tool = GuideTool.from_dict({
        "tool_id": "windows-repair",
        "title": "Windows 修复",
        "description": "仅 Windows",
        "download_url": "https://example.invalid/tool.ps1",
        "filename": "tool.ps1",
        "platforms": ["windows"],
        "run_mode": "powershell",
    })
    assert not windows_tool.applies_to("steamos")


def test_workspace_exports_only_cloud_confirmed_resources(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = PublisherCartridge.from_dict({
        "game_id": "test_game",
        "display_name": "测试游戏",
        "release_tag": "test_game",
        "appinfo_name": "test_game_appinfo.json",
        "executable_relative_path": "game.exe",
        "dlc_relative_dir": "DLC",
        "patch_platforms": {"steamos": {"executable_relative_path": "game"}},
    })
    workspace.save_game(profile)

    # A declared SteamOS variant is not enough: without a successful cloud
    # publish record it must not be exported as available.
    assert workspace.published_platform_resources(profile) == {}

    workspace.save_publish_state(profile, {
        "version": 1,
        "owner": "signriver",
        "repository": "signriver-dlc-assets",
        "release_tag": profile.release_tag,
        "assets": {
            "unlocker.dll": {}, "original.dll": {},
            profile.appinfo_name: {}, "dlc001_test.zip": {},
        },
    })
    assert workspace.published_platform_resources(profile) == {
        "windows": {"patch": True, "dlc": True},
    }

    explicit = PublisherCartridge.from_dict({
        **profile.to_dict(),
        "published_platform_resources": {
            "windows": {"patch": True, "dlc": True},
            "steamos": {"patch": False, "dlc": True},
        },
    })
    assert workspace.published_platform_resources(explicit) == {
        "windows": {"patch": True, "dlc": True},
        "steamos": {"patch": False, "dlc": True},
    }


def test_publisher_index_uses_explicit_cloud_resource_map(tmp_path: Path) -> None:
    profile = PublisherCartridge.from_dict({
        "game_id": "test_game",
        "display_name": "测试游戏",
        "release_tag": "test_game",
        "appinfo_name": "test_game_appinfo.json",
        "executable_relative_path": "game.exe",
        "dlc_relative_dir": "DLC",
    })
    document = tmp_path / "cartridge_test_game.json"
    document.write_text("{}", encoding="utf-8")
    index = build_client_cartridge_index(
        (profile,), documents={profile.game_id: document},
        resource_availability_by_game={
            profile.game_id: {"steamos": {"patch": False, "dlc": True}}
        },
    )
    assert index["cartridges"][0]["platform_resources"] == {
        "steamos": {"patch": False, "dlc": True}
    }


def test_guide_tool_download_is_platform_safe_and_atomic(tmp_path: Path) -> None:
    payload = b"Write-Output repaired"
    service = GuideCatalogService(
        tmp_path / "cache", platform="windows",
        opener=lambda _url, _timeout: payload,
    )
    tool = GuideTool.from_dict({
        "tool_id": "repair", "title": "修复", "description": "",
        "download_url": "https://example.invalid/repair.ps1",
        "filename": "repair.ps1", "platforms": ["all"],
        "run_mode": "powershell",
    })
    target = service.download_tool(tool)
    assert target.read_bytes() == payload
    assert not target.with_name(f".{target.name}.part").exists()

    asset_tool = GuideTool.from_dict({
        "tool_id": "official-note", "title": "官方附件", "description": "",
        "asset_name": "guide_network_note.txt", "platforms": ["all"],
    })
    asset_target = service.download_tool(asset_tool)
    assert asset_target.name == "guide_network_note.txt"
    assert asset_target.read_bytes() == payload

    linux_service = GuideCatalogService(tmp_path / "linux", platform="steamos")
    assert not tool.applies_to("steamos")
    with pytest.raises(GuideCatalogError, match="不适用于当前平台"):
        linux_service.download_tool(tool)

    insecure = GuideTool.from_dict({
        "tool_id": "bad", "title": "不安全", "description": "",
        "download_url": "http://example.invalid/bad", "filename": "bad",
        "platforms": ["windows"], "run_mode": "open",
    })
    with pytest.raises(GuideCatalogError, match="HTTPS"):
        service.download_tool(insecure)
