"""Restore archived application modules with an integrity check."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "module-archives.json"

SOURCE_BASES = {
    "gitlink": "https://gitlink.org.cn/{repository}/releases/download/{release}/{filename}",
    "github": "https://github.com/{repository}/releases/download/{release}/{filename}",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def repository_for(catalog: dict, source: str) -> str:
    """Return the asset repository for a download source.

    Platform-specific owners differ (GitHub: ``sign-river``, GitLink:
    ``signriver``), so prefer the per-source override when present and fall
    back to the legacy single ``repository`` field.
    """
    repositories = catalog.get("repositories") or {}
    return repositories.get(source) or catalog["repository"]


def select_modules(catalog: dict, versions: list[str] | None) -> list[dict]:
    modules = catalog["modules"]
    if not versions:
        return modules
    selected = [module for module in modules if module["version"] in versions]
    missing = sorted(set(versions) - {module["version"] for module in selected})
    if missing:
        raise SystemExit(f"unknown archived module version(s): {', '.join(missing)}")
    return selected


def archive_path(module: dict) -> Path:
    return ROOT / "dist" / "modules" / module["filename"]


def valid_archive(path: Path, module: dict) -> bool:
    return path.is_file() and path.stat().st_size == module["size"] and sha256(path) == module["sha256"]


def download(module: dict, catalog: dict, source: str, refresh: bool) -> Path:
    output = archive_path(module)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not refresh and valid_archive(output, module):
        return output
    url = SOURCE_BASES[source].format(
        repository=repository_for(catalog, source),
        release=catalog["release"],
        filename=module["filename"],
    )
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream)
    except urllib.error.URLError as error:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"could not download {module['filename']} from {source}: {error}") from error
    if not valid_archive(temporary, module):
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"integrity check failed for {module['filename']} from {source}")
    temporary.replace(output)
    return output


def restore(module: dict, archive: Path, replace: bool) -> None:
    target = ROOT / "app" / "versions" / module["version"]
    with tempfile.TemporaryDirectory(prefix="signriver-module-") as temporary_name:
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(archive) as package:
                for info in package.infolist():
                    path = Path(info.filename)
                    if path.is_absolute() or ".." in path.parts:
                        raise SystemExit(f"unsafe archive entry: {info.filename}")
                package.extractall(temporary)
        except zipfile.BadZipFile as error:
            raise SystemExit(f"invalid archive: {archive}") from error
        manifest = temporary / "module.json"
        if not manifest.is_file():
            raise SystemExit(f"module archive is missing module.json: {archive}")
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if metadata.get("version") != module["version"]:
            raise SystemExit(f"module version mismatch in {archive}")
        entrypoint = str(metadata.get("entrypoint", "")).split(":", 1)[0]
        if not entrypoint or not (temporary / entrypoint).is_file():
            raise SystemExit(f"module entrypoint is missing in {archive}")
        if target.exists():
            existing_manifest = target / "module.json"
            if existing_manifest.is_file() and not replace:
                existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
                if existing.get("version") == module["version"]:
                    return
            if not replace:
                raise SystemExit(f"module exists but is not valid: {target}; use --replace")
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(temporary, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=SOURCE_BASES, default="gitlink")
    parser.add_argument("--version", action="append", dest="versions")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="download again even when a valid local archive is cached",
    )
    args = parser.parse_args()
    catalog = load_catalog()
    for module in select_modules(catalog, args.versions):
        archive = download(module, catalog, args.source, args.refresh)
        if not args.verify_only:
            restore(module, archive, args.replace)
        print(f"verified {module['version']} from {args.source}: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
