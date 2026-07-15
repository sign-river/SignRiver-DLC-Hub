"""Application service that turns release assets into a DLC library.

The service exposes two views of the same underlying release:

* ``refresh()`` returns only the DLC catalog entries and keeps the historical
  signature relied on by tests and older callers.
* ``refresh_snapshot()`` additionally resolves the patch bundle so the UI can
  render "一键解锁" and "一键修复" without issuing a second network request.

Assets whose names match neither convention are ignored; the patch bundle is
only returned when every required patch asset was found on the release, so
callers can display a targeted error instead of silently mixing an outdated
patch with fresh DLC packages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain import (
    DlcCatalogEntry,
    NormalizedRelease,
    PatchBundle,
    PatchProfile,
    ReleaseAsset,
)

_STELLARIS_ASSET = re.compile(r"^(dlc\d{3,})_([a-z0-9_]+)\.zip$", re.I)


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """DLC catalog and (optionally) resolved patch bundle for one game.

    ``patch_bundle`` is ``None`` when the release does not currently ship the
    complete set of patch assets described by ``patch_profile``.  Callers can
    still surface the DLC list but should block the "一键解锁" affordance.
    """

    entries: tuple[DlcCatalogEntry, ...]
    patch_bundle: PatchBundle | None
    release_tag: str
    patch_profile: PatchProfile | None = None
    missing_patch_assets: tuple[str, ...] = ()


class ReleaseCatalogService:
    """Resolve DLC and patch assets published under one game cartridge release."""

    def __init__(
        self,
        release_source,
        *,
        release_tag: str = "ste",
        patch_profile: PatchProfile | None = None,
    ) -> None:
        self.release_source = release_source
        self.release_tag = release_tag
        self.patch_profile = patch_profile

    def refresh(self) -> tuple[DlcCatalogEntry, ...]:
        """Return only the DLC catalog for backwards-compatible callers."""
        return self.refresh_snapshot().entries

    def refresh_snapshot(self) -> CatalogSnapshot:
        release = self.release_source.get_release_by_tag(self.release_tag)
        entries = self._extract_entries(release)
        patch_bundle, missing = self._extract_patch_bundle(release)
        return CatalogSnapshot(
            entries=entries,
            patch_bundle=patch_bundle,
            release_tag=release.tag,
            patch_profile=self.patch_profile,
            missing_patch_assets=missing,
        )

    def _extract_entries(
        self, release: NormalizedRelease
    ) -> tuple[DlcCatalogEntry, ...]:
        entries: list[DlcCatalogEntry] = []
        for asset in release.assets:
            match = _STELLARIS_ASSET.fullmatch(asset.name)
            if not match:
                continue
            slug = match.group(2).lower()
            entries.append(DlcCatalogEntry(
                dlc_id=match.group(1).lower(), slug=slug,
                display_name=slug.replace("_", " ").title(), asset=asset,
                release_tag=release.tag,
            ))
        return tuple(sorted(entries, key=lambda item: item.dlc_id))

    def _extract_patch_bundle(
        self, release: NormalizedRelease
    ) -> tuple[PatchBundle | None, tuple[str, ...]]:
        profile = self.patch_profile
        if profile is None:
            return None, ()
        wanted = {
            profile.unlocker_dll_name.casefold(): "unlocker_dll",
            profile.original_backup_dll_name.casefold(): "original_backup_dll",
            profile.appinfo_asset_name.casefold(): "appinfo_json",
        }
        found: dict[str, ReleaseAsset] = {}
        for asset in release.assets:
            role = wanted.get(asset.name.casefold())
            if role is None or role in found:
                continue
            found[role] = asset
        missing = tuple(
            sorted(
                name for name, role in wanted.items() if role not in found
            )
        )
        if missing:
            return None, missing
        bundle = PatchBundle(
            profile=profile,
            unlocker_dll=found["unlocker_dll"],
            original_backup_dll=found["original_backup_dll"],
            appinfo_json=found["appinfo_json"],
            release_tag=release.tag,
        )
        return bundle, ()


StellarisCatalogService = ReleaseCatalogService


__all__ = ["CatalogSnapshot", "ReleaseCatalogService", "StellarisCatalogService"]
