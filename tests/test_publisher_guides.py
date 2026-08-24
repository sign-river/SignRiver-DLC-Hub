from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_publisher.client_guides import GuideExportError, export_hub_guides, inspect_hub_guides
from signriver_publisher.workspace import PublisherWorkspace


def _write_guide_source(root: Path, *, include_attachment: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(exist_ok=True)
    (root / "guides_index.json").write_text(json.dumps({
        "schema_version": 1,
        "guides": [{
            "guide_id": "network-basics", "title": "网络", "summary": "说明",
            "asset_name": "guide_network.json", "platforms": ["all"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "guide_network.json").write_text(json.dumps({
        "guide_id": "network-basics",
        "blocks": [{"kind": "text", "text": "说明"}],
        "tools": [{
            "tool_id": "network-note", "title": "网络说明", "asset_name": "guide_network_note.txt",
            "platforms": ["all"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    if include_attachment:
        (root / "assets" / "guide_network_note.txt").write_text("note", encoding="utf-8")


def test_export_hub_guides_copies_documents_and_cleans_only_previous_guide_assets(tmp_path: Path) -> None:
    source = tmp_path / "guides"
    output = tmp_path / "hub"
    output.mkdir()
    (output / "cartridges_index.json").write_text("{}", encoding="utf-8")
    _write_guide_source(source)

    written = export_hub_guides(source, output)

    assert {path.name for path in written} == {
        "guides_index.json", "guide_network.json", "guide_network_note.txt",
    }
    assert inspect_hub_guides(source).status_text == "已发现 1 篇文章、1 个附件"
    assert (output / "cartridges_index.json").is_file()

    (source / "guides_index.json").unlink()
    assert export_hub_guides(source, output) == ()
    assert not (output / "guides_index.json").exists()
    assert not (output / "guide_network.json").exists()
    assert not (output / "guide_network_note.txt").exists()
    assert (output / "cartridges_index.json").is_file()


def test_export_hub_guides_rejects_missing_attachment_and_collisions(tmp_path: Path) -> None:
    source = tmp_path / "guides"
    output = tmp_path / "hub"
    _write_guide_source(source, include_attachment=False)

    with pytest.raises(GuideExportError, match="指南附件不存在"):
        export_hub_guides(source, output)

    _write_guide_source(source)
    output.mkdir(exist_ok=True)
    (output / "guide_network_note.txt").write_text("other", encoding="utf-8")
    with pytest.raises(GuideExportError, match="重名"):
        export_hub_guides(source, output)


def test_workspace_hub_assets_include_configured_guides(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    _write_guide_source(workspace.guides_source_dir)

    assets = workspace.hub_publish_assets(default_game_id="stellaris")

    assert {asset.name for asset in assets}.issuperset({
        "guides_index.json", "guide_network.json", "guide_network_note.txt",
    })


def test_export_hub_guides_skips_tools_release_attachments(tmp_path: Path) -> None:
    source = tmp_path / "guides"
    output = tmp_path / "hub"
    source.mkdir()
    (source / "guides_index.json").write_text(
        json.dumps({
            "schema_version": 1,
            "guides": [{
                "guide_id": "close-windows-defender",
                "title": "关闭 Windows Defender 教程",
                "summary": "说明",
                "asset_name": "guide_close_windows_defender.json",
                "platforms": ["windows"],
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (source / "guide_close_windows_defender.json").write_text(
        json.dumps({
            "guide_id": "close-windows-defender",
            "blocks": [{"kind": "text", "text": "占位"}],
            "tools": [{
                "tool_id": "dcontrol",
                "title": "dControl",
                "asset_name": "dControl.zip",
                "release_tag": "tools",
                "package_kind": "zip",
                "launch_action": "exe",
                "executable_name": "dControl.exe",
                "run_as_admin": True,
                "platforms": ["windows"],
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    written = export_hub_guides(source, output)

    assert {path.name for path in written} == {
        "guides_index.json", "guide_close_windows_defender.json",
    }
    assert inspect_hub_guides(source).status_text == "已发现 1 篇文章、0 个附件"
    assert not (output / "dControl.zip").exists()
