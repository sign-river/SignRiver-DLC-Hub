"""Persistent, content-addressed storage for user-owned original game libraries."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ...domain.patches import PatchPlatform, PatchProfile

MAX_ORIGINAL_LIBRARY_BYTES = 128 * 1024 * 1024


class OriginalLibraryError(RuntimeError):
    """Raised when an original library cannot be trusted or persisted safely."""


@dataclass(frozen=True, slots=True)
class OriginalLibraryEntry:
    installation_key: str
    sha256: str
    path: Path
    metadata_path: Path
    filename: str
    size_bytes: int
    binary_format: str
    architecture: str
    source: str


class OriginalLibraryVault:
    """Content-addressed, persistent vault rooted outside normal download caches."""

    def __init__(self, data_root: Path, *, clock=time.time) -> None:
        self.root = Path(data_root).resolve() / "original-libraries" / "v1"
        self._clock = clock

    @staticmethod
    def installation_key(game_id: str, profile: PatchProfile, game_root: Path) -> str:
        identity = "|".join(
            (
                game_id.strip().casefold(),
                profile.platform.value,
                "x86_64",
                os.path.normcase(str(Path(game_root).resolve())),
                profile.install_relative_dir.casefold(),
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def validate_source(self, path: Path, platform: PatchPlatform) -> tuple[str, str, int]:
        path = Path(path)
        self._reject_link_or_reparse_chain(path)
        if not path.is_file():
            raise OriginalLibraryError("原生库文件不存在")
        size = path.stat().st_size
        if size <= 0:
            raise OriginalLibraryError("原生库大小为 0")
        if size > MAX_ORIGINAL_LIBRARY_BYTES:
            raise OriginalLibraryError("原生库大小超过安全上限")
        with path.open("rb") as stream:
            header = stream.read(4096)
        if platform is PatchPlatform.WINDOWS:
            self._validate_pe_x64(header)
            return "PE", "x86_64", size
        if platform is PatchPlatform.STEAMOS:
            self._validate_elf_x64(header)
            return "ELF", "x86_64", size
        if platform is PatchPlatform.MACOS:
            self._validate_macho_x64(header)
            return "Mach-O", "x86_64", size
        raise OriginalLibraryError(f"不支持的原生库平台：{platform}")

    def capture(
        self,
        source_path: Path,
        *,
        game_id: str,
        profile: PatchProfile,
        game_root: Path,
        source: str,
    ) -> OriginalLibraryEntry:
        source_path = Path(source_path)
        self._reject_link_or_reparse_chain(source_path)
        source_path = source_path.resolve(strict=True)
        binary_format, architecture, size = self.validate_source(
            source_path, profile.platform
        )
        sha256 = self.sha256_file(source_path)
        key = self.installation_key(game_id, profile, game_root)
        entry_dir = self.root / key[:32] / sha256
        self._reject_link_or_reparse_chain(entry_dir)
        library_path = entry_dir / profile.runtime_original_library_name
        metadata_path = entry_dir / "metadata.json"
        entry_dir.mkdir(parents=True, exist_ok=True)
        if library_path.exists():
            self._reject_link_or_reparse(library_path)
            if self.sha256_file(library_path) != sha256:
                raise OriginalLibraryError("原生库保险库条目已损坏")
        else:
            self._copy_atomic(source_path, library_path)
            if self.sha256_file(library_path) != sha256:
                library_path.unlink(missing_ok=True)
                raise OriginalLibraryError("原生库保险库写入后哈希不一致")
        now = self._clock()
        existing = self._read_metadata(metadata_path)
        document = {
            "schema": 1,
            "installation_key": key,
            "filename": profile.runtime_original_library_name,
            "size_bytes": size,
            "sha256": sha256,
            "binary_format": binary_format,
            "architecture": architecture,
            "source": source,
            "captured_at": existing.get("captured_at", now),
            "last_verified_at": now,
        }
        self._write_json_atomic(metadata_path, document)
        return OriginalLibraryEntry(
            key, sha256, library_path, metadata_path,
            profile.runtime_original_library_name, size,
            binary_format, architecture, source,
        )

    def resolve(
        self,
        *,
        installation_key: str,
        sha256: str,
        profile: PatchProfile,
    ) -> OriginalLibraryEntry:
        if not _is_sha256(sha256) or not _is_sha256(installation_key):
            raise OriginalLibraryError("原生库保险库索引无效")
        entry_dir = self.root / installation_key[:32] / sha256
        library_path = entry_dir / profile.runtime_original_library_name
        metadata_path = entry_dir / "metadata.json"
        self._reject_link_or_reparse(library_path)
        metadata = self._read_metadata(metadata_path)
        if (
            not metadata
            or metadata.get("sha256") != sha256
            or metadata.get("installation_key") != installation_key
            or metadata.get("filename") != profile.runtime_original_library_name
        ):
            raise OriginalLibraryError("原生库保险库元数据缺失或损坏")
        binary_format, architecture, size = self.validate_source(
            library_path, profile.platform
        )
        if self.sha256_file(library_path) != sha256:
            raise OriginalLibraryError("原生库保险库内容校验失败")
        metadata["last_verified_at"] = self._clock()
        self._write_json_atomic(metadata_path, metadata)
        return OriginalLibraryEntry(
            installation_key, sha256, library_path, metadata_path,
            profile.runtime_original_library_name, size,
            binary_format, architecture, str(metadata.get("source") or "vault"),
        )

    @classmethod
    def _reject_link_or_reparse_chain(cls, path: Path) -> None:
        """Reject links/reparse points in the file and every existing ancestor."""
        candidate = Path(path).absolute()
        while True:
            cls._reject_link_or_reparse(candidate)
            parent = candidate.parent
            if parent == candidate:
                break
            candidate = parent

    @staticmethod
    def _reject_link_or_reparse(path: Path) -> None:
        path = Path(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise OriginalLibraryError("拒绝使用符号链接形式的原生库")
        attributes = getattr(info, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if attributes & reparse:
            raise OriginalLibraryError("拒绝使用重解析点形式的原生库")

    @staticmethod
    def _validate_pe_x64(header: bytes) -> None:
        if len(header) < 0x40 or header[:2] != b"MZ":
            raise OriginalLibraryError("原生库不是有效的 PE 文件")
        offset = int.from_bytes(header[0x3C:0x40], "little")
        if offset + 6 > len(header) or header[offset:offset + 4] != b"PE\0\0":
            raise OriginalLibraryError("原生库 PE 头无效")
        if int.from_bytes(header[offset + 4:offset + 6], "little") != 0x8664:
            raise OriginalLibraryError("原生库不是 PE x64")

    @staticmethod
    def _validate_elf_x64(header: bytes) -> None:
        if len(header) < 20 or header[:4] != b"\x7fELF":
            raise OriginalLibraryError("原生库不是有效的 ELF 文件")
        if header[4] != 2 or header[5] not in {1, 2}:
            raise OriginalLibraryError("原生库不是 ELF 64 位文件")
        byteorder = "little" if header[5] == 1 else "big"
        if int.from_bytes(header[18:20], byteorder) != 0x3E:
            raise OriginalLibraryError("原生库不是 ELF x86_64")

    @staticmethod
    def _validate_macho_x64(header: bytes) -> None:
        if len(header) < 8:
            raise OriginalLibraryError("原生库 Mach-O 头无效")
        if header[:4] == b"\xcf\xfa\xed\xfe":
            byteorder = "little"
        elif header[:4] == b"\xfe\xed\xfa\xcf":
            byteorder = "big"
        else:
            raise OriginalLibraryError("原生库不是 Mach-O 64 位文件")
        if int.from_bytes(header[4:8], byteorder) != 0x01000007:
            raise OriginalLibraryError("原生库不是 Mach-O x86_64")

    @staticmethod
    def _copy_atomic(source: Path, destination: Path) -> None:
        handle = tempfile.NamedTemporaryFile(
            "wb", delete=False, dir=str(destination.parent),
            prefix=".original-", suffix=".tmp",
        )
        try:
            with source.open("rb") as input_stream, handle as output_stream:
                for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                    output_stream.write(chunk)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            if os.name != "nt":
                os.chmod(handle.name, source.stat().st_mode & 0o777)
            os.replace(handle.name, destination)
        except Exception:
            Path(handle.name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        handle = tempfile.NamedTemporaryFile(
            "wb", delete=False, dir=str(path.parent),
            prefix=".metadata-", suffix=".tmp",
        )
        try:
            with handle as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(handle.name, path)
        except Exception:
            Path(handle.name).unlink(missing_ok=True)
            raise


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "MAX_ORIGINAL_LIBRARY_BYTES",
    "OriginalLibraryEntry",
    "OriginalLibraryError",
    "OriginalLibraryVault",
]
