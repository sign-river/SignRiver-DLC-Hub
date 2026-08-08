from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _resolve_upx_dir(explicit: Path | None) -> Path | None:
    """Locate a directory containing upx.exe (explicit or on PATH)."""
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else ROOT / explicit
        if (candidate / "upx.exe").is_file():
            return candidate
        raise SystemExit(f"upx.exe not found in --upx-dir: {candidate}")
    found = shutil.which("upx")
    return Path(found).resolve().parent if found else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upx-dir",
        type=Path,
        default=None,
        help="directory containing upx.exe (default: PATH lookup)",
    )
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("The publisher executable must be built on Windows")
    upx_dir = _resolve_upx_dir(args.upx_dir)
    if upx_dir is None:
        print(
            "WARNING: UPX not found; the publisher EXE will NOT be compressed "
            "and will be significantly larger"
        )
    else:
        print(f"UPX:            {upx_dir / 'upx.exe'}")
    build_env = None
    if upx_dir is not None:
        build_env = dict(os.environ)
        build_env["PATH"] = str(upx_dir) + os.pathsep + build_env.get("PATH", "")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "SignRiver-Publisher",
            "--paths",
            str(ROOT / "src"),
            "--collect-all",
            "customtkinter",
            "--distpath",
            str(ROOT / "dist" / "publisher"),
            "--workpath",
            str(ROOT / "build" / "publisher"),
            str(ROOT / "publisher.py"),
        ],
        cwd=ROOT,
        check=True,
        env=build_env,
    )
    output_dir = ROOT / "dist" / "publisher"
    built = output_dir / "SignRiver-Publisher.exe"
    if built.is_file():
        print(f"Publisher EXE size: {built.stat().st_size:,} bytes")
    shutil.copy2(ROOT / "config" / "publisher.example.json", output_dir / "publisher.example.json")
    private_config = ROOT / "config" / "publisher.local.json"
    if private_config.is_file():
        shutil.copy2(private_config, output_dir / "publisher.local.json")
    print(f"Publisher executable: {output_dir / 'SignRiver-Publisher.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
