from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(source: Path, output_root: Path, base_url: str = "") -> tuple[Path, Path]:
    metadata_path = source / "module.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    version = metadata["version"]
    if not (source / metadata["entrypoint"].rsplit(":", 1)[0]).is_file():
        raise SystemExit("module.json entrypoint does not exist")

    output_root.mkdir(parents=True, exist_ok=True)
    archive = output_root / f"SignRiver-DLC-Hub-module-v{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            package.write(path, path.relative_to(source).as_posix())

    package_url = f"{base_url.rstrip('/')}/{archive.name}" if base_url else archive.name
    release = {
        "version": version,
        "kind": "module",
        "min_launcher_version": "0.1.0",
        "package_url": package_url,
        "sha256": sha256(archive),
        "size": archive.stat().st_size,
        "mandatory": False,
        "notes": "",
    }
    fragment = archive.with_suffix(".release.json")
    fragment.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return archive, fragment


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a SignRiver DLC Hub module update")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/modules"))
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()
    archive, fragment = build(args.source.resolve(), args.output.resolve(), args.base_url)
    print(f"Module:   {archive}")
    print(f"Manifest: {fragment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
