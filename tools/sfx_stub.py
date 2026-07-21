"""Self-extracting bootstrap used when 7-Zip SFX is unavailable.

PyInstaller packs the Chinese release ZIP as ``payload.zip``.  Double-clicking
this EXE extracts the full program folder next to itself and opens that folder
so users never run the launcher from inside a compressed preview.
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from tkinter import messagebox


def _payload_path() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "payload.zip"
    return Path(__file__).resolve().parent / "payload.zip"


def _target_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def main() -> int:
    from signriver_launcher.product import PRODUCT_DISPLAY_NAME, RELEASE_DIR_NAME

    payload = _payload_path()
    if not payload.is_file():
        messagebox.showerror(
            PRODUCT_DISPLAY_NAME,
            "自解压包缺少 payload.zip，请重新下载完整安装包。",
        )
        return 1
    destination = _target_dir() / RELEASE_DIR_NAME
    try:
        if destination.exists():
            # Replace a previous extract so users always get a complete tree.
            import shutil

            shutil.rmtree(destination)
        with zipfile.ZipFile(payload) as archive:
            archive.extractall(_target_dir())
    except Exception as error:
        messagebox.showerror(
            PRODUCT_DISPLAY_NAME,
            f"解压失败：{error}\n请换一个可写目录后再试。",
        )
        return 1

    messagebox.showinfo(
        PRODUCT_DISPLAY_NAME,
        (
            f"已解压到：\n{destination}\n\n"
            f"请打开该文件夹，双击「{RELEASE_DIR_NAME}.exe」启动。"
            "请勿只复制单个 EXE。"
        ),
    )
    try:
        os.startfile(destination)  # type: ignore[attr-defined]
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
