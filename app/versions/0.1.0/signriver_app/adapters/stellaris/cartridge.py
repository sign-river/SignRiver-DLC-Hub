"""The complete Stellaris cartridge shipped with the application."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from ...application import StellarisCatalogService
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
    patch_profile = STELLARIS_PATCH_PROFILE
    repository = GitLinkSourceConfig("signriver", "signriver-dlc-assets")

    def __init__(self) -> None:
        self._adapter = StellarisSteamAdapter()
        self._patch_task_roles = MappingProxyType({
            f"{self.cartridge_id}-patch-unlocker": "unlocker_dll",
            f"{self.cartridge_id}-patch-backup": "original_backup_dll",
            f"{self.cartridge_id}-patch-appinfo": "appinfo_json",
        })

    @property
    def adapter(self) -> StellarisSteamAdapter:
        return self._adapter

    @property
    def patch_task_roles(self):
        return self._patch_task_roles

    def create_catalog(self) -> StellarisCatalogService:
        return StellarisCatalogService(
            GitLinkReleaseSource(self.repository),
            release_tag=self.release_tag,
            patch_profile=self.patch_profile,
        )

    def create_install_engine(self, data_root: Path) -> StellarisInstallEngine:
        return StellarisInstallEngine(data_root)

    def inspect_package(self, path: Path):
        return inspect_stellaris_package(path)

    def discover_installed_dlc(self, game_root: Path) -> dict[str, Path]:
        return discover_installed_dlc(game_root)

    def remove_installed_dlc(self, game_root: Path, dlc_id: str) -> Path:
        return remove_installed_dlc(game_root, dlc_id)


__all__ = ["StellarisGameCartridge"]
