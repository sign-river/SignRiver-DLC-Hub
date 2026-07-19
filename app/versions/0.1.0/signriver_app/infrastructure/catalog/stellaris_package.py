"""Safe metadata inspection for Stellaris DLC ZIP packages."""

from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_ASSIGNMENT = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|([^#\s]+))')


class PackageInspectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StellarisPackageMetadata:
    dlc_id: str
    display_name: str
    archive_path: str
    category: str | None
    steam_id: str | None
    thumbnail_path: str | None
    package_size: int
    package_sha256: str
    payload_entries: int


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    path = PurePosixPath(info.filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PackageInspectionError(f"unsafe ZIP member: {info.filename}")
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise PackageInspectionError(f"symbolic links are not allowed: {info.filename}")
    return path


def inspect_stellaris_package(
    path: Path, *, known_sha256: str | None = None
) -> StellarisPackageMetadata:
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise PackageInspectionError("package is not a valid ZIP file")
    if known_sha256 is None:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        package_sha256 = digest.hexdigest()
    elif re.fullmatch(r"[0-9a-fA-F]{64}", known_sha256):
        package_sha256 = known_sha256.casefold()
    else:
        raise ValueError("known SHA-256 is invalid")

    with zipfile.ZipFile(path) as package:
        infos = package.infolist()
        if len(infos) > 10_000:
            raise PackageInspectionError("package contains too many files")
        names: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            member = _safe_member(info)
            key = member.as_posix().casefold()
            if key in names:
                raise PackageInspectionError(f"duplicate ZIP member: {info.filename}")
            names[key] = info
            total_size += info.file_size
            if total_size > 4 * 1024**3:
                raise PackageInspectionError("expanded package is too large")
        descriptors = [info for info in infos if PurePosixPath(info.filename).suffix.casefold() == ".dlc"]
        if len(descriptors) != 1:
            raise PackageInspectionError("package must contain exactly one .dlc descriptor")
        descriptor = descriptors[0]
        if descriptor.file_size > 256 * 1024:
            raise PackageInspectionError("DLC descriptor is too large")
        try:
            text = package.read(descriptor).decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise PackageInspectionError("DLC descriptor is not UTF-8") from error
        fields: dict[str, str] = {}
        for line in text.splitlines():
            match = _ASSIGNMENT.match(line)
            if match:
                fields[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
        if not fields.get("name") or not fields.get("archive"):
            raise PackageInspectionError("DLC descriptor is missing name or archive")
        archive = PurePosixPath(fields["archive"])
        if archive.is_absolute() or ".." in archive.parts or archive.suffix.casefold() != ".zip":
            raise PackageInspectionError("DLC archive path is unsafe")
        descriptor_parent = PurePosixPath(descriptor.filename).parent
        archive_name = archive.name.casefold()
        matching_archives = [
            info for info in infos
            if PurePosixPath(info.filename).parent == descriptor_parent
            and PurePosixPath(info.filename).name.casefold() == archive_name
        ]
        if len(matching_archives) != 1:
            raise PackageInspectionError("descriptor archive is missing from the package")
        try:
            with package.open(matching_archives[0]) as nested_stream:
                with zipfile.ZipFile(nested_stream) as nested:
                    payload_entries = len([item for item in nested.infolist() if not item.is_dir()])
        except (OSError, zipfile.BadZipFile) as error:
            raise PackageInspectionError("descriptor archive is not a valid ZIP") from error

    stem = PurePosixPath(descriptor.filename).stem
    thumbnail = fields.get("thumbnail")
    return StellarisPackageMetadata(
        dlc_id=stem,
        display_name=fields["name"],
        archive_path=fields["archive"],
        category=fields.get("category"),
        steam_id=fields.get("steam_id"),
        thumbnail_path=thumbnail,
        package_size=path.stat().st_size,
        package_sha256=package_sha256,
        payload_entries=payload_entries,
    )
