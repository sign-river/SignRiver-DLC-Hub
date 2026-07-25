from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .constants import FULL_UPDATE_HELPER_VERSION, FULL_UPDATE_SCHEMA_VERSION, MAX_ARCHIVE_FILES, MAX_ARCHIVE_UNCOMPRESSED_BYTES
from .errors import FullUpdateError, PackageError
from .jsonio import atomic_write_json, read_json
from .models import FullReleaseManifest, ReleaseInfo
from .paths import RuntimePaths

_PROTECTED_ROOTS = {"data", "cache", ".update-staging", ".update-backup"}


@dataclass
class FullUpdateTransaction:
    transaction_id: str
    version: str
    stage: str
    staging_path: str
    backup_path: str
    files: list[str]
    completed: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_dict(cls, value: dict) -> "FullUpdateTransaction":
        if value.get("schema_version") != FULL_UPDATE_SCHEMA_VERSION:
            raise FullUpdateError("unsupported full update transaction schema")
        required = ("transaction_id", "version", "stage", "staging_path", "backup_path", "files")
        if any(not isinstance(value.get(key), str) for key in required[:-1]) or not isinstance(value.get("files"), list):
            raise FullUpdateError("full update transaction is invalid")
        files = value["files"]
        completed = value.get("completed", [])
        if not all(isinstance(item, str) for item in files + completed):
            raise FullUpdateError("full update transaction contains invalid paths")
        error = value.get("error")
        if error is not None and not isinstance(error, str):
            raise FullUpdateError("full update transaction contains an invalid error")
        return cls(value["transaction_id"], value["version"], value["stage"], value["staging_path"], value["backup_path"], files, completed, error)

    def to_dict(self) -> dict:
        return {"schema_version": FULL_UPDATE_SCHEMA_VERSION, "transaction_id": self.transaction_id, "version": self.version, "stage": self.stage, "staging_path": self.staging_path, "backup_path": self.backup_path, "files": self.files, "completed": self.completed, "error": self.error}


