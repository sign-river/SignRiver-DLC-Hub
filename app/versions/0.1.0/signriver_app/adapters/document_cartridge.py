"""Build runtime GameCartridge instances from declarative documents."""

from __future__ import annotations

from ..domain import (
    CartridgeDocument,
    PatchConfigFormat,
    PatchPlatform,
    PatchProfile,
    PatchTemplate,
    host_patch_platform,
)
from ..infrastructure.catalog import (
    inspect_directory_package,
    inspect_grouped_directory_package,
    inspect_stellaris_package,
)
from .configured_cartridge import ConfiguredSteamCartridge


def build_cartridge_from_document(
    document: CartridgeDocument,
    platform: str | PatchPlatform | None = None,
) -> ConfiguredSteamCartridge:
    """Instantiate the shared Steam cartridge engine from a remote document.

    ``platform`` selects the patch layout (windows / steamos / macos); it
    defaults to the host platform the app is running on.
    """
    selected = PatchPlatform(str(platform or host_patch_platform()))
    fields = document.patch_fields_for(selected.value)
    executable_relative_path = str(
        fields.get("executable_relative_path") or document.executable_relative_path
    )
    dlc_relative_dir = str(
        fields.get("dlc_relative_dir") or document.dlc_relative_dir
    )
    inspectors = {
        "stellaris_zip": inspect_stellaris_package,
        "directory": inspect_directory_package,
        "grouped_directory": inspect_grouped_directory_package,
    }
    inspector = inspectors[document.package_inspector]
    return ConfiguredSteamCartridge(
        game_id=document.game_id,
        display_name=document.display_name,
        store_app_id=document.store_app_id,
        release_tag=document.release_tag,
        dlc_relative_dir=dlc_relative_dir,
        executable_relative_path=executable_relative_path,
        platform=selected.value,
        patch_profile=PatchProfile(
            unlocker_dll_name=str(fields["unlocker_dll_name"]),
            original_backup_dll_name=str(fields["original_backup_dll_name"]),
            appinfo_asset_name=str(fields["appinfo_asset_name"]),
            install_relative_dir=str(fields["install_relative_dir"]),
            template=PatchTemplate(
                ini_target_name=str(fields["ini_target_name"]),
                language=str(fields["language"]),
                unlock_all=bool(fields["unlock_all"]),
                extra_protection=bool(fields["extra_protection"]),
                force_offline=bool(fields["force_offline"]),
                config_format=PatchConfigFormat(str(fields["config_format"])),
            ),
            platform=selected,
        ),
        package_inspector=inspector,
        repository_owner=document.repository_owner,
        repository_name=document.repository_name,
        repositories=dict(document.repositories),
        install_directory_from_slug=document.install_directory_from_slug,
        dlc_group_search_roots=document.dlc_group_search_roots,
        freshness=document.freshness,
    )


__all__ = ["build_cartridge_from_document"]
