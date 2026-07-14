"""Stellaris game adapter."""

from .adapter import (
    STELLARIS_STEAM_APP_ID,
    StellarisSteamAdapter,
    discover_installed_dlc,
    remove_installed_dlc,
)
from .patch_profile import STELLARIS_PATCH_PROFILE

__all__ = [
    "STELLARIS_STEAM_APP_ID", "STELLARIS_PATCH_PROFILE", "StellarisSteamAdapter",
    "discover_installed_dlc", "remove_installed_dlc",
]
