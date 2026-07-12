"""Normalized, platform-independent DLC catalog models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    asset_id: str
    name: str
    download_url: str
    display_size: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedRelease:
    release_id: str
    tag: str
    name: str
    description: str
    assets: tuple[ReleaseAsset, ...]


@dataclass(frozen=True, slots=True)
class DlcCatalogEntry:
    dlc_id: str
    slug: str
    display_name: str
    asset: ReleaseAsset
    release_tag: str
    category: str | None = None
    steam_id: str | None = None


class CatalogTrust(StrEnum):
    VERIFIED = "verified"
    MANIFEST_MISSING = "manifest_missing"
    UNSIGNED = "unsigned"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class TrustedCatalogAsset:
    dlc_id: str
    asset_name: str
    size: int
    sha256: str
    min_game_version: str | None
    max_game_version: str | None
    distribution_authorized: bool


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    entries: tuple[DlcCatalogEntry, ...]
    trust: CatalogTrust
    trust_reason: str
    trusted_assets: tuple[TrustedCatalogAsset, ...] = ()

    @property
    def installation_allowed(self) -> bool:
        return self.trust is CatalogTrust.VERIFIED
