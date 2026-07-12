"""Reusable platform discovery helpers shared by game adapters."""

from .steam import (
    SteamAppInstallation,
    SteamInstallationLocator,
    SteamScanIssue,
    VdfError,
    discover_windows_steam_roots,
    parse_vdf,
)

__all__ = [
    "SteamAppInstallation",
    "SteamInstallationLocator",
    "SteamScanIssue",
    "VdfError",
    "discover_windows_steam_roots",
    "parse_vdf",
]

