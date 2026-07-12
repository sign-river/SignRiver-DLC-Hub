"""Release sources and package inspection for DLC catalogs."""

from .gitlink import GitLinkReleaseSource, GitLinkSourceConfig, ReleaseSourceError
from .stellaris_package import PackageInspectionError, StellarisPackageMetadata, inspect_stellaris_package
from .manifest import CatalogManifestError, ParsedCatalogManifest, parse_catalog_manifest

__all__ = [
    "GitLinkReleaseSource",
    "GitLinkSourceConfig",
    "PackageInspectionError",
    "ReleaseSourceError",
    "StellarisPackageMetadata",
    "inspect_stellaris_package",
    "CatalogManifestError",
    "ParsedCatalogManifest",
    "parse_catalog_manifest",
]
