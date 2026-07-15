from __future__ import annotations

import json
import http.client
import mimetypes
import os
import secrets
import shutil
import subprocess
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse


class GitLinkError(RuntimeError):
    pass


class UploadPaused(GitLinkError):
    """Raised after the current HTTP upload has been aborted by the user."""


class UploadControl:
    def __init__(self) -> None:
        self._pause_requested = threading.Event()

    def request_pause(self) -> None:
        self._pause_requested.set()

    @property
    def pause_requested(self) -> bool:
        return self._pause_requested.is_set()


@dataclass(frozen=True, slots=True)
class GitLinkRepository:
    owner: str = "signriver"
    name: str = "signriver-dlc-assets"

    def __post_init__(self) -> None:
        safe = re.compile(r"^[A-Za-z0-9_.-]+$")
        if not safe.fullmatch(self.owner) or not safe.fullmatch(self.name):
            raise GitLinkError("GitLink 所有者和仓库名格式不正确")


class GitLinkCli:
    """Safe wrapper around GitLink's official CLI; credentials stay in its keychain."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("gitlink-cli") or ""

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def current_user(self) -> dict[str, object]:
        return self._json("user", "+me")

    def repository_info(self, repository: GitLinkRepository) -> dict[str, object]:
        return self._json(
            "repo", "+info", "--owner", repository.owner, "--repo", repository.name
        )

    def create_repository(
        self, repository: GitLinkRepository, description: str
    ) -> dict[str, object]:
        # The official create shortcut creates the repository for the logged-in account.
        return self._json("repo", "+create", "-n", repository.name, "-d", description)

    def list_releases(
        self, repository: GitLinkRepository, *, token: str | None = None
    ) -> dict[str, object]:
        return self._json(
            "release",
            "+list",
            "--owner",
            repository.owner,
            "--repo",
            repository.name,
            token=token,
        )

    def create_release(
        self,
        repository: GitLinkRepository,
        *,
        tag: str,
        name: str,
        body: str,
        attachment_ids: list[str],
        token: str | None = None,
    ) -> dict[str, object]:
        return self._json(
            "release",
            "+create",
            "--owner",
            repository.owner,
            "--repo",
            repository.name,
            "--tag",
            tag,
            "--name",
            name,
            "--body",
            body,
            "--attachment-ids",
            ",".join(attachment_ids),
            token=token,
        )

    def update_release(
        self,
        repository: GitLinkRepository,
        *,
        release_id: str,
        tag: str,
        name: str,
        body: str,
        attachment_ids: list[str],
        token: str | None = None,
    ) -> dict[str, object]:
        return self._json(
            "release",
            "+update",
            "--owner",
            repository.owner,
            "--repo",
            repository.name,
            "--id",
            release_id,
            "--tag",
            tag,
            "--name",
            name,
            "--body",
            body,
            "--attachment-ids",
            ",".join(attachment_ids),
            token=token,
        )

    def _json(self, *arguments: str, token: str | None = None) -> dict[str, object]:
        if not self.available:
            raise GitLinkError("未安装 GitLink 官方命令行工具 gitlink-cli")
        command = [self.executable, *arguments, "--format", "json"]
        try:
            environment = os.environ.copy()
            if token:
                environment["GITLINK_TOKEN"] = token
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
                shell=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitLinkError(f"GitLink 命令执行失败：{error}") from error
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise GitLinkError(message or f"GitLink 命令退出码 {result.returncode}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise GitLinkError("GitLink 返回了无法识别的结果") from error
        if not isinstance(value, dict):
            raise GitLinkError("GitLink 返回格式不正确")
        return value


class GitLinkAttachmentClient:
    """Stream files to GitLink's documented attachment endpoint."""

    def __init__(
        self, token: str | None = None, *, base_url: str = "https://www.gitlink.org.cn"
    ) -> None:
        self.token = (token or os.environ.get("GITLINK_TOKEN", "")).strip()
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("GitLink base URL must be an HTTPS origin")
        self.host = parsed.hostname
        self.port = parsed.port

    def upload(
        self,
        path: Path,
        progress: Callable[[int, int], None] | None = None,
        control: UploadControl | None = None,
    ) -> str:
        if not self.token:
            raise GitLinkError("请输入 GitLink 私有令牌，或设置 GITLINK_TOKEN")
        path = path.resolve()
        if not path.is_file():
            raise GitLinkError(f"待上传文件不存在：{path.name}")
        boundary = "----SignRiver" + secrets.token_hex(16)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{_safe_filename(path.name)}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        file_size = path.stat().st_size
        total = len(prefix) + file_size + len(suffix)
        connection = http.client.HTTPSConnection(self.host, self.port, timeout=120)
        try:
            connection.putrequest("POST", "/api/attachments.json")
            connection.putheader("Authorization", f"Bearer {self.token}")
            connection.putheader("Accept", "application/json")
            connection.putheader("User-Agent", "SignRiver-Publisher/0.1")
            connection.putheader(
                "Content-Type", f"multipart/form-data; boundary={boundary}"
            )
            connection.putheader("Content-Length", str(total))
            connection.endheaders()
            connection.send(prefix)
            sent = 0
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    if control is not None and control.pause_requested:
                        raise UploadPaused(f"发布已暂停：{path.name}")
                    connection.send(chunk)
                    sent += len(chunk)
                    if progress:
                        progress(sent, file_size)
            if control is not None and control.pause_requested:
                raise UploadPaused(f"发布已暂停：{path.name}")
            connection.send(suffix)
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise GitLinkError("GitLink 上传响应过大")
            if response.status < 200 or response.status >= 300:
                message = raw.decode("utf-8", errors="replace").strip()
                raise GitLinkError(
                    f"上传 {path.name} 失败（HTTP {response.status}）：{message[:300]}"
                )
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as error:
                raise GitLinkError(f"上传 {path.name} 后收到无效响应") from error
            attachment_id = _find_attachment_id(value)
            if not attachment_id:
                raise GitLinkError(f"上传 {path.name} 后没有取得附件 ID")
            return attachment_id
        except OSError as error:
            raise GitLinkError(f"上传 {path.name} 失败：{error}") from error
        finally:
            connection.close()

    def list_releases(self, repository: GitLinkRepository) -> dict[str, object]:
        return self._json_request(
            "GET",
            f"/api/{repository.owner}/{repository.name}/releases.json?page=1&limit=100",
        )

    def create_release(
        self,
        repository: GitLinkRepository,
        *,
        tag: str,
        name: str,
        body: str,
        attachment_ids: list[str],
    ) -> dict[str, object]:
        return self._json_request(
            "POST",
            f"/api/{repository.owner}/{repository.name}/releases.json",
            _release_payload(tag, name, body, attachment_ids),
        )

    def update_release(
        self,
        repository: GitLinkRepository,
        *,
        release_id: str,
        tag: str,
        name: str,
        body: str,
        attachment_ids: list[str],
    ) -> dict[str, object]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", release_id):
            raise GitLinkError("Release ID 格式不正确")
        return self._json_request(
            "PUT",
            f"/api/{repository.owner}/{repository.name}/releases/{release_id}.json",
            _release_payload(tag, name, body, attachment_ids),
        )

    def delete_attachment(self, attachment_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", attachment_id):
            raise GitLinkError("附件 ID 格式不正确")
        self._json_request(
            "DELETE", f"/api/attachments/{attachment_id}.json", allow_empty=True
        )

    def attachment_matches(self, attachment_id: str, expected_name: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", attachment_id):
            raise GitLinkError("附件 ID 格式不正确")
        if not self.token:
            raise GitLinkError("请输入 GitLink 私有令牌，或设置 GITLINK_TOKEN")
        connection = http.client.HTTPSConnection(self.host, self.port, timeout=30)
        try:
            connection.request(
                "HEAD",
                f"/api/attachments/{attachment_id}.json",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "User-Agent": "SignRiver-Publisher/0.1",
                },
            )
            response = connection.getresponse()
            if response.status == 404:
                return False
            if response.status < 200 or response.status >= 300:
                raise GitLinkError(
                    f"检查附件失败（HTTP {response.status}）：{expected_name}"
                )
            disposition = response.getheader("Content-Disposition", "")
            encoded = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
            plain = re.search(r'filename="?([^";]+)', disposition, re.I)
            remote_name = (
                unquote(encoded.group(1))
                if encoded
                else (plain.group(1).strip() if plain else "")
            )
            return (
                bool(remote_name) and remote_name.casefold() == expected_name.casefold()
            )
        except OSError as error:
            raise GitLinkError(f"检查附件失败：{expected_name}（{error}）") from error
        finally:
            connection.close()

    def _json_request(
        self,
        method: str,
        target: str,
        payload: dict[str, object] | None = None,
        *,
        allow_empty: bool = False,
    ) -> dict[str, object]:
        if not self.token:
            raise GitLinkError("请输入 GitLink 私有令牌，或设置 GITLINK_TOKEN")
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "SignRiver-Publisher/0.1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        connection = http.client.HTTPSConnection(self.host, self.port, timeout=60)
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise GitLinkError("GitLink 响应过大")
            if response.status < 200 or response.status >= 300:
                message = raw.decode("utf-8", errors="replace").strip()
                raise GitLinkError(
                    f"GitLink API 请求失败（HTTP {response.status}）：{message[:300]}"
                )
            if allow_empty and not raw.strip():
                return {}
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as error:
                raise GitLinkError("GitLink 返回了无法识别的结果") from error
            if not isinstance(value, dict):
                raise GitLinkError("GitLink 返回格式不正确")
            api_status = value.get("status")
            try:
                api_status_code = int(api_status) if api_status is not None else 0
            except (TypeError, ValueError):
                api_status_code = 0
            if api_status_code >= 400:
                api_message = str(
                    value.get("message") or value.get("error") or "请求失败"
                ).strip()
                raise GitLinkError(
                    f"GitLink API 返回错误（{api_status_code}）：{api_message}"
                )
            return value
        except OSError as error:
            raise GitLinkError(f"GitLink 连接失败：{error}") from error
        finally:
            connection.close()


def find_release_id(payload: dict[str, object], tag: str) -> str | None:
    candidates: list[object] = []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("releases"), list):
        candidates = data["releases"]
    elif isinstance(payload.get("releases"), list):
        candidates = payload["releases"]
    for item in candidates:
        if isinstance(item, dict) and str(item.get("tag_name", "")) == tag:
            release_id = (
                item.get("version_id") or item.get("id") or item.get("version_gid")
            )
            if release_id is not None:
                return str(release_id)
    return None


def _safe_filename(name: str) -> str:
    return (
        name.replace("\\", "_")
        .replace("/", "_")
        .replace('"', "_")
        .replace("\r", "_")
        .replace("\n", "_")
    )


def _find_attachment_id(value: object) -> str | None:
    if isinstance(value, dict):
        if value.get("id") is not None:
            return str(value["id"])
        for key in ("data", "attachment"):
            found = _find_attachment_id(value.get(key))
            if found:
                return found
    return None


def _release_payload(
    tag: str, name: str, body: str, attachment_ids: list[str]
) -> dict[str, object]:
    return {
        "tag_name": tag,
        "name": name,
        "body": body,
        "target_commitish": "master",
        "draft": False,
        "prerelease": False,
        "attachment_ids": attachment_ids,
    }
