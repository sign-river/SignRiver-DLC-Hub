"""Normalized, platform-independent DLC catalog models."""

from __future__ import annotations

from dataclasses import dataclass


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
    parts: tuple[ReleaseAsset, ...] = ()

    @property
    def download_assets(self) -> tuple[ReleaseAsset, ...]:
        return self.parts or (self.asset,)
