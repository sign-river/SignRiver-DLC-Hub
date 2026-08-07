"""Create source-pinned baseline folders for dual-host update tests."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


MANIFEST_URLS = {
    "gitlink": (
        "https://gitlink.org.cn/signriver/signriver-dlc-assets/"
        "releases/download/updates/update-manifest.json"
    ),
    "github": (
        "https://github.com/sign-river/signriver-dlc-assets/"
        "releases/download/updates/update-manifest.json"
    ),
}


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    for entry in archive.infolist():
        member = PurePosixPath(entry.filename.replace("\\", "/"))
        if member.is_absolute() or ".." in member.parts or not member.parts:
            raise ValueError(f"unsafe installer path: {entry.filename}")
    archive.extractall(destination)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare separate GitLink/GitHub baseline installers"
    )
    parser.add_argument("installer_zip", type=Path)
    parser.add_argument(
        "--baseline-version",
        help=(
            "Activate an older bundled module while retaining the installer's "
            "launcher; useful for testing a launcher-fixed full update"
        ),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("dist/test-baselines")
    )
    args = parser.parse_args()

    installer = args.installer_zip.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="signriver-baseline-") as temporary:
        extracted = Path(temporary)
        with zipfile.ZipFile(installer) as archive:
            _safe_extract(archive, extracted)
        roots = [path for path in extracted.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ValueError("installer ZIP must contain exactly one product directory")
        source = roots[0]
        state = json.loads(
            (source / "app" / "state.json").read_text(encoding="utf-8")
        )
        baseline_version = args.baseline_version or state.get("active_version")
        if not isinstance(baseline_version, str) or not baseline_version:
            raise ValueError("test baseline version is invalid")
        baseline_module = (
            source / "app" / "versions" / baseline_version / "module.json"
        )
        if not baseline_module.is_file():
            raise ValueError(
                f"installer does not contain baseline module {baseline_version}"
            )
        state.update(
            {
                "active_version": baseline_version,
                "previous_version": None,
                "pending_version": None,
                "bad_versions": [],
            }
        )
        (source / "app" / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        for target, manifest_url in MANIFEST_URLS.items():
            target_root = output / f"{baseline_version}-{target}" / source.name
            if target_root.exists():
                raise FileExistsError(
                    f"baseline already exists; choose another output: {target_root}"
                )
            target_root.parent.mkdir(parents=True)
            shutil.copytree(source, target_root)
            config_path = target_root / "config" / "update.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config.update(
                {
                    "manifest_url": manifest_url,
                    "manifest_urls": MANIFEST_URLS,
                    "download_source": target,
                    "check_on_startup": False,
                }
            )
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            archive_path = (
                output
                / f"SignRiver-test-baseline-v{baseline_version}-{target}.zip"
            )
            with zipfile.ZipFile(
                archive_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                for path in sorted(target_root.rglob("*")):
                    if path.is_file():
                        archive.write(
                            path, Path(source.name) / path.relative_to(target_root)
                        )
            print(f"{target:7} folder: {target_root}")
            print(f"{target:7} ZIP:    {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
