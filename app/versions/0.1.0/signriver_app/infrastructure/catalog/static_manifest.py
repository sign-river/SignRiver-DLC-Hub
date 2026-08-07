"""Static Release catalog source that avoids provider API rate limits."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ...domain import NormalizedRelease, ReleaseAsset
from ..net_errors import describe_network_error
from .gitlink import ReleaseSourceError

CATALOG_ASSET_NAME = "catalog.json"
CATALOG_SCHEMA_VERSION = 1
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


class StaticManifestReleaseSource:
    """Read a fixed catalog asset, with legacy API and disk-cache fallbacks."""

    def __init__(
        self, provider: str, owner: str, repository: str, *, legacy_source,
        cache_path: Path | None = None, timeout: float = 15,
        max_response_bytes: int = 4 * 1024 * 1024,
        fetch: Callable[[str, float, int], bytes] | None = None,
    ) -> None:
        if provider not in {"gitlink", "github"}:
            raise ValueError("provider must be gitlink or github")
        if not _SAFE_COMPONENT.fullmatch(owner) or not _SAFE_COMPONENT.fullmatch(repository):
            raise ValueError("invalid release repository")
        self.provider = provider
        self.owner = owner
        self.repository = repository
        self.legacy_source = legacy_source
        self.cache_path = cache_path
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self._fetch = fetch or self._fetch_bytes

    def manifest_url(self, tag: str) -> str:
        host = "github.com" if self.provider == "github" else "gitlink.org.cn"
        return (
            f"https://{host}/{self.owner}/{self.repository}/releases/download/"
            f"{quote(tag, safe='')}/{CATALOG_ASSET_NAME}"
        )

    def asset_url(self, tag: str, name: str) -> str:
        host = "github.com" if self.provider == "github" else "gitlink.org.cn"
        return (
            f"https://{host}/{self.owner}/{self.repository}/releases/download/"
            f"{quote(tag, safe='')}/{quote(name, safe='._-')}"
        )

    def get_release_by_tag(self, tag: str) -> NormalizedRelease:
        if not _SAFE_COMPONENT.fullmatch(tag):
            raise ValueError("invalid release tag")
        errors: list[str] = []
        try:
            payload = self._fetch(
                self.manifest_url(tag), self.timeout, self.max_response_bytes
            )
            release = self._parse(payload, expected_tag=tag)
            self._save_cache(payload)
            return release
        except (OSError, ValueError, TypeError, json.JSONDecodeError, ReleaseSourceError) as error:
            errors.append(f"静态目录不可用：{error}")
        try:
            return self.legacy_source.get_release_by_tag(tag)
        except Exception as error:
            errors.append(f"Release 接口不可用：{error}")
        try:
            if self.cache_path is None:
                raise OSError("没有本地缓存")
            return self._parse(self.cache_path.read_bytes(), expected_tag=tag)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, ReleaseSourceError) as error:
            errors.append(f"本地缓存不可用：{error}")
        raise ReleaseSourceError("；".join(errors))

    def _parse(self, payload: bytes, *, expected_tag: str) -> NormalizedRelease:
        value = json.loads(payload)
        if not isinstance(value, dict) or value.get("schema_version") != CATALOG_SCHEMA_VERSION:
            raise ReleaseSourceError("静态目录格式或版本无效")
        tag = str(value.get("release_tag") or "")
        if tag != expected_tag:
            raise ReleaseSourceError("静态目录 Release 标签不匹配")
        raw_assets = value.get("assets")
        if not isinstance(raw_assets, list):
            raise ReleaseSourceError("静态目录缺少 assets")
        assets: list[ReleaseAsset] = []
        seen: set[str] = set()
        for raw in raw_assets:
            if not isinstance(raw, dict):
                raise ReleaseSourceError("静态目录包含无效附件")
            name = str(raw.get("name") or "")
            if not name or Path(name).name != name or name.casefold() in seen:
                raise ReleaseSourceError("静态目录包含不安全或重复的附件名")
            seen.add(name.casefold())
            size = raw.get("size_bytes")
            size_bytes = int(size) if isinstance(size, int) and size >= 0 else None
            digest = str(raw.get("sha256") or "").lower()
            asset_id = digest if re.fullmatch(r"[0-9a-f]{64}", digest) else name
            assets.append(ReleaseAsset(
                asset_id=asset_id, name=name,
                download_url=self.asset_url(tag, name),
                display_size=None if size_bytes is None else f"{size_bytes} B",
                size_bytes=size_bytes,
            ))
        return NormalizedRelease(
            release_id=f"static:{self.provider}:{tag}", tag=tag,
            name=str(value.get("name") or tag),
            description=str(value.get("description") or ""), assets=tuple(assets),
        )

    def _save_cache(self, payload: bytes) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(self.cache_path)

    @staticmethod
    def _fetch_bytes(url: str, timeout: float, limit: int) -> bytes:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "SignRiver-DLC-Hub/0.1"})
        try:
            with urlopen(request, timeout=timeout) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https":
                    raise ReleaseSourceError("静态目录重定向到了非 HTTPS 地址")
                data = response.read(limit + 1)
        except ReleaseSourceError:
            raise
        except (OSError, TimeoutError) as error:
            raise ReleaseSourceError(describe_network_error(error, url=url, action="读取静态目录")) from error
        if len(data) > limit:
            raise ReleaseSourceError("静态目录响应过大")
        return data


__all__ = ["CATALOG_ASSET_NAME", "CATALOG_SCHEMA_VERSION", "StaticManifestReleaseSource"]
