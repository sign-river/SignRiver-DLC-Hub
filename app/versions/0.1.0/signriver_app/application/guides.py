"""Lightweight, platform-filtered remote troubleshooting guide catalogue."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..infrastructure.catalog import (
    fixed_release_asset_url,
    normalize_download_source,
)
from ..infrastructure.net_errors import describe_network_error

LOGGER = logging.getLogger(__name__)
GUIDES_INDEX_ASSET_NAME = "guides_index.json"
GUIDES_RELEASE_TAG = "guides"
TOOLS_INDEX_ASSET_NAME = "tools_index.json"
TOOLS_RELEASE_TAG = "tools"
_GUIDE_SCHEMA = 1
_GUIDE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TOOL_DETAIL_ACTIONS = {"open_guide", "open_url", "open_folder"}


class GuideCatalogError(RuntimeError):
    """The optional troubleshooting guide catalogue could not be read."""


def _id(value: object, field: str) -> str:
    result = str(value or "").strip()
    if not _SAFE_ID.fullmatch(result):
        raise ValueError(f"{field} must be a lowercase id")
    return result


def _platforms(value: object) -> tuple[str, ...]:
    raw = ("all",) if value is None else value
    values = raw if isinstance(raw, list) else [raw]
    result = tuple(str(item).strip().lower().split("-", 1)[0] for item in values)
    if not result or any(item not in {"all", "windows", "steamos", "macos"} for item in result):
        raise ValueError("guide platforms must contain all/windows/steamos/macos")
    return result


@dataclass(frozen=True, slots=True)
class GuideIndexEntry:
    guide_id: str
    title: str
    summary: str
    asset_name: str
    platforms: tuple[str, ...]
    builtin: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, object], *, builtin: bool = False) -> "GuideIndexEntry":
        return cls(
            guide_id=_id(value.get("guide_id"), "guide_id"),
            title=str(value.get("title") or "").strip(),
            summary=str(value.get("summary") or "").strip(),
            asset_name=str(value.get("asset_name") or "").strip(),
            platforms=_platforms(value.get("platforms")),
            builtin=builtin,
        )

    def applies_to(self, platform: str) -> bool:
        return "all" in self.platforms or platform.split("-", 1)[0] in self.platforms


@dataclass(frozen=True, slots=True)
class ToolDetailAction:
    """A safe, declarative action rendered on a cloud tool's detail page."""

    action: str
    label: str
    guide_id: str = ""
    url: str = ""

    @classmethod
    def from_dict(cls, value: object) -> "ToolDetailAction":
        if not isinstance(value, dict):
            raise ValueError("tool detail button must be an object")
        action = str(value.get("action") or "").strip().lower()
        if action not in _TOOL_DETAIL_ACTIONS:
            raise ValueError("unsupported tool detail button action")
        label = str(value.get("label") or "").strip()
        if not label:
            raise ValueError("tool detail button label is required")
        guide_id = str(value.get("guide_id") or "").strip()
        url = str(value.get("url") or "").strip()
        if action == "open_guide":
            guide_id = _id(guide_id, "tool detail button guide_id")
        elif guide_id:
            raise ValueError("tool detail button guide_id only applies to open_guide")
        if action == "open_url":
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("tool detail button url must be HTTPS")
        elif url:
            raise ValueError("tool detail button url only applies to open_url")
        return cls(action=action, label=label, guide_id=guide_id, url=url)


