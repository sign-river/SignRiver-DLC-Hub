"""Build the combined Steam directory analyzer and DLL collector ZIP."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist"
OUTPUT_DIR = DIST_ROOT / "steam-directory-probe"
BUILD_DIR = ROOT / "build" / "steam-directory-probe"
ASCII_NAME = "SteamGameDirectoryProbe"
EXE_NAME = "Steam游戏目录扫描器.exe"
ZIP_NAME = "Steam游戏目录扫描器-Windows-x64.zip"


def _resolve_upx_dir(explicit: Path | None) -> Path | None:
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else ROOT / explicit
        if (candidate / "upx.exe").is_file():
            return candidate.resolve()
        raise SystemExit(f"upx.exe not found in --upx-dir: {candidate}")
    found = shutil.which("upx")
    return Path(found).resolve().parent if found else None


def _clear_output_dir() -> None:
    resolved = OUTPUT_DIR.resolve(strict=False)
    if resolved.parent != DIST_ROOT.resolve(strict=False):
        raise SystemExit(f"refusing to clear unexpected output directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _write_zip(zip_path: Path) -> None:
    temporary = zip_path.with_suffix(".zip.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(OUTPUT_DIR.iterdir(), key=lambda item: item.name.casefold()):
                archive.write(path, arcname=f"Steam游戏目录扫描器/{path.name}")
        temporary.replace(zip_path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upx-dir", type=Path, help="directory containing upx.exe")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("The Windows probe executable must be built on Windows")

    upx_dir = _resolve_upx_dir(args.upx_dir)
    _clear_output_dir()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        ASCII_NAME,
        "--distpath",
        str(OUTPUT_DIR),
        "--workpath",
        str(BUILD_DIR),
    ]
    if upx_dir is not None:
        command.extend(("--upx-dir", str(upx_dir)))
        print(f"UPX: {upx_dir / 'upx.exe'}")
    else:
        print("WARNING: UPX not found; the executable will be larger")
    command.append(str(ROOT / "tools" / "collect_steam_api64.py"))
    subprocess.run(command, cwd=ROOT, check=True)

    ascii_exe = OUTPUT_DIR / f"{ASCII_NAME}.exe"
    final_exe = OUTPUT_DIR / EXE_NAME
    if not ascii_exe.is_file():
        raise SystemExit(f"PyInstaller did not produce {ascii_exe}")
    ascii_exe.replace(final_exe)
    shutil.copy2(
        ROOT / "tools" / "steam_directory_probe_README.txt",
        OUTPUT_DIR / "使用说明.txt",
    )

    zip_path = DIST_ROOT / ZIP_NAME
    _write_zip(zip_path)
    print(f"Executable: {final_exe} ({final_exe.stat().st_size:,} bytes)")
    print(f"Distribution ZIP: {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
