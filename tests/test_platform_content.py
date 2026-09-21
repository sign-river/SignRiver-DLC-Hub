from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from signriver_app.application.cartridge_catalog import (
    CartridgeCatalogError,
    CartridgeCatalogService,
)
from signriver_app.application.guides import GuideCatalogError, GuideCatalogService, GuideIndexEntry, GuideTool, resolve_bootstrap_dir
from signriver_app.adapters.document_cartridge import build_cartridge_from_document
from signriver_app.domain import CartridgeDocument, CartridgeIndexEntry, INDEX_ASSET_NAME
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
        "patch_assets_missing", "update-module-basics",
        "steamos-app-permission", "steamos-proton-native",
    ]
    windows_entries = GuideCatalogService(
        tmp_path / "windows-cache", bootstrap_dir=GUIDES, platform="windows", opener=object(),
    ).refresh_index(allow_network=False)
    security_entry = next(entry for entry in windows_entries if entry.guide_id == "security-interference")
    assert security_entry.title == "杀毒软件隔离、拦截或删除文件问题"
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


@pytest.mark.parametrize(
    ("platform", "native_marker", "forbidden_marker"),
    (
        ("steamos", "原生 `.so`", "unlock.dll"),
        ("macos", "原生 `.dylib`", "unlock.dll"),
    ),
)
def test_native_platform_guides_describe_native_assets_only(
    tmp_path: Path, platform: str, native_marker: str, forbidden_marker: str,
) -> None:
    service = GuideCatalogService(
        tmp_path / f"{platform}-cache", bootstrap_dir=GUIDES, platform=platform,
    )
    entries = service.refresh_index(allow_network=False)
    patch_entry = next(item for item in entries if item.guide_id == "patch-state")
    directory_entry = next(item for item in entries if item.guide_id == "game-directory-missing")
    patch_text = "\n".join(
        block[1] for block in service.load_guide(patch_entry, allow_network=False).blocks
        if block[0] == "text"
    )
    directory_text = "\n".join(
        block[1] for block in service.load_guide(directory_entry, allow_network=False).blocks
        if block[0] == "text"
    )

    assert native_marker in patch_text
    assert forbidden_marker not in patch_text
    expected_label = "SteamOS" if platform == "steamos" else "macOS"
    assert expected_label in patch_entry.title
    assert expected_label in directory_entry.title
    assert "游戏根目录" in directory_text


def test_update_guide_mentions_code_issue_and_both_latest_package_sources(tmp_path: Path) -> None:
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    entry = next(
        item for item in service.refresh_index(allow_network=False)
        if item.guide_id == "update-module-basics"
    )
    document = service.load_guide(entry, allow_network=False)
    text = "\n".join(block[1] for block in document.blocks if block[0] == "text")
    targets = {block[2] for block in document.blocks if block[0] == "button"}

    assert "程序代码中的兼容性问题" in text
    assert "tool:latest-installer" in targets
    assert sum(block[1] == "仍无法解决时" for block in document.blocks if block[0] == "heading") == 1


def test_paradox_launcher_guides_include_warning_flow_and_installer_fallback(tmp_path: Path) -> None:
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    entries = service.refresh_index(allow_network=False)
    warning = service.load_guide(
        next(item for item in entries if item.guide_id == "paradox-launcher-dlc-warning"),
        allow_network=False,
    )
    steam_error = service.load_guide(
        next(item for item in entries if item.guide_id == "paradox-launcher-steam-error"),
        allow_network=False,
    )
    warning_text = "\n".join(block[1] for block in warning.blocks if block[0] == "text")
    steam_text = "\n".join(block[1] for block in steam_error.blocks if block[0] == "text")
    warning_targets = {block[2] for block in warning.blocks if block[0] == "button"}
    steam_targets = {block[2] for block in steam_error.blocks if block[0] == "button"}
    assert "正常现象" in warning_text and "不影响 DLC 使用" in warning_text
    assert {Path(block[1]).name for block in warning.blocks if block[0] == "image"} >= {
        "paradox-launcher-warning.png", "paradox-launcher-versions.png",
    }
    assert "Steam 运行时通讯错误" in steam_text
    assert warning_targets == {"tool:paradox-launcher-warning"}
    assert steam_targets == {"tool:paradox-launcher-warning", "tool:paradox-launcher-installer"}


