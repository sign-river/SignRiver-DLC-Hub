"""Crash-auditable, rollback-capable Stellaris DLC installer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from ...domain import (
    InstallAudit, InstallHealth, InstallPhase, InstallPlan, InstallReceipt, OwnedFile,
    game_relative_path, normalize_game_relative_directory, resolve_game_directory,
)
from ..catalog import inspect_stellaris_package

_DLC_DIRECTORY = re.compile(r"^dlc\d{3,}_[a-z0-9_]+$", re.I)


class InstallError(RuntimeError):
    pass


class StellarisInstallEngine:
    def __init__(
        self,
        data_root: Path,
        *,
        replace: Callable[[Path, Path], None] = os.replace,
        dlc_relative_dir: str = "dlc",
        executable_name: str = "stellaris.exe",
        game_id: str = "stellaris",
        package_inspector=inspect_stellaris_package,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self._replace = replace
        self.dlc_relative_dir = normalize_game_relative_directory(
            dlc_relative_dir, field_name="DLC install directory"
        )
        self._dlc_relative_path = game_relative_path(
            self.dlc_relative_dir, field_name="DLC install directory"
        )
        self.executable_name = normalize_game_relative_directory(
            executable_name, field_name="game executable path"
        )
        if self.executable_name == ".":
            raise ValueError("game executable path must name a file")
        self._executable_relative_path = game_relative_path(
            self.executable_name, field_name="game executable path"
        )
        self.game_id = game_id
        self.package_inspector = package_inspector

    def plan(
        self,
        package_path: Path,
        game_root: Path,
        *,
        expected_sha256: str,
        transaction_id: str | None = None,
    ) -> InstallPlan:
        package_path = Path(package_path).resolve(strict=True)
        game_root = Path(game_root).resolve(strict=True)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("a valid expected SHA-256 is required")
        actual = self._sha256(package_path)
        if actual.casefold() != expected_sha256.casefold():
            raise InstallError("package SHA-256 changed before installation")
        metadata = self.package_inspector(package_path)
        dlc_root = self._dlc_root(game_root)
        if not (game_root / self._executable_relative_path).is_file() or not dlc_root.is_dir():
            raise InstallError("目标目录不是当前卡带已验证的游戏安装目录")
        top_level = self._package_root(package_path)
        install_directory = getattr(metadata, "install_directory", None)
        if install_directory is not None:
            if top_level.casefold() != str(install_directory).casefold():
                raise InstallError("package install directory does not match its metadata")
        else:
            if not _DLC_DIRECTORY.fullmatch(top_level):
                raise InstallError("package DLC directory name is invalid")
            if not top_level.casefold().startswith(metadata.dlc_id.casefold() + "_"):
                raise InstallError("package directory and descriptor DLC ID do not match")
        transaction_id = transaction_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]+", transaction_id):
            raise ValueError("invalid transaction ID")
        transaction_root = self.data_root / "transactions" / transaction_id
        return InstallPlan(
            transaction_id=transaction_id,
            game_id=self.game_id,
            dlc_id=metadata.dlc_id,
            package_path=package_path,
            package_sha256=actual,
            game_root=game_root,
            relative_target=self._dlc_relative_path / top_level,
            staging_root=transaction_root / "staging",
            backup_root=self.data_root / "backups" / transaction_id,
            journal_path=transaction_root / "journal.json",
        )

    def install(self, plan: InstallPlan) -> InstallReceipt:
        target = self._contained(plan.game_root, plan.target_path)
        staged = plan.staging_root / plan.relative_target.name
        backup = plan.backup_root / plan.relative_target.name
        replaced_existing = target.exists()
        self._write_journal(plan, InstallPhase.PLANNED, replaced_existing)
        try:
            self._stage(plan, staged)
            self._write_journal(plan, InstallPhase.STAGED, replaced_existing)
            if replaced_existing:
                plan.backup_root.mkdir(parents=True, exist_ok=True)
                self._replace(target, backup)
                self._write_journal(plan, InstallPhase.BACKED_UP, True)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._replace(staged, target)
            self._write_journal(plan, InstallPhase.COMMITTED, replaced_existing)
        except Exception as error:
            self._rollback(plan, target, staged, backup, replaced_existing)
            if isinstance(error, InstallError):
                raise
            raise InstallError(f"installation failed and was rolled back: {error}") from error
        return InstallReceipt(
            transaction_id=plan.transaction_id,
            game_id=plan.game_id,
            dlc_id=plan.dlc_id,
            target_path=target,
            package_sha256=plan.package_sha256,
            replaced_existing=replaced_existing,
            backup_path=backup if replaced_existing else None,
            installed_tree_sha256=self._tree_sha256(target),
            owned_files=self._owned_files(target),
        )

    def verify(self, receipt: InstallReceipt, allowed_game_root: Path) -> bool:
        return self.assess(receipt, allowed_game_root) is InstallHealth.HEALTHY

    def assess(self, receipt: InstallReceipt, allowed_game_root: Path) -> InstallHealth:
        return self.audit(receipt, allowed_game_root).health

    def audit(self, receipt: InstallReceipt, allowed_game_root: Path) -> InstallAudit:
        target = self._trusted_receipt_target(receipt, allowed_game_root)
        if not target.is_dir():
            return InstallAudit(
                InstallHealth.MISSING,
                missing=tuple(item.relative_path for item in receipt.owned_files),
            )
        expected = {item.relative_path: item for item in receipt.owned_files}
        actual_paths = {
            path.relative_to(target).as_posix(): path
            for path in target.rglob("*") if path.is_file()
        }
        missing = tuple(sorted(set(expected) - set(actual_paths)))
        unknown = tuple(sorted(set(actual_paths) - set(expected)))
        modified = []
        for relative in sorted(set(expected) & set(actual_paths)):
            record = expected[relative]
            path = actual_paths[relative]
            if path.stat().st_size != record.size or self._sha256(path) != record.sha256:
                modified.append(relative)
        if not target.exists() or (missing and len(missing) == len(expected)):
            health = InstallHealth.MISSING
        elif missing or modified or unknown:
            health = InstallHealth.MODIFIED
        else:
            health = InstallHealth.HEALTHY
        return InstallAudit(health, missing, tuple(modified), unknown)

    def repair_missing(
        self,
        receipt: InstallReceipt,
        package_path: Path,
        allowed_game_root: Path,
    ) -> InstallAudit:
        """Restore only absent owned files; modified and unknown files are preserved."""
        target = self._trusted_receipt_target(receipt, allowed_game_root)
        package_path = Path(package_path).resolve(strict=True)
        if self._sha256(package_path) != receipt.package_sha256:
            raise InstallError("repair package SHA-256 does not match install receipt")
        before = self.audit(receipt, allowed_game_root)
        if not before.missing:
            return before
        target.mkdir(parents=True, exist_ok=True)
        root_name = target.name
        wanted = set(before.missing)
        restored = set()
        with zipfile.ZipFile(package_path) as archive:
            for info in archive.infolist():
                member = PurePosixPath(info.filename.replace("\\", "/"))
                if info.is_dir() or len(member.parts) < 2:
                    continue
                if member.parts[0].casefold() != root_name.casefold():
                    continue
                relative = PurePosixPath(*member.parts[1:]).as_posix()
                if relative not in wanted:
                    continue
                destination = target.joinpath(*member.parts[1:])
                self._contained(target, destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".repair.tmp")
                with archive.open(info) as source, temporary.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, destination)
                restored.add(relative)
        if restored != wanted:
            raise InstallError("repair package is missing files recorded by the receipt")
        return self.audit(receipt, allowed_game_root)

    def uninstall(self, receipt: InstallReceipt, allowed_game_root: Path) -> None:
        """Remove exactly the recorded tree, restoring a displaced predecessor."""
        target = self._trusted_receipt_target(receipt, allowed_game_root)
        if not target.is_dir():
            raise InstallError("installed DLC directory is missing")
        if self._tree_sha256(target) != receipt.installed_tree_sha256:
            raise InstallError("installed DLC files were modified; refusing unsafe uninstall")
        transaction_root = self.data_root / "transactions" / f"uninstall-{receipt.transaction_id}"
        removed = transaction_root / "removed" / target.name
        journal = transaction_root / "journal.json"
        transaction_root.mkdir(parents=True, exist_ok=True)
        self._write_simple_journal(journal, "removing", receipt)
        try:
            removed.parent.mkdir(parents=True, exist_ok=True)
            self._replace(target, removed)
            if receipt.backup_path is not None and receipt.backup_path.exists():
                self._contained(self.data_root / "backups", receipt.backup_path)
                self._replace(receipt.backup_path, target)
            self._write_simple_journal(journal, "committed", receipt)
            if removed.exists():
                shutil.rmtree(removed)
        except Exception as error:
            try:
                if not target.exists() and removed.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._replace(removed, target)
                self._write_simple_journal(journal, "rolled_back", receipt)
            except Exception as rollback_error:
                raise InstallError(f"uninstall rollback failed: {rollback_error}") from rollback_error
            raise InstallError(f"uninstall failed and was rolled back: {error}") from error

    def uninstall_committed(self, receipt: InstallReceipt) -> bool:
        journal = (
            self.data_root / "transactions" /
            f"uninstall-{receipt.transaction_id}" / "journal.json"
        )
        try:
            payload = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return (
            payload.get("operation") == "uninstall"
            and payload.get("transaction_id") == receipt.transaction_id
            and payload.get("phase") == "committed"
        )

    def recover_incomplete(self, allowed_game_roots) -> tuple[str, ...]:
        """Roll back interrupted transactions for explicitly trusted game roots."""
        allowed = {
            Path(root).resolve(strict=True) for root in allowed_game_roots
        }
        transactions = self.data_root / "transactions"
        if not transactions.is_dir():
            return ()
        recovered = []
        for journal_path in transactions.glob("*/journal.json"):
            try:
                if journal_path.stat().st_size > 256 * 1024:
                    raise InstallError("install journal is too large")
                payload = json.loads(journal_path.read_text(encoding="utf-8"))
                phase = InstallPhase(payload["phase"])
                if phase in {InstallPhase.COMMITTED, InstallPhase.ROLLED_BACK}:
                    continue
                transaction_id = str(payload["transaction_id"])
                if journal_path.parent.name != transaction_id or not re.fullmatch(
                    r"[A-Za-z0-9_-]+", transaction_id
                ):
                    raise InstallError("install journal transaction ID is invalid")
                game_root = Path(payload["game_root"]).resolve(strict=True)
                if game_root not in allowed:
                    continue
                relative_target = Path(payload["target"])
                if relative_target.is_absolute() or ".." in relative_target.parts:
                    raise InstallError("install journal target is unsafe")
                plan = InstallPlan(
                    transaction_id=transaction_id,
                    game_id=str(payload["game_id"]),
                    dlc_id=str(payload["dlc_id"]),
                    package_path=Path(payload["package_path"]),
                    package_sha256=str(payload["package_sha256"]),
                    game_root=game_root,
                    relative_target=relative_target,
                    staging_root=journal_path.parent / "staging",
                    backup_root=self.data_root / "backups" / transaction_id,
                    journal_path=journal_path,
                )
                target = self._contained(game_root, plan.target_path)
                staged = plan.staging_root / relative_target.name
                backup = plan.backup_root / relative_target.name
                replaced = bool(payload["replaced_existing"])
                self._rollback(plan, target, staged, backup, replaced)
                recovered.append(transaction_id)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise InstallError(f"invalid install journal {journal_path}: {error}") from error
        return tuple(recovered)

    def _stage(self, plan: InstallPlan, staged: Path) -> None:
        if plan.staging_root.exists():
            shutil.rmtree(plan.staging_root)
        plan.staging_root.mkdir(parents=True)
        root_name = plan.relative_target.name.casefold()
        with zipfile.ZipFile(plan.package_path) as archive:
            for info in archive.infolist():
                member = PurePosixPath(info.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts or not member.parts:
                    raise InstallError(f"unsafe package member: {info.filename}")
                mode = info.external_attr >> 16
                if mode and stat.S_ISLNK(mode):
                    raise InstallError("package symbolic links are not allowed")
                if member.parts[0].casefold() != root_name:
                    raise InstallError("package contains files outside its DLC directory")
                destination = plan.staging_root.joinpath(*member.parts)
                self._contained(plan.staging_root, destination)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
        if not staged.is_dir():
            raise InstallError("staging did not produce the expected DLC directory")

    def _rollback(self, plan, target, staged, backup, replaced_existing) -> None:
        try:
            if target.exists():
                shutil.rmtree(target)
            if replaced_existing and backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                self._replace(backup, target)
            if staged.exists():
                shutil.rmtree(staged)
            self._write_journal(plan, InstallPhase.ROLLED_BACK, replaced_existing)
        except Exception as rollback_error:
            raise InstallError(f"installation rollback failed: {rollback_error}") from rollback_error

    def _write_journal(self, plan, phase, replaced_existing) -> None:
        plan.journal_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "transaction_id": plan.transaction_id,
            "game_id": plan.game_id,
            "dlc_id": plan.dlc_id,
            "phase": phase.value,
            "package_sha256": plan.package_sha256,
            "package_path": str(plan.package_path),
            "game_root": str(plan.game_root),
            "target": plan.relative_target.as_posix(),
            "replaced_existing": replaced_existing,
        }
        temporary = plan.journal_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, plan.journal_path)

    @staticmethod
    def _write_simple_journal(path: Path, phase: str, receipt: InstallReceipt) -> None:
        payload = {
            "schema_version": 1,
            "operation": "uninstall",
            "phase": phase,
            "transaction_id": receipt.transaction_id,
            "dlc_id": receipt.dlc_id,
            "target_path": str(receipt.target_path),
            "installed_tree_sha256": receipt.installed_tree_sha256,
        }
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _trusted_receipt_target(self, receipt, allowed_game_root) -> Path:
        game_root = Path(allowed_game_root).resolve(strict=True)
        dlc_root = self._dlc_root(game_root)
        target = self._contained(dlc_root, receipt.target_path)
        if target.parent != dlc_root:
            raise InstallError("receipt target is not a direct configured DLC directory")
        return target

    def _dlc_root(self, game_root: Path) -> Path:
        try:
            return resolve_game_directory(
                game_root, self.dlc_relative_dir,
                field_name="DLC install directory",
            )
        except ValueError as error:
            raise InstallError(str(error)) from error

    @staticmethod
    def _contained(root: Path, candidate: Path) -> Path:
        root = root.resolve(strict=False)
        candidate = candidate.resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise InstallError("installation path escaped its allowed root") from error
        return candidate

    @staticmethod
    def _package_root(path: Path) -> str:
        with zipfile.ZipFile(path) as archive:
            roots = {
                PurePosixPath(item.filename.replace("\\", "/")).parts[0]
                for item in archive.infolist() if item.filename
            }
        if len(roots) != 1:
            raise InstallError("package must contain exactly one top-level directory")
        return next(iter(roots))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _tree_sha256(root: Path) -> str:
        digest = hashlib.sha256()
        files = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix().casefold(),
        )
        for path in files:
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        return digest.hexdigest()

    @classmethod
    def _owned_files(cls, root: Path) -> tuple[OwnedFile, ...]:
        records = []
        for path in sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root).as_posix().casefold(),
        ):
            records.append(OwnedFile(
                relative_path=path.relative_to(root).as_posix(),
                size=path.stat().st_size,
                sha256=cls._sha256(path),
            ))
        return tuple(records)
