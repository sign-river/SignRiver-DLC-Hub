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


def test_guide_tool_quick_check_declaration_is_platform_safe_and_non_interactive() -> None:
    tool = GuideTool.from_dict({
        "tool_id": "security-scan", "title": "安全软件扫描", "description": "",
        "asset_name": "security-scan.ps1", "platforms": ["windows"],
        "run_mode": "powershell", "quick_check": True,
        "quick_check_read_only": True,
        "quick_check_success": "未发现需要处理的项目。",
        "quick_check_problem_guide": "security-interference",
        "quick_check_timeout_seconds": 45,
    })

    assert tool.quick_check
    assert tool.quick_check_timeout_seconds == 45
    assert tool.quick_check_problem_guide == "security-interference"
    assert tool.applies_to("windows")
    assert not tool.applies_to("steamos")

    with pytest.raises(ValueError, match="explicitly read-only"):
        GuideTool.from_dict({
            "tool_id": "not-read-only", "title": "未声明", "description": "",
            "asset_name": "check.ps1", "platforms": ["windows"],
            "run_mode": "powershell", "quick_check": True,
        })

    with pytest.raises(ValueError, match="command run_mode"):
        GuideTool.from_dict({
            "tool_id": "graphic", "title": "图形工具", "description": "",
            "asset_name": "graphic.exe", "platforms": ["windows"],
            "quick_check": True,
        })
    with pytest.raises(ValueError, match="between 5 and 120"):
        GuideTool.from_dict({
            "tool_id": "bad-timeout", "title": "超时", "description": "",
            "asset_name": "check.ps1", "platforms": ["windows"],
            "run_mode": "powershell", "quick_check": True,
            "quick_check_read_only": True,
            "quick_check_timeout_seconds": 121,
        })


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


def test_invalid_cached_guide_detail_falls_back_to_bootstrap(tmp_path: Path) -> None:
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    entries = service.refresh_index(allow_network=False)
    entry = next(item for item in entries if item.guide_id == "network-basics")
    cached_detail = tmp_path / "cache" / entry.asset_name
    cached_detail.parent.mkdir(parents=True, exist_ok=True)
    cached_detail.write_text(
        json.dumps({"status": 404, "message": "not found"}), encoding="utf-8",
    )

    document = service.load_guide(entry, allow_network=False)

    assert document.entry.guide_id == "network-basics"
    assert document.blocks


def test_mismatched_cached_guide_detail_falls_back_to_bootstrap(tmp_path: Path) -> None:
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    entries = service.refresh_index(allow_network=False)
    entry = next(item for item in entries if item.guide_id == "network-basics")
    cached_detail = tmp_path / "cache" / entry.asset_name
    cached_detail.parent.mkdir(parents=True, exist_ok=True)
    cached_detail.write_text(
        json.dumps({"guide_id": "disk-space", "blocks": [], "tools": []}), encoding="utf-8",
    )

    document = service.load_guide(entry, allow_network=False)

    assert document.entry.guide_id == "network-basics"
    assert document.blocks


def test_windows_bootstrap_guides_include_close_windows_defender_helper_tool() -> None:
    service = GuideCatalogService(
        Path("unused-cache"), bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    entries = service.refresh_index(allow_network=False)
    ids = [entry.guide_id for entry in entries]
    assert "close-windows-defender" in ids
    assert "security-interference" in ids
    entry = next(item for item in entries if item.guide_id == "close-windows-defender")
    document = service.load_guide(entry, allow_network=False)
    assert document.entry.title == "关闭 Windows Defender 教程"
    assert document.tools
    tool = document.tools[0]
    assert tool.tool_id == "dcontrol"
    assert tool.release_tag == "tools"
    assert tool.package_kind == "zip"
    assert tool.launch_action == "exe"
    assert tool.executable_name == "dControl.exe"
    assert tool.run_as_admin
    assert tool.is_helper_tool()
    assert tool.applies_to("windows")
    assert not tool.applies_to("steamos")


def test_remote_guides_cannot_replace_builtin_guides_or_tools(tmp_path: Path) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "guides_index.json").write_text(json.dumps({
        "schema_version": 1,
        "guides": [{
            "guide_id": "base", "title": "内置", "summary": "",
            "asset_name": "guide_base.json", "platforms": ["all"],
        }],
    }), encoding="utf-8")
    (bootstrap / "guide_base.json").write_text(json.dumps({
        "guide_id": "base", "blocks": [{"kind": "text", "text": "内置正文"}],
        "tools": [{"tool_id": "base-tool", "title": "内置工具", "platforms": ["all"]}],
    }), encoding="utf-8")

    remote_index = json.dumps({
        "schema_version": 1,
        "guides": [
            {"guide_id": "base", "title": "云端覆盖", "summary": "", "asset_name": "guide_base_remote.json", "platforms": ["all"]},
            {"guide_id": "extra", "title": "扩展", "summary": "", "asset_name": "guide_extra.json", "platforms": ["all"]},
        ],
    }).encode()
    remote_details = {
        "guide_extra.json": json.dumps({
            "guide_id": "extra", "blocks": [{"kind": "text", "text": "扩展正文"}],
            "tools": [{"tool_id": "base-tool", "title": "云端同名工具", "platforms": ["all"]}],
        }).encode(),
    }
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=bootstrap, platform="windows",
        opener=lambda url, _timeout: remote_index if url.endswith("guides_index.json") else remote_details[Path(url).name],
    )
    entries = service.refresh_index(allow_network=True)
    assert [entry.guide_id for entry in entries] == ["base", "extra"]
    assert entries[0].builtin
    assert service.load_guide(entries[0], allow_network=True).blocks[0][1] == "内置正文"
    extra = service.load_guide(entries[1], allow_network=True)
    assert extra.blocks[0][1] == "扩展正文"
    assert not extra.tools


