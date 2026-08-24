"""Download, extract and launch solution helper tools from the tools Release."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import threading
import zipfile
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
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        filename = tool.asset_name or tool.filename or f"{tool.tool_id}.bin"
        part = dest / f".{filename}.part"
        archive = dest / filename
        try:
            payload = self._fetch(self.resolve_url(tool), cancel)
            if cancel.is_set():
                raise HelperToolCancelled("已取消下载")
            if not payload:
                raise HelperToolError("工具下载为空")
            part.write_bytes(payload)
            os.replace(part, archive)
            if tool.package_kind == "zip":
                self._extract_zip(archive, dest)
                archive.unlink(missing_ok=True)
            return dest
        except HelperToolCancelled:
            self.delete(tool.tool_id)
            raise
        except Exception:
            self.delete(tool.tool_id)
            raise
        finally:
            part.unlink(missing_ok=True)

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
