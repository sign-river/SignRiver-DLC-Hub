"""Safe inspection for generic cartridge DLC directory ZIP packages."""

from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .stellaris_package import PackageInspectionError

_ASSET_NAME = re.compile(r"^(dlc\d{3,})_([a-z0-9_]+)\.zip$", re.I)
_INSTALL_DIRECTORY = re.compile(r"^[a-z0-9][a-z0-9_. -]*$", re.I)


@dataclass(frozen=True, slots=True)
class DirectoryPackageMetadata:
    dlc_id: str
    display_name: str
    package_size: int
    package_sha256: str
    payload_entries: int
    install_directory: str


def inspect_directory_package(path: Path) -> DirectoryPackageMetadata:
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise PackageInspectionError("package is not a valid ZIP file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    roots: set[str] = set()
    names: set[str] = set()
    total_size = 0
    payload_entries = 0
    with zipfile.ZipFile(path) as package:
        infos = package.infolist()
        if not infos or len(infos) > 10_000:
            raise PackageInspectionError("package is empty or contains too many files")
        for info in infos:
            member = PurePosixPath(info.filename.replace("\\", "/"))
            if member.is_absolute() or ".." in member.parts or not member.parts:
                raise PackageInspectionError(f"unsafe ZIP member: {info.filename}")
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise PackageInspectionError("package symbolic links are not allowed")
            key = member.as_posix().casefold()
            if key in names:
                raise PackageInspectionError(f"duplicate ZIP member: {info.filename}")
            names.add(key)
            roots.add(member.parts[0])
            total_size += info.file_size
            if total_size > 8 * 1024**3:
                raise PackageInspectionError("expanded package is too large")
            if not info.is_dir():
                payload_entries += 1
    if len(roots) != 1:
        raise PackageInspectionError("package must contain exactly one top-level directory")
    root = next(iter(roots))
    if _INSTALL_DIRECTORY.fullmatch(root) is None or root in {".", ".."}:
        raise PackageInspectionError("package root is not a safe install directory")
    match = _ASSET_NAME.fullmatch(path.name)
    if match is None:
        raise PackageInspectionError(
            "资源包文件名必须使用管理编号格式，例如 dlc001_name.zip"
        )
    return DirectoryPackageMetadata(
        dlc_id=match.group(1).lower(),
        display_name=match.group(2).replace("_", " ").title(),
        package_size=path.stat().st_size,
        package_sha256=digest.hexdigest(),
        payload_entries=payload_entries,
        install_directory=root,
    )


__all__ = ["DirectoryPackageMetadata", "inspect_directory_package"]
