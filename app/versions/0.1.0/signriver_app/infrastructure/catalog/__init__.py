"""Release sources and package inspection for DLC catalogs."""

from .gitlink import GitLinkReleaseSource, GitLinkSourceConfig, ReleaseSourceError
from .stellaris_package import PackageInspectionError, StellarisPackageMetadata, inspect_stellaris_package
from .directory_package import DirectoryPackageMetadata, inspect_directory_package

__all__ = [
    "GitLinkReleaseSource",
    "GitLinkSourceConfig",
    "PackageInspectionError",
    "ReleaseSourceError",
    "StellarisPackageMetadata",
    "inspect_stellaris_package",
    "DirectoryPackageMetadata",
    "inspect_directory_package",
]
