from __future__ import annotations

import hashlib
import io
from pathlib import Path

from signriver_publisher.github import GitHubRelease
from signriver_publisher.release_models import ReleaseArtifact, ReleasePlan, ReleaseKind
from signriver_publisher.remote import RemoteAsset, RemoteRelease
from signriver_publisher.remote_release_providers import (
    GitHubReleaseProvider,
    GitLinkReleaseProvider,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class _GitHubClient:
    token = "not-a-real-token"

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.uploaded = 0

    def get_release_by_tag(self, tag):
        return GitHubRelease(
            1,
            tag,
            "https://uploads.invalid/assets{?name}",
            (
                {
                    "id": 9,
                    "name": "package.zip",
                    "size": len(self.payload),
                    "browser_download_url": "https://downloads.invalid/package.zip",
                },
            ),
        )

    def ensure_release(self, tag):
        return self.get_release_by_tag(tag)

    def upload_asset(self, release, path, **kwargs):
        self.uploaded += 1
        self.payload = Path(path).read_bytes()
        progress = kwargs.get("progress")
        if callable(progress):
            progress(len(self.payload), len(self.payload))
        return {"id": 9}


def test_github_provider_wraps_existing_client_and_verifies_download(
    tmp_path: Path,
) -> None:
    payload = b"verified-package"
    package = tmp_path / "package.zip"
    package.write_bytes(payload)
    client = _GitHubClient(payload)
    provider = GitHubReleaseProvider(
        client,
        opener=lambda *_args, **_kwargs: _Response(client.payload),
    )
    artifact = ReleaseArtifact(
        role="windows_full",
        filename=package.name,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )

    result = provider.upload(artifact, package)

    assert client.uploaded == 1
    assert result.exists
    assert result.size == artifact.size
    assert result.sha256 == artifact.sha256


class _Repository:
    owner = "owner"
    name = "repository"


class _GitLinkManager:
    repository = _Repository()

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.uploaded = 0

    def get_release(self, tag):
        return RemoteRelease(
            "1",
            tag,
            "updates",
            "",
            (RemoteAsset("attachment", "package.zip", "1 B", ""),),
        )

    def upload_file_to_release(self, tag, release_name, path, **kwargs):
        self.uploaded += 1
        self.payload = Path(path).read_bytes()
        progress = kwargs.get("progress")
        if callable(progress):
            progress(len(self.payload), len(self.payload))


def test_gitlink_provider_wraps_resource_manager_and_verifies_download(
    tmp_path: Path,
) -> None:
    payload = b"verified-package"
    package = tmp_path / "package.zip"
    package.write_bytes(payload)
    manager = _GitLinkManager(payload)
    provider = GitLinkReleaseProvider(
        manager,
        opener=lambda *_args, **_kwargs: _Response(manager.payload),
    )
    artifact = ReleaseArtifact(
        role="windows_full",
        filename=package.name,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )

    result = provider.upload(artifact, package)

    assert manager.uploaded == 1
    assert result.exists
    assert result.size == artifact.size
    assert result.sha256 == artifact.sha256


def test_manifest_publish_exposes_remote_json_evidence(tmp_path: Path) -> None:
    payload = b'{"schema_version":1,"channel":"stable","releases":[]}'
    manifest = tmp_path / "update-manifest.json"
    manifest.write_bytes(payload)
    client = _GitHubClient(payload)
    client.get_release_by_tag = lambda tag: GitHubRelease(
        1,
        tag,
        "https://uploads.invalid/assets{?name}",
        (
            {
                "id": 10,
                "name": manifest.name,
                "size": len(client.payload),
                "browser_download_url": "https://downloads.invalid/update-manifest.json",
            },
        ),
    )
    provider = GitHubReleaseProvider(
        client,
        opener=lambda *_args, **_kwargs: _Response(client.payload),
    )

    result = provider.publish_index(
        ReleasePlan.create(ReleaseKind.PROGRAM, {"version": "0.2.0"}), manifest
    )

    assert result.evidence["manifest"]["channel"] == "stable"


def test_read_baseline_returns_credential_free_release_metadata() -> None:
    payload = b"verified-package"
    github = GitHubReleaseProvider(
        _GitHubClient(payload),
        opener=lambda *_args, **_kwargs: _Response(payload),
    )
    gitlink = GitLinkReleaseProvider(
        _GitLinkManager(payload),
        opener=lambda *_args, **_kwargs: _Response(payload),
    )

    github_snapshot = github.read_baseline()
    gitlink_snapshot = gitlink.read_baseline()

    assert github_snapshot["release_exists"] is True
    assert github_snapshot["assets"] == [
        {"name": "package.zip", "size": len(payload), "remote_id": "9"}
    ]
    assert gitlink_snapshot["release_exists"] is True
    assert gitlink_snapshot["assets"] == [
        {"name": "package.zip", "display_size": "1 B", "remote_id": "attachment"}
    ]


def test_release_providers_forward_file_upload_progress(tmp_path: Path) -> None:
    payload = b"progress-package"
    package = tmp_path / "package.zip"
    package.write_bytes(payload)
    artifact = ReleaseArtifact(
        role="windows_full",
        filename=package.name,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    reports: list[tuple[str, str, int, int]] = []

    def report(source: str, item: ReleaseArtifact, sent: int, total: int) -> None:
        reports.append((source, item.filename, sent, total))

    github_client = _GitHubClient(payload)
    github = GitHubReleaseProvider(
        github_client,
        opener=lambda *_args, **_kwargs: _Response(github_client.payload),
        upload_progress=report,
    )
    gitlink_manager = _GitLinkManager(payload)
    gitlink = GitLinkReleaseProvider(
        gitlink_manager,
        opener=lambda *_args, **_kwargs: _Response(gitlink_manager.payload),
        upload_progress=report,
    )

    github.upload(artifact, package)
    gitlink.upload(artifact, package)

    assert ("github", package.name, 0, len(payload)) in reports
    assert ("github", package.name, len(payload), len(payload)) in reports
    assert ("gitlink", package.name, 0, len(payload)) in reports
    assert ("gitlink", package.name, len(payload), len(payload)) in reports