@dataclass(frozen=True, slots=True)
class GuideTool:
    tool_id: str
    title: str
    description: str
    download_url: str
    asset_name: str
    filename: str
    platforms: tuple[str, ...]
    run_mode: str = "open"
    quick_check: bool = False
    quick_check_read_only: bool = False
    quick_check_success: str = ""
    quick_check_problem_guide: str = ""
    quick_check_timeout_seconds: int = 30
    release_tag: str = "hub"
    package_kind: str = "file"
    launch_action: str = "legacy"
    executable_name: str = ""
    run_as_admin: bool = False
    requires_cloud_download: bool = True
    builtin: bool = False
    revision: str = ""
    detail_intro: str = ""
    detail_warnings: tuple[str, ...] = ()
    detail_actions: tuple[ToolDetailAction, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, object], *, builtin: bool = False) -> "GuideTool":
        run_mode = str(value.get("run_mode") or "open").strip().lower()
        if run_mode not in {"open", "powershell", "cmd", "shell"}:
            raise ValueError("unsupported guide tool run_mode")
        raw_quick_check = value.get("quick_check", False)
        if not isinstance(raw_quick_check, bool):
            raise ValueError("guide tool quick_check must be a boolean")
        quick_check = raw_quick_check
        raw_read_only = value.get("quick_check_read_only", False)
        if not isinstance(raw_read_only, bool):
            raise ValueError("guide tool quick_check_read_only must be a boolean")
        if quick_check and run_mode == "open":
            raise ValueError("quick-check guide tools must use a command run_mode")
        if quick_check and not raw_read_only:
            raise ValueError("quick-check guide tools must be explicitly read-only")
        raw_timeout = value.get("quick_check_timeout_seconds", 30)
        if isinstance(raw_timeout, bool):
            raise ValueError("guide tool quick_check_timeout_seconds must be an integer")
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError) as error:
            raise ValueError("guide tool quick_check_timeout_seconds must be an integer") from error
        if not 5 <= timeout_seconds <= 120:
            raise ValueError("guide tool quick_check_timeout_seconds must be between 5 and 120")
        raw_problem_guide = str(value.get("quick_check_problem_guide") or "").strip()
        problem_guide = _id(raw_problem_guide, "quick_check_problem_guide") if raw_problem_guide else ""
        raw_asset_name = str(value.get("asset_name") or "").strip()
        asset_name = Path(raw_asset_name).name
        if raw_asset_name and asset_name != raw_asset_name:
            raise ValueError("guide tool asset_name must be a flat filename")
        filename = Path(str(value.get("filename") or "")).name
        release_tag = str(value.get("release_tag") or "hub").strip().lower()
        if not _SAFE_ID.fullmatch(release_tag):
            raise ValueError("guide tool release_tag must be a lowercase id")
        package_kind = str(value.get("package_kind") or "file").strip().lower()
        if package_kind not in {"file", "zip"}:
            raise ValueError("unsupported guide tool package_kind")
        launch_action = str(value.get("launch_action") or "legacy").strip().lower()
        if launch_action not in {"legacy", "exe", "open_folder"}:
            raise ValueError("unsupported guide tool launch_action")
        raw_executable = str(value.get("executable_name") or "").strip()
        executable_name = Path(raw_executable).name
        if raw_executable and executable_name != raw_executable:
            raise ValueError("guide tool executable_name must be a flat filename")
        if launch_action == "exe" and not executable_name:
            raise ValueError("exe helper tools must declare executable_name")
        raw_admin = value.get("run_as_admin", False)
        if not isinstance(raw_admin, bool):
            raise ValueError("guide tool run_as_admin must be a boolean")
        requires_cloud_download = value.get("requires_cloud_download", True)
        if not isinstance(requires_cloud_download, bool):
            raise ValueError("guide tool requires_cloud_download must be a boolean")
        raw_detail = value.get("detail", {})
        if raw_detail is None:
            raw_detail = {}
        if not isinstance(raw_detail, dict):
            raise ValueError("tool detail must be an object")
        raw_warnings = raw_detail.get("warnings", [])
        if not isinstance(raw_warnings, list) or not all(isinstance(item, str) for item in raw_warnings):
            raise ValueError("tool detail warnings must be a list of strings")
        raw_actions = raw_detail.get("buttons", [])
        if not isinstance(raw_actions, list):
            raise ValueError("tool detail buttons must be a list")
        return cls(
            tool_id=_id(value.get("tool_id"), "tool_id"),
            title=str(value.get("title") or "").strip(),
            description=str(value.get("description") or "").strip(),
            download_url=str(value.get("download_url") or "").strip(),
            asset_name=asset_name,
            filename=filename or asset_name,
            platforms=_platforms(value.get("platforms")),
            run_mode=run_mode,
            quick_check=quick_check,
            quick_check_read_only=raw_read_only,
            quick_check_success=str(value.get("quick_check_success") or "").strip(),
            quick_check_problem_guide=problem_guide,
            quick_check_timeout_seconds=timeout_seconds,
            release_tag=release_tag,
            package_kind=package_kind,
            launch_action=launch_action,
            executable_name=executable_name,
            run_as_admin=raw_admin,
            requires_cloud_download=requires_cloud_download,
            builtin=builtin,
            revision=str(value.get("revision") or "").strip(),
            detail_intro=str(raw_detail.get("intro") or "").strip(),
            detail_warnings=tuple(item.strip() for item in raw_warnings if item.strip()),
            detail_actions=tuple(ToolDetailAction.from_dict(item) for item in raw_actions),
        )

    def is_helper_tool(self) -> bool:
        return self.launch_action in {"exe", "open_folder"}

    def applies_to(self, platform: str) -> bool:
        normalized = platform.split("-", 1)[0]
        if "all" not in self.platforms and normalized not in self.platforms:
            return False
        # Command interpreters are platform-specific even when a mistakenly
        # broad guide entry uses ``all``.  Do not expose a button that cannot
        # run on the current client.
        if self.run_mode in {"powershell", "cmd"}:
            return normalized == "windows"
        if self.run_mode == "shell":
            return normalized in {"steamos", "macos"}
        return True


