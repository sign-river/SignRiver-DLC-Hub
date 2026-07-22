from ..configured_cartridge import ConfiguredSteamCartridge
from ...infrastructure.catalog import inspect_directory_package
from .patch_profile import CIVILIZATION_6_PATCH_PROFILE


class Civilization6GameCartridge(ConfiguredSteamCartridge):
    def __init__(self) -> None:
        super().__init__(
            game_id="civilization_6",
            display_name="文明6 (Civilization VI)",
            store_app_id="289070",
            release_tag="civilization_6",
            dlc_relative_dir="DLC",
            executable_relative_path="Base/Binaries/Win64Steam/CivilizationVI.exe",
            patch_profile=CIVILIZATION_6_PATCH_PROFILE,
            package_inspector=inspect_directory_package,
            install_directory_from_slug=True,
        )


__all__ = ["Civilization6GameCartridge"]
