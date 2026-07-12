from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_ROOT = PROJECT_ROOT / "app" / "versions" / "0.1.0"
if str(VERSION_ROOT) not in sys.path:
    sys.path.insert(0, str(VERSION_ROOT))

from signriver_app.infrastructure.catalog import inspect_stellaris_package  # noqa: E402


ASSET_NAME = re.compile(r"^dlc\d{3}_[a-z0-9_]+\.zip$", re.I)


def generate(
    source: Path,
    output: Path,
    *,
    catalog_id: str,
    revision: int,
    min_game_version: str | None,
    max_game_version: str | None,
    distribution_authorized: bool = False,
) -> dict:
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("source must be a directory")
    if revision < 1:
        raise ValueError("revision must be positive")
    packages = sorted(
        (path for path in source.iterdir() if path.is_file() and ASSET_NAME.fullmatch(path.name)),
        key=lambda path: path.name.casefold(),
    )
    if not packages:
        raise ValueError("source contains no Stellaris DLC ZIP packages")
    assets = []
    for package in packages:
        metadata = inspect_stellaris_package(package)
        assets.append({
            "dlc_id": metadata.dlc_id,
            "asset_name": package.name,
            "size": metadata.package_size,
            "sha256": metadata.package_sha256,
            "min_game_version": min_game_version,
            "max_game_version": max_game_version,
            "distribution_authorized": distribution_authorized,
        })
    if len({item["dlc_id"] for item in assets}) != len(assets):
        raise ValueError("multiple packages describe the same DLC ID")
    manifest = {
        "schema_version": 1,
        "catalog_id": catalog_id,
        "game_id": "stellaris",
        "revision": revision,
        "assets": assets,
        "signature": {
            "key_id": "unsigned-draft",
            "value": "UNSIGNED_DRAFT_REQUIRES_PUBLISHER_SIGNATURE_0000000000000000",
        },
    }
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an unsigned Stellaris DLC catalog draft from local ZIP packages"
    )
    parser.add_argument("source", type=Path, help="directory containing dlcNNN_*.zip files")
    parser.add_argument("--output", type=Path, default=Path("dlc-catalog.json"))
    parser.add_argument("--catalog-id", default="stellaris-ste")
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--min-game-version")
    parser.add_argument("--max-game-version")
    parser.add_argument(
        "--confirm-authorized",
        action="store_true",
        help="confirm the publisher is authorized to distribute every scanned package",
    )
    args = parser.parse_args()
    manifest = generate(
        args.source,
        args.output,
        catalog_id=args.catalog_id,
        revision=args.revision,
        min_game_version=args.min_game_version,
        max_game_version=args.max_game_version,
        distribution_authorized=args.confirm_authorized,
    )
    print(f"Manifest draft: {args.output.resolve()}")
    print(f"Assets: {len(manifest['assets'])}")
    print("Distribution authorized: " + ("yes" if args.confirm_authorized else "no (safe default)"))
    print("Signature: unsigned draft; signing is required before production trust")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