class FullUpdateManager:
    """Prepares and applies a manifest-owned full release without touching user state."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    @property
    def transaction_path(self) -> Path:
        return self.paths.update_data_dir / "transaction.json"

    @property
    def lock_path(self) -> Path:
        return self.paths.update_data_dir / "full-update.lock"

    def load(self) -> FullUpdateTransaction | None:
        if not self.transaction_path.exists():
            return None
        return FullUpdateTransaction.from_dict(read_json(self.transaction_path))

    def prepare(self, archive: Path, release: ReleaseInfo) -> FullUpdateTransaction:
        if release.installer_version > FULL_UPDATE_HELPER_VERSION:
            raise FullUpdateError("full update requires a newer update helper")
        existing = self.load()
        if existing is not None and existing.stage not in {"confirmed", "rolled_back"}:
            raise FullUpdateError("another full update transaction is already pending")
        transaction_id = uuid.uuid4().hex
        staging = self.paths.full_update_staging_dir / transaction_id
        backup = self.paths.full_update_backup_dir / transaction_id
        self._acquire_lock(transaction_id)
        try:
            staging.mkdir(parents=True)
            self._safe_extract(archive, staging)
            manifest = self._read_manifest(staging, release.version)
            self._validate_staged_files(staging, manifest)
            self._check_disk_space(manifest)
            files = [entry.path for entry in manifest.files]
            transaction = FullUpdateTransaction(transaction_id, release.version, "prepared", str(staging), str(backup), files)
            self._save(transaction)
            return transaction
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            self.lock_path.unlink(missing_ok=True)
            raise

    def apply(self, transaction_id: str) -> FullUpdateTransaction:
        transaction = self._require(transaction_id)
        if transaction.stage == "swapped":
            return transaction
        if transaction.stage != "prepared":
            raise FullUpdateError(f"cannot apply full update in stage {transaction.stage}")
        staging, backup = Path(transaction.staging_path), Path(transaction.backup_path)
        try:
            for relative in transaction.files:
                target = self._owned_target(relative)
                source = staging.joinpath(*PurePosixPath(relative).parts)
                if not source.is_file():
                    raise FullUpdateError(f"staged release file is missing: {relative}")
                old = target
                old_backup = backup.joinpath(*PurePosixPath(relative).parts)
                if old.exists():
                    old_backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old, old_backup)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                transaction.completed.append(relative)
                self._save(transaction)
            transaction.stage = "swapped"
            self._save(transaction)
            return transaction
        except Exception as error:
            transaction.error = str(error)
            transaction.stage = "rollback_required"
            self._save(transaction)
            self.rollback(transaction_id)
            raise FullUpdateError(f"unable to apply full update: {error}") from error

    def confirm(self, transaction_id: str) -> None:
        transaction = self._require(transaction_id)
        if transaction.stage != "swapped":
            raise FullUpdateError("full update is not awaiting confirmation")
        transaction.stage = "confirmed"
        self._save(transaction)
        shutil.rmtree(transaction.staging_path, ignore_errors=True)
        self.lock_path.unlink(missing_ok=True)

    def rollback(self, transaction_id: str) -> FullUpdateTransaction:
        transaction = self._require(transaction_id)
        backup = Path(transaction.backup_path)
        for relative in reversed(transaction.completed):
            target = self._owned_target(relative)
            prior = backup.joinpath(*PurePosixPath(relative).parts)
            target.unlink(missing_ok=True)
            if prior.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(prior, target)
        transaction.stage = "rolled_back"
        self._save(transaction)
        self.lock_path.unlink(missing_ok=True)
        return transaction

    def recover_pending(self) -> FullUpdateTransaction | None:
        transaction = self.load()
        if transaction is not None and transaction.stage == "rollback_required":
            return self.rollback(transaction.transaction_id)
        return transaction

    def _require(self, transaction_id: str) -> FullUpdateTransaction:
        transaction = self.load()
        if transaction is None or transaction.transaction_id != transaction_id:
            raise FullUpdateError("full update transaction was not found")
        return transaction

    def _save(self, transaction: FullUpdateTransaction) -> None:
        atomic_write_json(self.transaction_path, transaction.to_dict())

    def _acquire_lock(self, transaction_id: str) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise FullUpdateError("another full update helper is active") from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(transaction_id)

    def _read_manifest(self, staging: Path, expected_version: str) -> FullReleaseManifest:
        try:
            manifest = FullReleaseManifest.from_dict(read_json(staging / "release-manifest.json"))
        except (OSError, ValueError, PackageError) as error:
            raise FullUpdateError(f"full release manifest is invalid: {error}") from error
        if manifest.version != expected_version:
            raise FullUpdateError("full release manifest version does not match the update release")
        for entry in manifest.files:
            self._owned_target(entry.path)
        return manifest

    def _validate_staged_files(self, staging: Path, manifest: FullReleaseManifest) -> None:
        for entry in manifest.files:
            path = staging.joinpath(*PurePosixPath(entry.path).parts)
            if not path.is_file() or path.stat().st_size != entry.size or self._sha256(path) != entry.sha256:
                raise FullUpdateError(f"full release file verification failed: {entry.path}")

    def _check_disk_space(self, manifest: FullReleaseManifest) -> None:
        required = sum(entry.size for entry in manifest.files)
        for entry in manifest.files:
            target = self._owned_target(entry.path)
            if target.is_file():
                required += target.stat().st_size
        if shutil.disk_usage(self.paths.root).free < required:
            raise FullUpdateError("insufficient disk space for full update staging and backup")

    def _owned_target(self, relative: str) -> Path:
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] in _PROTECTED_ROOTS or relative == "release-manifest.json":
            raise FullUpdateError(f"full update cannot manage path: {relative}")
        target = self.paths.root.joinpath(*parts).resolve()
        if self.paths.root.resolve() not in target.parents:
            raise FullUpdateError(f"full update path escapes installation root: {relative}")
        return target

    @staticmethod
    def _safe_extract(archive: Path, destination: Path) -> None:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if len(entries) > MAX_ARCHIVE_FILES or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise FullUpdateError("full update archive exceeds safety limits")
            for entry in entries:
                member = PurePosixPath(entry.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts or not member.parts or stat.S_ISLNK(entry.external_attr >> 16):
                    raise FullUpdateError(f"unsafe full update archive path: {entry.filename}")
                target = destination.joinpath(*member.parts)
                if destination.resolve() not in target.resolve().parents and target.resolve() != destination.resolve():
                    raise FullUpdateError(f"full update archive path escapes staging: {entry.filename}")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, 1024 * 256)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
