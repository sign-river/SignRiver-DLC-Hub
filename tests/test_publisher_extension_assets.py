from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_publisher.extension_assets import ExtensionExportError
from signriver_publisher.workspace import PublisherWorkspace


def _write_extension_source(
    workspace: PublisherWorkspace, *, tool_id: str = "sample-tool",
    reference: dict[str, object] | None = None, include_package: bool = True,
) -> None:
    guides = workspace.guides_source_dir
    tools = workspace.tools_source_dir
    guides.mkdir(parents=True, exist_ok=True)
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "assets").mkdir(exist_ok=True)
    (guides / "guides_index.json").write_text(
        json.dumps({
            "schema_version": 1,
            "guides": [{
                "guide_id": "sample-guide",
                "title": "样例指南",
                "summary": "说明",
                "summary_type": "problem_detail",
                "asset_name": "guide_sample.json",
                "platforms": ["all"],
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    tool_reference = reference or {"tool_id": tool_id, "release_tag": "tools"}
    (guides / "guide_sample.json").write_text(
        json.dumps({
            "guide_id": "sample-guide",
            "blocks": [{"kind": "text", "text": "说明"}],
            "tools": [tool_reference],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    package = "sample-tool.zip"
    (tools / "tools_index.json").write_text(
        json.dumps({
            "schema_version": 1,
            "tools": [{
                "tool_id": tool_id,
                "title": "样例工具",
                "description": "用于发布预检测试。",
                "asset_name": package,
                "filename": package,
                "revision": "2026.08.25.1",
                "platforms": ["all"],
                "package_kind": "zip",
                "launch_action": "open_folder",
                "release_tag": "tools",
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    if include_package:
        (tools / "assets" / package).write_bytes(b"sample tool package")


def test_extension_publish_assets_materialises_guides_and_tools(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace)

    plan = workspace.extension_publish_assets()

    assert {asset.name for asset in plan.guides} == {
        "guides_index.json", "guide_sample.json",
    }
    assert {asset.name for asset in plan.tools} == {"sample-tool.zip"}
    assert plan.summary.status_text == "指南 已发现 1 篇文章、0 个附件；工具 已发现 1 个工具"
    profile = workspace.tools_release_profile()
    assert profile.release_tag == "tools"
    assert profile.appinfo_name == "tools_index.json"


def test_extension_preflight_requires_problem_detail_summary_type(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace)
    index_path = workspace.guides_source_dir / "guides_index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["guides"][0].pop("summary_type")
    index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ExtensionExportError, match="summary_type 必须为 problem_detail"):
        workspace.extension_publish_assets()


def test_extension_preflight_rejects_missing_tool_reference(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace, reference={"tool_id": "missing-tool", "release_tag": "tools"})

    with pytest.raises(ExtensionExportError, match="不存在于 tools_index.json"):
        workspace.extension_publish_assets()


def test_extension_preflight_rejects_missing_tool_package(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace, include_package=False)

    with pytest.raises(ExtensionExportError, match="工具包不存在"):
        workspace.extension_publish_assets()


def test_extension_preflight_rejects_inconsistent_guide_metadata(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(
        workspace,
        reference={
            "tool_id": "sample-tool",
            "release_tag": "tools",
            "revision": "different",
        },
    )

    with pytest.raises(ExtensionExportError, match="revision 与 tools_index.json 不一致"):
        workspace.extension_publish_assets()


def test_extension_preflight_rejects_non_boolean_download_requirement(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace)
    index = workspace.tools_source_dir / "tools_index.json"
    payload = json.loads(index.read_text(encoding="utf-8"))
    payload["tools"][0]["requires_cloud_download"] = "false"
    index.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ExtensionExportError, match="requires_cloud_download 必须是布尔值"):
        workspace.extension_publish_assets()


def test_extension_preflight_rejects_inconsistent_download_requirement(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(
        workspace,
        reference={
            "tool_id": "sample-tool",
            "release_tag": "tools",
            "requires_cloud_download": False,
        },
    )

    with pytest.raises(ExtensionExportError, match="requires_cloud_download 与 tools_index.json 不一致"):
        workspace.extension_publish_assets()


def test_extension_preflight_allows_unreferenced_tools(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace, reference={"tool_id": "sample-tool", "release_tag": "hub"})

    plan = workspace.extension_publish_assets()

    assert {asset.name for asset in plan.tools} == {"sample-tool.zip"}


def test_changed_publish_assets_uses_only_local_successful_hashes(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace)
    plan = workspace.extension_publish_assets()
    profile = workspace.tools_release_profile()

    assert workspace.changed_publish_assets(profile, "owner", "repository", plan.tools) == plan.tools

    workspace.save_publish_state(
        profile, workspace.publish_state_for_assets(profile, "owner", "repository", plan.tools)
    )
    assert workspace.changed_publish_assets(profile, "owner", "repository", plan.tools) == ()

    changed_path = workspace.tools_source_dir / "assets" / "sample-tool.zip"
    changed_path.write_bytes(b"changed tool package")
    changed_plan = workspace.extension_publish_assets()
    changed = workspace.changed_publish_assets(profile, "owner", "repository", changed_plan.tools)

    assert [asset.name for asset in changed] == ["sample-tool.zip"]


def test_sync_local_guides_and_tools_writes_client_definitions(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_extension_source(workspace)
    target = tmp_path / "client-config" / "guides"

    from signriver_publisher.extension_assets import sync_local_client_resources
    written = sync_local_client_resources(
        workspace.guides_source_dir, workspace.tools_source_dir, target
    )

    assert {path.name for path in written} == {
        "guides_index.json", "guide_sample.json", "tools_index.json",
    }
    assert (target / "tools_index.json").is_file()
