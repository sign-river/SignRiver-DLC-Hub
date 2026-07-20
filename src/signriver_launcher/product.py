"""User-facing product names for Windows release packages.

PyInstaller still builds an ASCII binary first; ``tools/build_release.py``
renames the folder and EXE for distribution.  Runtime code must never depend
on these strings — frozen apps resolve the install root via ``sys.executable``.
"""

from __future__ import annotations

# Stable ASCII name used only while compiling the onefile launcher.
BUILD_EXE_BASENAME = "SignRiver-DLC-Hub"

# Names shown to end users after unzipping the release package.
PRODUCT_DISPLAY_NAME = "星河DLC一键解锁"
RELEASE_DIR_NAME = "星河DLC一键解锁"
RELEASE_EXE_NAME = "星河DLC一键解锁.exe"

# Outer ZIP keeps an ASCII stem so mirrors/CDN tooling stay boring.
RELEASE_ZIP_STEM = "SignRiver-DLC-Hub"


__all__ = [
    "BUILD_EXE_BASENAME",
    "PRODUCT_DISPLAY_NAME",
    "RELEASE_DIR_NAME",
    "RELEASE_EXE_NAME",
    "RELEASE_ZIP_STEM",
]
