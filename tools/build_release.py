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


def application_hidden_imports() -> list[str]:
    package_root = ROOT / "app" / "versions" / "0.1.0" / "signriver_app"
    modules = {"webbrowser", "signriver_app"}
    for path in package_root.rglob("*.py"):
        relative = path.relative_to(package_root)
        if relative.name == "__init__.py":
            parts = relative.parent.parts
        else:
            parts = relative.with_suffix("").parts
        modules.add(".".join(("signriver_app", *parts)) if parts else "signriver_app")
    return sorted(modules)


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Windows release packages must be built on Windows")

    dist = ROOT / "dist"
    work = ROOT / "build"
    release = dist / "SignRiver-DLC-Hub"
    hidden_import_args = [
        argument
        for module in application_hidden_imports()
        for argument in ("--hidden-import", module)
    ]
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
            "--paths",
            str(ROOT / "app" / "versions" / "0.1.0"),
            *hidden_import_args,
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
