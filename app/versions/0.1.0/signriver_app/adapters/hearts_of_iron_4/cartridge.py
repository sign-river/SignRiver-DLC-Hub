from ..configured_cartridge import ConfiguredSteamCartridge
from ...infrastructure.catalog import inspect_directory_package
from .patch_profile import HEARTS_OF_IRON_4_PATCH_PROFILE


class HeartsOfIron4GameCartridge(ConfiguredSteamCartridge):
    def __init__(self) -> None:
        super().__init__(
            game_id="hearts_of_iron_4",
            display_name="Hearts of Iron IV",
            store_app_id="394360",
            release_tag="hearts_of_iron_4",
            dlc_relative_dir="dlc",
            executable_relative_path="hoi4.exe",
            patch_profile=HEARTS_OF_IRON_4_PATCH_PROFILE,
            package_inspector=inspect_directory_package,
        )


__all__ = ["HeartsOfIron4GameCartridge"]
