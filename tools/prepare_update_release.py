"""Prepare matching GitLink and GitHub manifests for one update package."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from signriver_publisher.updates import (  # noqa: E402
    UPDATE_MANIFEST_ASSET,
    UpdateReleaseDraft,
    release_asset_url,
    write_update_manifest,
)


TARGETS = {
    "gitlink": ("signriver", "signriver-dlc-assets"),
    "github": ("sign-river", "signriver-dlc-assets"),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare matching update manifests for GitLink and GitHub"
    )
    parser.add_argument("package", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--kind", choices=("module", "full"), required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--min-launcher-version", default="0.1.0")
    parser.add_argument("--installer-version", type=int, default=1)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist" / "updates"
    )
    args = parser.parse_args()

    package = args.package.resolve()
    draft = UpdateReleaseDraft(
        version=args.version,
        kind=args.kind,
        package=package,
        min_launcher_version=args.min_launcher_version,
        notes=args.notes,
        mandatory=args.mandatory,
        installer_version=args.installer_version,
    )
    output = args.output.resolve()
    print(f"Update package (upload unchanged to both hosts): {package}")
    for target, (owner, repository) in TARGETS.items():
        manifest = write_update_manifest(
            output / target / UPDATE_MANIFEST_ASSET,
            channel="stable",
            releases=[
                draft.release_dict(
                    release_asset_url(
                        target, owner, repository, package.name
                    )
                )
            ],
        )
        print(f"{target:7} manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
