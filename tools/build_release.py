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
    RELEASE_SFX_NAME,
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


def _find_7z() -> Path | None:
    candidates = [
        shutil.which("7z"),
        shutil.which("7za"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.is_file():
            return path
    return None


def _build_sfx(release: Path, archive_7z: Path, sfx_path: Path) -> bool:
    """Build a GUI 7-Zip SFX so users extract before running the app."""
    seven_zip = _find_7z()
    if seven_zip is None:
        return False
    sfx_module = seven_zip.parent / "7z.sfx"
    if not sfx_module.is_file():
        return False
    archive_7z.unlink(missing_ok=True)
    subprocess.run(
        [
            str(seven_zip),
            "a",
            "-t7z",
            "-mx=9",
            str(archive_7z),
            f".\\{release.name}\\*",
        ],
        cwd=release.parent,
        check=True,
    )
    config = release.parent / "sfx_config.txt"
    config.write_text(
        "\n".join(
            (
                ";!@Install@!UTF-8!",
                f'Title="{PRODUCT_DISPLAY_NAME}"',
                (
                    'BeginPrompt="将解压出完整程序文件夹。'
                    "请勿只运行其中的 EXE；请解压后再启动。"
                    '"'
                ),
                f'ExtractTitle="正在解压 {PRODUCT_DISPLAY_NAME}"',
                "GUIFlags=\"8+32+64\"",
                "OverwriteMode=\"2\"",
                ";!@InstallEnd@!",
                "",
            )
        ),
        encoding="utf-8",
    )
    sfx_path.unlink(missing_ok=True)
    # copy /b 7z.sfx + config + archive.7z sfx.exe
    with sfx_path.open("wb") as output:
        output.write(sfx_module.read_bytes())
        output.write(config.read_bytes())
        output.write(archive_7z.read_bytes())
    config.unlink(missing_ok=True)
    archive_7z.unlink(missing_ok=True)
    return True


def _build_python_sfx(archive_zip: Path, sfx_path: Path) -> bool:
    """Fallback SFX built with PyInstaller when 7-Zip is not installed."""
    dist = ROOT / "dist"
    work = ROOT / "build"
    icon_path = ROOT / "config" / "app.ico"
    icon_args = ["--icon", str(icon_path)] if icon_path.is_file() else []
    staging = work / "sfx-stub"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    payload = staging / "payload.zip"
    shutil.copy2(archive_zip, payload)
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
            "SignRiver-SFX",
            *icon_args,
            "--paths",
            str(ROOT / "src"),
            "--add-data",
            f"{payload};.",
            "--distpath",
            str(dist / "bin"),
            "--workpath",
            str(work / "pyinstaller-sfx"),
            "--specpath",
            str(work / "pyinstaller-sfx"),
            str(ROOT / "tools" / "sfx_stub.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    built = dist / "bin" / "SignRiver-SFX.exe"
    if not built.is_file():
        return False
    sfx_path.unlink(missing_ok=True)
    shutil.copy2(built, sfx_path)
    return True


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
    for stale in (
        release,
        dist / "SignRiver-DLC-Hub",
        dist / "星河DLC一键解锁",
    ):
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
        f"推荐：双击「{RELEASE_SFX_NAME}」自解压包，解压出完整文件夹后再使用。\n"
        f"若使用 ZIP：请先完整解压，再双击文件夹内的「{RELEASE_EXE_NAME}」。\n"
        "不要只在压缩包预览窗口里直接运行 EXE。\n"
        "文件夹可放到含中文的路径下；请保持本目录内的 app、config 完整。\n"
    )
    (release / "使用说明.txt").write_text(instructions, encoding="utf-8")

    archive = dist / f"{RELEASE_ZIP_STEM}-v{VERSION}-windows-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(release.rglob("*")):
            if path.is_file():
                package.write(path, Path(release.name) / path.relative_to(release))
    print(f"Release ZIP:     {archive}")

    sfx_path = dist / f"{RELEASE_ZIP_STEM}-v{VERSION}-windows-x64-自解压.exe"
    # Prefer a stable short name for casual sharing as well.
    sfx_alias = dist / RELEASE_SFX_NAME
    archive_7z = dist / f"{RELEASE_ZIP_STEM}-v{VERSION}.7z"
    built_sfx = False
    if _build_sfx(release, archive_7z, sfx_path):
        built_sfx = True
    elif _build_python_sfx(archive, sfx_path):
        built_sfx = True
    if built_sfx:
        shutil.copy2(sfx_path, sfx_alias)
        print(f"Release SFX:     {sfx_path}")
        print(f"Release SFX alias: {sfx_alias}")
    else:
        print("Release SFX:     failed to build self-extracting package")

    print(f"Release folder:  {release}")
    print(f"Launcher EXE:    {release / RELEASE_EXE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
