"""Build the SteamOS or macOS native package on the matching host."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from signriver_common.platforms import HostPlatform, detect_host_platform  # noqa: E402
from signriver_launcher.constants import LAUNCHER_VERSION  # noqa: E402
from tools.build_release import application_hidden_imports  # noqa: E402


def _validate_release_metadata(root: Path, launcher_version: str) -> None:
    state_path = root / "app" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("active_version") != launcher_version:
        raise SystemExit(
            "active module and launcher versions must match: "
            f"{state.get('active_version')!r} != {launcher_version!r}"
        )

    module_path = root / "app" / "versions" / launcher_version / "module.json"
    if not module_path.is_file():
        raise SystemExit(f"active module metadata does not exist: {module_path}")
    module = json.loads(module_path.read_text(encoding="utf-8"))
    if module.get("version") != launcher_version:
        raise SystemExit(
            "active module metadata and launcher versions must match: "
            f"{module.get('version')!r} != {launcher_version!r}"
        )


def _copy_runtime(destination: Path) -> None:
    shutil.copytree(
        ROOT / "app",
        destination / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".staging"),
    )
    shutil.copytree(
        ROOT / "config",
        destination / "config",
        ignore=shutil.ignore_patterns("publisher.local.json"),
    )


def _write_manifest(
    release: Path,
    platform: str,
    *,
    manifest_path: Path | None = None,
    path_prefix: str = "",
    bundle_path: str | None = None,
) -> None:
    from build_release import write_release_manifest

    write_release_manifest(
        release,
        LAUNCHER_VERSION,
        target_platform=platform,
        target_arch="x64",
        manifest_path=manifest_path,
        path_prefix=path_prefix,
        bundle_path=bundle_path,
    )


def _zip_flat(source: Path, output: Path, arc_prefix: str = "") -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                archive_name = f"{arc_prefix.rstrip('/')}/{relative}" if arc_prefix else relative
                info = zipfile.ZipInfo(archive_name)
                info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                with path.open("rb") as stream:
                    package.writestr(info, stream.read(), compress_type=zipfile.ZIP_DEFLATED)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("steamos", "macos"), required=True)
    args = parser.parse_args()
    native = detect_host_platform()
    expected = HostPlatform(args.platform)
    if native is not expected:
        raise SystemExit(f"{args.platform} package must be built on {args.platform}")
    if os.uname().machine.lower() not in {"x86_64", "amd64"}:
        raise SystemExit("0.2.0 supports x64 hosts only")
    _validate_release_metadata(ROOT, LAUNCHER_VERSION)

    dist, work = ROOT / "dist", ROOT / "build"
    name = "SignRiver-DLC-Hub"
    common = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", name,
        "--paths", str(ROOT / "src"),
        "--paths", str(ROOT / "app" / "versions" / LAUNCHER_VERSION),
        "--collect-all", "customtkinter", "--collect-all", "PIL",
        *(
            argument
            for module in application_hidden_imports()
            for argument in ("--hidden-import", module)
        ),
        "--distpath", str(dist / "native-bin"),
        "--workpath", str(work / f"pyinstaller-{args.platform}"),
        str(ROOT / "launcher.py"),
    ]
    subprocess.run(common, cwd=ROOT, check=True)
    release = dist / (
        f"{name}.app" if expected is HostPlatform.MACOS
        else f"SignRiver-DLC-Hub-{args.platform}-x64"
    )
    if release.exists():
        shutil.rmtree(release)
    release.mkdir(parents=True)
    if expected is HostPlatform.MACOS:
        bundle = dist / "native-bin" / f"{name}.app"
        if not bundle.is_dir():
            raise SystemExit("PyInstaller did not produce the macOS app bundle")
        shutil.copytree(bundle, release, dirs_exist_ok=True)
        runtime = release / "Contents" / "Resources" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        _copy_runtime(runtime)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(release)], check=True)
        install = dist / f"SignRiver-DLC-Hub-v{LAUNCHER_VERSION}-macos-x64.app.zip"
        _zip_flat(release, install, release.name)
        update_payload = work / "native-update-macos"
        if update_payload.exists():
            shutil.rmtree(update_payload)
        update_payload.mkdir(parents=True)
        shutil.copytree(release, update_payload / release.name, symlinks=True)
        _write_manifest(
            release,
            args.platform,
            manifest_path=update_payload / "release-manifest.json",
            path_prefix=release.name,
            bundle_path=release.name,
        )
    else:
        binary = dist / "native-bin" / name
        shutil.copy2(binary, release / name)
        (release / name).chmod(0o755)
        _copy_runtime(release)
        _write_manifest(release, args.platform)
        install = dist / f"SignRiver-DLC-Hub-v{LAUNCHER_VERSION}-steamos-x64.tar.gz"
        install.unlink(missing_ok=True)
        with tarfile.open(install, "w:gz") as package:
            package.add(release, arcname=release.name)
        update_payload = release
    _zip_flat(
        update_payload,
        dist / "updates" / f"SignRiver-DLC-Hub-full-v{LAUNCHER_VERSION}-{args.platform}-x64.zip",
    )
    print(install)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
