"""Download, extract and launch solution helper tools from the tools Release."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import threading
import zipfile
import json
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.request import Request, urlopen

from .guides import GuideTool
from ..infrastructure.catalog import fixed_release_asset_url, normalize_download_source
from ..infrastructure.net_errors import describe_network_error

LOGGER = logging.getLogger(__name__)
_CHUNK_SIZE = 64 * 1024


class HelperToolError(RuntimeError):
    """A solution helper tool could not be downloaded, extracted or launched."""


class HelperToolCancelled(HelperToolError):
    """The current helper-tool download was cancelled by the user."""


def _safe_zip_member(info: zipfile.ZipInfo) -> PurePosixPath | None:
    path = PurePosixPath(info.filename.replace("\\", "/"))
    if not path.parts:
        return None
    if path.is_absolute() or ".." in path.parts:
        raise HelperToolError(f"压缩包包含不安全路径：{info.filename}")
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise HelperToolError(f"压缩包不允许包含符号链接：{info.filename}")
    return path


class HelperToolsService:
    """Stores helper tools under ``data/helper-tools/{tool_id}/``."""

    def __init__(
        self,
        root: Path,
        *,
        download_source: str = "gitlink",
        opener: Callable[..., bytes] | None = None,
        timeout: float = 30,
    ) -> None:
        self.root = Path(root)
        self.download_source = normalize_download_source(download_source)
        self.timeout = timeout
        self._open = opener

    def set_download_source(self, source: str) -> None:
        self.download_source = normalize_download_source(source)

    def tool_dir(self, tool_id: str) -> Path:
        return self.root / str(tool_id).strip()

    def _metadata_path(self, tool: GuideTool) -> Path:
        return self.tool_dir(tool.tool_id) / ".tool-meta.json"

    @staticmethod
    def _signature(tool: GuideTool) -> dict[str, object]:
        return {
            "tool_id": tool.tool_id,
            "revision": tool.revision,
            "asset_name": tool.asset_name,
            "filename": tool.filename,
            "release_tag": tool.release_tag,
            "package_kind": tool.package_kind,
            "launch_action": tool.launch_action,
            "executable_name": tool.executable_name,
            "requires_cloud_download": tool.requires_cloud_download,
        }

    def resolve_url(self, tool: GuideTool) -> str:
        if tool.asset_name:
            return fixed_release_asset_url(
                self.download_source, tool.release_tag, tool.asset_name
            )
        parsed_scheme = str(tool.download_url or "").strip()
        if not parsed_scheme.lower().startswith("https://"):
            raise HelperToolError("工具下载地址必须为 HTTPS，或指定 Release 附件名")
        return tool.download_url

    def is_installed(self, tool: GuideTool) -> bool:
        root = self.tool_dir(tool.tool_id)
        if not root.is_dir():
            return False
        try:
            metadata = json.loads(self._metadata_path(tool).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if metadata != self._signature(tool):
            return False
        if tool.launch_action == "exe":
            return self.find_executable(tool) is not None
        return any(
            path.is_file() and not path.name.startswith(".")
            for path in root.rglob("*")
        )

    def find_executable(self, tool: GuideTool) -> Path | None:
        root = self.tool_dir(tool.tool_id)
        wanted = str(tool.executable_name or "").casefold()
        if not root.is_dir() or not wanted:
            return None
        matches = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.name.casefold() == wanted
        ]
        matches.sort(key=lambda path: (len(path.parts), str(path).casefold()))
        return matches[0] if matches else None

    def download(self, tool: GuideTool, cancel_event: threading.Event | None = None) -> Path:
        cancel = cancel_event or threading.Event()
        dest = self.tool_dir(tool.tool_id)
        LOGGER.info(
            "Helper tool download started: tool=%s revision=%s source=%s asset=%s",
            tool.tool_id, tool.revision or "", self.download_source, tool.asset_name or tool.filename,
        )
        staging = self.root / f".{tool.tool_id}.download"
        backup = self.root / f".{tool.tool_id}.previous"
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists():
            shutil.rmtree(backup)
        staging.mkdir(parents=True, exist_ok=True)
        filename = tool.asset_name or tool.filename or f"{tool.tool_id}.bin"
        part = staging / f".{filename}.part"
        try:
            payload = self._fetch(self.resolve_url(tool), cancel)
            if cancel.is_set():
                raise HelperToolCancelled("已取消下载")
            if not payload:
                raise HelperToolError("工具下载为空")
            part.write_bytes(payload)
            os.replace(part, staging / filename)
            if tool.package_kind == "zip":
                self._extract_zip(staging / filename, staging)
                (staging / filename).unlink(missing_ok=True)
            (staging / ".tool-meta.json").write_text(
                json.dumps(self._signature(tool), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            if dest.exists():
                os.replace(dest, backup)
            os.replace(staging, dest)
            if backup.exists():
                shutil.rmtree(backup)
            LOGGER.info(
                "Helper tool download finished: tool=%s revision=%s path=%s",
                tool.tool_id, tool.revision or "", dest,
            )
            return dest
        except HelperToolCancelled:
            LOGGER.info("Helper tool download cancelled: tool=%s revision=%s", tool.tool_id, tool.revision or "")
            if staging.exists():
                shutil.rmtree(staging)
            raise
        except Exception:
            LOGGER.exception("Helper tool download failed: tool=%s revision=%s", tool.tool_id, tool.revision or "")
            if staging.exists():
                shutil.rmtree(staging)
            if not dest.exists() and backup.exists():
                os.replace(backup, dest)
            raise
        finally:
            part.unlink(missing_ok=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if backup.exists() and dest.exists():
                shutil.rmtree(backup, ignore_errors=True)

    def delete(self, tool_id: str) -> None:
        dest = self.tool_dir(tool_id)
        if dest.exists():
            shutil.rmtree(dest)

    def _fetch(self, url: str, cancel: threading.Event) -> bytes:
        if self._open is not None:
            try:
                return self._open(url, self.timeout, cancel)
            except TypeError:
                if cancel.is_set():
                    raise HelperToolCancelled("已取消下载") from None
                return self._open(url, self.timeout)
        return self._stream_bytes(url, cancel)

    def _stream_bytes(self, url: str, cancel: threading.Event) -> bytes:
        request = Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "SignRiver-DLC-Hub/0.2",
            },
        )
        chunks: list[bytes] = []
        try:
            with urlopen(request, timeout=self.timeout) as response:
                while True:
                    if cancel.is_set():
                        raise HelperToolCancelled("已取消下载")
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except HelperToolCancelled:
            raise
        except (OSError, TimeoutError) as error:
            raise HelperToolError(
                describe_network_error(error, url=url, action="下载辅助工具")
            ) from error
        if cancel.is_set():
            raise HelperToolCancelled("已取消下载")
        return b"".join(chunks)

    @staticmethod
    def _extract_zip(archive: Path, dest: Path) -> None:
        if not zipfile.is_zipfile(archive):
            raise HelperToolError("下载的工具不是有效的 ZIP 压缩包")
        with zipfile.ZipFile(archive) as package:
            for info in package.infolist():
                member = _safe_zip_member(info)
                if member is None:
                    continue
                target = dest.joinpath(*member.parts)
                if info.is_dir() or info.filename.endswith(("/", "\\")):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)


__all__ = [
    "HelperToolCancelled",
    "HelperToolError",
    "HelperToolsService",
]
