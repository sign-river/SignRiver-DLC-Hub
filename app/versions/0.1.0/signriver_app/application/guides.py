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
    filename: str
    platforms: tuple[str, ...]
    run_mode: str = "open"

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "GuideTool":
        run_mode = str(value.get("run_mode") or "open").strip().lower()
        if run_mode not in {"open", "powershell", "cmd", "shell"}:
            raise ValueError("unsupported guide tool run_mode")
        return cls(
            tool_id=_id(value.get("tool_id"), "tool_id"),
            title=str(value.get("title") or "").strip(),
            description=str(value.get("description") or "").strip(),
            download_url=str(value.get("download_url") or "").strip(),
            filename=Path(str(value.get("filename") or "")).name,
            platforms=_platforms(value.get("platforms")),
            run_mode=run_mode,
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

    def refresh_index(self, *, allow_network: bool = True) -> tuple[GuideIndexEntry, ...]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        candidates: list[tuple[str, Path | None]] = []
        if allow_network:
            try:
                payload = self._fetch(GUIDES_INDEX_ASSET_NAME)
                path = self.cache_dir / GUIDES_INDEX_ASSET_NAME
                path.write_bytes(payload)
                candidates.append(("remote", path))
            except Exception as error:
                LOGGER.info("Optional remote guide index unavailable: %s", error)
        candidates.extend((("cache", self.cache_dir / GUIDES_INDEX_ASSET_NAME),
                           ("bootstrap", None if self.bootstrap_dir is None else self.bootstrap_dir / GUIDES_INDEX_ASSET_NAME)))
        for label, path in candidates:
            if path is None or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if int(payload.get("schema_version", 0)) != _GUIDE_SCHEMA:
                    raise ValueError("unsupported guide schema")
                raw_entries = payload.get("guides")
                if not isinstance(raw_entries, list):
                    raise ValueError("guides must be a list")
                self.entries = tuple(
                    entry for entry in (GuideIndexEntry.from_dict(item) for item in raw_entries if isinstance(item, dict))
                    if entry.applies_to(self.platform)
                )
                return self.entries
            except Exception as error:
                LOGGER.warning("Ignoring invalid %s guide index: %s", label, error)
        self.entries = ()
        return ()

    def load_guide(self, entry: GuideIndexEntry, *, allow_network: bool = True) -> GuideDocument:
        path = self.cache_dir / entry.asset_name
        if allow_network:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self._fetch(entry.asset_name))
            except Exception as error:
                LOGGER.info("Optional remote guide %s unavailable: %s", entry.guide_id, error)
        for candidate in (path, None if self.bootstrap_dir is None else self.bootstrap_dir / entry.asset_name):
            if candidate is None or not candidate.is_file():
                continue
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if _id(payload.get("guide_id"), "guide_id") != entry.guide_id:
                raise GuideCatalogError("guide detail id does not match index")
            raw_blocks = payload.get("blocks", [])
            blocks: list[tuple[str, str]] = []
            if not isinstance(raw_blocks, list):
                raise GuideCatalogError("guide blocks must be a list")
            for block in raw_blocks:
                if not isinstance(block, dict):
                    continue
                kind, text = str(block.get("kind") or "text"), str(block.get("text") or "").strip()
                if kind in {"heading", "text"} and text:
                    blocks.append((kind, text))
            raw_tools = payload.get("tools", [])
            tools = tuple(tool for tool in (GuideTool.from_dict(item) for item in raw_tools if isinstance(item, dict)) if tool.applies_to(self.platform))
            return GuideDocument(entry=entry, blocks=tuple(blocks), tools=tools)
        raise GuideCatalogError(f"未找到指南详情：{entry.title}")

    def download_tool(self, tool: GuideTool) -> Path:
        if not tool.applies_to(self.platform):
            raise GuideCatalogError("该工具不适用于当前平台")
        parsed = urlparse(tool.download_url)
        if parsed.scheme != "https" or not parsed.netloc or not tool.filename:
            raise GuideCatalogError("工具下载地址必须为 HTTPS，且必须提供文件名")
        target = self.cache_dir / "tools" / tool.tool_id / tool.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._open(tool.download_url, self.timeout)
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
