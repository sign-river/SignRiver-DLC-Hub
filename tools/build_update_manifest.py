"""Create the update Release manifest for a built client package."""

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build update-manifest.json for the SignRiver updates Release"
    )
    parser.add_argument("package", type=Path, help="module or full update ZIP")
    parser.add_argument("--version", required=True)
    parser.add_argument("--kind", choices=("module", "full"), required=True)
    parser.add_argument("--target", choices=("gitlink", "github"), required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--min-launcher-version", default="0.1.0")
    parser.add_argument("--notes", default="")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--installer-version", type=int, default=1)
    parser.add_argument("--output", type=Path, default=None)
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
    output = (args.output or package.parent / UPDATE_MANIFEST_ASSET).resolve()
    package_url = release_asset_url(
        args.target, args.owner, args.repository, package.name
    )
    manifest = write_update_manifest(
        output, channel=args.channel, releases=[draft.release_dict(package_url)]
    )
    print(f"Package:  {package}")
    print(f"Manifest: {manifest}")
    print(f"URL:      {package_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
