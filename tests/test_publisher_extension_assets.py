from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_publisher.extension_assets import (
    ExtensionExportError,
    build_tool_snapshot,
    export_tool_assets,
    validate_tool_snapshot,
)


def _assets(root: Path) -> Path:
    path = root / "tools" / "assets"
    path.mkdir(parents=True)
    return path


def test_build_and_export_tools_without_metadata(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    (assets / "tool-a.zip").write_bytes(b"abc")
    snapshot = build_tool_snapshot(tmp_path / "tools")
    assert snapshot["schema_version"] == 1
    assert snapshot["files"][0]["name"] == "tool-a.zip"
    assert snapshot["files"][0]["size_bytes"] == 3
    output = tmp_path / "output"
    files, count = export_tool_assets(tmp_path / "tools", output)
    assert count == 1
    assert [item.name for item in files] == ["tool-a.zip"]
    assert (output / "tool-a.zip").read_bytes() == b"abc"


def test_empty_assets_fail(tmp_path: Path) -> None:
    _assets(tmp_path)
    with pytest.raises(ExtensionExportError):
        build_tool_snapshot(tmp_path / "tools")


def test_nested_directories_and_case_duplicates_fail(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    (assets / "nested").mkdir()
    with pytest.raises(ExtensionExportError):
        build_tool_snapshot(tmp_path / "tools")


def test_changed_assets_require_rebuild(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    target = assets / "tool.zip"
    target.write_bytes(b"before")
    build_tool_snapshot(tmp_path / "tools")
    target.write_bytes(b"after")
    with pytest.raises(ExtensionExportError):
        validate_tool_snapshot(tmp_path / "tools")


def test_snapshot_does_not_read_tools_index(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    (assets / "tool.bin").write_bytes(b"payload")
    (tmp_path / "tools" / "tools_index.json").write_text("not json", encoding="utf-8")
    build_tool_snapshot(tmp_path / "tools")
    payload = json.loads((tmp_path / "tools" / ".tools-build.json").read_text(encoding="utf-8"))
    assert payload["files"][0]["name"] == "tool.bin"
