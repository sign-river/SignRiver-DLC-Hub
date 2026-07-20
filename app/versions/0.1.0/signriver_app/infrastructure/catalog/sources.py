"""Shared release-source provider identifiers and factory helpers."""

from __future__ import annotations

from typing import Literal

from .github import GitHubReleaseSource, GitHubSourceConfig
from .gitlink import GitLinkReleaseSource, GitLinkSourceConfig, ReleaseSourceError

DownloadSource = Literal["gitlink", "github"]
DOWNLOAD_SOURCES: tuple[DownloadSource, ...] = ("gitlink", "github")

# Mirrored asset repositories.  Owner names differ between platforms, but the
# repository name and Release/tag/asset layout stay identical.
DEFAULT_ASSET_REPOS: dict[str, tuple[str, str]] = {
    "gitlink": ("signriver", "signriver-dlc-assets"),
    "github": ("sign-river", "signriver-dlc-assets"),
}


def normalize_download_source(value: object) -> DownloadSource:
    text = str(value or "gitlink").strip().lower()
    if text not in DOWNLOAD_SOURCES:
        raise ValueError("download_source must be gitlink or github")
    return text  # type: ignore[return-value]


def default_repository_for(provider: DownloadSource) -> tuple[str, str]:
    return DEFAULT_ASSET_REPOS[provider]


def resolve_repository(
    provider: DownloadSource,
    *,
    owner: str | None = None,
    repository: str | None = None,
    repositories: dict[str, dict[str, str]] | None = None,
) -> tuple[str, str]:
    """Pick owner/repo for the active provider with safe fallbacks."""
    if repositories:
        specific = repositories.get(provider)
        if isinstance(specific, dict):
            specific_owner = str(specific.get("owner") or "").strip()
            specific_repo = str(specific.get("repository") or "").strip()
            if specific_owner and specific_repo:
                return specific_owner, specific_repo
    if owner and repository:
        # When the cartridge only stores one coordinate pair, keep the repo
        # name and substitute the provider's default owner if needed.
        default_owner, default_repo = default_repository_for(provider)
        if provider == "github" and owner == DEFAULT_ASSET_REPOS["gitlink"][0]:
            return default_owner, repository or default_repo
        return owner, repository
    return default_repository_for(provider)


def create_release_source(
    provider: DownloadSource,
    owner: str,
    repository: str,
    *,
    fetch=None,
    timeout: float = 15,
):
    """Build the concrete ReleaseSource used by catalogs and hub loading."""
    provider = normalize_download_source(provider)
    if provider == "github":
        return GitHubReleaseSource(
            GitHubSourceConfig(owner, repository),
            timeout=timeout,
            fetch=fetch,
        )
    return GitLinkReleaseSource(
        GitLinkSourceConfig(owner, repository),
        timeout=timeout,
        fetch=fetch,
    )


def create_hub_release_source(
    provider: DownloadSource,
    *,
    fetch=None,
    timeout: float = 20,
):
    owner, repository = default_repository_for(normalize_download_source(provider))
    return create_release_source(
        provider, owner, repository, fetch=fetch, timeout=timeout,
    )


def speed_test_url(provider: DownloadSource) -> str:
    provider = normalize_download_source(provider)
    owner, repository = default_repository_for(provider)
    if provider == "github":
        return (
            f"https://github.com/{owner}/{repository}/releases/download/test/test.bin"
        )
    return (
        f"https://gitlink.org.cn/{owner}/{repository}/releases/download/test/test.bin"
    )


def repository_home_url(provider: DownloadSource) -> str:
    provider = normalize_download_source(provider)
    owner, repository = default_repository_for(provider)
    if provider == "github":
        return f"https://github.com/{owner}/{repository}"
    return f"https://www.gitlink.org.cn/{owner}/{repository}"


def provider_display_name(provider: DownloadSource) -> str:
    return "GitHub" if normalize_download_source(provider) == "github" else "GitLink"


__all__ = [
    "DOWNLOAD_SOURCES",
    "DEFAULT_ASSET_REPOS",
    "DownloadSource",
    "ReleaseSourceError",
    "create_hub_release_source",
    "create_release_source",
    "default_repository_for",
    "normalize_download_source",
    "provider_display_name",
    "repository_home_url",
    "resolve_repository",
    "speed_test_url",
]
