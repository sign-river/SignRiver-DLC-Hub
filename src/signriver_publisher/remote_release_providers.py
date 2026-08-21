"""Adapters from the existing GitHub/GitLink clients to release pipeline providers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .gitlink import UploadControl, UploadPaused
from .github import GitHubReleaseClient, GitHubUploadPaused
from .release_interfaces import RemoteVerification
from .release_models import ReleaseArtifact, ReleasePlan
from .release_orchestrator import ReleasePauseRequested
from .remote import RemoteResourceManager
from .updates import UPDATE_RELEASE_TAG


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
        release = self.client.get_release_by_tag(self.release_tag)
        if release is None:
            return {"release_exists": False, "release_tag": self.release_tag, "assets": []}
        assets = [
            {"name": str(item.get("name") or ""), "size": int(item.get("size") or 0), "remote_id": str(item.get("id") or "")}
            for item in release.assets
        ]
        return {
            "release_exists": True,
            "release_tag": self.release_tag,
            "assets": assets,
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
        return RemoteVerification(
            True,
            size=int(asset.get("size") or 0),
            remote_id=str(asset.get("id") or "") or None,
        )

    def upload(self, artifact: ReleaseArtifact, local_path: Path) -> RemoteVerification:
        self._ensure_repository()
        release = self.client.ensure_release(self.release_tag)
        try:
            self._report_upload_progress(artifact, 0, max(0, int(artifact.size or local_path.stat().st_size)))
            uploaded = self.client.upload_asset(
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
        remote_id = str(uploaded.get("id") or "") if isinstance(uploaded, dict) else ""
        remote_size = (
            int(uploaded.get("size") or artifact.size or local_path.stat().st_size)
            if isinstance(uploaded, dict)
            else int(artifact.size or local_path.stat().st_size)
        )
        return RemoteVerification(True, size=remote_size, remote_id=remote_id or None)

    def delete(self, remote_key: str) -> RemoteVerification:
        release = self.client.get_release_by_tag(self.release_tag)
        if release is None:
            return RemoteVerification(False)
        asset = next(
            (item for item in release.assets if str(item.get("name")) == remote_key),
            None,
        )
        if asset is None:
            return RemoteVerification(False)
        remote_id = str(asset.get("id") or "")
        if not remote_id:
            raise RuntimeError(f"无法定位 GitHub 附件：{remote_key}")
        self.client.delete_asset(int(remote_id))
        refreshed = self.client.get_release_by_tag(self.release_tag)
        still_exists = refreshed is not None and any(
            str(item.get("name")) == remote_key for item in refreshed.assets
        )
        if still_exists:
            raise RuntimeError(f"GitHub 附件删除后仍存在：{remote_key}")
        return RemoteVerification(False)

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
        release = self.manager.get_release(self.release_tag)
        if release is None:
            return {"release_exists": False, "release_tag": self.release_tag, "assets": []}
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
        }

    def inspect(self, remote_key: str) -> RemoteVerification:
        release = self.manager.get_release(self.release_tag)
        if release is None:
            return RemoteVerification(False)
        asset = next((item for item in release.assets if item.name == remote_key), None)
        if asset is None:
            return RemoteVerification(False)
        return RemoteVerification(
            True,
            remote_id=asset.asset_id,
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
            uploaded = self.manager.upload_file_to_release(
                self.release_tag,
                self.release_name,
                local_path,
                progress=progress,
                control=control if self.pause_requested else None,
            )
        except UploadPaused as exc:
            raise ReleasePauseRequested(str(exc)) from exc
        remote_id = str(getattr(getattr(uploaded, "asset", None), "asset_id", ""))
        if not remote_id:
            release = self.manager.get_release(self.release_tag)
            asset = next(
                (item for item in release.assets if item.name == artifact.filename),
                None,
            ) if release is not None else None
            remote_id = str(getattr(asset, "asset_id", ""))
        return RemoteVerification(
            True,
            size=int(artifact.size or local_path.stat().st_size),
            remote_id=remote_id or None,
        )

    def delete(self, remote_key: str) -> RemoteVerification:
        release = self.manager.get_release(self.release_tag)
        if release is None:
            return RemoteVerification(False)
        asset = next((item for item in release.assets if item.name == remote_key), None)
        if asset is None:
            return RemoteVerification(False)
        if not asset.asset_id:
            raise RuntimeError(f"无法定位 GitLink 附件：{remote_key}")
        self.manager.client.delete_attachment(str(asset.asset_id))
        refreshed = self.manager.get_release(self.release_tag)
        still_exists = refreshed is not None and any(
            item.name == remote_key for item in refreshed.assets
        )
        if still_exists:
            raise RuntimeError(f"GitLink 附件删除后仍存在：{remote_key}")
        return RemoteVerification(False)

    def publish_index(self, plan: ReleasePlan, local_path: Path) -> RemoteVerification:
        artifact = ReleaseArtifact(role="program_manifest", filename=local_path.name)
        return self.upload(artifact, local_path)
