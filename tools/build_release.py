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
from signriver_launcher.product import (  # noqa: E402
    BUILD_EXE_BASENAME,
    PRODUCT_DISPLAY_NAME,
    RELEASE_DIR_NAME,
    RELEASE_EXE_NAME,
    RELEASE_ZIP_STEM,
)

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
    release = dist / RELEASE_DIR_NAME
    hidden_import_args = [
        argument
        for module in application_hidden_imports()
        for argument in ("--hidden-import", module)
    ]
    # Build with an ASCII PyInstaller name first, then rename for distribution.
    # This avoids historic Unicode issues in the compiler while still shipping
    # a Chinese folder/EXE for domestic users.
    icon_path = ROOT / "config" / "app.ico"
    icon_args = ["--icon", str(icon_path)] if icon_path.is_file() else []
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
            BUILD_EXE_BASENAME,
            *icon_args,
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

    built_exe = dist / "bin" / f"{BUILD_EXE_BASENAME}.exe"
    if not built_exe.is_file():
        raise SystemExit(f"PyInstaller did not produce {built_exe}")

    # Drop both the previous Chinese release and any leftover English folder.
    for stale in (release, dist / "SignRiver-DLC-Hub"):
        if stale.exists():
            shutil.rmtree(stale)
    release.mkdir(parents=True)
    shutil.copy2(built_exe, release / RELEASE_EXE_NAME)
    shutil.copytree(
        ROOT / "app",
        release / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".staging"),
    )
    shutil.copytree(ROOT / "config", release / "config")
    (release / "cache").mkdir()
    (release / "data").mkdir()

    instructions = (
        f"{PRODUCT_DISPLAY_NAME}\n"
        f"（SignRiver DLC Hub）\n\n"
        f"双击「{RELEASE_EXE_NAME}」启动程序。\n"
        "请完整解压整个文件夹后再使用，不要只把 EXE 单独移出目录。\n"
        "文件夹可放到含中文的路径下；请保持本目录内的 app、config 完整。\n"
    )
    (release / "使用说明.txt").write_text(instructions, encoding="utf-8")

    archive = dist / f"{RELEASE_ZIP_STEM}-v{VERSION}-windows-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(release.rglob("*")):
            if path.is_file():
                package.write(path, Path(release.name) / path.relative_to(release))
    print(f"Release package: {archive}")
    print(f"Release folder:  {release}")
    print(f"Launcher EXE:    {release / RELEASE_EXE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
