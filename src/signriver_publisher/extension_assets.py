"""Validate and materialise the separate guide and helper-tool Releases.

The client treats the two Releases as a single extension system: guides may
link to a tool, while the tool catalogue is also independently visible.  This
module gives the publisher the same view before anything is uploaded.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .client_guides import (
    GUIDES_INDEX_ASSET_NAME,
    GuideResourceSummary,
    export_guides,
    inspect_hub_guides,
)
from .models import PublishAsset


TOOLS_INDEX_ASSET_NAME = "tools_index.json"
TOOLS_RELEASE_TAG = "tools"
_TOOLS_MANIFEST_NAME = ".tools-manifest.json"
_LOCAL_MANIFEST_NAME = ".local-guides-tools-manifest.json"
_SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")


class ExtensionExportError(RuntimeError):
    """Guide and tool extension sources do not form a publishable whole."""


@dataclass(frozen=True, slots=True)
class ToolResourceSummary:
    configured: bool
    tool_count: int = 0
    error: str = ""

    @property
    def status_text(self) -> str:
        if self.error:
            return f"配置异常：{self.error}"
        if not self.configured:
            return "未配置"
        return f"已发现 {self.tool_count} 个工具"


@dataclass(frozen=True, slots=True)
class ExtensionResourceSummary:
    guides: GuideResourceSummary
    tools: ToolResourceSummary

    @property
    def status_text(self) -> str:
        return f"指南 {self.guides.status_text}；工具 {self.tools.status_text}"


@dataclass(frozen=True, slots=True)
class ExtensionPublishAssets:
    guides: tuple[PublishAsset, ...]
    tools: tuple[PublishAsset, ...]
    summary: ExtensionResourceSummary


@dataclass(frozen=True, slots=True)
class _ToolRecord:
    tool_id: str
    payload: dict[str, object]
    asset_name: str


def _read_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExtensionExportError(f"{label} 无法读取：{error}") from error
    if not isinstance(payload, dict):
        raise ExtensionExportError(f"{label} 根节点必须是对象")
    return payload


def _flat_name(value: object, label: str) -> str:
    raw = str(value or "").strip()
    name = Path(raw).name
    if not raw or name != raw or name in {".", ".."}:
        raise ExtensionExportError(f"{label} 必须是非空的平铺文件名")
    return name


def _safe_id(value: object, label: str) -> str:
    result = str(value or "").strip()
    if (
        not result
        or len(result) > 64
        or result[0] not in "abcdefghijklmnopqrstuvwxyz0123456789"
        or any(character not in _SAFE_ID_CHARS for character in result)
    ):
        raise ExtensionExportError(f"{label} 必须是小写 ID")
    return result


def _normalise_platforms(value: object, label: str) -> tuple[str, ...]:
    items = ["all"] if value is None else (value if isinstance(value, list) else [value])
    platforms = tuple(str(item).strip().lower().split("-", 1)[0] for item in items)
    if not platforms or any(item not in {"all", "windows", "steamos", "macos"} for item in platforms):
        raise ExtensionExportError(f"{label} 只允许 all/windows/steamos/macos")
    return platforms


def _tool_records(source_dir: Path) -> tuple[dict[str, _ToolRecord], tuple[Path, ...]]:
    index_path = source_dir / TOOLS_INDEX_ASSET_NAME
    if not index_path.is_file():
        raise ExtensionExportError("工具目录缺少 tools_index.json")
    index = _read_object(index_path, TOOLS_INDEX_ASSET_NAME)
    raw_tools = index.get("tools")
    if not isinstance(raw_tools, list):
        raise ExtensionExportError("tools_index.json 的 tools 必须是列表")

    records: dict[str, _ToolRecord] = {}
    files: list[Path] = [index_path]
    seen_names = {TOOLS_INDEX_ASSET_NAME.casefold()}
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            raise ExtensionExportError("tools_index.json 的 tools 条目必须是对象")
        tool_id = _safe_id(raw_tool.get("tool_id"), "工具 tool_id")
        if tool_id in records:
            raise ExtensionExportError(f"tools_index.json 的 tool_id 重复：{tool_id}")
        asset_name = _flat_name(raw_tool.get("asset_name"), f"工具 {tool_id} 的 asset_name")
        if asset_name.casefold() in seen_names:
            raise ExtensionExportError(f"工具发布文件名重复：{asset_name}")
        release_tag = str(raw_tool.get("release_tag") or TOOLS_RELEASE_TAG).strip().lower()
        if release_tag != TOOLS_RELEASE_TAG:
            raise ExtensionExportError(f"工具 {tool_id} 的 release_tag 必须为 tools")
        if not str(raw_tool.get("title") or "").strip():
            raise ExtensionExportError(f"工具 {tool_id} 缺少 title")
        if not str(raw_tool.get("description") or "").strip():
            raise ExtensionExportError(f"工具 {tool_id} 缺少 description")
        if not str(raw_tool.get("revision") or "").strip():
            raise ExtensionExportError(f"工具 {tool_id} 缺少 revision")
        requires_cloud_download = raw_tool.get("requires_cloud_download", True)
        if not isinstance(requires_cloud_download, bool):
            raise ExtensionExportError(f"工具 {tool_id} 的 requires_cloud_download 必须是布尔值")
        _normalise_platforms(raw_tool.get("platforms"), f"工具 {tool_id} 的 platforms")
        package_kind = str(raw_tool.get("package_kind") or "file").strip().lower()
        launch_action = str(raw_tool.get("launch_action") or "legacy").strip().lower()
        if package_kind not in {"file", "zip"}:
            raise ExtensionExportError(f"工具 {tool_id} 的 package_kind 无效")
        if launch_action not in {"exe", "open_folder"}:
            raise ExtensionExportError(f"工具 {tool_id} 的 launch_action 无效")
        if launch_action == "exe" and not str(raw_tool.get("executable_name") or "").strip():
            raise ExtensionExportError(f"工具 {tool_id} 使用 exe 启动时必须声明 executable_name")
        package_path = source_dir / "assets" / asset_name
        if not package_path.is_file():
            raise ExtensionExportError(f"工具包不存在：assets/{asset_name}")
        seen_names.add(asset_name.casefold())
        records[tool_id] = _ToolRecord(tool_id, raw_tool, asset_name)
        files.append(package_path)
    return records, tuple(files)


def _validate_guide_tool_references(
    guides_source_dir: Path, tool_records: dict[str, _ToolRecord]
) -> None:
    index_path = guides_source_dir / GUIDES_INDEX_ASSET_NAME
    index = _read_object(index_path, GUIDES_INDEX_ASSET_NAME)
    raw_guides = index.get("guides")
    if not isinstance(raw_guides, list):
        raise ExtensionExportError("guides_index.json 的 guides 必须是列表")
    for raw_guide in raw_guides:
        if not isinstance(raw_guide, dict):
            raise ExtensionExportError("guides_index.json 的 guides 条目必须是对象")
        guide_id = _safe_id(raw_guide.get("guide_id"), "指南 guide_id")
        detail_name = _flat_name(raw_guide.get("asset_name"), f"指南 {guide_id} 的 asset_name")
        detail = _read_object(guides_source_dir / detail_name, detail_name)
        raw_tools = detail.get("tools", [])
        if not isinstance(raw_tools, list):
            raise ExtensionExportError(f"{detail_name} 的 tools 必须是列表")
        for reference in raw_tools:
            if not isinstance(reference, dict):
                raise ExtensionExportError(f"{detail_name} 的 tools 条目必须是对象")
            if str(reference.get("release_tag") or "hub").strip().lower() != TOOLS_RELEASE_TAG:
                continue
            tool_id = _safe_id(reference.get("tool_id"), f"{detail_name} 的工具 tool_id")
            record = tool_records.get(tool_id)
            if record is None:
                raise ExtensionExportError(
                    f"{detail_name} 引用了不存在于 tools_index.json 的工具：{tool_id}"
                )
            for field in (
                "asset_name", "filename", "package_kind", "launch_action",
                "executable_name", "revision", "requires_cloud_download",
            ):
                expected = record.payload.get(field)
                actual = reference.get(field)
                if actual not in {None, ""} and str(actual).strip() != str(expected or "").strip():
                    raise ExtensionExportError(
                        f"{detail_name} 引用工具 {tool_id} 的 {field} 与 tools_index.json 不一致"
                    )
            if "platforms" in reference and _normalise_platforms(
                reference.get("platforms"), f"{detail_name} 的工具 {tool_id} platforms"
            ) != _normalise_platforms(record.payload.get("platforms"), f"工具 {tool_id} 的 platforms"):
                raise ExtensionExportError(
                    f"{detail_name} 引用工具 {tool_id} 的 platforms 与 tools_index.json 不一致"
                )


def inspect_extension_resources(guides_source_dir: Path, tools_source_dir: Path) -> ExtensionResourceSummary:
    guides = inspect_hub_guides(guides_source_dir)
    try:
        records, _ = _tool_records(tools_source_dir)
        if not guides.configured:
            raise ExtensionExportError("指南目录缺少 guides_index.json")
        if guides.error:
            raise ExtensionExportError(guides.error)
        _validate_guide_tool_references(guides_source_dir, records)
        tools = ToolResourceSummary(True, len(records))
    except ExtensionExportError as error:
        tools = ToolResourceSummary(True, error=str(error))
    return ExtensionResourceSummary(guides, tools)


def _load_manifest(output_dir: Path) -> set[str]:
    try:
        value = json.loads((output_dir / _TOOLS_MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    values = value.get("files") if isinstance(value, dict) else None
    if not isinstance(values, list):
        return set()
    return {
        str(item) for item in values
        if Path(str(item)).name == str(item)
    }


def _write_manifest(output_dir: Path, names: set[str]) -> None:
    path = output_dir / _TOOLS_MANIFEST_NAME
    if names:
        path.write_text(
            json.dumps({"files": sorted(names, key=str.casefold)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        path.unlink(missing_ok=True)


def export_extension_assets(
    guides_source_dir: Path, tools_source_dir: Path, guides_output_dir: Path, tools_output_dir: Path
) -> tuple[tuple[Path, ...], tuple[Path, ...], ExtensionResourceSummary]:
    """Validate the cross-Release contract, then materialise both asset sets."""
    summary = inspect_extension_resources(guides_source_dir, tools_source_dir)
    if not summary.guides.configured or summary.guides.error:
        raise ExtensionExportError(summary.guides.error or "指南目录缺少 guides_index.json")
    if summary.tools.error:
        raise ExtensionExportError(summary.tools.error)
    _, tool_files = _tool_records(tools_source_dir)
    guide_files = export_guides(guides_source_dir, guides_output_dir)
    tools_output_dir.mkdir(parents=True, exist_ok=True)
    previous = _load_manifest(tools_output_dir)
    for name in previous:
        (tools_output_dir / name).unlink(missing_ok=True)
    written_tools: list[Path] = []
    for source in tool_files:
        target = tools_output_dir / source.name
        shutil.copy2(source, target)
        written_tools.append(target)
    _write_manifest(tools_output_dir, {path.name for path in written_tools})
    return guide_files, tuple(written_tools), summary


def export_tool_assets(
    tools_source_dir: Path, tools_output_dir: Path
) -> tuple[tuple[Path, ...], ToolResourceSummary]:
    """Materialise only downloadable tool payloads for the tools Release."""
    try:
        _records, tool_files = _tool_records(tools_source_dir)
    except ExtensionExportError as error:
        return (), ToolResourceSummary(True, error=str(error))
    tools_output_dir.mkdir(parents=True, exist_ok=True)
    previous = _load_manifest(tools_output_dir)
    for name in previous:
        (tools_output_dir / name).unlink(missing_ok=True)
    written: list[Path] = []
    for source in tool_files:
        if source.name == TOOLS_INDEX_ASSET_NAME:
            continue
        target = tools_output_dir / source.name
        shutil.copy2(source, target)
        written.append(target)
    _write_manifest(tools_output_dir, {path.name for path in written})
    return tuple(written), ToolResourceSummary(True, len(_records))


def sync_local_client_resources(
    guides_source_dir: Path, tools_source_dir: Path, target_dir: Path
) -> tuple[Path, ...]:
    """Validate and atomically refresh the built-in guide/tool definitions."""
    summary = inspect_extension_resources(guides_source_dir, tools_source_dir)
    if not summary.guides.configured or summary.guides.error:
        raise ExtensionExportError(summary.guides.error or "指南目录缺少 guides_index.json")
    if summary.tools.error:
        raise ExtensionExportError(summary.tools.error)
    _tool_records(tools_source_dir)
    staging = target_dir.parent / f".{target_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        guide_files = export_guides(guides_source_dir, staging)
        shutil.copy2(tools_source_dir / TOOLS_INDEX_ASSET_NAME, staging / TOOLS_INDEX_ASSET_NAME)
        names = {path.name for path in guide_files} | {TOOLS_INDEX_ASSET_NAME}
        old_names: set[str] = set()
        manifest = target_dir / _LOCAL_MANIFEST_NAME
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            old_names = {Path(str(item)).name for item in value.get("files", [])}
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            pass
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in old_names - names:
            (target_dir / name).unlink(missing_ok=True)
        written: list[Path] = []
        for name in names:
            source = staging / name
            target = target_dir / name
            shutil.copy2(source, target)
            written.append(target)
        manifest.write_text(json.dumps({"files": sorted(names)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return tuple(sorted(written, key=lambda path: path.name.casefold()))
    finally:
        if staging.exists():
            shutil.rmtree(staging)


__all__ = [
    "ExtensionExportError", "ExtensionPublishAssets", "ExtensionResourceSummary",
    "TOOLS_INDEX_ASSET_NAME", "TOOLS_RELEASE_TAG", "ToolResourceSummary",
    "export_extension_assets", "export_tool_assets", "inspect_extension_resources",
    "sync_local_client_resources",
]
