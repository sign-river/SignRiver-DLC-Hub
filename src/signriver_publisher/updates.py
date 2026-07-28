"""Build the immutable assets and mutable manifest for client updates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from signriver_launcher.versioning import Version


UPDATE_RELEASE_TAG = "updates"
UPDATE_MANIFEST_ASSET = "update-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class UpdateReleaseDraft:
    version: str
    kind: str
    package: Path
    min_launcher_version: str = "0.1.0"
    notes: str = ""
    mandatory: bool = False
    installer_version: int = 1

    def __post_init__(self) -> None:
        if self.kind not in {"module", "full"}:
            raise ValueError("update kind must be module or full")
        if not self.version.strip() or not self.min_launcher_version.strip():
            raise ValueError("update versions cannot be empty")
        try:
            Version.parse(self.version)
            Version.parse(self.min_launcher_version)
        except ValueError as error:
            raise ValueError("update versions must use semantic versioning") from error
        if not Path(self.package).is_file():
            raise ValueError(f"update package does not exist: {self.package}")
        if self.installer_version < 1:
            raise ValueError("installer version must be positive")

    def release_dict(self, package_url: str) -> dict[str, object]:
        package = Path(self.package)
        return {
            "version": self.version,
            "kind": self.kind,
            "min_launcher_version": self.min_launcher_version,
            "package_url": package_url,
            "sha256": sha256(package),
            "size": package.stat().st_size,
            "mandatory": self.mandatory,
            "notes": self.notes,
            "installer_version": self.installer_version,
        }


def release_asset_url(
    target: str, owner: str, repository: str, asset_name: str,
) -> str:
    """Return the stable public attachment URL for the updates Release."""
    target = target.casefold()
    if target == "github":
        return f"https://github.com/{owner}/{repository}/releases/download/{UPDATE_RELEASE_TAG}/{asset_name}"
    if target == "gitlink":
        return f"https://gitlink.org.cn/{owner}/{repository}/releases/download/{UPDATE_RELEASE_TAG}/{asset_name}"
    raise ValueError("publish target must be gitlink or github")


def write_update_manifest(
    output: Path,
    *,
    channel: str,
    releases: list[dict[str, object]],
) -> Path:
    """Atomically write the only mutable asset in the update Release."""
    if not channel.strip():
        raise ValueError("update channel cannot be empty")
    payload = {
        "schema_version": 1,
        "channel": channel,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "releases": releases,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(output)
    return output


__all__ = [
    "UPDATE_MANIFEST_ASSET", "UPDATE_RELEASE_TAG", "UpdateReleaseDraft",
    "release_asset_url", "sha256", "write_update_manifest",
]
