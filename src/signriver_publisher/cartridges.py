"""Built-in publisher cartridges.

Disk cartridges under ``publisher-workspace/games`` remain the source of
truth. Built-ins are only used to seed an empty publisher workspace.
"""

from __future__ import annotations

from .models import PublisherCartridge


def create_builtin_cartridges() -> tuple[PublisherCartridge, ...]:
    return (
        PublisherCartridge(
            game_id="stellaris",
            display_name="Stellaris",
            release_tag="stellaris",
            appinfo_name="stellaris_appinfo.json",
            steam_app_id="281990",
            dlc_relative_dir="dlc",
            patch_relative_dir=".",
            executable_relative_path="stellaris.exe",
            package_inspector="stellaris_zip",
        ),
        PublisherCartridge(
            game_id="civilization_6",
            display_name="Civilization VI",
            release_tag="civilization_6",
            appinfo_name="civilization_6_appinfo.json",
            steam_app_id="289070",
            dlc_relative_dir="DLC",
            patch_relative_dir="Base/Binaries/Win64Steam",
            dlc_archive_root_mode="strip_id_prefix",
            dlc_import_naming_mode="auto_prefix",
            dlc_import_layout_mode="children_if_root",
            executable_relative_path="Base/Binaries/Win64Steam/CivilizationVI.exe",
            package_inspector="directory",
            install_directory_from_slug=True,
        ),
        PublisherCartridge(
            game_id="hearts_of_iron_4",
            display_name="Hearts of Iron IV",
            release_tag="hearts_of_iron_4",
            appinfo_name="hearts_of_iron_4_appinfo.json",
            steam_app_id="394360",
            dlc_relative_dir="dlc",
            patch_relative_dir=".",
            dlc_archive_root_mode="source",
            executable_relative_path="hoi4.exe",
            package_inspector="directory",
        ),
    )


__all__ = ["create_builtin_cartridges"]
