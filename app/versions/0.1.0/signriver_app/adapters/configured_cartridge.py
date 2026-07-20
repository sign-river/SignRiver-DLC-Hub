"""Reusable implementation for declarative Steam game cartridges."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from types import MappingProxyType

from ..application.dlc_catalog import ReleaseCatalogService
from ..domain import PatchBundle, PatchProfile, ReleaseAsset, resolve_game_directory
from ..infrastructure.catalog import (
    GitLinkReleaseSource, GitLinkSourceConfig,
)
from ..infrastructure.installs import DirectoryInstallEngine
from .common import (
    ConfiguredSteamAdapter, discover_numbered_dlc, remove_numbered_dlc,
)


class ConfiguredSteamCartridge:
    def __init__(
        self,
        *,
        game_id: str,
        display_name: str,
        store_app_id: str,
        release_tag: str,
        dlc_relative_dir: str,
        executable_relative_path: str,
        patch_profile: PatchProfile,
        package_inspector,
        repository: GitLinkSourceConfig | None = None,
        install_directory_from_slug: bool = False,
    ) -> None:
        self.cartridge_id = f"{game_id}.steam"
        self.selection_name = f"{display_name} · Steam"
        self.platform_name = "Steam"
        self.store_app_id = store_app_id
        self.release_tag = release_tag
        self.dlc_relative_dir = dlc_relative_dir
        self.executable_name = executable_relative_path
        self.patch_profile = patch_profile
        self.repository = repository or GitLinkSourceConfig(
            "signriver", "signriver-dlc-assets"
        )
        self.package_inspector = package_inspector
        self.install_directory_from_slug = install_directory_from_slug
        self._installed_paths: dict[str, Path] = {}
        self._adapter = ConfiguredSteamAdapter(
            game_id=game_id,
            display_name=display_name,
            steam_app_id=store_app_id,
            executable_relative_path=executable_relative_path,
            required_relative_dirs=(dlc_relative_dir,),
        )

    @property
    def adapter(self) -> ConfiguredSteamAdapter:
        return self._adapter

    def patch_task_roles(self, bundle: PatchBundle):
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

    def create_catalog(self) -> ReleaseCatalogService:
        return ReleaseCatalogService(
            GitLinkReleaseSource(self.repository),
            release_tag=self.release_tag,
            patch_profile=self.patch_profile,
        )

    def create_install_engine(self, data_root: Path) -> DirectoryInstallEngine:
        return DirectoryInstallEngine(
            data_root,
            dlc_relative_dir=self.dlc_relative_dir,
            executable_name=self.executable_name,
            game_id=self.adapter.descriptor.game_id,
            package_inspector=self.package_inspector,
        )

    def inspect_package(
        self,
        path: Path,
        *,
        asset_name: str | None = None,
        known_sha256: str | None = None,
    ):
        return self.package_inspector(
            path, asset_name=asset_name, known_sha256=known_sha256
        )

    def discover_installed_dlc(self, game_root: Path, catalog_entries=()) -> dict[str, Path]:
        installed = discover_numbered_dlc(game_root, self.dlc_relative_dir)
        if self.install_directory_from_slug:
            try:
                dlc_root = resolve_game_directory(
                    game_root, self.dlc_relative_dir,
                    field_name="DLC install directory",
                )
                children = {
                    path.name.casefold(): path
                    for path in dlc_root.iterdir() if path.is_dir()
                }
            except (OSError, ValueError):
                children = {}
            for entry in catalog_entries:
                path = children.get(entry.slug.casefold())
                if path is not None:
                    installed[entry.dlc_id.casefold()] = path
        self._installed_paths = dict(installed)
        return installed

    def remove_installed_dlc(self, game_root: Path, dlc_id: str) -> Path:
        target = self._installed_paths.get(dlc_id.casefold())
        if target is None or re.match(r"^dlc\d{3,}_", target.name, re.I):
            return remove_numbered_dlc(game_root, dlc_id, self.dlc_relative_dir)
        dlc_root = resolve_game_directory(
            game_root, self.dlc_relative_dir, field_name="DLC install directory"
        ).resolve(strict=True)
        resolved = target.resolve(strict=True)
        if resolved.parent != dlc_root:
            raise ValueError("refusing to remove an unsafe DLC directory")
        shutil.rmtree(resolved)
        self._installed_paths.pop(dlc_id.casefold(), None)
        return resolved


__all__ = ["ConfiguredSteamCartridge"]
