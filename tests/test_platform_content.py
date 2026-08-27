from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from signriver_app.application.cartridge_catalog import (
    CartridgeCatalogError,
    CartridgeCatalogService,
)
from signriver_app.application.guides import GuideCatalogError, GuideCatalogService, GuideIndexEntry, GuideTool
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
        "update-module-basics",
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
    assert image_blocks and image_blocks[0][1].endswith("defender-control.png")
    assert not any(block[0] == "heading" and block[1] == "常见原因" for block in document.blocks)
    assert not any(block[0] == "heading" and block[1] == "注意事项" for block in document.blocks)


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
