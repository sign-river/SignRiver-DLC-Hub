"""Read-only GitHub Releases source with the same DTO shape as GitLink."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ...domain import NormalizedRelease, ReleaseAsset
from .gitlink import ReleaseSourceError

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class GitHubSourceConfig:
    owner: str
    repository: str
    api_base_url: str = "https://api.github.com"
    download_base_url: str = "https://github.com"

    def __post_init__(self) -> None:
        if not _SAFE_COMPONENT.fullmatch(self.owner):
            raise ValueError("invalid GitHub owner")
        if not _SAFE_COMPONENT.fullmatch(self.repository):
            raise ValueError("invalid GitHub repository")
        for field_name, value in (
            ("api_base_url", self.api_base_url),
            ("download_base_url", self.download_base_url),
        ):
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError(f"GitHub {field_name} must be an HTTPS origin")


class GitHubReleaseSource:
    """Fetch and normalize public GitHub releases without downloading assets."""

    def __init__(
        self,
        config: GitHubSourceConfig,
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
        return (
            f"{self.config.api_base_url.rstrip('/')}"
            f"/repos/{self.config.owner}/{self.config.repository}/releases"
        )

    def list_releases(self) -> tuple[NormalizedRelease, ...]:
        try:
            payload = json.loads(
                self._fetch(self.releases_url, self.timeout, self.max_response_bytes)
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ReleaseSourceError(f"unable to read GitHub releases: {error}") from error
        if not isinstance(payload, list):
            raise ReleaseSourceError("GitHub returned an unexpected release response")
        return tuple(self._normalize_release(item) for item in payload)

    def get_release_by_tag(self, tag: str) -> NormalizedRelease:
        if not _SAFE_COMPONENT.fullmatch(tag):
            raise ValueError("invalid GitHub release tag")
        url = f"{self.releases_url}/tags/{tag}"
        try:
            payload = json.loads(self._fetch(url, self.timeout, self.max_response_bytes))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            # Fall back to scanning the list so mirrors that omit the tags
            # endpoint still work with the same layout as GitLink.
            try:
                for release in self.list_releases():
                    if release.tag == tag:
                        return release
            except ReleaseSourceError:
                pass
            raise ReleaseSourceError(
                f"unable to read GitHub release tag {tag}: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise ReleaseSourceError("GitHub returned a malformed tagged release")
        return self._normalize_release(payload)

    def _normalize_release(self, value: object) -> NormalizedRelease:
        if not isinstance(value, dict):
            raise ReleaseSourceError("GitHub returned a malformed release")
        assets: list[ReleaseAsset] = []
        for raw_asset in value.get("assets", []):
            if not isinstance(raw_asset, dict):
                continue
            name = raw_asset.get("name")
            download_url = raw_asset.get("browser_download_url")
            if not isinstance(name, str) or not isinstance(download_url, str):
                continue
            parsed = urlparse(download_url)
            allowed = {
                urlparse(self.config.download_base_url).netloc,
                "github.com",
                "objects.githubusercontent.com",
                "release-assets.githubusercontent.com",
            }
            if parsed.scheme != "https" or parsed.netloc not in allowed:
                raise ReleaseSourceError("GitHub asset URL escaped the allowed hosts")
            size = raw_asset.get("size")
            size_bytes = int(size) if isinstance(size, int) and size >= 0 else None
            assets.append(
                ReleaseAsset(
                    asset_id=str(raw_asset.get("id", "")),
                    name=name,
                    download_url=download_url,
                    display_size=None if size_bytes is None else f"{size_bytes} B",
                    size_bytes=size_bytes,
                )
            )
        return NormalizedRelease(
            release_id=str(value.get("id", "")),
            tag=str(value.get("tag_name", "")),
            name=str(value.get("name", "") or value.get("tag_name", "")),
            description=str(value.get("body", "") or ""),
            assets=tuple(assets),
        )

    @staticmethod
    def _fetch_json(url: str, timeout: float, limit: int) -> bytes:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "SignRiver-DLC-Hub/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https":
                raise ReleaseSourceError("GitHub redirected to a non-HTTPS endpoint")
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ReleaseSourceError("GitHub release response is too large")
        return data


__all__ = ["GitHubReleaseSource", "GitHubSourceConfig"]
