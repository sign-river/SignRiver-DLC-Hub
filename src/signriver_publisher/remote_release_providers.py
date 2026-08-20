"""Adapters from the existing GitHub/GitLink clients to release pipeline providers."""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from .gitlink import UploadControl, UploadPaused
from .github import GitHubReleaseClient, GitHubUploadPaused
from .release_interfaces import RemoteVerification
from .release_models import ReleaseArtifact, ReleasePlan
from .release_orchestrator import ReleasePauseRequested
from .remote import RemoteResourceManager
from .updates import UPDATE_MANIFEST_ASSET, UPDATE_RELEASE_TAG, release_asset_url


def _raise_if_pause_requested(pause_requested: Callable[[], bool] | None) -> None:
    """Stop an interruptible remote read before it starts more work."""
    if pause_requested is not None and pause_requested():
        raise ReleasePauseRequested("发布已在远端校验期间安全暂停")


def _hash_stream(
    stream: BinaryIO,
    *,
    pause_requested: Callable[[], bool] | None = None,
) -> tuple[int, str, bytes]:
    digest = hashlib.sha256()
    size = 0
    captured = bytearray()
    while True:
        _raise_if_pause_requested(pause_requested)
        chunk = stream.read(256 * 1024)
        _raise_if_pause_requested(pause_requested)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
        if len(captured) <= 4 * 1024 * 1024:
            captured.extend(chunk)
    return size, digest.hexdigest(), bytes(captured)


def _read_url(
    url: str,
    *,
    opener: Callable[..., object],
    headers: dict[str, str] | None = None,
    pause_requested: Callable[[], bool] | None = None,
) -> tuple[int, str, bytes]:
    _raise_if_pause_requested(pause_requested)
    request = urllib.request.Request(url, headers=headers or {})
    try:
        # A verification read is cancellable work too.  Do not leave a pause
        # request behind the previous two-minute connection timeout.
        with opener(request, timeout=20) as response:
            return _hash_stream(response, pause_requested=pause_requested)
    except socket.timeout as error:
        if pause_requested is not None and pause_requested():
            raise ReleasePauseRequested("发布已在远端校验期间安全暂停") from error
        raise


def _manifest_evidence(name: str, payload: bytes) -> dict[str, object]:
    if name != "update-manifest.json":
        return {}
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"manifest_error": "invalid_json"}
    return (
        {"manifest": value}
        if isinstance(value, dict)
        else {"manifest_error": "invalid_root"}
    )


class GitHubReleaseProvider:
    source_id = "github"

    def __init__(
        self,
        client: GitHubReleaseClient,
        *,
        release_tag: str = UPDATE_RELEASE_TAG,
        opener: Callable[..., object] | None = None,
        pause_requested: Callable[[], bool] | None = None,
        upload_progress: Callable[[str, ReleaseArtifact, int, int], None] | None = None,
        ensure_repository: bool = False,
        repository_description: str = "SignRiver DLC / 补丁发布资源",
    ) -> None:
        self.client = client
        self.release_tag = release_tag
        self.opener = opener or urllib.request.urlopen
        self.pause_requested = pause_requested
        self.upload_progress = upload_progress
        self.ensure_repository = ensure_repository
        self.repository_description = repository_description
        self._repository_ready = False

    def _ensure_repository(self) -> None:
        if not self.ensure_repository or self._repository_ready:
            return
        ensure = getattr(self.client, "ensure_repository", None)
        if callable(ensure):
            ensure(self.repository_description)
        self._repository_ready = True

    def set_upload_progress_reporter(
        self, reporter: Callable[[str, ReleaseArtifact, int, int], None] | None
    ) -> None:
        self.upload_progress = reporter

    def _report_upload_progress(
        self, artifact: ReleaseArtifact, sent: int, total: int
    ) -> None:
        if self.upload_progress:
            self.upload_progress(self.source_id, artifact, sent, total)

    def read_baseline(self) -> dict[str, object]:
        """Return a credential-free, read-only release snapshot for review."""
        self._ensure_repository()
        release = self.client.get_release_by_tag(self.release_tag)
        if release is None:
            return {"release_exists": False, "release_tag": self.release_tag, "assets": []}
        assets = [
            {"name": str(item.get("name") or ""), "size": int(item.get("size") or 0), "remote_id": str(item.get("id") or "")}
            for item in release.assets
        ]
        manifest = self.inspect(UPDATE_MANIFEST_ASSET)
        return {
            "release_exists": True,
            "release_tag": self.release_tag,
            "assets": assets,
            "update_manifest": manifest.evidence,
        }

    def inspect(self, remote_key: str) -> RemoteVerification:
        release = self.client.get_release_by_tag(self.release_tag)
        if release is None:
            return RemoteVerification(False)
        asset = next(
            (item for item in release.assets if str(item.get("name")) == remote_key),
            None,
        )
        if asset is None:
            return RemoteVerification(False)
        url = str(asset.get("browser_download_url") or "")
        if not url:
            return RemoteVerification(
                True,
                size=int(asset.get("size") or 0),
                remote_id=str(asset.get("id") or "") or None,
            )
        size, digest, payload = _read_url(
            url,
            opener=self.opener,
            headers={
                "Authorization": f"Bearer {self.client.token}",
                "User-Agent": "SignRiver-Publisher/0.1",
            },
            pause_requested=self.pause_requested,
        )
        return RemoteVerification(
            True,
            size=size,
            sha256=digest,
            remote_id=str(asset.get("id") or "") or None,
            evidence=_manifest_evidence(remote_key, payload),
        )

    def upload(self, artifact: ReleaseArtifact, local_path: Path) -> RemoteVerification:
        self._ensure_repository()
        release = self.client.ensure_release(self.release_tag)
        try:
            self._report_upload_progress(artifact, 0, max(0, int(artifact.size or local_path.stat().st_size)))
            self.client.upload_asset(
                release,
                local_path,
                replace_existing=True,
                should_pause=self.pause_requested,
                progress=lambda sent, total: self._report_upload_progress(
                    artifact, sent, total
                ),
            )
        except GitHubUploadPaused as exc:
            raise ReleasePauseRequested(str(exc)) from exc
        return self.inspect(artifact.filename)

    def delete(self, remote_key: str) -> RemoteVerification:
        current = self.inspect(remote_key)
        if not current.exists:
            return current
        if not current.remote_id:
            raise RuntimeError(f"无法定位 GitHub 附件：{remote_key}")
        self.client.delete_asset(int(current.remote_id))
        result = self.inspect(remote_key)
        if result.exists:
            raise RuntimeError(f"GitHub 附件删除后仍存在：{remote_key}")
        return result

    def publish_index(self, plan: ReleasePlan, local_path: Path) -> RemoteVerification:
        artifact = ReleaseArtifact(role="program_manifest", filename=local_path.name)
        return self.upload(artifact, local_path)


