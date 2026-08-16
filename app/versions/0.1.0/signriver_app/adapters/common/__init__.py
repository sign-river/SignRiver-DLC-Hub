"""Reusable platform discovery helpers shared by game adapters."""

from .steam import (
    SteamAppInstallation,
    SteamInstallationLocator,
    SteamScanIssue,
    VdfError,
    discover_steam_roots,
    discover_windows_steam_roots,
    parse_vdf,
)
from .configured_steam import ConfiguredSteamAdapter
from .dlc_directories import discover_numbered_dlc, remove_numbered_dlc

__all__ = [
    "SteamAppInstallation",
    "SteamInstallationLocator",
    "SteamScanIssue",
    "VdfError",
    "discover_steam_roots",
    "discover_windows_steam_roots",
    "parse_vdf",
    "ConfiguredSteamAdapter",
    "discover_numbered_dlc",
    "remove_numbered_dlc",
]
