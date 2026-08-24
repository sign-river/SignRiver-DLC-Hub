"""Lightweight, platform-filtered remote troubleshooting guide catalogue."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
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
_GUIDE_SCHEMA = 1
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


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

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "GuideIndexEntry":
        return cls(
            guide_id=_id(value.get("guide_id"), "guide_id"),
            title=str(value.get("title") or "").strip(),
            summary=str(value.get("summary") or "").strip(),
            asset_name=str(value.get("asset_name") or "").strip(),
            platforms=_platforms(value.get("platforms")),
        )

    def applies_to(self, platform: str) -> bool:
        return "all" in self.platforms or platform.split("-", 1)[0] in self.platforms


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

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "GuideTool":
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
        )

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
    blocks: tuple[tuple[str, str], ...]
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

    def set_download_source(self, source: str) -> None:
        self.download_source = normalize_download_source(source)
        self.entries = ()

    def _parse_index_payload(self, raw_payload: bytes | str) -> tuple[GuideIndexEntry, ...]:
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            raise ValueError("guide index must be an object")
        if int(payload.get("schema_version", 0)) != _GUIDE_SCHEMA:
            raise ValueError("unsupported guide schema")
        raw_entries = payload.get("guides")
        if not isinstance(raw_entries, list):
            raise ValueError("guides must be a list")
        return tuple(
            entry
            for entry in (
                GuideIndexEntry.from_dict(item)
                for item in raw_entries
                if isinstance(item, dict)
            )
            if entry.applies_to(self.platform)
        )

    def refresh_index(self, *, allow_network: bool = True) -> tuple[GuideIndexEntry, ...]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / GUIDES_INDEX_ASSET_NAME
        if allow_network:
            try:
                raw_payload = self._fetch(GUIDES_INDEX_ASSET_NAME)
                entries = self._parse_index_payload(raw_payload)
            except Exception as error:
                # A reverse proxy may return a JSON/HTML 404 response.  Never
                # persist it as a cache entry or turn an optional guide refresh
                # into recurring startup warning noise.
                LOGGER.debug("Ignoring invalid remote guide index: %s", error)
            else:
                cache_path.write_bytes(raw_payload)
                self.entries = entries
                return entries
        candidates = (
            ("cache", cache_path),
            (
                "bootstrap",
                None if self.bootstrap_dir is None
                else self.bootstrap_dir / GUIDES_INDEX_ASSET_NAME,
            ),
        )
        for label, path in candidates:
            if path is None or not path.is_file():
                continue
            try:
                entries = self._parse_index_payload(path.read_text(encoding="utf-8"))
            except Exception as error:
                if label == "cache":
                    path.unlink(missing_ok=True)
                LOGGER.debug("Ignoring invalid %s guide index: %s", label, error)
                continue
            self.entries = entries
            return entries
        self.entries = ()
        return ()

    def _parse_guide_payload(
        self, entry: GuideIndexEntry, raw_payload: bytes | str
    ) -> GuideDocument:
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            raise GuideCatalogError("guide detail must be an object")
        if _id(payload.get("guide_id"), "guide_id") != entry.guide_id:
            raise GuideCatalogError("guide detail id does not match index")
        raw_blocks = payload.get("blocks", [])
        if not isinstance(raw_blocks, list):
            raise GuideCatalogError("guide blocks must be a list")
        blocks: list[tuple[str, str]] = []
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            kind = str(block.get("kind") or "text")
            text = str(block.get("text") or "").strip()
            if kind in {"heading", "text"} and text:
                blocks.append((kind, text))
        raw_tools = payload.get("tools", [])
        if not isinstance(raw_tools, list):
            raise GuideCatalogError("guide tools must be a list")
        tools = tuple(
            tool
            for tool in (
                GuideTool.from_dict(item)
                for item in raw_tools
                if isinstance(item, dict)
            )
            if tool.applies_to(self.platform)
        )
        return GuideDocument(entry=entry, blocks=tuple(blocks), tools=tools)

    def load_guide(
        self, entry: GuideIndexEntry, *, allow_network: bool = True
    ) -> GuideDocument:
        path = self.cache_dir / entry.asset_name
        if allow_network:
            try:
                raw_payload = self._fetch(entry.asset_name)
                document = self._parse_guide_payload(entry, raw_payload)
            except Exception as error:
                LOGGER.debug(
                    "Ignoring invalid remote guide detail %s: %s",
                    entry.guide_id,
                    error,
                )
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw_payload)
                return document
        bootstrap_path = (
            None if self.bootstrap_dir is None
            else self.bootstrap_dir / entry.asset_name
        )
        for label, candidate in (("cache", path), ("bootstrap", bootstrap_path)):
            if candidate is None or not candidate.is_file():
                continue
            try:
                return self._parse_guide_payload(
                    entry, candidate.read_text(encoding="utf-8")
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ValueError,
                GuideCatalogError,
            ) as error:
                if label == "cache":
                    candidate.unlink(missing_ok=True)
                LOGGER.debug(
                    "Ignoring invalid optional %s guide detail %s at %s: %s",
                    label,
                    entry.guide_id,
                    candidate,
                    error,
                )
        raise GuideCatalogError(f"未找到指南详情：{entry.title}")

    def download_tool(self, tool: GuideTool) -> Path:
        if not tool.applies_to(self.platform):
            raise GuideCatalogError("该工具不适用于当前平台")
        if not tool.filename:
            raise GuideCatalogError("工具必须提供文件名")
        if tool.asset_name:
            url = fixed_release_asset_url(
                self.download_source, "hub", tool.asset_name
            )
        else:
            parsed = urlparse(tool.download_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise GuideCatalogError("工具下载地址必须为 HTTPS，或指定 hub 附件名")
            url = tool.download_url
        target = self.cache_dir / "tools" / tool.tool_id / tool.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._open(url, self.timeout)
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
        return target

    def _fetch(self, asset_name: str) -> bytes:
        return self._open(fixed_release_asset_url(self.download_source, "hub", asset_name), self.timeout)

    @staticmethod
    def _download_bytes(url: str, timeout: float) -> bytes:
        request = Request(url, headers={"Accept": "application/json,application/octet-stream", "User-Agent": "SignRiver-DLC-Hub/0.2"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError) as error:
            raise GuideCatalogError(describe_network_error(error, url=url, action="下载报错指南资源")) from error


__all__ = ["GUIDES_INDEX_ASSET_NAME", "GuideCatalogError", "GuideCatalogService", "GuideDocument", "GuideIndexEntry", "GuideTool"]