def test_graphics_guide_explains_dxdiag_check_and_repair_with_current_images(tmp_path: Path) -> None:
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    entry = next(
        item for item in service.refresh_index(allow_network=False)
        if item.guide_id == "graphics-device-compatibility"
    )
    document = service.load_guide(entry, allow_network=False)
    text = "\n".join(block[1] for block in document.blocks if block[0] == "text")
    images = {Path(block[1]).name for block in document.blocks if block[0] == "image"}
    targets = {block[2] for block in document.blocks if block[0] == "button"}

    assert "打开 DirectX 诊断工具" in text
    assert "DirectDraw 加速" in text and "Direct3D 加速" in text
    assert "未启用" in text and "修复图形设备配置" in text
    assert "不代表所有启动失败" not in text
    assert "修复失败或仍无法启动" not in text
    assert images == {"graphics-device-dxdiag-display.png", "graphics-device-repair.png"}
    assert "tool:graphics-compatibility" in targets
    assert "tool:support-collection" not in targets


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


def test_guide_tool_detail_is_declarative_and_limits_buttons_to_safe_actions() -> None:
    tool = GuideTool.from_dict({
        "tool_id": "save-repair", "title": "存档修复", "description": "修复存档。",
        "asset_name": "save-repair.zip", "platforms": ["windows"],
        "package_kind": "zip", "launch_action": "open_folder", "release_tag": "tools",
        "detail": {
            "intro": "仅处理用户主动选择的存档。",
            "warnings": ["先备份存档。", "不会上传文件。"],
            "buttons": [
                {"action": "open_guide", "label": "查看教程", "guide_id": "save-repair-guide"},
                {"action": "open_url", "label": "项目主页", "url": "https://example.invalid/tool"},
                {"action": "open_folder", "label": "打开工具目录"},
            ],
        },
    })

    assert tool.detail_intro == "仅处理用户主动选择的存档。"
    assert tool.detail_warnings == ("先备份存档。", "不会上传文件。")
    assert [item.action for item in tool.detail_actions] == [
        "open_guide", "open_url", "open_folder",
    ]
    with pytest.raises(ValueError, match="unsupported tool detail button action"):
        GuideTool.from_dict({
            "tool_id": "unsafe-detail", "title": "不安全", "description": "",
            "asset_name": "tool.zip", "platforms": ["windows"],
            "detail": {"buttons": [{"action": "run_command", "label": "执行"}]},
        })
    with pytest.raises(ValueError, match="must be HTTPS"):
        GuideTool.from_dict({
            "tool_id": "http-detail", "title": "不安全", "description": "",
            "asset_name": "tool.zip", "platforms": ["windows"],
            "detail": {"buttons": [{"action": "open_url", "label": "打开", "url": "http://example.invalid"}]},
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
    assert any("部分运营商提供的网络可能无法正常登录或连接 GitLink" in block[1] for block in document.blocks if block[0] == "text")


def test_remote_guide_image_is_downloaded_and_cached_per_guide(tmp_path: Path) -> None:
    image_bytes = b"fake-png"

    entry = GuideIndexEntry.from_dict({
        "guide_id": "remote-image",
        "title": "图片指南",
        "summary": "",
        "asset_name": "remote-image.json",
        "platforms": ["all"],
    })
    payload = json.dumps({
        "guide_id": "remote-image",
        "blocks": [{"kind": "image", "asset_name": "guide-image.png"}],
        "tools": [],
    })
    def opener(url: str, _timeout: float) -> bytes:
        if url.endswith("remote-image.json"):
            return payload.encode()
        return image_bytes if url.endswith("guide-image.png") else b""

    service = GuideCatalogService(tmp_path / "cache", opener=opener)
    with pytest.raises(GuideCatalogError):
        service.load_guide(entry, allow_network=True)


def test_guide_internal_navigation_buttons_are_whitelisted(tmp_path: Path) -> None:
    service = GuideCatalogService(tmp_path / "cache")
    entry = GuideIndexEntry.from_dict({
        "guide_id": "navigation",
        "title": "导航",
        "summary": "",
        "asset_name": "navigation.json",
        "platforms": ["all"],
    })
    document = service._parse_guide_payload(entry, json.dumps({
        "guide_id": "navigation",
        "blocks": [
            {"kind": "button", "text": "补丁工具", "target": "patch-tool"},
            {"kind": "button", "text": "安全软件", "target": "guide:security-interference"},
            {"kind": "button", "text": "工具详情", "target": "tool:dcontrol"},
            {"kind": "button", "text": "危险命令", "target": "cmd:del"},
        ],
        "tools": [],
    }))
    assert document.blocks == (
        ("button", "补丁工具", "patch-tool"),
        ("button", "安全软件", "guide:security-interference"),
        ("button", "工具详情", "tool:dcontrol"),
    )


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
    assert tool.requires_cloud_download
    assert tool.is_helper_tool()
    assert tool.applies_to("windows")
    assert not tool.applies_to("steamos")
    assert document.blocks[0] == ("heading", "建议操作")
    assert ("button", "进入关闭 Windows Defender 工具界面 →", "tool:dcontrol") in document.blocks
    image_blocks = [block for block in document.blocks if block[0] == "image"]
    assert {Path(block[1]).name for block in image_blocks} >= {
        "defender-download.png", "defender-launch.png", "defender-control.png",
    }
    assert "弹出权限请求，正常授予即可" in document.blocks[1][1]
    assert not any(block[0] == "heading" and block[1] == "常见原因" for block in document.blocks)
    assert not any(block[0] == "heading" and block[1] == "注意事项" for block in document.blocks)


def test_security_interference_guide_explains_open_source_false_positive_and_github() -> None:
    service = GuideCatalogService(
        Path("unused-cache"), bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    entries = service.refresh_index(allow_network=False)
    entry = next(item for item in entries if item.guide_id == "security-interference")
    document = service.load_guide(entry, allow_network=False)
    assert any("自行开发并开源" in block[1] and "误判" in block[1] for block in document.blocks if block[0] == "text")
    assert ("button", "进入杀毒软件检测工具 →", "tool:security-products") in document.blocks
    assert ("image", str(GUIDES / "assets" / "security-products-list.png")) in document.blocks
    assert ("image", str(GUIDES / "assets" / "windows-defender-history.png")) in document.blocks
    assert ("button", "查看关闭 Windows Defender 指南 →", "guide:close-windows-defender") in document.blocks


def test_guide_tool_can_be_marked_as_not_requiring_cloud_download() -> None:
    tool = GuideTool.from_dict({
        "tool_id": "local-check",
        "title": "本地检查",
        "description": "",
        "platforms": ["windows"],
        "requires_cloud_download": False,
    })
    assert not tool.requires_cloud_download


def test_guide_tool_requires_cloud_download_must_be_boolean() -> None:
    with pytest.raises(ValueError, match="requires_cloud_download"):
        GuideTool.from_dict({
            "tool_id": "invalid-check",
            "title": "无效检查",
            "description": "",
            "platforms": ["windows"],
            "requires_cloud_download": "false",
        })


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
    assert [entry.guide_id for entry in entries] == ["base"]
    assert entries[0].builtin
    assert service.load_guide(entries[0], allow_network=True).blocks[0][1] == "内置正文"
    with pytest.raises(IndexError):
        _ = entries[1]


def test_guides_catalog_uses_dedicated_release_tag(tmp_path: Path) -> None:
    seen: list[str] = []
    payload = json.dumps({"schema_version": 1, "guides": []}).encode()

    def opener(url: str, _timeout: float) -> bytes:
        seen.append(url)
        return payload

    service = GuideCatalogService(tmp_path / "cache", platform="windows", opener=opener)
    service.refresh_index(allow_network=True)

    assert seen == []


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


def test_missing_optional_tools_index_does_not_emit_terminal_warning(tmp_path: Path, caplog) -> None:
    def opener(_url: str, _timeout: float) -> bytes:
        raise GuideCatalogError("资源不存在；详情：HTTP Error 404: Not Found")

    service = GuideCatalogService(tmp_path / "cache", opener=opener)
    with caplog.at_level(logging.DEBUG, logger="signriver_app.application.guides"):
        assert service.refresh_tools(allow_network=True) == ()

    assert caplog.text == ""
    assert not [
        record for record in caplog.records
        if record.levelno >= logging.WARNING
        and "Guide resource unavailable" in record.getMessage()
    ]


def test_remote_empty_tools_index_removes_downloaded_tool_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "tools_index.json").write_text(json.dumps({
        "schema_version": 1,
        "tools": [{
            "tool_id": "old-tool", "title": "旧工具", "description": "",
            "asset_name": "old-tool.zip", "filename": "old-tool.zip",
            "platforms": ["all"], "package_kind": "zip",
            "launch_action": "open_folder", "release_tag": "tools",
        }],
    }), encoding="utf-8")
    old_tool = cache / "tools" / "old-tool"
    old_tool.mkdir(parents=True)
    (old_tool / "old-tool.zip").write_bytes(b"cached")

    service = GuideCatalogService(
        cache, opener=lambda _url, _timeout: json.dumps({
            "schema_version": 1, "tools": [],
        }).encode(),
    )

    assert service.refresh_tools(allow_network=True) == ()
    assert old_tool.exists()


def test_remote_empty_guide_index_removes_cached_guide_detail(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "guides_index.json").write_text(json.dumps({
        "schema_version": 1,
        "guides": [{
            "guide_id": "old-guide", "title": "旧指南", "summary": "",
            "asset_name": "old-guide.json", "platforms": ["all"],
        }],
    }), encoding="utf-8")
    detail = cache / "old-guide.json"
    detail.write_text("{}", encoding="utf-8")

    service = GuideCatalogService(
        cache, opener=lambda _url, _timeout: json.dumps({
            "schema_version": 1, "guides": [],
        }).encode(),
    )

    assert service.refresh_index(allow_network=True) == ()
    assert detail.exists()


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

    assert tools == ()
    assert seen == []


def test_every_guide_referenced_by_the_client_exists(tmp_path: Path) -> None:
    app_entry = (ROOT / "app" / "versions" / "0.1.0" / "app_entry.py").read_text(encoding="utf-8")
    referenced = set(re.findall(r'_open_solution_article\("([a-z0-9_-]+)"', app_entry))
    service = GuideCatalogService(
        tmp_path / "cache", bootstrap_dir=GUIDES, platform="windows", opener=object(),
    )
    available = {entry.guide_id for entry in service.refresh_index(allow_network=False)}
    assert referenced
    assert referenced <= available


def test_native_platform_guides_cover_blocked_app_and_proton(tmp_path: Path) -> None:
    expectations = {
        "macos": ("macos-app-blocked", ("隐私与安全性", "仍要打开")),
        "macos-proton": ("macos-game-not-unlocked", ("补丁工具", "一键解锁")),
        "steamos": ("steamos-proton-native", ("Proton", "属性")),
        "steamos-permission": ("steamos-app-permission", ("执行", "桌面模式")),
    }
    for label, (guide_id, markers) in expectations.items():
        platform = label.split("-", 1)[0]
        service = GuideCatalogService(
            tmp_path / label, bootstrap_dir=GUIDES, platform=platform, opener=object(),
        )
        entries = service.refresh_index(allow_network=False)
        entry = next(item for item in entries if item.guide_id == guide_id)
        document = service.load_guide(entry, allow_network=False)
        text = "\n".join(block[1] for block in document.blocks if block[0] == "text")
        assert text
        assert all(marker in text for marker in markers), (guide_id, text)


def test_guides_bootstrap_dir_selects_a_directory_that_really_has_the_index(tmp_path: Path) -> None:
    packaged = tmp_path / "bundle" / "config" / "guides"
    packaged.mkdir(parents=True)
    (packaged / "guides_index.json").write_text("{}", encoding="utf-8")
    writable = tmp_path / "data-home" / "config" / "guides"

    assert resolve_bootstrap_dir(packaged, writable) == packaged
    assert resolve_bootstrap_dir(writable, packaged) == packaged
    assert resolve_bootstrap_dir(writable) == writable
    assert resolve_bootstrap_dir(None, None) is None


def test_client_resolves_guides_from_the_packaged_app_bundle() -> None:
    for version in ("0.1.0", "0.2.0"):
        source = (ROOT / "app" / "versions" / version / "app_entry.py").read_text(encoding="utf-8")
        assert "def _guide_bootstrap_candidates(self) -> tuple[Path, ...]:" in source
        assert 'install / "Contents" / "Resources" / "runtime" / "config" / "guides"' in source
        assert 'Path(paths.root) / "config" / "guides"' in source
        ctor = source.split("self.guide_catalog = GuideCatalogService(", 1)[1].split(
            "self.helper_tools =", 1
        )[0]
        assert "bootstrap_dir=resolve_bootstrap_dir(*self._guide_bootstrap_candidates())" in ctor


def _build_macos_cities_tree(root: Path) -> None:
    """Recreate the real Cities: Skylines macOS layout observed on the test VM."""
    macos = root / "Cities.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "Cities").write_bytes(b"exe")
    files = root / "Cities.app" / "Contents" / "Resources" / "Files"
    (files / "Radio").mkdir(parents=True)
    plugins = root / "Cities.app" / "Contents" / "Plugins" / "ColossalNative.bundle" / "Contents" / "MacOS"
    plugins.mkdir(parents=True)
    (plugins / "libsteam_api.dylib").write_bytes(b"steam")


def _cities_cartridge(platform: str):
    document = json.loads(
        (ROOT / "config" / "cartridges" / "cartridge_cities_skylines.json").read_text(encoding="utf-8")
    )
    return build_cartridge_from_document(CartridgeDocument.from_dict(document), platform=platform)


def test_cities_skylines_macos_layout_is_declared_with_app_bundle_paths(tmp_path: Path) -> None:
    document = json.loads(
        (ROOT / "config" / "cartridges" / "cartridge_cities_skylines.json").read_text(encoding="utf-8")
    )
    macos = document["patch"]["platforms"]["macos"]

    assert macos["executable_relative_path"] == "Cities.app/Contents/MacOS/Cities"
    assert macos["dlc_relative_dir"] == "Cities.app/Contents/Resources/Files"
    assert macos["install_relative_dir"] == (
        "Cities.app/Contents/Plugins/ColossalNative.bundle/Contents/MacOS"
    )
    assert document["dlc_relative_dir"] == "Files", "Windows 目录布局不能被改动"


def test_cities_skylines_macos_validation_accepts_real_app_bundle_layout(tmp_path: Path) -> None:
    root = tmp_path / "Cities_Skylines"
    _build_macos_cities_tree(root)
    cartridge = _cities_cartridge("macos")

    validation = cartridge.adapter.validate(root)

    assert validation.valid, validation.errors
    assert validation.executable == root / "Cities.app" / "Contents" / "MacOS" / "Cities"


def test_cities_skylines_macos_validation_rejects_flat_windows_style_root(tmp_path: Path) -> None:
    """A root without the app bundle (old Windows-style layout) must not validate."""
    root = tmp_path / "Cities_Skylines"
    (root / "Files").mkdir(parents=True)
    (root / "Cities.exe").write_bytes(b"exe")
    cartridge = _cities_cartridge("macos")

    validation = cartridge.adapter.validate(root)

    assert not validation.valid
    assert any("Cities.app/Contents/MacOS/Cities" in item for item in validation.errors)


def test_cities_skylines_macos_missing_dlc_dir_is_only_a_warning(tmp_path: Path) -> None:
    """启动文件存在时，DLC 目录声明错误不应再表现成“找不到游戏根目录”。"""
    root = tmp_path / "Cities_Skylines"
    macos = root / "Cities.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "Cities").write_bytes(b"exe")  # 只有可执行文件，没有 Resources/Files
    cartridge = _cities_cartridge("macos")

    validation = cartridge.adapter.validate(root)

    assert validation.valid, validation.errors
    assert any("未找到必要目录" in item for item in validation.warnings)


def test_cities_index_only_claims_platforms_that_are_actually_published() -> None:
    index = json.loads(
        (ROOT / "config" / "cartridges" / "cartridges_index.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in index["cartridges"] if item["game_id"] == "cities_skylines")

    assert entry["platform_resources"] == {
        "windows": {"patch": True, "dlc": True},
        "macos": {"patch": True, "dlc": True},
    }, "未上传 SteamOS 资源时不得声明 steamos 可用"


def test_macos_cartridges_use_library_only_patch_layout() -> None:
    """macOS 使用替换型解锁库：只换库文件，不再生成配置文件。"""
    documents = sorted((ROOT / "config" / "cartridges").glob("cartridge_*.json"))

    assert documents, "未找到卡带文档"
    checked = 0
    for path in documents:
        document = json.loads(path.read_text(encoding="utf-8"))
        macos = document.get("patch", {}).get("platforms", {}).get("macos")
        if macos is None:
            continue
        checked += 1
        assert macos.get("config_format") == "none", path.name
        assert macos.get("ini_target_name") == "icecream.ini", path.name
        assert macos.get("unlocker_dll_name") == "libsteam_api.dylib", path.name
        assert (
            macos.get("runtime_original_library_name") == "libsteam_api_o.dylib"
        ), path.name

    assert checked == 5, "macOS 卡带数量变化时请同步更新本用例"


def test_game_detection_failure_shows_the_specific_reason() -> None:
    source = (ROOT / "app" / "versions" / "0.1.0" / "app_entry.py").read_text(encoding="utf-8")
    block = source.split('self.game_status.configure(text="未检测到有效安装")', 1)[1].split(
        "installation = next(", 1
    )[0]

    assert "issue.adapter_id == self.cartridge.adapter.descriptor.adapter_id" in block
    assert "检测失败原因：" in block
