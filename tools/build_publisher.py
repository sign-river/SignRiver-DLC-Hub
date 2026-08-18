from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_EXE_NAME = "SignRiver-Publisher.exe"
# The publisher's declared runtime dependencies are CustomTkinter and Pillow. A larger
# artifact means PyInstaller has captured an unintended native dependency tree.
MAX_PUBLISHER_EXE_BYTES = 25 * 1024 * 1024
FORBIDDEN_RUNTIME_MARKERS = {
    b"numpy\\": "NumPy",
    b"mkl_": "Intel MKL",
    b"omptarget": "OpenMP target runtime",
    b"msmpi": "Microsoft MPI",
}


def _resolve_upx_dir(explicit: Path | None) -> Path | None:
    """Locate a directory containing upx.exe (explicit or on PATH)."""
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else ROOT / explicit
        if (candidate / "upx.exe").is_file():
            return candidate
        raise SystemExit(f"upx.exe not found in --upx-dir: {candidate}")
    found = shutil.which("upx")
    return Path(found).resolve().parent if found else None


def _verify_publisher_artifact(artifact: Path) -> str:
    """Reject accidental optional-runtime captures before replacing the release EXE."""
    size = artifact.stat().st_size
    if size > MAX_PUBLISHER_EXE_BYTES:
        raise SystemExit(
            f"publisher artifact is unexpectedly large: {size:,} bytes "
            f"(limit: {MAX_PUBLISHER_EXE_BYTES:,} bytes)"
        )
    raw_payload = artifact.read_bytes()
    captured = [
        label
        for marker, label in FORBIDDEN_RUNTIME_MARKERS.items()
        if marker in raw_payload.lower()
    ]
    if captured:
        raise SystemExit(
            "publisher artifact contains forbidden optional runtimes: "
            + ", ".join(captured)
        )
    return hashlib.sha256(raw_payload).hexdigest().upper()


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
    staging_dir = ROOT / "build" / "publisher-artifact"
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
            # Pillow can expose optional NumPy imports to PyInstaller's analysis.
            # The publisher does not use NumPy; excluding it avoids bundling Conda's
            # large MKL/OpenMP runtime set into the standalone executable.
            "--exclude-module",
            "numpy",
            "--distpath",
            str(staging_dir),
            "--workpath",
            str(ROOT / "build" / "publisher"),
            str(ROOT / "publisher.py"),
        ],
        cwd=ROOT,
        check=True,
        env=build_env,
    )
    staged = staging_dir / PUBLISHER_EXE_NAME
    if not staged.is_file():
        raise SystemExit(f"publisher artifact was not produced: {staged}")
    digest = _verify_publisher_artifact(staged)

    output_dir = ROOT / "dist" / "publisher"
    output_dir.mkdir(parents=True, exist_ok=True)
    built = output_dir / PUBLISHER_EXE_NAME
    shutil.copy2(staged, built)
    built_digest = _verify_publisher_artifact(built)
    if built_digest != digest:
        raise SystemExit("publisher artifact changed while copying it to dist")
    print(f"Publisher EXE size: {built.stat().st_size:,} bytes")
    print(f"Publisher EXE SHA-256: {built_digest}")
    shutil.copy2(ROOT / "config" / "publisher.example.json", output_dir / "publisher.example.json")
    private_config = ROOT / "config" / "publisher.local.json"
    if private_config.is_file():
        shutil.copy2(private_config, output_dir / "publisher.local.json")
    print(f"Publisher executable: {output_dir / 'SignRiver-Publisher.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
