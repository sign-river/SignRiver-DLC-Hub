from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
import hashlib
import json
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
APP_VERSION = json.loads(
    (ROOT / "app" / "state.json").read_text(encoding="utf-8")
)["active_version"]
APP_VERSION_ROOT = ROOT / "app" / "versions" / APP_VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_manifest(release: Path, version: str = VERSION) -> Path:
    """Write the ownership manifest consumed by the in-place full updater."""
    protected = {
        Path("app/state.json"),
        Path("config/update.json"),
        Path("config/publisher.local.json"),
    }
    files = []
    for path in sorted(release.rglob("*")):
        if not path.is_file() or path.name == "release-manifest.json":
            continue
        relative = path.relative_to(release)
        if relative in protected or relative.parts[0] in {"data", "cache"}:
            continue
        files.append({"path": relative.as_posix(), "size": path.stat().st_size, "sha256": _sha256(path)})
    manifest = release / "release-manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "version": version, "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_full_update_archive(
    release: Path, output: Path, version: str = VERSION
) -> Path:
    """Build the flat ZIP consumed by FullUpdateManager."""
    manifest = json.loads(
        (release / "release-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("version") != version:
        raise SystemExit("release-manifest.json version does not match update version")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as package:
        package.write(release / "release-manifest.json", "release-manifest.json")
        for item in manifest["files"]:
            relative = Path(item["path"])
            package.write(release / relative, relative.as_posix())
    return output


def application_hidden_imports() -> list[str]:
    package_root = APP_VERSION_ROOT / "signriver_app"
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


def resolve_upx_dir(explicit: Path | None) -> Path | None:
    """Locate the directory containing ``upx.exe`` for PyInstaller.

    Prefer the explicit ``--upx-dir``; otherwise search ``PATH``.  Return
    ``None`` when UPX is unavailable so callers can warn loudly instead of
    silently producing an uncompressed (much larger) onefile EXE.
    """
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
        raise SystemExit("Windows release packages must be built on Windows")
    upx_dir = resolve_upx_dir(args.upx_dir)
    if upx_dir is None:
        print(
            "WARNING: UPX not found; the launcher EXE will NOT be compressed "
            "and release packages will be much larger than expected"
        )
    else:
        print(f"UPX:            {upx_dir / 'upx.exe'}")
    if APP_VERSION != VERSION:
        raise SystemExit(
            f"active app version {APP_VERSION} must match launcher version {VERSION}"
        )
    if not APP_VERSION_ROOT.is_dir():
        restore = ROOT / "tools" / "restore_module_archives.py"
        result = subprocess.run(
            [sys.executable, str(restore), "--version", APP_VERSION], cwd=ROOT
        )
        if result.returncode or not APP_VERSION_ROOT.is_dir():
            raise SystemExit(
                f"active application module is missing: {APP_VERSION_ROOT}; "
                "restore it with tools/restore_module_archives.py"
            )

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
            BUILD_EXE_BASENAME,
            *icon_args,
            "--paths",
            str(ROOT / "src"),
            "--paths",
            str(APP_VERSION_ROOT),
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
        env=build_env,
    )

    built_exe = dist / "bin" / f"{BUILD_EXE_BASENAME}.exe"
    if not built_exe.is_file():
        raise SystemExit(f"PyInstaller did not produce {built_exe}")
    print(f"Launcher EXE size: {built_exe.stat().st_size:,} bytes")

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
    shutil.copytree(
        ROOT / "config",
        release / "config",
        ignore=shutil.ignore_patterns("publisher.local.json"),
    )
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
    write_release_manifest(release)

    archive = dist / f"{RELEASE_ZIP_STEM}-v{VERSION}-windows-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(release.rglob("*")):
            if path.is_file():
                package.write(path, Path(release.name) / path.relative_to(release))
    print(f"Release ZIP:     {archive}")
    full_update_archive = build_full_update_archive(
        release,
        dist / "updates" / f"SignRiver-DLC-Hub-full-v{VERSION}-windows-x64.zip",
    )
    print(f"Full update ZIP: {full_update_archive}")

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
