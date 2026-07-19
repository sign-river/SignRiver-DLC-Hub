"""The complete Stellaris cartridge shipped with the application."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from types import MappingProxyType

from ...application import StellarisCatalogService
from ...domain import PatchBundle, ReleaseAsset
from ...infrastructure.catalog import (
    GitLinkReleaseSource,
    GitLinkSourceConfig,
    inspect_stellaris_package,
)
from ...infrastructure.installs import StellarisInstallEngine
from .adapter import (
    STELLARIS_STEAM_APP_ID,
    StellarisSteamAdapter,
    discover_installed_dlc,
    remove_installed_dlc,
)
from .patch_profile import STELLARIS_PATCH_PROFILE


class StellarisGameCartridge:
    """Wire Stellaris-specific services without leaking them into the shell."""

    cartridge_id = "stellaris.steam"
    selection_name = "Stellaris · Steam"
    platform_name = "Steam"
    store_app_id = STELLARIS_STEAM_APP_ID
    release_tag = "stellaris"
    dlc_relative_dir = "dlc"
    executable_name = "stellaris.exe"
    patch_profile = STELLARIS_PATCH_PROFILE
    repository = GitLinkSourceConfig("signriver", "signriver-dlc-assets")

    def __init__(self) -> None:
        self._adapter = StellarisSteamAdapter(
            dlc_relative_dir=self.dlc_relative_dir,
            executable_name=self.executable_name,
        )

    @property
    def adapter(self) -> StellarisSteamAdapter:
        return self._adapter

    def patch_task_roles(self, bundle: PatchBundle):
        """Return task IDs tied to the exact Release attachment generation.

        GitLink replaces an attachment by creating a new attachment ID.  By
        including that ID in the task key, an unchanged bundle can reuse its
        persisted cache while a newly published patch can never inherit the
        READY state of an older file with the same filename.
        """
        return MappingProxyType({
            self._patch_task_id("unlocker", bundle.unlocker_dll): "unlocker_dll",
            self._patch_task_id("backup", bundle.original_backup_dll): "original_backup_dll",
            self._patch_task_id("appinfo", bundle.appinfo_json): "appinfo_json",
        })

    def _patch_task_id(self, role: str, asset: ReleaseAsset) -> str:
        revision = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(asset.asset_id)).strip("-.")
        if not revision:
            revision = hashlib.sha256(asset.download_url.encode("utf-8")).hexdigest()[:16]
        return f"{self.cartridge_id}-patch-{role}-{revision}"

    def create_catalog(self) -> StellarisCatalogService:
        return StellarisCatalogService(
            GitLinkReleaseSource(self.repository),
            release_tag=self.release_tag,
            patch_profile=self.patch_profile,
        )

    def create_install_engine(self, data_root: Path) -> StellarisInstallEngine:
        return StellarisInstallEngine(
            data_root,
            dlc_relative_dir=self.dlc_relative_dir,
            executable_name=self.executable_name,
        )

    def inspect_package(
        self,
        path: Path,
        *,
        asset_name: str | None = None,
        known_sha256: str | None = None,
    ):
        return inspect_stellaris_package(path, known_sha256=known_sha256)

    def discover_installed_dlc(self, game_root: Path, catalog_entries=()) -> dict[str, Path]:
        return discover_installed_dlc(game_root, self.dlc_relative_dir)

    def remove_installed_dlc(self, game_root: Path, dlc_id: str) -> Path:
        return remove_installed_dlc(game_root, dlc_id, self.dlc_relative_dir)


__all__ = ["StellarisGameCartridge"]
