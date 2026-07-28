"""Minimal GitHub Releases client used by the publisher mirror target."""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote


class GitHubPublisherError(RuntimeError):
    pass


class GitHubUploadPaused(GitHubPublisherError):
    """Raised when a streaming GitHub asset upload is paused by the user."""


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    name: str

    def __post_init__(self) -> None:
        safe_name = re.compile(r"^[A-Za-z0-9_.-]+$")
        if not safe_name.fullmatch(self.owner) or not safe_name.fullmatch(self.name):
            raise GitHubPublisherError("GitHub 所有者和仓库名格式不正确")


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

    def repository_info(self) -> dict[str, object]:
        url = (
            f"{self.api_base}/repos/{quote(self.repository.owner, safe='')}/"
            f"{quote(self.repository.name, safe='')}"
        )
        payload = self._request_json("GET", url)
        if not isinstance(payload, dict):
            raise GitHubPublisherError("GitHub 仓库响应无效")
        return payload

    def create_repository(self, description: str) -> GitHubRepository:
        user = self._request_json("GET", f"{self.api_base}/user")
        if not isinstance(user, dict) or not str(user.get("login") or "").strip():
            raise GitHubPublisherError("无法确认 GitHub token 对应的账户")
        login = str(user["login"]).strip()
        if login.casefold() == self.repository.owner.casefold():
            url = f"{self.api_base}/user/repos"
        else:
            url = (
                f"{self.api_base}/orgs/"
                f"{quote(self.repository.owner, safe='')}/repos"
            )
        payload = self._request_json(
            "POST",
            url,
            body={
                "name": self.repository.name,
                "description": description,
                "private": False,
                "has_issues": False,
                "has_projects": False,
                "has_wiki": False,
                "auto_init": True,
            },
        )
        if not isinstance(payload, dict):
            raise GitHubPublisherError("GitHub 创建仓库响应无效")
        owner = payload.get("owner")
        actual_owner = (
            str(owner.get("login") or "").strip() if isinstance(owner, dict) else ""
        )
        actual_name = str(payload.get("name") or "").strip()
        if not actual_owner or not actual_name:
            raise GitHubPublisherError("GitHub 创建仓库后未返回仓库信息")
        return GitHubRepository(actual_owner, actual_name)

    def ensure_release(self, tag: str, *, name: str | None = None) -> GitHubRelease:
        existing = self.get_release_by_tag(tag)
        if existing is not None:
            return existing
        url = (
            f"{self.api_base}/repos/{self.repository.owner}/"
            f"{self.repository.name}/releases"
        )
        release_payload = {
            "tag_name": tag,
            "name": name or tag,
            "draft": False,
            "prerelease": False,
        }
        try:
            payload = self._request_json("POST", url, body=release_payload)
        except GitHubPublisherError as error:
            if "Repository is empty" not in str(error):
                raise
            self._initialize_repository()
            payload = self._request_json("POST", url, body=release_payload)
        return self._normalize(payload)

    def _initialize_repository(self) -> None:
        url = (
            f"{self.api_base}/repos/{quote(self.repository.owner, safe='')}/"
            f"{quote(self.repository.name, safe='')}/contents/README.md"
        )
        content = base64.b64encode(
            b"# SignRiver DLC release assets\n"
        ).decode("ascii")
        self._request_json(
            "PUT",
            url,
            body={
                "message": "Initialize release repository",
                "content": content,
            },
        )

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
        should_pause: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        path = Path(path)
        if replace_existing:
            for asset in release.assets:
                if str(asset.get("name")) == path.name:
                    self.delete_asset(int(asset["id"]))
        upload_base = release.upload_url.split("{", 1)[0]
        url = f"{upload_base}?name={quote(path.name)}"
        size = path.stat().st_size
        for attempt in range(3):
            body = _FileUploadBody(path, progress=progress, should_pause=should_pause)
            request = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                    "User-Agent": "SignRiver-Publisher/0.1",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            try:
                with self._opener(request, timeout=120) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except GitHubUploadPaused:
                raise
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                if (
                    error.code == 422
                    and "already_exists" in detail
                    and attempt < 2
                ):
                    self._remove_partial_asset(release.tag, path.name)
                    time.sleep(1 << attempt)
                    continue
                raise GitHubPublisherError(
                    f"GitHub 上传失败 HTTP {error.code}: {detail}"
                ) from error
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                if attempt == 2:
                    raise GitHubPublisherError(
                        f"GitHub 上传失败，已重试 3 次：{error}"
                    ) from error
                self._remove_partial_asset(release.tag, path.name)
                time.sleep(1 << attempt)
        if not isinstance(payload, dict):
            raise GitHubPublisherError("GitHub 上传返回了异常响应")
        return payload

    def _remove_partial_asset(self, tag: str, name: str) -> None:
        """Clear a server-side asset when the connection closed after upload."""
        try:
            release = self.get_release_by_tag(tag)
        except GitHubPublisherError:
            return
        if release is None:
            return
        for asset in release.assets:
            if str(asset.get("name")) == name and asset.get("id") is not None:
                self.delete_asset(int(asset["id"]))

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
            with self._open_request(request, timeout=60) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise GitHubPublisherError(
                f"GitHub API HTTP {error.code}: {detail}"
            ) from error
        except OSError as error:
            raise GitHubPublisherError(
                f"GitHub 连接失败，请检查网络或代理设置：{error}"
            ) from error
        if not expect_json or not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GitHubPublisherError(f"GitHub API 响应不是 JSON：{error}") from error

    def _open_request(self, request, *, timeout: int):
        for attempt in range(3):
            try:
                return self._opener(request, timeout=timeout)
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, OSError):
                if attempt == 2:
                    raise
                time.sleep(1 << attempt)


class _FileUploadBody:
    """Iterable request body that reports real upload progress per chunk."""

    def __init__(
        self,
        path: Path,
        *,
        progress: Callable[[int, int], None] | None,
        should_pause: Callable[[], bool] | None,
    ) -> None:
        self.path = path
        self.progress = progress
        self.should_pause = should_pause
        self.size = path.stat().st_size

    def __iter__(self):
        sent = 0
        if self.progress is not None:
            self.progress(sent, self.size)
        with self.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if self.should_pause is not None and self.should_pause():
                    raise GitHubUploadPaused(f"发布已暂停：{self.path.name}")
                yield chunk
                sent += len(chunk)
                if self.progress is not None:
                    self.progress(sent, self.size)


__all__ = [
    "GitHubPublisherError",
    "GitHubRelease",
    "GitHubReleaseClient",
    "GitHubRepository",
    "GitHubUploadPaused",
]