class GitLinkReleaseProvider:
    source_id = "gitlink"

    def __init__(
        self,
        manager: RemoteResourceManager,
        *,
        release_tag: str = UPDATE_RELEASE_TAG,
        release_name: str = "SignRiver 程序更新",
        opener: Callable[..., object] | None = None,
        pause_requested: Callable[[], bool] | None = None,
        upload_progress: Callable[[str, ReleaseArtifact, int, int], None] | None = None,
        repository_ensurer: Callable[[], object] | None = None,
    ) -> None:
        self.manager = manager
        self.release_tag = release_tag
        self.release_name = release_name
        self.opener = opener or urllib.request.urlopen
        self.pause_requested = pause_requested
        self.upload_progress = upload_progress
        self.repository_ensurer = repository_ensurer
        self._repository_ready = False

    def _ensure_repository(self) -> None:
        if self._repository_ready:
            return
        if self.repository_ensurer is not None:
            self.repository_ensurer()
        self._repository_ready = True

    def set_upload_progress_reporter(
        self, reporter: Callable[[str, ReleaseArtifact, int, int], None] | None
    ) -> None:
        self.upload_progress = reporter

    def _report_upload_progress(
        self, artifact: ReleaseArtifact, sent: int, total: int
    ) -> None:
        if self.upload_progress:
            self.upload_progress(self.source_id, artifact, sent, total)

    def read_baseline(self) -> dict[str, object]:
        """Return a credential-free, read-only release snapshot for review."""
        self._ensure_repository()
        release = self.manager.get_release(self.release_tag)
        if release is None:
            return {"release_exists": False, "release_tag": self.release_tag, "assets": []}
        manifest = self.inspect(UPDATE_MANIFEST_ASSET)
        return {
            "release_exists": True,
            "release_tag": self.release_tag,
            "assets": [
                {
                    "name": item.name,
                    "display_size": item.display_size,
                    "remote_id": item.asset_id,
                }
                for item in release.assets
            ],
            "update_manifest": manifest.evidence,
        }

    def inspect(self, remote_key: str) -> RemoteVerification:
        release = self.manager.get_release(self.release_tag)
        if release is None:
            return RemoteVerification(False)
        asset = next((item for item in release.assets if item.name == remote_key), None)
        if asset is None:
            return RemoteVerification(False)
        repository = self.manager.repository
        url = release_asset_url(
            "gitlink", repository.owner, repository.name, remote_key
        )
        size, digest, payload = _read_url(
            url,
            opener=self.opener,
            pause_requested=self.pause_requested,
        )
        return RemoteVerification(
            True,
            size=size,
            sha256=digest,
            remote_id=asset.asset_id,
            evidence=_manifest_evidence(remote_key, payload),
        )

    def upload(self, artifact: ReleaseArtifact, local_path: Path) -> RemoteVerification:
        self._ensure_repository()
        control = UploadControl()

        def progress(sent: int, total: int) -> None:
            self._report_upload_progress(artifact, sent, total)
            if self.pause_requested and self.pause_requested():
                control.request_pause()

        try:
            self._report_upload_progress(artifact, 0, max(0, int(artifact.size or local_path.stat().st_size)))
            self.manager.upload_file_to_release(
                self.release_tag,
                self.release_name,
                local_path,
                progress=progress,
                control=control if self.pause_requested else None,
            )
        except UploadPaused as exc:
            raise ReleasePauseRequested(str(exc)) from exc
        return self.inspect(artifact.filename)

    def delete(self, remote_key: str) -> RemoteVerification:
        current = self.inspect(remote_key)
        if not current.exists:
            return current
        if not current.remote_id:
            raise RuntimeError(f"无法定位 GitLink 附件：{remote_key}")
        self.manager.client.delete_attachment(str(current.remote_id))
        result = self.inspect(remote_key)
        if result.exists:
            raise RuntimeError(f"GitLink 附件删除后仍存在：{remote_key}")
        return result

    def publish_index(self, plan: ReleasePlan, local_path: Path) -> RemoteVerification:
        artifact = ReleaseArtifact(role="program_manifest", filename=local_path.name)
        return self.upload(artifact, local_path)
