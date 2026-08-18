"""Adapters from the existing GitHub/GitLink clients to release pipeline providers."""

from __future__ import annotations

import hashlib
import json
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


def _hash_stream(stream: BinaryIO) -> tuple[int, str, bytes]:
    digest = hashlib.sha256()
    size = 0
    captured = bytearray()
    while chunk := stream.read(1024 * 1024):
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
) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers=headers or {})
    with opener(request, timeout=120) as response:
        return _hash_stream(response)


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
    ) -> None:
        self.client = client
        self.release_tag = release_tag
        self.opener = opener or urllib.request.urlopen
        self.pause_requested = pause_requested
        self.upload_progress = upload_progress

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
        )
        return RemoteVerification(
            True,
            size=size,
            sha256=digest,
            remote_id=str(asset.get("id") or "") or None,
            evidence=_manifest_evidence(remote_key, payload),
        )

    def upload(self, artifact: ReleaseArtifact, local_path: Path) -> RemoteVerification:
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
    ) -> None:
        self.manager = manager
        self.release_tag = release_tag
        self.release_name = release_name
        self.opener = opener or urllib.request.urlopen
        self.pause_requested = pause_requested
        self.upload_progress = upload_progress

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
        size, digest, payload = _read_url(url, opener=self.opener)
        return RemoteVerification(
            True,
            size=size,
            sha256=digest,
            remote_id=asset.asset_id,
            evidence=_manifest_evidence(remote_key, payload),
        )

    def upload(self, artifact: ReleaseArtifact, local_path: Path) -> RemoteVerification:
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

    def publish_index(self, plan: ReleasePlan, local_path: Path) -> RemoteVerification:
        artifact = ReleaseArtifact(role="program_manifest", filename=local_path.name)
        return self.upload(artifact, local_path)
