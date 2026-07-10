from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from signriver_launcher.constants import LAUNCHER_VERSION  # noqa: E402

VERSION = LAUNCHER_VERSION


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Windows release packages must be built on Windows")

    dist = ROOT / "dist"
    work = ROOT / "build"
    release = dist / "SignRiver-DLC-Hub"
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
            "SignRiver-DLC-Hub",
            "--paths",
            str(ROOT / "src"),
            "--collect-all",
            "customtkinter",
            "--collect-all",
            "PIL",
            "--distpath",
            str(dist / "bin"),
            "--workpath",
            str(work / "pyinstaller"),
            str(ROOT / "launcher.py"),
        ],
        cwd=ROOT,
        check=True,
    )

    if release.exists():
        shutil.rmtree(release)
    release.mkdir(parents=True)
    shutil.copy2(dist / "bin" / "SignRiver-DLC-Hub.exe", release / "SignRiver-DLC-Hub.exe")
    shutil.copytree(
        ROOT / "app",
        release / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".staging"),
    )
    shutil.copytree(ROOT / "config", release / "config")
    (release / "cache").mkdir()
    (release / "data").mkdir()

    instructions = (
        "SignRiver DLC Hub\n\n"
        "运行 SignRiver-DLC-Hub.exe 启动程序。\n"
        "请完整解压后使用，不要只把 EXE 单独移出目录。\n"
    )
    (release / "使用说明.txt").write_text(instructions, encoding="utf-8")

    archive = dist / f"SignRiver-DLC-Hub-v{VERSION}-windows-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(release.rglob("*")):
            if path.is_file():
                package.write(path, Path(release.name) / path.relative_to(release))
    print(f"Release package: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
