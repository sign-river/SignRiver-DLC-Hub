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
from signriver_launcher.versioning import Version  # noqa: E402

VERSION = LAUNCHER_VERSION
PYINSTALLER_EXCLUDED_MODULES = ("numpy",)


def pyinstaller_exclude_args() -> list[str]:
    """Keep optional image-library dependencies out of frozen launchers.

    Pillow can discover NumPy through optional plugins when the build environment
    happens to provide it. The application does not use NumPy, and collecting it
    also pulls large BLAS/MKL runtimes into otherwise identical release builds.
    """
    return [
        argument
        for module in PYINSTALLER_EXCLUDED_MODULES
        for argument in ("--exclude-module", module)
    ]
APP_VERSION = json.loads(
    (ROOT / "app" / "state.json").read_text(encoding="utf-8")
)["active_version"]
APP_VERSION_ROOT = ROOT / "app" / "versions" / APP_VERSION


def _maintained_module_versions() -> tuple[str, ...]:
    """``config/module-archives.json`` 里仍在维护的模块版本。"""
    try:
        document = json.loads(
            (ROOT / "config" / "module-archives.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return ()
    modules = document.get("modules")
    if not isinstance(modules, list):
        return ()
    return tuple(
        str(item["version"])
        for item in modules
        if isinstance(item, dict) and item.get("version")
    )


def packaged_module_versions(active_version: str | None = None) -> tuple[str, ...]:
    """``app/versions`` 下真正随包发布的模块目录。

    ``app/versions`` 会一直累积历史模块，但它们对安装没有任何用处：运行哪个
    版本只由 ``app/state.json`` 的 ``active_version`` 决定。因此包里只带
    **当前版本 + 最近一个仍在维护的旧版本**，后者是激活模块加载失败时启动器
    自动回退的目标（见 ``signriver_launcher.main._find_usable_module``）。
    没有回退目标的新装用户一遇到坏模块就只能重新下载整个包。
    """
    active = active_version or APP_VERSION
    versions_root = ROOT / "app" / "versions"
    if not versions_root.is_dir():
        return (active,)
    available = {
        item.name
        for item in versions_root.iterdir()
        if item.is_dir() and (item / "module.json").is_file()
    }
    if active not in available:
        return tuple(sorted(available))
    selected = [active]
    active_key = _parse_version(active)
    fallbacks: list[tuple[Version, str]] = []
    for candidate in _maintained_module_versions():
        key = _parse_version(candidate)
        if (
            key is None
            or active_key is None
            or candidate == active
            or candidate not in available
            or key >= active_key
        ):
            continue
        fallbacks.append((key, candidate))
    if fallbacks:
        selected.append(max(fallbacks)[1])
    return tuple(selected)


def _parse_version(value: str) -> Version | None:
    try:
        return Version.parse(value)
    except ValueError:
        return None


def _app_tree_ignore(directory, names):
    """``shutil.copytree`` 的 ignore：只保留 :func:`packaged_module_versions`。"""
    ignored = {
        name
        for name in names
        if name in {"__pycache__", ".staging"} or name.endswith((".pyc", ".pyo"))
    }
    directory = Path(directory)
    if directory.name == "versions" and directory.parent.name == "app":
        keep = set(packaged_module_versions())
        ignored.update(
            name
            for name in names
            if name not in keep and (directory / name).is_dir()
        )
    return ignored


def copy_app_tree(destination: Path) -> None:
    """把 ``app/`` 复制到发布目录，并按需裁剪模块版本目录。"""
    shutil.copytree(ROOT / "app", destination, ignore=_app_tree_ignore)


def _latest_source_mtime(version: str) -> float:
    """模块源码目录里最新的修改时间，用于判断模块归档是否已经过期。"""
    module_root = ROOT / "app" / "versions" / version
    latest = 0.0
    if not module_root.is_dir():
        return latest
    for path in module_root.rglob("*"):
        if path.is_file():
            latest = max(latest, path.stat().st_mtime)
    return latest


def sync_publisher_inbox(
    *, platform: str = "windows", version: str | None = None
) -> list[Path]:
    """把刚构建的产物同步到发布器收件目录。

    发布器「发布包与归档」页默认从 ``publisher-workspace/output`` 收件：三端包
    在 ``updates``，模块归档在 ``modules``。以前每次构建后都要手工搬文件，容易
    漏搬或把旧包发出去，所以直接在这里同步。没有发布器工作区（例如 CI 或
    SteamOS/macOS 来宾机）时静默跳过。模块归档比源码旧时跳过并提示，避免把
    过期模块带进发布。
    """
    version = version or VERSION
    output_root = ROOT / "publisher-workspace" / "output"
    if not (output_root / "updates").is_dir() and not (output_root / "modules").is_dir():
        return []
    copied: list[Path] = []
    package = (
        ROOT / "dist" / "updates"
        / f"SignRiver-DLC-Hub-full-v{version}-{platform}-x64.zip"
    )
    if package.is_file():
        target = output_root / "updates"
        target.mkdir(parents=True, exist_ok=True)
        destination = target / package.name
        shutil.copy2(package, destination)
        copied.append(destination)
    module_archive = ROOT / "dist" / "modules" / f"SignRiver-DLC-Hub-module-v{version}.zip"
    if module_archive.is_file():
        if module_archive.stat().st_mtime < _latest_source_mtime(version):
            print(
                "跳过模块归档同步："
                f"{module_archive.name} 比源码旧，请先运行 tools/build_module.py"
            )
        else:
            target = output_root / "modules"
            target.mkdir(parents=True, exist_ok=True)
            destination = target / module_archive.name
            shutil.copy2(module_archive, destination)
            copied.append(destination)
    return copied


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_manifest(
    release: Path,
    version: str = VERSION,
    *,
    target_platform: str = "windows",
    target_arch: str = "x64",
    manifest_path: Path | None = None,
    path_prefix: str = "",
    bundle_path: str | None = None,
) -> Path:
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
        stored_relative = (
            f"{path_prefix.rstrip('/')}/{relative.as_posix()}"
            if path_prefix else relative.as_posix()
        )
        item = {"path": stored_relative, "size": path.stat().st_size, "sha256": _sha256(path)}
        if target_platform != "windows":
            item["mode"] = path.stat().st_mode & 0o7777
        files.append(item)
    manifest = manifest_path or (release / "release-manifest.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "version": version,
        "target_platform": target_platform,
        "target_arch": target_arch,
        "files": files,
    }
    if bundle_path:
        payload["bundle_path"] = bundle_path
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
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
    # The application modules are copied into the runtime directory and loaded
    # dynamically by the launcher. Keep SQLite explicit so PyInstaller also
    # bundles the stdlib wrapper and its platform extension.
    modules = {"webbrowser", "sqlite3", "_sqlite3", "signriver_app"}
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


def _find_bandizip() -> Path | None:
    """Locate Bandizip's console tool (``bz.exe``).

    Bandizip ships ``bdzsfx.x86.sfx`` next to ``bz.exe``; its SFX stub runs as
    ``asInvoker``（不弹 UAC），解压时把 payload 的顶层文件夹放到 EXE 同级目录。
    """
    candidates = [shutil.which("bz"), shutil.which("bz.exe")]
    if sys.platform == "win32":
        try:
            import winreg
        except ImportError:  # pragma: no cover - 非 Windows 不会走到这里
            winreg = None
        if winreg is not None:
            roots = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            )
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for root in roots:
                    try:
                        with winreg.OpenKey(hive, root) as key:
                            count = winreg.QueryInfoKey(key)[0]
                    except OSError:
                        continue
                    for index in range(count):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, index)) as entry:
                                display = str(winreg.QueryValueEx(entry, "DisplayName")[0])
                                if "bandizip" not in display.casefold():
                                    continue
                                location = str(
                                    winreg.QueryValueEx(entry, "InstallLocation")[0]
                                ).strip()
                        except OSError:
                            continue
                        if location:
                            candidates.append(str(Path(location) / "bz.exe"))
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.is_file():
            return path
    return None


