"""Read-only GitLink release source."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ...domain import NormalizedRelease, ReleaseAsset
from ..net_errors import describe_network_error

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


class ReleaseSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GitLinkSourceConfig:
    owner: str
    repository: str
    base_url: str = "https://www.gitlink.org.cn"

    def __post_init__(self) -> None:
        if not _SAFE_COMPONENT.fullmatch(self.owner):
            raise ValueError("invalid GitLink owner")
        if not _SAFE_COMPONENT.fullmatch(self.repository):
            raise ValueError("invalid GitLink repository")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("GitLink base_url must be an HTTPS origin")


def _parse_display_size(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(字节|B|KB|MB|GB)\s*", value, re.I)
    if not match:
        return None
    unit = "B" if match.group(2) == "字节" else match.group(2).upper()
    return round(float(match.group(1)) * _SIZE_UNITS[unit])


class GitLinkReleaseSource:
    """Fetch and normalize public GitLink releases without downloading assets."""

    def __init__(
        self,
        config: GitLinkSourceConfig,
        *,
        timeout: float = 15,
        max_response_bytes: int = 2 * 1024 * 1024,
        fetch: Callable[[str, float, int], bytes] | None = None,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self._fetch = fetch or self._fetch_json

    @property
    def releases_url(self) -> str:
        return urljoin(
            self.config.base_url.rstrip("/") + "/",
            f"api/{self.config.owner}/{self.config.repository}/releases",
        )

    def list_releases(self) -> tuple[NormalizedRelease, ...]:
        try:
            payload = json.loads(
                self._fetch(self.releases_url, self.timeout, self.max_response_bytes)
            )
        except ReleaseSourceError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ReleaseSourceError(f"无法读取 GitLink Release 列表：{error}") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("releases"), list):
            raise ReleaseSourceError("GitLink 返回了意外的 Release 响应")
        return tuple(self._normalize_release(item) for item in payload["releases"])

    def get_release_by_tag(self, tag: str) -> NormalizedRelease:
        if not _SAFE_COMPONENT.fullmatch(tag):
            raise ValueError("invalid GitLink release tag")
        for release in self.list_releases():
            if release.tag == tag:
                return release
        raise ReleaseSourceError(f"未找到 GitLink Release 标签：{tag}")

    def _normalize_release(self, value: object) -> NormalizedRelease:
        if not isinstance(value, dict):
            raise ReleaseSourceError("GitLink 返回了格式错误的 Release")
        assets: list[ReleaseAsset] = []
        for raw_asset in value.get("attachments", []):
            if not isinstance(raw_asset, dict):
                continue
            relative_url = raw_asset.get("url")
            name = raw_asset.get("title")
            if not isinstance(relative_url, str) or not isinstance(name, str):
                continue
            absolute_url = urljoin(self.config.base_url.rstrip("/") + "/", relative_url)
            parsed = urlparse(absolute_url)
            base = urlparse(self.config.base_url)
            if parsed.scheme != "https" or parsed.netloc != base.netloc:
                raise ReleaseSourceError("GitLink 资源链接超出了配置的源站")
            display_size = raw_asset.get("filesize")
            assets.append(
                ReleaseAsset(
                    asset_id=str(raw_asset.get("id", "")),
                    name=name,
                    download_url=absolute_url,
                    display_size=display_size if isinstance(display_size, str) else None,
                    size_bytes=_parse_display_size(display_size),
                )
            )
        return NormalizedRelease(
            release_id=str(value.get("id", "")),
            tag=str(value.get("tag_name", "")),
            name=str(value.get("name", "")),
            description=str(value.get("body", "")),
            assets=tuple(assets),
        )

    @staticmethod
    def _fetch_json(url: str, timeout: float, limit: int) -> bytes:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "SignRiver-DLC-Hub/0.1"})
        try:
            with urlopen(request, timeout=timeout) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https":
                    raise ReleaseSourceError("GitLink 重定向到了非 HTTPS 地址")
                data = response.read(limit + 1)
        except ReleaseSourceError:
            raise
        except (OSError, TimeoutError) as error:
            raise ReleaseSourceError(
                describe_network_error(error, url=url, action="访问 GitLink")
            ) from error
        if len(data) > limit:
            raise ReleaseSourceError("GitLink Release 响应过大")
        return data
