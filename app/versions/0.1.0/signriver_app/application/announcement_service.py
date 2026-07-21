"""Fetch and cache the remote startup announcement from the hub Release."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..domain import ANNOUNCEMENT_ASSET_NAME, Announcement, HUB_RELEASE_TAG
from ..infrastructure.catalog import (
    create_hub_release_source,
    normalize_download_source,
)

LOGGER = logging.getLogger(__name__)


class AnnouncementError(RuntimeError):
    pass


class AnnouncementService:
    def __init__(
        self,
        cache_dir: Path,
        *,
        bootstrap_path: Path | None = None,
        download_source: str = "gitlink",
        source=None,
        opener: Callable[[str, float], bytes] | None = None,
        timeout: float = 15,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.bootstrap_path = Path(bootstrap_path) if bootstrap_path else None
        self.download_source = normalize_download_source(download_source)
        self.source = source or create_hub_release_source(self.download_source)
        self._open = opener or self._download_bytes
        self.timeout = timeout
        self.current: Announcement | None = None
        self.source_label: str | None = None

    def set_download_source(self, download_source: str) -> None:
        normalized = normalize_download_source(download_source)
        if normalized == self.download_source:
            return
        self.download_source = normalized
        self.source = create_hub_release_source(normalized)

    def refresh(self, *, allow_network: bool = True) -> Announcement:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        remote_error: Exception | None = None
        if allow_network:
            try:
                announcement = self._fetch_remote()
                self._write_json(self._cache_path(), announcement.to_dict())
                self.current = announcement
                self.source_label = "remote"
                return announcement
            except Exception as error:
                remote_error = error
                LOGGER.warning("Remote announcement refresh failed: %s", error)
        for label, path in (
            ("cache", self._cache_path()),
            ("bootstrap", self.bootstrap_path),
        ):
            if path is None or not path.is_file():
                continue
            try:
                announcement = Announcement.from_dict(self._read_json(path))
                self.current = announcement
                self.source_label = label
                return announcement
            except Exception as error:
                LOGGER.warning("Ignoring unusable %s announcement: %s", label, error)
        if remote_error is not None:
            raise AnnouncementError(f"无法加载公告：{remote_error}") from remote_error
        raise AnnouncementError("未找到可用公告")

    def should_display(
        self,
        announcement: Announcement,
        *,
        mute_until_update: bool,
        muted_id: str,
    ) -> bool:
        if not mute_until_update:
            return True
        return muted_id.strip() != announcement.announcement_id

    def _fetch_remote(self) -> Announcement:
        release = self.source.get_release_by_tag(HUB_RELEASE_TAG)
        for asset in release.assets:
            if asset.name == ANNOUNCEMENT_ASSET_NAME:
                payload = self._open(asset.download_url, self.timeout)
                return Announcement.from_dict(
                    json.loads(payload.decode("utf-8"))
                )
        raise AnnouncementError(
            f"hub Release 中缺少资源：{ANNOUNCEMENT_ASSET_NAME}"
        )

    def _cache_path(self) -> Path:
        return self.cache_dir / ANNOUNCEMENT_ASSET_NAME

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object")
        return payload

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _download_bytes(url: str, timeout: float) -> bytes:
        from ..infrastructure.net_errors import describe_network_error

        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AnnouncementError("announcement downloads must use HTTPS")
        request = Request(
            url,
            headers={
                "Accept": "application/json,application/octet-stream",
                "User-Agent": "SignRiver-DLC-Hub/0.1",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError) as error:
            raise OSError(
                describe_network_error(error, url=url, action="下载公告")
            ) from error


__all__ = ["AnnouncementError", "AnnouncementService"]
