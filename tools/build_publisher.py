from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        raise SystemExit("The publisher executable must be built on Windows")
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
    )
    output_dir = ROOT / "dist" / "publisher"
    shutil.copy2(ROOT / "config" / "publisher.example.json", output_dir / "publisher.example.json")
    private_config = ROOT / "config" / "publisher.local.json"
    if private_config.is_file():
        shutil.copy2(private_config, output_dir / "publisher.local.json")
    print(f"Publisher executable: {output_dir / 'SignRiver-Publisher.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
