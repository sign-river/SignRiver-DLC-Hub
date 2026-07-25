from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .constants import HOST_API_VERSION
from .errors import ManifestError, PackageError
from .versioning import Version


@dataclass(frozen=True)
class ModuleMetadata:
    version: str
    api_version: int
    entrypoint: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModuleMetadata":
        version = value.get("version")
        api_version = value.get("api_version")
        entrypoint = value.get("entrypoint")
        if not isinstance(version, str):
            raise PackageError("module.json is missing version")
        Version.parse(version)
        if not isinstance(api_version, int) or api_version < 1:
            raise PackageError("module.json has an invalid api_version")
        if api_version > HOST_API_VERSION:
            raise PackageError(
                f"Module requires host API {api_version}, launcher supports {HOST_API_VERSION}"
            )
        if not isinstance(entrypoint, str) or ":" not in entrypoint:
            raise PackageError("module.json entrypoint must use path.py:callable format")
        return cls(version, api_version, entrypoint)


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    kind: Literal["module", "full"]
    package_url: str
    sha256: str
    size: int | None
    min_launcher_version: str
    notes: str = ""
    mandatory: bool = False
    installer_version: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReleaseInfo":
        try:
            version = value["version"]
            kind = value["kind"]
            package_url = value["package_url"]
            sha256 = value["sha256"]
            min_launcher = value.get("min_launcher_version", "0.1.0")
        except KeyError as error:
            raise ManifestError(f"Release is missing {error.args[0]}") from error
        if not all(isinstance(item, str) for item in (version, kind, package_url, sha256, min_launcher)):
            raise ManifestError("Release string fields have invalid types")
        Version.parse(version)
        Version.parse(min_launcher)
        if kind not in ("module", "full"):
            raise ManifestError(f"Unsupported release kind: {kind}")
        if len(sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in sha256):
            raise ManifestError("Release sha256 must be 64 hexadecimal characters")
        size = value.get("size")
        if size is not None and (not isinstance(size, int) or size < 0):
            raise ManifestError("Release size must be a non-negative integer")
        notes = value.get("notes", "")
        mandatory = value.get("mandatory", False)
        installer_version = value.get("installer_version", 1)
        if (
            not isinstance(notes, str)
            or not isinstance(mandatory, bool)
            or not isinstance(installer_version, int)
            or installer_version < 1
        ):
            raise ManifestError("Release notes or mandatory flag has an invalid type")
        return cls(
            version, kind, package_url, sha256.lower(), size, min_launcher,
            notes, mandatory, installer_version,
        )


@dataclass(frozen=True)
class ReleaseFile:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReleaseFile":
        path, size, sha256 = value.get("path"), value.get("size"), value.get("sha256")
        if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
            raise PackageError("release manifest has an unsafe path")
        if not isinstance(size, int) or size < 0:
            raise PackageError("release manifest has an invalid file size")
        if not isinstance(sha256, str) or len(sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in sha256):
            raise PackageError("release manifest has an invalid SHA-256")
        return cls(path.replace("\\", "/"), size, sha256.lower())


@dataclass(frozen=True)
class FullReleaseManifest:
    version: str
    files: tuple[ReleaseFile, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FullReleaseManifest":
        if value.get("schema_version") != 1:
            raise PackageError("unsupported full release manifest schema")
        version, files = value.get("version"), value.get("files")
        if not isinstance(version, str) or not isinstance(files, list) or not files:
            raise PackageError("full release manifest is incomplete")
        Version.parse(version)
        parsed = tuple(ReleaseFile.from_dict(item) for item in files if isinstance(item, dict))
        if len(parsed) != len(files) or len({item.path for item in parsed}) != len(parsed):
            raise PackageError("full release manifest file entries are invalid")
        return cls(version, parsed)


@dataclass(frozen=True)
class UpdateManifest:
    channel: str
    releases: tuple[ReleaseInfo, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UpdateManifest":
        if value.get("schema_version") != 1:
            raise ManifestError("Unsupported update manifest schema")
        channel = value.get("channel")
        releases = value.get("releases")
        if not isinstance(channel, str) or not channel:
            raise ManifestError("Manifest is missing channel")
        if not isinstance(releases, list):
            raise ManifestError("Manifest releases must be an array")
        if not all(isinstance(item, dict) for item in releases):
            raise ManifestError("Every manifest release must be an object")
        return cls(channel, tuple(ReleaseInfo.from_dict(item) for item in releases))
