"""Minimal GitHub Releases client used by the publisher mirror target."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote


class GitHubPublisherError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    name: str


@dataclass(frozen=True, slots=True)
class GitHubRelease:
    release_id: int
    tag: str
    upload_url: str
    assets: tuple[dict[str, object], ...]


class GitHubReleaseClient:
    """Create/update public GitHub Releases and upload assets by filename."""

    def __init__(
        self,
        repository: GitHubRepository,
        token: str,
        *,
        api_base: str = "https://api.github.com",
        opener: Callable[..., object] | None = None,
    ) -> None:
        if not token.strip():
            raise GitHubPublisherError("GitHub token 不能为空")
        self.repository = repository
        self.token = token.strip()
        self.api_base = api_base.rstrip("/")
        self._opener = opener or urllib.request.urlopen

    def get_release_by_tag(self, tag: str) -> GitHubRelease | None:
        url = (
            f"{self.api_base}/repos/{self.repository.owner}/"
            f"{self.repository.name}/releases/tags/{quote(tag)}"
        )
        try:
            payload = self._request_json("GET", url)
        except GitHubPublisherError as error:
            if "404" in str(error):
                return None
            raise
        return self._normalize(payload)

    def ensure_release(self, tag: str, *, name: str | None = None) -> GitHubRelease:
        existing = self.get_release_by_tag(tag)
        if existing is not None:
            return existing
        url = (
            f"{self.api_base}/repos/{self.repository.owner}/"
            f"{self.repository.name}/releases"
        )
        payload = self._request_json(
            "POST",
            url,
            body={
                "tag_name": tag,
                "name": name or tag,
                "draft": False,
                "prerelease": False,
            },
        )
        return self._normalize(payload)

    def delete_asset(self, asset_id: int) -> None:
        url = (
            f"{self.api_base}/repos/{self.repository.owner}/"
            f"{self.repository.name}/releases/assets/{asset_id}"
        )
        self._request_json("DELETE", url, expect_json=False)

    def upload_asset(
        self,
        release: GitHubRelease,
        path: Path,
        *,
        replace_existing: bool = True,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, object]:
        path = Path(path)
        if replace_existing:
            for asset in release.assets:
                if str(asset.get("name")) == path.name:
                    self.delete_asset(int(asset["id"]))
        upload_base = release.upload_url.split("{", 1)[0]
        url = f"{upload_base}?name={quote(path.name)}"
        data = path.read_bytes()
        if progress is not None:
            progress(0, len(data))
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(data)),
                "User-Agent": "SignRiver-Publisher/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self._opener(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise GitHubPublisherError(
                f"GitHub 上传失败 HTTP {error.code}: {detail}"
            ) from error
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise GitHubPublisherError(f"GitHub 上传失败：{error}") from error
        if progress is not None:
            progress(len(data), len(data))
        if not isinstance(payload, dict):
            raise GitHubPublisherError("GitHub 上传返回了异常响应")
        return payload

    def _normalize(self, payload: object) -> GitHubRelease:
        if not isinstance(payload, dict):
            raise GitHubPublisherError("GitHub Release 响应无效")
        assets = payload.get("assets")
        return GitHubRelease(
            release_id=int(payload["id"]),
            tag=str(payload.get("tag_name") or ""),
            upload_url=str(payload.get("upload_url") or ""),
            assets=tuple(assets) if isinstance(assets, list) else (),
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, object] | None = None,
        expect_json: bool = True,
    ) -> object:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "SignRiver-Publisher/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener(request, timeout=60) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise GitHubPublisherError(
                f"GitHub API HTTP {error.code}: {detail}"
            ) from error
        except OSError as error:
            raise GitHubPublisherError(f"GitHub API 请求失败：{error}") from error
        if not expect_json or not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GitHubPublisherError(f"GitHub API 响应不是 JSON：{error}") from error


__all__ = [
    "GitHubPublisherError",
    "GitHubRelease",
    "GitHubReleaseClient",
    "GitHubRepository",
]
