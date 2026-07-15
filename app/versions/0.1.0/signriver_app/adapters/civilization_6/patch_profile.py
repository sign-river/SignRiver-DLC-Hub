from ...domain import PatchProfile, PatchTemplate


CIVILIZATION_6_PATCH_PROFILE = PatchProfile(
    unlocker_dll_name="steam_api64.dll",
    original_backup_dll_name="steam_api64_o.dll",
    appinfo_asset_name="civilization_6_appinfo.json",
    template=PatchTemplate(ini_target_name="cream_api.ini", language="schinese"),
    install_relative_dir="Base/Binaries/Win64Steam",
)


__all__ = ["CIVILIZATION_6_PATCH_PROFILE"]
