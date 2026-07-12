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

from ...domain import InstallPhase, InstallPlan, InstallReceipt
from ..catalog import inspect_stellaris_package

_DLC_DIRECTORY = re.compile(r"^dlc\d{3}_[a-z0-9_]+$", re.I)


class InstallError(RuntimeError):
    pass


class StellarisInstallEngine:
    def __init__(
        self,
        data_root: Path,
        *,
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self._replace = replace

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
        metadata = inspect_stellaris_package(package_path)
        if not (game_root / "stellaris.exe").is_file() or not (game_root / "dlc").is_dir():
            raise InstallError("target is not a validated Stellaris installation")
        top_level = self._package_root(package_path)
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
            game_id="stellaris",
            dlc_id=metadata.dlc_id,
            package_path=package_path,
            package_sha256=actual,
            game_root=game_root,
            relative_target=Path("dlc") / top_level,
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
