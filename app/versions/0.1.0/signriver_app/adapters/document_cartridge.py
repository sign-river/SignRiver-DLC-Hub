"""Build runtime GameCartridge instances from declarative documents."""

from __future__ import annotations

from ..domain import CartridgeDocument, PatchProfile, PatchTemplate
from ..infrastructure.catalog import (
    inspect_directory_package,
    inspect_stellaris_package,
)
from .configured_cartridge import ConfiguredSteamCartridge


def build_cartridge_from_document(document: CartridgeDocument) -> ConfiguredSteamCartridge:
    """Instantiate the shared Steam cartridge engine from a remote document."""
    inspector = (
        inspect_stellaris_package
        if document.package_inspector == "stellaris_zip"
        else inspect_directory_package
    )
    return ConfiguredSteamCartridge(
        game_id=document.game_id,
        display_name=document.display_name,
        store_app_id=document.store_app_id,
        release_tag=document.release_tag,
        dlc_relative_dir=document.dlc_relative_dir,
        executable_relative_path=document.executable_relative_path,
        patch_profile=PatchProfile(
            unlocker_dll_name=document.unlocker_dll_name,
            original_backup_dll_name=document.original_backup_dll_name,
            appinfo_asset_name=document.appinfo_asset_name,
            install_relative_dir=document.patch_install_relative_dir,
            template=PatchTemplate(
                ini_target_name=document.ini_target_name,
                language=document.language,
                unlock_all=document.unlock_all,
                extra_protection=document.extra_protection,
                force_offline=document.force_offline,
            ),
        ),
        package_inspector=inspector,
        repository_owner=document.repository_owner,
        repository_name=document.repository_name,
        repositories=dict(document.repositories),
        install_directory_from_slug=document.install_directory_from_slug,
        freshness=document.freshness,
    )


__all__ = ["build_cartridge_from_document"]
