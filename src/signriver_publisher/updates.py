"""Build the immutable assets and mutable manifest for client updates."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath

from signriver_launcher.versioning import Version


UPDATE_RELEASE_TAG = "updates"
UPDATE_MANIFEST_ASSET = "update-manifest.json"
MODULE_ARCHIVE_RELEASE_TAG = "modules"
_PACKAGE_FILENAME = re.compile(
    r"(?:^|[-_])(?P<kind>module|full)[-_]v?"
    r"(?P<version>[0-9]+\.[0-9]+\.[0-9]+)"
    r"(?=[-_.]|$)",
    re.I,
)


@dataclass(frozen=True, slots=True)
class UpdatePackageInfo:
    version: str
    kind: str


@dataclass(frozen=True, slots=True)
class ModuleArchiveInfo:
    """Identity of a stored module snapshot, not a client update release."""

    version: str


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
        _validate_package(self.package, self.kind, self.version)

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


def _validate_package(package: Path, kind: str, version: str) -> None:
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("update ZIP contains duplicate paths")
            for name in names:
                member = PurePosixPath(name.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError("update ZIP contains unsafe paths")
            metadata_name = (
                "module.json" if kind == "module" else "release-manifest.json"
            )
            if metadata_name not in names:
                raise ValueError(
                    f"{kind} update ZIP must contain {metadata_name} at its root"
                )
            metadata = json.loads(archive.read(metadata_name).decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"update package is not a valid ZIP: {error}") from error
    if not isinstance(metadata, dict) or metadata.get("version") != version:
        raise ValueError(
            f"update package version does not match requested version {version}"
        )
    if kind == "module":
        entrypoint = str(metadata.get("entrypoint") or "").rsplit(":", 1)[0]
        if not entrypoint or entrypoint not in names:
            raise ValueError("module update ZIP entrypoint is missing")
    elif metadata.get("schema_version") != 1:
        raise ValueError("full update ZIP has an invalid release manifest")


def inspect_update_package(package: Path) -> UpdatePackageInfo:
    """Read update type and version from root metadata and verify its filename."""
    package = Path(package)
    try:
        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist())
            metadata_names = names & {"module.json", "release-manifest.json"}
            if len(metadata_names) != 1:
                raise ValueError(
                    "update ZIP must contain exactly one root metadata file"
                )
            metadata_name = metadata_names.pop()
            kind = "module" if metadata_name == "module.json" else "full"
            metadata = json.loads(
                archive.read(metadata_name).decode("utf-8")
            )
    except (
        OSError,
        zipfile.BadZipFile,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError(f"update package is not a valid ZIP: {error}") from error
    version = str(metadata.get("version") or "").strip()
    try:
        Version.parse(version)
    except ValueError as error:
        raise ValueError(
            "update package metadata has an invalid semantic version"
        ) from error
    filename_match = _PACKAGE_FILENAME.search(package.name)
    if filename_match and (
        filename_match.group("kind").casefold() != kind
        or filename_match.group("version") != version
    ):
        raise ValueError(
            "update package filename does not match its embedded type/version"
        )
    _validate_package(package, kind, version)
    return UpdatePackageInfo(version, kind)


def inspect_module_archive(package: Path) -> ModuleArchiveInfo:
    """Verify a module ZIP before storing it in the immutable modules Release."""
    info = inspect_update_package(package)
    if info.kind != "module":
        raise ValueError("模块归档必须包含根目录 module.json，不能使用全量更新包")
    return ModuleArchiveInfo(info.version)


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
    "UPDATE_MANIFEST_ASSET", "UPDATE_RELEASE_TAG", "UpdatePackageInfo",
    "UpdateReleaseDraft", "inspect_update_package", "release_asset_url",
    "sha256", "write_update_manifest",
]
