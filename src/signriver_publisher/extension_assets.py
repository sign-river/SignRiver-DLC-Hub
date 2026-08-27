"""Build and validate the publisher's downloadable tool payload snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

_BUILD_SNAPSHOT_NAME = ".tools-build.json"
_TOOLS_MANIFEST_NAME = ".tools-manifest.json"


class ExtensionExportError(RuntimeError):
    """The local tool payload directory is not publishable."""


def _scan_tool_assets(assets_dir: Path) -> tuple[Path, ...]:
    if not assets_dir.is_dir():
        raise ExtensionExportError("工具目录缺少 assets 文件夹")
    entries = tuple(sorted(assets_dir.iterdir(), key=lambda item: item.name.casefold()))
    if not entries:
        raise ExtensionExportError("assets 文件夹中没有工具文件")
    seen: set[str] = set()
    files: list[Path] = []
    for path in entries:
        if path.is_symlink():
            raise ExtensionExportError(f"工具文件不能是符号链接：{path.name}")
        if not path.is_file():
            raise ExtensionExportError(f"assets 只能直接放普通文件：{path.name}")
        key = path.name.casefold()
        if key in seen:
            raise ExtensionExportError(f"工具文件名大小写重复：{path.name}")
        seen.add(key)
        files.append(path)
    return tuple(files)


def _file_snapshot(path: Path) -> dict[str, object]:
    before = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ExtensionExportError(f"工具文件在校验期间发生变化：{path.name}")
    return {"name": path.name, "size_bytes": after.st_size, "sha256": digest}


def build_tool_snapshot(tools_source_dir: Path) -> dict[str, object]:
    """Hash all flat assets and atomically write the local build snapshot."""
    tools_source_dir.mkdir(parents=True, exist_ok=True)
    files = _scan_tool_assets(tools_source_dir / "assets")
    snapshot = {
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "files": [_file_snapshot(path) for path in files],
    }
    target = tools_source_dir / _BUILD_SNAPSHOT_NAME
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    return snapshot


def _read_snapshot(tools_source_dir: Path) -> dict[str, object]:
    try:
        value = json.loads(
            (tools_source_dir / _BUILD_SNAPSHOT_NAME).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExtensionExportError("请先构建工具快照") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ExtensionExportError("工具快照格式无效，请重新构建")
    files = value.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(item, dict) for item in files):
        raise ExtensionExportError("工具快照中没有有效文件，请重新构建")
    return value


def validate_tool_snapshot(tools_source_dir: Path) -> tuple[Path, ...]:
    snapshot = _read_snapshot(tools_source_dir)
    current = _scan_tool_assets(tools_source_dir / "assets")
    actual = [_file_snapshot(path) for path in current]
    if actual != snapshot["files"]:
        raise ExtensionExportError("工具文件已变化，请重新构建工具快照")
    return current


def _load_manifest(output_dir: Path) -> set[str]:
    try:
        value = json.loads((output_dir / _TOOLS_MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    values = value.get("files") if isinstance(value, dict) else None
    return {str(item) for item in values or [] if Path(str(item)).name == str(item)}


def _write_manifest(output_dir: Path, names: set[str]) -> None:
    path = output_dir / _TOOLS_MANIFEST_NAME
    if names:
        path.write_text(
            json.dumps({"files": sorted(names, key=str.casefold)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        path.unlink(missing_ok=True)


def export_tool_assets(
    tools_source_dir: Path, tools_output_dir: Path, *, require_snapshot: bool = True
) -> tuple[tuple[Path, ...], int]:
    """Copy the snapshotted payload files into the tools Release staging area."""
    files = validate_tool_snapshot(tools_source_dir) if require_snapshot else _scan_tool_assets(tools_source_dir / "assets")
    tools_output_dir.mkdir(parents=True, exist_ok=True)
    for name in _load_manifest(tools_output_dir):
        (tools_output_dir / name).unlink(missing_ok=True)
    written: list[Path] = []
    for source in files:
        target = tools_output_dir / source.name
        shutil.copy2(source, target)
        written.append(target)
    _write_manifest(tools_output_dir, {path.name for path in written})
    return tuple(written), len(written)


__all__ = ["ExtensionExportError", "build_tool_snapshot", "export_tool_assets", "validate_tool_snapshot"]