@dataclass(frozen=True, slots=True)
class GuideDocument:
    entry: GuideIndexEntry
    blocks: tuple[tuple[str, ...], ...]
    tools: tuple[GuideTool, ...]


class GuideCatalogService:
    """Reads optional hub guides; absence never disables local diagnostics."""

    def __init__(self, cache_dir: Path, *, bootstrap_dir: Path | None = None,
                 download_source: str = "gitlink", platform: str = "windows",
                 opener: Callable[[str, float], bytes] | None = None, timeout: float = 20) -> None:
        self.cache_dir = Path(cache_dir)
        self.bootstrap_dir = Path(bootstrap_dir) if bootstrap_dir else None
        self.download_source = normalize_download_source(download_source)
        self.platform = platform.split("-", 1)[0]
        self.timeout = timeout
        self._open = opener or self._download_bytes
        self.entries: tuple[GuideIndexEntry, ...] = ()
        self._builtin_tool_ids: set[str] = set()
        self._indexed_tools: dict[str, GuideTool] = {}
        self._guide_tools: dict[str, GuideTool] = {}

    @property
    def tools(self) -> tuple[GuideTool, ...]:
        """All known tools, including tools without a guide association."""
        merged = dict(self._indexed_tools)
        for tool_id, tool in self._guide_tools.items():
            if tool_id not in merged and tool_id not in self._builtin_tool_ids:
                merged[tool_id] = tool
        return tuple(merged.values())

    def set_download_source(self, source: str) -> None:
        self.download_source = normalize_download_source(source)
        self.entries = ()

    def _parse_index_payload(self, raw_payload: bytes | str, *, builtin: bool = False) -> tuple[GuideIndexEntry, ...]:
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            raise ValueError("guide index must be an object")
        if int(payload.get("schema_version", 0)) != _GUIDE_SCHEMA:
            raise ValueError("unsupported guide schema")
        raw_entries = payload.get("guides")
        if not isinstance(raw_entries, list):
            raise ValueError("guides must be a list")
        entries = tuple(
            entry
            for entry in (
                GuideIndexEntry.from_dict(item, builtin=builtin)
                for item in raw_entries
                if isinstance(item, dict)
            )
            if entry.applies_to(self.platform)
        )
        return entries

    def _load_bootstrap_entries(self) -> tuple[GuideIndexEntry, ...]:
        if self.bootstrap_dir is None:
            return ()
        path = self.bootstrap_dir / GUIDES_INDEX_ASSET_NAME
        if not path.is_file():
            return ()
        try:
            return self._parse_index_payload(path.read_text(encoding="utf-8"), builtin=True)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return ()

    def _parse_tools_payload(self, raw_payload: bytes | str, *, builtin: bool = False) -> tuple[GuideTool, ...]:
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != _GUIDE_SCHEMA:
            raise ValueError("unsupported tools index schema")
        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, list):
            raise ValueError("tools must be a list")
        tools: list[GuideTool] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized.setdefault("release_tag", TOOLS_RELEASE_TAG)
            tool = GuideTool.from_dict(normalized, builtin=builtin)
            if tool.applies_to(self.platform):
                tools.append(tool)
        return tuple(tools)

    def _load_bootstrap_tools(self) -> tuple[GuideTool, ...]:
        if self.bootstrap_dir is None:
            return ()
        path = self.bootstrap_dir / TOOLS_INDEX_ASSET_NAME
        if not path.is_file():
            return ()
        try:
            return self._parse_tools_payload(path.read_text(encoding="utf-8"), builtin=True)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, GuideCatalogError):
            return ()

    @staticmethod
    def _remote_resource_missing(error: Exception) -> bool:
        detail = str(error).casefold()
        return any(marker in detail for marker in ("404", "not found", "资源不存在", "不存在"))

    def _remove_cached_tool_dirs(self, keep_ids: set[str]) -> None:
        tools_dir = self.cache_dir / "tools"
        if not tools_dir.is_dir():
            return
        keep = {str(tool_id).casefold() for tool_id in keep_ids}
        for child in tools_dir.iterdir():
            if child.is_dir() and child.name.casefold() not in keep:
                shutil.rmtree(child, ignore_errors=True)

    def _remove_cached_guides(
        self, previous_entries: tuple[GuideIndexEntry, ...], keep_entries: tuple[GuideIndexEntry, ...]
    ) -> None:
        keep = {entry.asset_name.casefold() for entry in keep_entries}
        for entry in previous_entries:
            if entry.asset_name.casefold() not in keep:
                (self.cache_dir / entry.asset_name).unlink(missing_ok=True)
                shutil.rmtree(self.cache_dir / "assets" / entry.guide_id, ignore_errors=True)

    def refresh_tools(self, *, allow_network: bool = True) -> tuple[GuideTool, ...]:
        """Load the built-in tools catalogue; only tool payloads are remote."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        builtin_tools = self._load_bootstrap_tools()
        self._guide_tools = {}
        self._indexed_tools = {tool.tool_id: tool for tool in builtin_tools}
        return self.tools

    def refresh_index(self, *, allow_network: bool = True) -> tuple[GuideIndexEntry, ...]:
        """Load the fixed local guide catalogue; guides are not cloud content."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.entries = self._load_bootstrap_entries()
        return self.entries

    def _parse_guide_payload(
        self, entry: GuideIndexEntry, raw_payload: bytes | str, *, builtin: bool = False,
        image_root: Path | None = None,
    ) -> GuideDocument:
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            raise GuideCatalogError("guide detail must be an object")
        if _id(payload.get("guide_id"), "guide_id") != entry.guide_id:
            raise GuideCatalogError("guide detail id does not match index")
        raw_blocks = payload.get("blocks", [])
        if not isinstance(raw_blocks, list):
            raise GuideCatalogError("guide blocks must be a list")
        blocks: list[tuple[str, ...]] = []
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            kind = str(block.get("kind") or "text")
            text = str(block.get("text") or "").strip()
            if kind in {"heading", "text"} and text:
                blocks.append((kind, text))
            elif kind == "link" and text:
                url = str(block.get("url") or "").strip()
                if url.startswith("https://"):
                    blocks.append((kind, text, url))
            elif kind == "button" and text:
                target = str(block.get("target") or "").strip()
                if (
                    target in {"patch-tool", "dlc-home"}
                    or target.startswith("guide:")
                    or (
                        target.startswith("tool:")
                        and bool(_SAFE_ID.fullmatch(target.removeprefix("tool:").strip()))
                    )
                ):
                    blocks.append((kind, text, target))
            elif kind == "image":
                raw_path = str(block.get("asset_name") or block.get("path") or "").strip().replace("\\", "/")
                if raw_path.startswith("config/guides/") and builtin and ".." not in raw_path:
                    blocks.append((kind, raw_path))
                    continue
                asset_name = Path(raw_path).name
                if (
                    raw_path == asset_name
                    and asset_name not in {"", ".", ".."}
                    and Path(asset_name).suffix.casefold() in _GUIDE_IMAGE_EXTENSIONS
                ):
                    candidate = (image_root or (self.cache_dir / "assets")) / asset_name
                    if candidate.is_file():
                        blocks.append((kind, str(candidate)))
        raw_tools = payload.get("tools", [])
        if not isinstance(raw_tools, list):
            raise GuideCatalogError("guide tools must be a list")
        tools = tuple(
            tool
            for tool in (
                GuideTool.from_dict(item, builtin=builtin)
                for item in raw_tools
                if isinstance(item, dict)
            )
            if tool.applies_to(self.platform)
        )
        # Migrate guide attachments produced before the dedicated guides
        # Release existed.  This keeps old cached details from requesting the
        # removed hub/<asset> URL.
        tools = tuple(
            replace(tool, release_tag=GUIDES_RELEASE_TAG)
            if tool.release_tag == "hub" and not tool.is_helper_tool()
            else tool
            for tool in tools
        )
        if builtin:
            self._builtin_tool_ids.update(tool.tool_id for tool in tools)
        else:
            tools = tuple(tool for tool in tools if tool.tool_id not in self._builtin_tool_ids)
        for tool in tools:
            self._guide_tools.setdefault(tool.tool_id, tool)
        return GuideDocument(entry=entry, blocks=tuple(blocks), tools=tools)

    def load_guide(
        self, entry: GuideIndexEntry, *, allow_network: bool = True
    ) -> GuideDocument:
        # 内置指南正文随客户端发布，云端只负责拓展指南；不要为内置项
        # 发起一次必然被拒绝的远程请求。旧版本这里会在启动时把内置
        # asset_name 请求到 guides Release，资源不存在时刷出 404 traceback。
        bootstrap_path = (
            None if self.bootstrap_dir is None
            else self.bootstrap_dir / entry.asset_name
        )
        candidates = (("bootstrap", bootstrap_path),)
        for label, candidate in candidates:
            if candidate is None or not candidate.is_file():
                continue
            try:
                return self._parse_guide_payload(
                    entry, candidate.read_text(encoding="utf-8"), builtin=entry.builtin,
                    image_root=(self.bootstrap_dir / "assets") if entry.builtin and self.bootstrap_dir else self.cache_dir / "assets" / entry.guide_id,
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ValueError,
                GuideCatalogError,
            ) as error:
                LOGGER.debug(
                    "Ignoring invalid optional %s guide detail %s at %s: %s",
                    label,
                    entry.guide_id,
                    candidate,
                    error,
                )
        raise GuideCatalogError(f"未找到指南详情：{entry.title}")

    def _cache_guide_images(self, guide_id: str, raw_payload: bytes | str) -> None:
        try:
            payload = json.loads(raw_payload)
        except (TypeError, UnicodeError, json.JSONDecodeError):
            return
        blocks = payload.get("blocks", []) if isinstance(payload, dict) else []
        if not isinstance(blocks, list):
            return
        target_dir = self.cache_dir / "assets" / guide_id
        for block in blocks:
            if not isinstance(block, dict) or str(block.get("kind") or "") != "image":
                continue
            raw_name = str(block.get("asset_name") or block.get("path") or "").strip().replace("\\", "/")
            asset_name = Path(raw_name).name
            if (
                raw_name != asset_name
                or asset_name in {"", ".", ".."}
                or Path(asset_name).suffix.casefold() not in _GUIDE_IMAGE_EXTENSIONS
            ):
                continue
            target = target_dir / asset_name
            if target.is_file() and target.stat().st_size > 0:
                continue
            payload_bytes = self._fetch(asset_name)
            if not payload_bytes:
                raise GuideCatalogError(f"指南图片为空：{asset_name}")
            target_dir.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.part")
            try:
                temporary.write_bytes(payload_bytes)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)

    def download_tool(self, tool: GuideTool) -> Path:
        if not tool.applies_to(self.platform):
            raise GuideCatalogError("该工具不适用于当前平台")
        if not tool.filename:
            raise GuideCatalogError("工具必须提供文件名")
        if tool.asset_name:
            url = fixed_release_asset_url(
                self.download_source, tool.release_tag, tool.asset_name
            )
        else:
            parsed = urlparse(tool.download_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise GuideCatalogError("工具下载地址必须为 HTTPS，或指定 hub 附件名")
            url = tool.download_url
        LOGGER.info(
            "Guide attachment download started: tool=%s revision=%s url=%s",
            tool.tool_id, tool.revision or "", url,
        )
        target = self.cache_dir / "tools" / tool.tool_id / tool.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = self._open(url, self.timeout)
        except Exception:
            LOGGER.exception("Guide attachment download failed: tool=%s url=%s", tool.tool_id, url)
            raise
        if not payload:
            raise GuideCatalogError("工具下载为空")
        temporary = target.with_name(f".{target.name}.part")
        try:
            temporary.write_bytes(payload)
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise GuideCatalogError("工具下载为空")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        LOGGER.info(
            "Guide attachment download finished: tool=%s revision=%s path=%s bytes=%s",
            tool.tool_id, tool.revision or "", target, target.stat().st_size,
        )
        return target

    def _fetch(
        self, asset_name: str, *, release_tag: str = GUIDES_RELEASE_TAG,
        optional: bool = False,
    ) -> bytes:
        url = fixed_release_asset_url(self.download_source, release_tag, asset_name)
        LOGGER.info("Guide resource download started: release=%s asset=%s source=%s url=%s", release_tag, asset_name, self.download_source, url)
        try:
            payload = self._open(url, self.timeout)
        except GuideCatalogError as error:
            # Guides and the standalone tools index are optional online
            # content. In particular, a tools Release without tools_index.json
            # is a normal rollout state, so keep it out of the terminal's
            # warning stream while preserving diagnostic detail at DEBUG level.
            log = LOGGER.debug if optional else LOGGER.warning
            log(
                "Guide resource unavailable: release=%s asset=%s url=%s detail=%s",
                release_tag,
                asset_name,
                url,
                error,
            )
            raise
        except Exception:
            LOGGER.exception("Guide resource download failed: release=%s asset=%s url=%s", release_tag, asset_name, url)
            raise
        LOGGER.info("Guide resource download finished: asset=%s bytes=%s", asset_name, len(payload))
        return payload

    @staticmethod
    def _download_bytes(url: str, timeout: float) -> bytes:
        request = Request(url, headers={"Accept": "application/json,application/octet-stream", "User-Agent": "SignRiver-DLC-Hub/0.2"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError) as error:
            raise GuideCatalogError(describe_network_error(error, url=url, action="下载报错指南资源")) from error


__all__ = ["GUIDES_INDEX_ASSET_NAME", "GUIDES_RELEASE_TAG", "TOOLS_INDEX_ASSET_NAME", "TOOLS_RELEASE_TAG", "GuideCatalogError", "GuideCatalogService", "GuideDocument", "GuideIndexEntry", "GuideTool", "ToolDetailAction"]