def test_guides_catalog_uses_dedicated_release_tag(tmp_path: Path) -> None:
    seen: list[str] = []
    payload = json.dumps({"schema_version": 1, "guides": []}).encode()

    def opener(url: str, _timeout: float) -> bytes:
        seen.append(url)
        return payload

    service = GuideCatalogService(tmp_path / "cache", platform="windows", opener=opener)
    service.refresh_index(allow_network=True)

    assert seen and "/releases/download/guides/guides_index.json" in seen[0]


def test_legacy_hub_guide_attachment_is_migrated_to_guides_release(tmp_path: Path) -> None:
    service = GuideCatalogService(tmp_path / "cache", platform="windows", opener=object())
    entry = service._parse_index_payload(json.dumps({
        "schema_version": 1,
        "guides": [{
            "guide_id": "legacy-guide", "title": "旧指南", "summary": "",
            "asset_name": "guide_legacy.json", "platforms": ["all"],
        }],
    }))[0]
    document = service._parse_guide_payload(entry, json.dumps({
        "guide_id": "legacy-guide", "blocks": [], "tools": [{
            "tool_id": "legacy-note", "title": "旧附件", "asset_name": "legacy.txt",
            "release_tag": "hub", "platforms": ["all"],
        }],
    }))
    assert document.tools[0].release_tag == "guides"


def test_builtin_guide_never_fetches_remote_detail(tmp_path: Path) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "guides_index.json").write_text(json.dumps({
        "schema_version": 1,
        "guides": [{
            "guide_id": "base", "title": "内置", "summary": "",
            "asset_name": "guide_base.json", "platforms": ["all"],
        }],
    }), encoding="utf-8")
    (bootstrap / "guide_base.json").write_text(json.dumps({
        "guide_id": "base", "blocks": [{"kind": "text", "text": "内置正文"}],
        "tools": [],
    }), encoding="utf-8")

    def opener(_url: str, _timeout: float) -> bytes:
        raise AssertionError("内置指南不应访问云端正文")

    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=bootstrap, opener=opener,
    )
    entry = service.refresh_index(allow_network=False)[0]
    document = service.load_guide(entry, allow_network=True)

    assert document.blocks == (("text", "内置正文"),)


def test_tools_catalog_is_independent_from_guides(tmp_path: Path) -> None:
    payload = json.dumps({
        "schema_version": 1,
        "tools": [{
            "tool_id": "standalone-tool", "title": "独立工具", "description": "",
            "asset_name": "standalone.zip", "filename": "standalone.zip",
            "platforms": ["all"], "package_kind": "zip",
            "launch_action": "open_folder", "release_tag": "tools",
        }],
    }).encode()
    seen: list[str] = []

    def opener(url: str, _timeout: float) -> bytes:
        seen.append(url)
        return payload

    service = GuideCatalogService(tmp_path / "cache", opener=opener)
    tools = service.refresh_tools(allow_network=True)

    assert [tool.tool_id for tool in tools] == ["standalone-tool"]
    assert "/releases/download/tools/tools_index.json" in seen[0]
