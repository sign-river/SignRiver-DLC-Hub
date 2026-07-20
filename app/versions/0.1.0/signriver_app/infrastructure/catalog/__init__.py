"""Release sources and package inspection for DLC catalogs."""

from .gitlink import GitLinkReleaseSource, GitLinkSourceConfig, ReleaseSourceError
from .github import GitHubReleaseSource, GitHubSourceConfig
from .sources import (
    DEFAULT_ASSET_REPOS,
    DOWNLOAD_SOURCES,
    DownloadSource,
    create_hub_release_source,
    create_release_source,
    default_repository_for,
    normalize_download_source,
    provider_display_name,
    repository_home_url,
    resolve_repository,
    speed_test_url,
)
from .stellaris_package import (
    PackageInspectionError,
    StellarisPackageMetadata,
    inspect_stellaris_package,
)
from .directory_package import DirectoryPackageMetadata, inspect_directory_package

__all__ = [
    "DEFAULT_ASSET_REPOS",
    "DOWNLOAD_SOURCES",
    "DownloadSource",
    "DirectoryPackageMetadata",
    "GitHubReleaseSource",
    "GitHubSourceConfig",
    "GitLinkReleaseSource",
    "GitLinkSourceConfig",
    "PackageInspectionError",
    "ReleaseSourceError",
    "StellarisPackageMetadata",
    "create_hub_release_source",
    "create_release_source",
    "default_repository_for",
    "inspect_directory_package",
    "inspect_stellaris_package",
    "normalize_download_source",
    "provider_display_name",
    "repository_home_url",
    "resolve_repository",
    "speed_test_url",
]
