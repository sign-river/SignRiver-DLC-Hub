"""User-facing product names for Windows release packages.

PyInstaller still builds an ASCII binary first; ``tools/build_release.py``
renames the folder and EXE for distribution.  Runtime code must never depend
on these strings — frozen apps resolve the install root via ``sys.executable``.
"""

from __future__ import annotations

# Stable ASCII name used only while compiling the onefile launcher.
BUILD_EXE_BASENAME = "SignRiver-DLC-Hub"

# Names shown to end users after unpacking the release package.
PRODUCT_DISPLAY_NAME = "唏嘘南溪DLC一键解锁工具"
RELEASE_DIR_NAME = "唏嘘南溪DLC一键解锁工具"
RELEASE_EXE_NAME = "唏嘘南溪DLC一键解锁工具.exe"
AUTHOR_EN = "SignRiver"
AUTHOR_CN = "唏嘘南溪"
WINDOW_TITLE = "唏嘘南溪DLC一键解锁"

# Outer archive / SFX stem uses the same Chinese product name.
RELEASE_ZIP_STEM = "唏嘘南溪DLC一键解锁工具"
RELEASE_SFX_NAME = "唏嘘南溪DLC一键解锁工具-自解压.exe"


__all__ = [
    "BUILD_EXE_BASENAME",
    "PRODUCT_DISPLAY_NAME",
    "RELEASE_DIR_NAME",
    "RELEASE_EXE_NAME",
    "RELEASE_ZIP_STEM",
    "RELEASE_SFX_NAME",
    "AUTHOR_EN",
    "AUTHOR_CN",
    "WINDOW_TITLE",
]
