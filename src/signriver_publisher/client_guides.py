"""Collect simple troubleshooting guide assets for the shared hub Release."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


GUIDES_INDEX_ASSET_NAME = "guides_index.json"
GUIDES_RELEASE_TAG = "guides"
_MANIFEST_NAME = ".guides-manifest.json"


class GuideExportError(RuntimeError):
    """The publisher guide source directory is not ready for hub export."""


@dataclass(frozen=True, slots=True)
class GuideResourceSummary:
    configured: bool
    guide_count: int = 0
    attachment_count: int = 0
    error: str = ""

    @property
    def status_text(self) -> str:
        if self.error:
            return f"配置异常：{self.error}"
        if not self.configured:
            return "未配置"
        return f"已发现 {self.guide_count} 篇文章、{self.attachment_count} 个附件"


def _flat_name(value: object, field: str) -> str:
    raw = str(value or "").strip()
    name = Path(raw).name
    if not raw or name != raw or name in {".", ".."}:
        raise GuideExportError(f"{field} 必须是非空的平铺文件名")
    return name


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GuideExportError(f"{label} 无法读取：{error}") from error
    if not isinstance(value, dict):
        raise GuideExportError(f"{label} 根节点必须是对象")
    return value


def _manifest_path(output_dir: Path) -> Path:
    return output_dir / _MANIFEST_NAME


def _load_manifest(output_dir: Path) -> set[str]:
    path = _manifest_path(output_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    names = value.get("files") if isinstance(value, dict) else None
    if not isinstance(names, list):
        return set()
    return {Path(str(item)).name for item in names if Path(str(item)).name == str(item)}


def _write_manifest(output_dir: Path, names: set[str]) -> None:
    path = _manifest_path(output_dir)
    if not names:
        path.unlink(missing_ok=True)
        return
    path.write_text(
        json.dumps({"files": sorted(names, key=str.casefold)}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _clear_previous(output_dir: Path, previous: set[str]) -> None:
    for name in previous:
        (output_dir / name).unlink(missing_ok=True)
    _write_manifest(output_dir, set())


def _collect(source_dir: Path) -> tuple[GuideResourceSummary, tuple[Path, ...]]:
    index_path = source_dir / GUIDES_INDEX_ASSET_NAME
    if not index_path.is_file():
        return GuideResourceSummary(configured=False), ()
    index = _load_object(index_path, GUIDES_INDEX_ASSET_NAME)
    raw_entries = index.get("guides")
    if not isinstance(raw_entries, list):
        raise GuideExportError("guides_index.json 的 guides 必须是列表")

    files: list[Path] = [index_path]
    output_names = {GUIDES_INDEX_ASSET_NAME.casefold()}
    attachment_count = 0
    for item in raw_entries:
        if not isinstance(item, dict):
            raise GuideExportError("guides_index.json 的 guides 条目必须是对象")
        detail_name = _flat_name(item.get("asset_name"), "指南详情 asset_name")
        if detail_name.casefold() in output_names:
            raise GuideExportError(f"指南资源文件名重复：{detail_name}")
        detail_path = source_dir / detail_name
        if not detail_path.is_file():
            raise GuideExportError(f"指南详情文件不存在：{detail_name}")
        detail = _load_object(detail_path, detail_name)
        output_names.add(detail_name.casefold())
        files.append(detail_path)
        tools = detail.get("tools", [])
        if not isinstance(tools, list):
            raise GuideExportError(f"{detail_name} 的 tools 必须是列表")
        for tool in tools:
            if not isinstance(tool, dict):
                raise GuideExportError(f"{detail_name} 的 tools 条目必须是对象")
            raw_attachment = tool.get("asset_name")
            if raw_attachment in {None, ""}:
                continue
            release_tag = str(tool.get("release_tag") or "hub").strip().lower()
            if release_tag != "hub":
                # tools/other Release assets are published separately.
                continue
            attachment_name = _flat_name(raw_attachment, "工具 asset_name")
            if attachment_name.casefold() in output_names:
                raise GuideExportError(f"指南资源文件名重复：{attachment_name}")
            attachment_path = source_dir / "assets" / attachment_name
            if not attachment_path.is_file():
                raise GuideExportError(f"指南附件不存在：assets/{attachment_name}")
            output_names.add(attachment_name.casefold())
            files.append(attachment_path)
            attachment_count += 1
    return GuideResourceSummary(True, len(raw_entries), attachment_count), tuple(files)


def inspect_hub_guides(source_dir: Path) -> GuideResourceSummary:
    """Return a compact status for the publisher UI without modifying files."""
    try:
        summary, _ = _collect(source_dir)
        return summary
    except GuideExportError as error:
        return GuideResourceSummary(configured=True, error=str(error))


def export_hub_guides(source_dir: Path, output_dir: Path) -> tuple[Path, ...]:
    """Copy the configured guide index, details and attachments into hub output."""
    output_dir.mkdir(parents=True, exist_ok=True)
    previous = _load_manifest(output_dir)
    summary, files = _collect(source_dir)
    if not summary.configured:
        _clear_previous(output_dir, previous)
        return ()

    names = {path.name for path in files}
    other_names = {
        path.name.casefold()
        for path in output_dir.iterdir()
        if path.is_file() and path.name not in previous and path.name != _MANIFEST_NAME
    }
    conflicts = sorted(name for name in names if name.casefold() in other_names)
    if conflicts:
        raise GuideExportError(f"指南资源与现有 hub 附件重名：{', '.join(conflicts)}")

    _clear_previous(output_dir, previous)
    written: list[Path] = []
    for source in files:
        target = output_dir / source.name
        shutil.copy2(source, target)
        written.append(target)
    _write_manifest(output_dir, {path.name for path in written})
    return tuple(written)


def export_guides(source_dir: Path, output_dir: Path) -> tuple[Path, ...]:
    """Materialise guide assets for the dedicated guides Release."""
    return export_hub_guides(source_dir, output_dir)


def clear_exported_guides(output_dir: Path) -> None:
    """Remove guide files previously materialised in a shared hub directory."""
    previous = _load_manifest(output_dir)
    _clear_previous(output_dir, previous)


__all__ = [
    "GUIDES_INDEX_ASSET_NAME",
    "GUIDES_RELEASE_TAG",
    "GuideExportError",
    "GuideResourceSummary",
    "export_hub_guides",
    "export_guides",
    "clear_exported_guides",
    "inspect_hub_guides",
]