def _build_bandizip_sfx(release: Path, sfx_path: Path) -> bool:
    """Build the self-extractor with Bandizip when it is installed.

    与 7-Zip 的 SFX 相比，Bandizip 的 stub 以 ``asInvoker`` 运行，不需要
    管理员权限；解压结果同样是 ``<EXE 同级目录>\\<发布目录>``。
    """
    bandizip = _find_bandizip()
    if bandizip is None:
        return False
    module = bandizip.parent / "bdzsfx.x86.sfx"
    if not module.is_file():
        return False
    sfx_path.unlink(missing_ok=True)
    result = subprocess.run(
        [
            str(bandizip),
            "c",
            "-l:9",
            "-y",
            f"-sfx:{module}",
            str(sfx_path),
            # 传入发布目录本身（不是 \*），保证解压后落在单一文件夹里。
            str(release),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0 and sfx_path.is_file()


def _build_sfx(release: Path, archive_7z: Path, sfx_path: Path) -> bool:
    """Build a GUI 7-Zip SFX so users extract before running the app."""
    if _build_bandizip_sfx(release, sfx_path):
        return True
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
            # 必须连发布文件夹本身一起打包：SFX 会把内容解压到用户选择的
            # 目录，只打目录内容会让文件散落到目标盘根目录（曾污染整个盘）。
            release.name,
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
    """PyInstaller 外壳版自解压包（默认方案）。

    双击后自动解压到 ``<EXE 同级目录>\\<发布目录>``，不需要选择路径、
    不需要管理员权限，完成后提示并打开该文件夹；v0.1.x 一直用它。
    """
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
            *pyinstaller_exclude_args(),
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
    copy_app_tree(release / "app")
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
    # 优先用 Bandizip/7-Zip 的 SFX 模块：产物只有 ZIP + 几十 KB 的 stub，
    # 其中 Bandizip 的 stub 以 asInvoker 运行（不弹 UAC）且解压到单一文件夹；
    # Python 外壳版会多出约 11.9 MB，只在两个模块都不可用时兜底。
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
    for synced in sync_publisher_inbox():
        print(f"发布器收件：      {synced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
