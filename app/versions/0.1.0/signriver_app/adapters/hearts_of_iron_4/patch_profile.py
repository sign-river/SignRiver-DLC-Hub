from ...domain import PatchProfile, PatchTemplate


HEARTS_OF_IRON_4_PATCH_PROFILE = PatchProfile(
    unlocker_dll_name="steam_api64.dll",
    original_backup_dll_name="steam_api64_o.dll",
    appinfo_asset_name="hearts_of_iron_4_appinfo.json",
    template=PatchTemplate(ini_target_name="cream_api.ini", language="schinese"),
    install_relative_dir=".",
)


__all__ = ["HEARTS_OF_IRON_4_PATCH_PROFILE"]
