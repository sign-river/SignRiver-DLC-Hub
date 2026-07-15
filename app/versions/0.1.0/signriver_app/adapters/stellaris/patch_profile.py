"""Stellaris Steam CreamAPI patch profile.

Every game that ships an unlock patch declares its own ``PatchProfile`` so
that the shared patch engine can drive apply / audit / remove without any
Stellaris-specific hard-coding.  For Stellaris we ship the CreamAPI DLL as
``steam_api64.dll``, keep the original as ``steam_api64_o.dll`` and render
``cream_api.ini`` on the client from ``stellaris_appinfo.json``.
"""

from __future__ import annotations

from ...domain.patches import PatchProfile, PatchTemplate


STELLARIS_PATCH_PROFILE = PatchProfile(
    unlocker_dll_name="steam_api64.dll",
    original_backup_dll_name="steam_api64_o.dll",
    appinfo_asset_name="stellaris_appinfo.json",
    install_relative_dir=".",
    template=PatchTemplate(
        ini_target_name="cream_api.ini",
        language="schinese",
        unlock_all=True,
        extra_protection=False,
        force_offline=False,
    ),
)


__all__ = ["STELLARIS_PATCH_PROFILE"]
