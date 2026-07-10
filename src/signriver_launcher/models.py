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
        if not isinstance(notes, str) or not isinstance(mandatory, bool):
            raise ManifestError("Release notes or mandatory flag has an invalid type")
        return cls(version, kind, package_url, sha256.lower(), size, min_launcher, notes, mandatory)


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
