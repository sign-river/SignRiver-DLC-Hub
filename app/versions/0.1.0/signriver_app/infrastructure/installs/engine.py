"""Crash-auditable, rollback-capable Stellaris DLC installer."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import time
import uuid
import zipfile
from errno import EACCES, EPERM, EXDEV
from pathlib import Path, PurePosixPath
from typing import Callable

from ...domain import (
    DiskSpaceRequirement,
    InstallAudit,
    InstallHealth,
    InstallMaintenanceEntry,
    InstallMaintenancePreview,
    InstallMaintenanceResult,
    InstallPhase,
    InstallPlan,
    InstallReceipt,
    InstallSpaceEstimate,
    OwnedFile,
    game_relative_path, normalize_game_relative_directory, resolve_game_directory,
)
from ..catalog import inspect_stellaris_package

_DLC_DIRECTORY = re.compile(r"^dlc\d{3,}_[a-z0-9_]+$", re.I)
LOGGER = logging.getLogger(__name__)


class InstallError(RuntimeError):
    pass


class InstallAccessError(InstallError):
    """The game destination could not be changed safely."""


class InstallConflictError(InstallError):
    """The destination changed while an installation was in progress."""


class InstallSpaceError(InstallError):
    """Installation cannot start without risking an out-of-space rollback."""


class InstallRecoveryConflict(InstallError):
    """An interrupted transaction cannot be changed without risking user data."""


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
        sleep: Callable[[float], None] = time.sleep,
        replace_retry_delays: tuple[float, ...] = (0.15, 0.4, 0.8),
        disk_usage: Callable[[Path], object] = shutil.disk_usage,
        space_margin_bytes: int = 64 * 1024 * 1024,
        volume_key: Callable[[Path], object] | None = None,
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
        self._sleep = sleep
        self._replace_retry_delays = tuple(replace_retry_delays)
        self._disk_usage = disk_usage
        if space_margin_bytes < 0:
            raise ValueError("space margin cannot be negative")
        self._space_margin_bytes = int(space_margin_bytes)
        self._volume_key_override = volume_key
        self._last_recovery_warnings: tuple[str, ...] = ()

    @property
    def last_recovery_warnings(self) -> tuple[str, ...]:
        """Diagnostics for journals retained during the latest recovery pass."""
        return self._last_recovery_warnings

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
        metadata = self.package_inspector(
            package_path, known_sha256=actual
        )
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

    def install(
        self,
        plan: InstallPlan,
        *,
        previous_transaction_id: str | None = None,
    ) -> InstallReceipt:
        target = self._contained(plan.game_root, plan.target_path)
        staged = plan.staging_root / plan.relative_target.name
        backup = plan.backup_root / plan.relative_target.name
        replaced_existing = self._inspect_target(target)
        self.ensure_disk_space(plan, replaced_existing=replaced_existing)
        backup_created = False
        destructive_backup_started = False
        committed = False
        self._write_journal(plan, InstallPhase.PLANNED, replaced_existing)
        try:
            self._stage(plan, staged)
            self._write_journal(plan, InstallPhase.STAGED, replaced_existing)
            if replaced_existing:
                plan.backup_root.mkdir(parents=True, exist_ok=True)
                try:
                    self._replace_with_retry(target, backup)
                    backup_created = True
                except OSError as error:
                    if not self._is_cross_device(error):
                        raise self._destination_error(
                            error, target, "备份已有 DLC"
                        ) from error
                    self._copy_tree_atomic(target, backup)
                    backup_created = True
                    self._write_journal(
                        plan, InstallPhase.BACKUP_COPIED, True
                    )
                    destructive_backup_started = True
                    self._remove_tree(target)
                self._write_journal(plan, InstallPhase.BACKED_UP, True)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._write_journal(
                plan, InstallPhase.COMMITTING, replaced_existing
            )
            self._commit_staged(plan, staged, target)
            committed = True
            installed_tree_sha256, owned_files = self._installed_snapshot(target)
            receipt = InstallReceipt(
                transaction_id=plan.transaction_id,
                game_id=plan.game_id,
                dlc_id=plan.dlc_id,
                target_path=target,
                package_sha256=plan.package_sha256,
                replaced_existing=replaced_existing,
                backup_path=backup if replaced_existing else None,
                installed_tree_sha256=installed_tree_sha256,
                owned_files=owned_files,
                previous_transaction_id=previous_transaction_id,
            )
            self._write_journal(
                plan,
                InstallPhase.COMMITTED,
                replaced_existing,
                receipt=receipt,
            )
        except Exception as error:
            backup_created = backup_created or self._completed_backup_exists(
                plan, target, backup
            )
            self._rollback(
                plan,
                target,
                staged,
                backup,
                replaced_existing,
                backup_created=backup_created,
                remove_target=committed or destructive_backup_started,
            )
            if isinstance(error, InstallError):
                raise
            raise InstallError(f"installation failed and was rolled back: {error}") from error
        return receipt

    def estimate_disk_space(
        self,
        plan: InstallPlan,
        *,
        replaced_existing: bool | None = None,
    ) -> InstallSpaceEstimate:
        """Return a conservative, per-filesystem install space estimate.

        The estimate reserves room for extraction in the transaction area and
        for the verified destination-side temporary copy used when a direct
        rename is rejected.  When data and game directories are on different
        filesystems, it also reserves a full copy of the displaced target in
        the backup area.
        """
        target = self._contained(plan.game_root, plan.target_path)
        if replaced_existing is None:
            replaced_existing = self._inspect_target(target)
        expanded = self._expanded_package_size(plan.package_path)
        existing = self._tree_size(target) if replaced_existing else 0

        data_probe = self._existing_ancestor(plan.staging_root)
        target_probe = self._existing_ancestor(target.parent)
        data_volume = self._volume_key(data_probe)
        target_volume = self._volume_key(target_probe)
        requirements: dict[object, dict[str, object]] = {}

        def reserve(
            volume: object, probe: Path, amount: int, purpose: str
        ) -> None:
            bucket = requirements.setdefault(
                volume,
                {"probe": probe, "bytes": 0, "purposes": []},
            )
            bucket["bytes"] = int(bucket["bytes"]) + max(0, int(amount))
            cast_purposes = bucket["purposes"]
            assert isinstance(cast_purposes, list)
            cast_purposes.append(purpose)

        reserve(data_volume, data_probe, expanded, "解压暂存")
        reserve(target_volume, target_probe, expanded, "目标侧安全提交副本")
        if replaced_existing and data_volume != target_volume:
            reserve(data_volume, data_probe, existing, "已有 DLC 回滚备份")

        results = []
        for bucket in requirements.values():
            probe = Path(bucket["probe"])
            required = int(bucket["bytes"]) + self._space_margin_bytes
            try:
                usage = self._disk_usage(probe)
                available = int(getattr(usage, "free"))
            except (OSError, TypeError, ValueError, AttributeError) as error:
                raise InstallError(
                    f"无法检查安装磁盘的可用空间：{probe}（{error}）"
                ) from error
            results.append(DiskSpaceRequirement(
                probe_path=probe,
                required_bytes=required,
                available_bytes=available,
                purposes=tuple(str(item) for item in bucket["purposes"]),
            ))
        return InstallSpaceEstimate(
            expanded_package_bytes=expanded,
            existing_target_bytes=existing,
            requirements=tuple(results),
        )

    def ensure_disk_space(
        self,
        plan: InstallPlan,
        *,
        replaced_existing: bool | None = None,
    ) -> InstallSpaceEstimate:
        estimate = self.estimate_disk_space(
            plan, replaced_existing=replaced_existing
        )
        insufficient = tuple(
            item for item in estimate.requirements if not item.sufficient
        )
        if insufficient:
            details = "; ".join(
                f"{item.probe_path} 需要约 {self._format_bytes(item.required_bytes)}，"
                f"可用 {self._format_bytes(item.available_bytes)}"
                for item in insufficient
            )
            raise InstallSpaceError(
                "安装前磁盘空间检查未通过：" + details +
                "。尚未改动游戏文件，请清理空间后重试。"
            )
        return estimate

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
        # Keep the displaced tree beside the target.  The first rename is then
        # same-volume and atomic even when the application data lives on a
        # different drive from the game library.
        removed = self._uninstall_removed_path(target, receipt.transaction_id)
        if self._path_present(removed):
            raise InstallConflictError(
                f"uninstall temporary directory already exists: {removed}"
            )
        journal = transaction_root / "journal.json"
        backup = receipt.backup_path
        if backup is not None:
            backup = self._contained(self.data_root / "backups", backup)
        transaction_root.mkdir(parents=True, exist_ok=True)
        self._write_simple_journal(
            journal, "removing", receipt,
            removed_path=removed, backup_path=backup,
        )
        backup_was_copied = False
        try:
            self._replace_with_retry(target, removed)
            self._write_simple_journal(
                journal, "removed", receipt,
                removed_path=removed, backup_path=backup,
            )
            if backup is not None and self._path_present(backup):
                if self._is_link(backup) or not backup.is_dir():
                    raise InstallConflictError(
                        "uninstall predecessor backup is not a trusted directory"
                    )
                self._write_simple_journal(
                    journal, "restoring_predecessor", receipt,
                    removed_path=removed, backup_path=backup,
                )
                backup_was_copied = self._restore_uninstall_backup(
                    backup, target
                )
            self._write_simple_journal(
                journal, "committed", receipt,
                removed_path=removed, backup_path=backup,
            )
        except Exception as error:
            try:
                self._rollback_uninstall_files(
                    target=target,
                    removed=removed,
                    backup=backup,
                    installed_tree_sha256=receipt.installed_tree_sha256,
                )
                self._write_simple_journal(
                    journal, "rolled_back", receipt,
                    removed_path=removed, backup_path=backup,
                )
            except Exception as rollback_error:
                raise InstallError(f"uninstall rollback failed: {rollback_error}") from rollback_error
            raise InstallError(f"uninstall failed and was rolled back: {error}") from error

        # The committed journal is authoritative.  Cleanup must never turn a
        # successful uninstall into a reported rollback or prevent database
        # reconciliation; startup and maintenance can retry leftovers.
        self._cleanup_uninstall_tree_best_effort(removed)
        if backup_was_copied and backup is not None:
            self._cleanup_uninstall_tree_best_effort(backup)

    def uninstall_committed(self, receipt: InstallReceipt) -> bool:
        journal = (
            self.data_root / "transactions" /
            f"uninstall-{receipt.transaction_id}" / "journal.json"
        )
        try:
            payload = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        committed = (
            payload.get("operation") == "uninstall"
            and payload.get("transaction_id") == receipt.transaction_id
            and payload.get("phase") == "committed"
        )
        if committed:
            expected = self._uninstall_removed_path(
                receipt.target_path, receipt.transaction_id
            )
            try:
                recorded = payload.get("removed_path")
                if recorded is not None and Path(recorded).resolve(strict=False) == expected:
                    self._cleanup_uninstall_tree_best_effort(expected)
            except (OSError, TypeError, ValueError):
                pass
        return committed

    def pending_committed_receipts(
        self, allowed_game_roots
    ) -> tuple[InstallReceipt, ...]:
        """Rebuild receipts for installs committed before database persistence.

        Only schema-v2 committed journals under an explicitly trusted game root
        are considered.  The installed tree must still match the durable tree
        digest written at commit time; otherwise no database state is guessed.
        """
        allowed = tuple(
            Path(root).resolve(strict=True) for root in allowed_game_roots
        )
        transactions = self.data_root / "transactions"
        if not transactions.is_dir():
            return ()
        receipts = []
        conflicts = []
        for journal_path in sorted(
            transactions.glob("*/journal.json"),
            key=lambda item: item.parent.name.casefold(),
        ):
            try:
                receipt = self._pending_receipt_from_journal(
                    journal_path, allowed
                )
                if receipt is not None:
                    receipts.append(receipt)
            except InstallRecoveryConflict as error:
                conflicts.append(f"{journal_path.parent.name}: {error}")
            except (OSError, InstallError, ValueError, KeyError, TypeError,
                    UnicodeError, json.JSONDecodeError):
                # Invalid/unrelated journals are already reported by the main
                # recovery pass and remain untouched for diagnostics.
                continue
        if conflicts:
            raise InstallRecoveryConflict(
                "存在无法安全补记的已完成安装：" + "；".join(conflicts)
            )
        return tuple(receipts)

    def mark_receipt_persisted(self, transaction_id: str) -> None:
        self._update_committed_install_journal(
            transaction_id, receipt_persisted=True
        )

    def mark_install_compensated(self, transaction_id: str) -> None:
        self._update_committed_install_journal(
            transaction_id,
            phase=InstallPhase.ROLLED_BACK.value,
            receipt_persisted=False,
        )

    def _pending_receipt_from_journal(
        self, journal_path: Path, allowed_game_roots: tuple[Path, ...]
    ) -> InstallReceipt | None:
        transactions = (self.data_root / "transactions").resolve(strict=True)
        transaction_root = journal_path.parent.resolve(strict=True)
        if (
            transaction_root.parent != transactions
            or self._is_link(transaction_root)
            or self._is_link(journal_path)
            or not journal_path.is_file()
        ):
            raise InstallError("committed install journal is not trusted")
        if journal_path.stat().st_size > 256 * 1024:
            raise InstallError("committed install journal is too large")
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise InstallError("committed install journal root must be an object")
        if (
            payload.get("schema_version") != 2
            or payload.get("operation") != "install"
            or payload.get("phase") != InstallPhase.COMMITTED.value
            or payload.get("receipt_persisted") is True
        ):
            return None
        transaction_id = str(payload["transaction_id"])
        if (
            transaction_root.name != transaction_id
            or not re.fullmatch(r"[A-Za-z0-9_-]+", transaction_id)
        ):
            raise InstallError("committed install transaction ID is invalid")
        try:
            game_root = Path(payload["game_root"]).resolve(strict=True)
        except (OSError, TypeError, ValueError) as error:
            raise InstallError("committed install game root is unavailable") from error
        if game_root not in allowed_game_roots:
            return None
        if str(payload["game_id"]) != self.game_id:
            raise InstallRecoveryConflict("已完成安装的游戏编号与当前卡带不匹配")
        relative_target = Path(payload["target"])
        if (
            relative_target.is_absolute()
            or ".." in relative_target.parts
            or relative_target.parent != self._dlc_relative_path
            or not relative_target.name
        ):
            raise InstallRecoveryConflict("已完成安装的目标不在卡带 DLC 目录内")
        target = self._contained(game_root, game_root / relative_target)
        dlc_root = self._dlc_root(game_root)
        if target.parent != dlc_root:
            raise InstallRecoveryConflict("已完成安装的目标越过 DLC 根目录")
        if not target.is_dir() or self._is_link(target):
            raise InstallRecoveryConflict("已完成安装的目标已缺失或不是普通目录")
        replaced = payload["replaced_existing"]
        if not isinstance(replaced, bool):
            raise InstallRecoveryConflict("已完成安装的替换状态无效")
        receipt_payload = payload.get("receipt")
        if not isinstance(receipt_payload, dict):
            raise InstallRecoveryConflict("已完成安装缺少可恢复的记录摘要")
        expected_tree = str(receipt_payload["installed_tree_sha256"])
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_tree):
            raise InstallRecoveryConflict("已完成安装的目录摘要无效")
        actual_tree, owned_files = self._installed_snapshot(target)
        if actual_tree.casefold() != expected_tree.casefold():
            raise InstallRecoveryConflict(
                "已完成安装的文件在记录落库前发生变化，未自动补记"
            )
        previous = receipt_payload.get("previous_transaction_id")
        if previous is not None:
            previous = str(previous)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", previous):
                raise InstallRecoveryConflict("前一版本安装记录编号无效")
        package_sha256 = str(payload["package_sha256"])
        if not re.fullmatch(r"[0-9a-fA-F]{64}", package_sha256):
            raise InstallRecoveryConflict("资源包摘要无效")
        backup = self.data_root / "backups" / transaction_id / target.name
        backup_present = self._path_present(backup)
        if backup_present and (
            self._is_link(backup) or not backup.is_dir()
        ):
            raise InstallRecoveryConflict("已完成安装的回滚备份不可信")
        if replaced and not backup_present:
            raise InstallRecoveryConflict("已完成安装缺少恢复前一版本所需的备份")
        return InstallReceipt(
            transaction_id=transaction_id,
            game_id=self.game_id,
            dlc_id=str(payload["dlc_id"]),
            target_path=target,
            package_sha256=package_sha256,
            replaced_existing=replaced,
            backup_path=backup if replaced else None,
            installed_tree_sha256=actual_tree,
            owned_files=owned_files,
            previous_transaction_id=previous,
        )

    def _update_committed_install_journal(
        self,
        transaction_id: str,
        *,
        phase: str | None = None,
        receipt_persisted: bool,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", transaction_id):
            raise InstallError("install transaction ID is invalid")
        journal = self.data_root / "transactions" / transaction_id / "journal.json"
        payload = self._read_maintenance_journal(journal)
        if (
            payload.get("schema_version") != 2
            or payload.get("operation") != "install"
            or payload.get("transaction_id") != transaction_id
            or payload.get("phase") != InstallPhase.COMMITTED.value
        ):
            raise InstallError("committed install journal no longer matches")
        if phase is not None:
            payload["phase"] = phase
        payload["receipt_persisted"] = bool(receipt_persisted)
        self._write_json_atomic(journal, payload)

    def recover_incomplete(self, allowed_game_roots) -> tuple[str, ...]:
        """Recover interrupted transactions under explicitly trusted roots.

        Journals are isolated from one another: unrelated malformed history is
        retained and logged, while a conflict that can be tied to one of the
        trusted game roots fails closed.  Recovery never deletes an existing
        target directory unless ownership can be proven by the live install
        operation; ambiguous startup state is preserved for manual review.
        """
        allowed = tuple(
            Path(root).resolve(strict=True) for root in allowed_game_roots
        )
        transactions = self.data_root / "transactions"
        if not transactions.is_dir():
            self._last_recovery_warnings = ()
            return ()
        recovered = []
        conflicts = []
        warnings = []
        for journal_path in sorted(
            transactions.glob("*/journal.json"),
            key=lambda item: item.parent.name.casefold(),
        ):
            try:
                transaction_id = self._recover_journal(journal_path, allowed)
                if transaction_id is not None:
                    recovered.append(transaction_id)
            except InstallRecoveryConflict as error:
                conflicts.append(f"{journal_path.parent.name}: {error}")
            except (OSError, InstallError, ValueError, KeyError, TypeError,
                    UnicodeError, json.JSONDecodeError) as error:
                # A damaged journal that cannot be associated with an allowed
                # root must not prevent recovery of every other game.  It is
                # retained so diagnostics and maintenance can report it.
                LOGGER.warning(
                    "Ignoring untrusted or invalid install journal %s: %s",
                    journal_path, error,
                )
                warnings.append(f"{journal_path.parent.name}: {error}")
        self._last_recovery_warnings = tuple(warnings)
        if conflicts:
            raise InstallRecoveryConflict(
                "存在无法安全自动恢复的安装事务：" + "；".join(conflicts)
            )
        return tuple(recovered)

    def _recover_journal(
        self, journal_path: Path, allowed_game_roots: tuple[Path, ...]
    ) -> str | None:
        transactions = (self.data_root / "transactions").resolve(strict=True)
        transaction_root = journal_path.parent.resolve(strict=True)
        if transaction_root.parent != transactions:
            raise InstallError("transaction directory escaped its storage root")
        if (
            self._is_link(transaction_root)
            or self._is_link(journal_path)
            or not journal_path.is_file()
        ):
            raise InstallError("transaction journal cannot be a link or junction")
        if journal_path.stat().st_size > 256 * 1024:
            raise InstallError("install journal is too large")
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise InstallError("install journal root must be an object")
        schema_version = payload.get("schema_version")
        if schema_version not in {1, 2}:
            raise InstallError("unsupported install journal schema")
        operation = payload.get("operation", "install")
        if operation == "uninstall":
            return self._recover_uninstall_journal(
                journal_path, payload, allowed_game_roots
            )
        if operation != "install":
            raise InstallError("unsupported transaction operation")

        phase = InstallPhase(payload["phase"])
        if phase in {InstallPhase.COMMITTED, InstallPhase.ROLLED_BACK}:
            return None
        transaction_id = str(payload["transaction_id"])
        if transaction_root.name != transaction_id or not re.fullmatch(
            r"[A-Za-z0-9_-]+", transaction_id
        ):
            raise InstallError("install journal transaction ID is invalid")
        try:
            game_root = Path(payload["game_root"]).resolve(strict=True)
        except (OSError, TypeError, ValueError) as error:
            raise InstallError("install journal game root is unavailable") from error
        if game_root not in allowed_game_roots:
            return None

        try:
            if str(payload["game_id"]) != self.game_id:
                raise InstallRecoveryConflict("日志游戏编号与当前卡带不匹配")
            relative_target = Path(payload["target"])
            if (
                relative_target.is_absolute()
                or ".." in relative_target.parts
                or relative_target.parent != self._dlc_relative_path
                or not relative_target.name
            ):
                raise InstallRecoveryConflict(
                    "日志目标不是当前卡带 DLC 目录的直接子目录"
                )
            replaced = payload["replaced_existing"]
            if not isinstance(replaced, bool):
                raise InstallRecoveryConflict("日志替换状态无效")
            plan = InstallPlan(
                transaction_id=transaction_id,
                game_id=self.game_id,
                dlc_id=str(payload["dlc_id"]),
                package_path=Path(payload["package_path"]),
                package_sha256=str(payload["package_sha256"]),
                game_root=game_root,
                relative_target=relative_target,
                staging_root=transaction_root / "staging",
                backup_root=self.data_root / "backups" / transaction_id,
                journal_path=journal_path,
            )
            dlc_root = self._dlc_root(game_root)
            target = self._contained(dlc_root, plan.target_path)
            if target.parent != dlc_root:
                raise InstallRecoveryConflict("日志目标越过 DLC 根目录")
            staged = plan.staging_root / relative_target.name
            backup = plan.backup_root / relative_target.name
            for root in (plan.staging_root, plan.backup_root):
                if self._path_present(root) and self._is_link(root):
                    raise InstallRecoveryConflict("事务目录包含链接或目录联接")
            target_present = self._path_present(target)
            backup_present = self._path_present(backup)
            if target_present and self._is_link(target):
                raise InstallRecoveryConflict("目标 DLC 是链接或目录联接")
            if backup_present and (
                self._is_link(backup) or not backup.is_dir()
            ):
                raise InstallRecoveryConflict("回滚备份不是可信目录")

            if phase is InstallPhase.BACKUP_COPIED and target_present:
                if not backup_present or self._tree_sha256(target) != self._tree_sha256(backup):
                    raise InstallRecoveryConflict(
                        "目标与复制备份不一致，已全部保留"
                    )
                # The original target is still intact.  Make the rollback
                # durable first; maintenance removes the duplicate backup.
                self._write_journal(plan, InstallPhase.ROLLED_BACK, replaced)
                self._cleanup_staging_best_effort(staged)
                return transaction_id

            if target_present:
                if backup_present:
                    raise InstallRecoveryConflict(
                        "目标和回滚备份同时存在，无法证明目标归属，已全部保留"
                    )
                # A previous rollback may already have consumed the backup but
                # crashed before persisting ROLLED_BACK.  Never delete this
                # surviving target on a later startup.
                self._write_journal(plan, InstallPhase.ROLLED_BACK, replaced)
                self._cleanup_staging_best_effort(staged)
                return transaction_id

            if replaced and not backup_present:
                raise InstallRecoveryConflict(
                    "原 DLC 目标和可信回滚备份均缺失，不能自动继续"
                )
            backup_created = backup_present and replaced
            self._rollback(
                plan, target, staged, backup, replaced,
                backup_created=backup_created,
                remove_target=False,
            )
            return transaction_id
        except InstallRecoveryConflict:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise InstallRecoveryConflict(str(error)) from error

    def _recover_uninstall_journal(
        self, journal_path: Path, payload: dict,
        allowed_game_roots: tuple[Path, ...],
    ) -> str | None:
        transaction_id = str(payload["transaction_id"])
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]+", transaction_id)
            or journal_path.parent.name != f"uninstall-{transaction_id}"
        ):
            raise InstallError("uninstall journal transaction ID is invalid")
        target = Path(payload["target_path"]).resolve(strict=False)
        matched_root = None
        for game_root in allowed_game_roots:
            dlc_root = self._dlc_root(game_root)
            if target.parent == dlc_root:
                matched_root = game_root
                break
        if matched_root is None:
            return None
        phase = str(payload["phase"])
        if phase == "rolled_back":
            return None
        removed = self._uninstall_removed_from_journal(
            journal_path, payload, target, transaction_id
        )
        if phase == "committed":
            self._cleanup_uninstall_tree_best_effort(removed)
            return None
        if phase not in {"removing", "removed", "restoring_predecessor"}:
            raise InstallRecoveryConflict("卸载事务阶段无效")
        if self._path_present(target) and self._is_link(target):
            raise InstallRecoveryConflict("卸载目标是链接或目录联接")
        if self._path_present(removed) and (
            self._is_link(removed) or not removed.is_dir()
        ):
            raise InstallRecoveryConflict("卸载暂存目录无效")
        backup = self._uninstall_backup_from_journal(payload)
        self._rollback_uninstall_files(
            target=target,
            removed=removed,
            backup=backup,
            installed_tree_sha256=str(payload["installed_tree_sha256"]),
        )
        payload = dict(payload)
        payload["phase"] = "rolled_back"
        self._write_json_atomic(journal_path, payload)
        return transaction_id

    def _cleanup_staging_best_effort(self, staged: Path) -> None:
        if not self._path_present(staged):
            return
        try:
            self._remove_tree(staged)
        except OSError:
            pass

    def preview_maintenance(
        self,
        *,
        protected_transaction_ids=(),
        retired_transaction_ids=(),
        min_age_seconds: float = 24 * 60 * 60,
        now: float | None = None,
    ) -> InstallMaintenancePreview:
        """Find old transaction storage that can be removed without guessing.

        A committed transaction is removable only when its receipt is known to
        be retired.  Rolled-back transactions are removable without a receipt.
        Active receipt chains and unknown committed transactions are retained.
        No path lacking a small, valid terminal journal is ever proposed.
        """
        if min_age_seconds < 0:
            raise ValueError("maintenance age cannot be negative")
        protected = frozenset(str(item) for item in protected_transaction_ids)
        retired = frozenset(str(item) for item in retired_transaction_ids)
        current_time = time.time() if now is None else float(now)
        transactions = self.data_root / "transactions"
        backups = self.data_root / "backups"
        if not transactions.is_dir():
            return InstallMaintenancePreview()

        candidates: list[InstallMaintenanceEntry] = []
        retained: list[str] = []
        for transaction_root in sorted(
            transactions.iterdir(), key=lambda item: item.name.casefold()
        ):
            if not transaction_root.is_dir() or self._is_link(transaction_root):
                retained.append(f"{transaction_root.name}: 不是普通事务目录")
                continue
            journal = transaction_root / "journal.json"
            try:
                payload = self._read_maintenance_journal(journal)
                transaction_id, terminal, rolled_back = (
                    self._maintenance_journal_state(transaction_root, payload)
                )
            except (InstallError, OSError, ValueError, KeyError, TypeError) as error:
                retained.append(f"{transaction_root.name}: {error}")
                continue
            if not terminal:
                retained.append(f"{transaction_root.name}: 事务尚未结束")
                continue
            if transaction_id in protected:
                retained.append(f"{transaction_root.name}: 活动安装记录仍在引用")
                continue
            if not rolled_back and transaction_id not in retired:
                retained.append(f"{transaction_root.name}: 完成记录来源未知，保守保留")
                continue
            if current_time - journal.stat().st_mtime < min_age_seconds:
                retained.append(f"{transaction_root.name}: 尚未达到清理时间")
                continue
            if self._tree_has_link(transaction_root):
                retained.append(f"{transaction_root.name}: 包含链接或目录联接")
                continue

            reason = "已回滚的旧事务" if rolled_back else "已卸载记录的旧事务"
            candidates.append(InstallMaintenanceEntry(
                path=transaction_root.resolve(strict=True),
                transaction_id=transaction_id,
                kind="transaction",
                size_bytes=self._tree_size(transaction_root),
                reason=reason,
            ))

            backup_root = backups / transaction_id
            if (
                backup_root.is_dir()
                and not self._is_link(backup_root)
                and not self._tree_has_link(backup_root)
            ):
                candidates.append(InstallMaintenanceEntry(
                    path=backup_root.resolve(strict=True),
                    transaction_id=transaction_id,
                    kind="backup",
                    size_bytes=self._tree_size(backup_root),
                    reason="不再被活动安装链引用的回滚备份",
                ))
        unique_candidates = {
            item.path: item for item in candidates
        }
        return InstallMaintenancePreview(
            candidates=tuple(unique_candidates.values()),
            retained=tuple(retained),
        )

    def execute_maintenance(
        self,
        *,
        protected_transaction_ids=(),
        retired_transaction_ids=(),
        min_age_seconds: float = 24 * 60 * 60,
        now: float | None = None,
    ) -> InstallMaintenanceResult:
        """Re-scan and remove only candidates proven safe in this pass."""
        preview = self.preview_maintenance(
            protected_transaction_ids=protected_transaction_ids,
            retired_transaction_ids=retired_transaction_ids,
            min_age_seconds=min_age_seconds,
            now=now,
        )
        removed = []
        failed = []
        blocked_transactions: set[str] = set()
        candidates = sorted(
            preview.candidates,
            key=lambda item: 0 if item.kind == "backup" else 1,
        )
        for entry in candidates:
            if (
                entry.kind == "transaction"
                and entry.transaction_id in blocked_transactions
            ):
                failed.append((
                    entry,
                    "associated backup could not be removed; journal retained for retry",
                ))
                continue
            try:
                allowed_parent = (
                    self.data_root / "transactions"
                    if entry.kind == "transaction"
                    else self.data_root / "backups"
                ).resolve(strict=False)
                path = entry.path.resolve(strict=True)
                if path.parent != allowed_parent:
                    raise InstallError("maintenance path escaped its storage root")
                if self._is_link(path) or self._tree_has_link(path):
                    raise InstallError("maintenance path contains a link or junction")
                self._remove_tree(path)
                removed.append(entry)
            except (OSError, InstallError) as error:
                if entry.kind == "backup":
                    blocked_transactions.add(entry.transaction_id)
                failed.append((entry, str(error)))
        return InstallMaintenanceResult(
            preview=preview,
            removed=tuple(removed),
            failed=tuple(failed),
        )

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

    def _rollback(
        self,
        plan,
        target,
        staged,
        backup,
        replaced_existing,
        *,
        backup_created: bool,
        remove_target: bool,
    ) -> None:
        try:
            if remove_target and self._path_present(target):
                self._remove_tree(target)
            if backup_created and self._path_present(backup):
                if self._path_present(target):
                    raise InstallConflictError(
                        "回滚时目标 DLC 目录被其他程序重新创建；原目录已保存在备份中，"
                        "为避免误删未自动覆盖"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    self._replace_with_retry(backup, target)
                except OSError as error:
                    if not self._is_cross_device(error):
                        raise
                    self._copy_tree_atomic(backup, target)
                    self._remove_tree(backup)
            self._write_journal(plan, InstallPhase.ROLLED_BACK, replaced_existing)
            if self._path_present(staged):
                try:
                    self._remove_tree(staged)
                except OSError:
                    # The rollback is already durable and user data is safe.
                    # Terminal-transaction maintenance can retry this cleanup.
                    pass
        except Exception as rollback_error:
            raise InstallError(f"installation rollback failed: {rollback_error}") from rollback_error

    def _commit_staged(self, plan: InstallPlan, staged: Path, target: Path) -> None:
        try:
            self._replace_with_retry(staged, target)
            return
        except OSError as direct_error:
            # A rename can fail across volumes.  Windows security software can
            # also reject a move because the source directory carries a
            # different ACL.  Copying to a target-side temporary directory
            # gives the final rename destination-local ACLs and keeps the
            # visible commit atomic.
            if not (
                self._is_cross_device(direct_error)
                or self._is_access_error(direct_error)
            ):
                raise self._destination_error(
                    direct_error, target, "提交 DLC 目录"
                ) from direct_error
            if self._path_present(target):
                raise InstallConflictError(
                    f"安装过程中目标 DLC 目录被其他程序创建或占用：{target}；"
                    "为避免覆盖未知文件，本次安装已停止"
                ) from direct_error
            try:
                self._copy_tree_atomic(staged, target)
            except OSError as fallback_error:
                raise self._destination_error(
                    fallback_error, target, "写入 DLC 目录"
                ) from fallback_error
            except InstallError:
                raise
            try:
                self._remove_tree(staged)
            except OSError:
                # The target is already committed and verified next.  A stale
                # staging directory is safe and can be removed by maintenance.
                pass

    def _copy_tree_atomic(self, source: Path, destination: Path) -> None:
        """Copy a directory cross-volume, exposing it only at final rename."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".signriver-{uuid.uuid4().hex}.tmp"
        self._contained(destination.parent, temporary)
        try:
            shutil.copytree(source, temporary, copy_function=shutil.copy2)
            if self._tree_sha256(source) != self._tree_sha256(temporary):
                raise InstallError("复制到游戏目录的 DLC 文件校验不一致")
            if self._path_present(destination):
                raise InstallConflictError(
                    f"安装过程中目标目录被其他程序创建：{destination}"
                )
            self._replace_with_retry(temporary, destination)
        finally:
            if self._path_present(temporary):
                self._remove_tree(temporary)

    def _restore_uninstall_backup(
        self, backup: Path, target: Path
    ) -> bool:
        """Restore a predecessor and report whether its backup was copied."""
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._replace_with_retry(backup, target)
            return False
        except OSError as direct_error:
            if not (
                self._is_cross_device(direct_error)
                or self._is_access_error(direct_error)
            ):
                raise self._destination_error(
                    direct_error, target, "restore predecessor DLC"
                ) from direct_error
            if self._path_present(target):
                raise InstallConflictError(
                    f"uninstall target changed while restoring predecessor: {target}"
                ) from direct_error
            try:
                self._copy_tree_atomic(backup, target)
            except OSError as fallback_error:
                raise self._destination_error(
                    fallback_error, target, "restore predecessor DLC"
                ) from fallback_error
            return True

    def _rollback_uninstall_files(
        self,
        *,
        target: Path,
        removed: Path,
        backup: Path | None,
        installed_tree_sha256: str,
    ) -> None:
        """Restore the pre-uninstall filesystem state without deleting ambiguity."""
        target_present = self._path_present(target)
        removed_present = self._path_present(removed)
        if removed_present:
            if self._is_link(removed) or not removed.is_dir():
                raise InstallRecoveryConflict(
                    "uninstall temporary tree is not a trusted directory"
                )
            if self._tree_sha256(removed) != installed_tree_sha256:
                raise InstallRecoveryConflict(
                    "uninstall temporary tree no longer matches the receipt"
                )
        if target_present and self._is_link(target):
            raise InstallRecoveryConflict(
                "uninstall target became a link or junction"
            )

        if target_present and removed_present:
            if backup is None:
                raise InstallRecoveryConflict(
                    "uninstall target and temporary tree both exist without a predecessor backup"
                )
            if self._path_present(backup):
                if self._is_link(backup) or not backup.is_dir():
                    raise InstallRecoveryConflict(
                        "uninstall predecessor backup is not a trusted directory"
                    )
                if self._tree_sha256(target) != self._tree_sha256(backup):
                    raise InstallRecoveryConflict(
                        "restored predecessor and retained backup differ"
                    )
                self._remove_tree(target)
            else:
                backup.parent.mkdir(parents=True, exist_ok=True)
                try:
                    self._replace_with_retry(target, backup)
                except OSError as direct_error:
                    if not (
                        self._is_cross_device(direct_error)
                        or self._is_access_error(direct_error)
                    ):
                        raise
                    self._copy_tree_atomic(target, backup)
                    self._remove_tree(target)
            target_present = False

        if not target_present and removed_present:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._replace_with_retry(removed, target)
            return
        if target_present and not removed_present:
            if (
                not target.is_dir()
                or self._tree_sha256(target) != installed_tree_sha256
            ):
                raise InstallRecoveryConflict(
                    "uninstall target changed before rollback could be confirmed"
                )
            return
        raise InstallRecoveryConflict(
            "uninstall target and temporary tree are both missing"
        )

    def _uninstall_removed_path(
        self, target: Path, transaction_id: str
    ) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", transaction_id):
            raise InstallError("uninstall transaction ID is invalid")
        return self._contained(
            target.parent,
            target.parent / f".signriver-uninstall-{transaction_id}.removed",
        )

    def _uninstall_removed_from_journal(
        self,
        journal_path: Path,
        payload: dict,
        target: Path,
        transaction_id: str,
    ) -> Path:
        recorded = payload.get("removed_path")
        if recorded is None:
            # Schema-v2 journals written by older builds kept this directory
            # below the data transaction root.
            return journal_path.parent / "removed" / target.name
        try:
            actual = Path(recorded).resolve(strict=False)
            expected = self._uninstall_removed_path(target, transaction_id)
        except (OSError, TypeError, ValueError) as error:
            raise InstallRecoveryConflict(
                "uninstall temporary path is invalid"
            ) from error
        if actual != expected:
            raise InstallRecoveryConflict(
                "uninstall temporary path escaped the configured DLC directory"
            )
        return expected

    def _uninstall_backup_from_journal(self, payload: dict) -> Path | None:
        recorded = payload.get("backup_path")
        if recorded is None:
            return None
        try:
            backup = Path(recorded).resolve(strict=False)
            self._contained(self.data_root / "backups", backup)
        except (OSError, TypeError, ValueError, InstallError) as error:
            raise InstallRecoveryConflict(
                "uninstall predecessor backup path is invalid"
            ) from error
        if self._path_present(backup) and (
            self._is_link(backup) or not backup.is_dir()
        ):
            raise InstallRecoveryConflict(
                "uninstall predecessor backup is not a trusted directory"
            )
        return backup

    def _cleanup_uninstall_tree_best_effort(self, path: Path) -> None:
        try:
            if (
                self._path_present(path)
                and not self._is_link(path)
                and path.is_dir()
            ):
                self._remove_tree(path)
        except OSError:
            pass

    def _replace_with_retry(self, source: Path, destination: Path) -> None:
        for delay in (*self._replace_retry_delays, None):
            try:
                self._replace(source, destination)
                return
            except OSError as error:
                if delay is None or not self._is_access_error(error):
                    raise
                self._sleep(delay)

    def _inspect_target(self, target: Path) -> bool:
        try:
            info = target.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise self._destination_error(
                error, target, "检查目标 DLC 目录"
            ) from error
        is_junction = getattr(target, "is_junction", lambda: False)()
        if target.is_symlink() or is_junction:
            raise InstallConflictError(f"目标 DLC 路径不能是链接或联接：{target}")
        if not stat.S_ISDIR(info.st_mode):
            raise InstallConflictError(f"目标 DLC 路径已被同名文件占用：{target}")
        try:
            with os.scandir(target) as entries:
                next(entries, None)
        except OSError as error:
            raise self._destination_error(
                error, target, "读取已有 DLC 目录"
            ) from error
        return True

    @staticmethod
    def _path_present(path: Path) -> bool:
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _is_access_error(error: OSError) -> bool:
        return (
            isinstance(error, PermissionError)
            or error.errno in {EACCES, EPERM}
            or getattr(error, "winerror", None) in {5, 32, 33}
        )

    @staticmethod
    def _is_cross_device(error: OSError) -> bool:
        return error.errno == EXDEV or getattr(error, "winerror", None) == 17

    @classmethod
    def _destination_error(
        cls, error: OSError, target: Path, operation: str
    ) -> InstallError:
        if cls._is_access_error(error):
            return InstallAccessError(
                f"{operation}失败：游戏 DLC 目录拒绝访问或正被占用（{target}）。"
                "请关闭游戏及相关启动器，确认杀毒软件未锁定文件，并检查目录写入权限；"
                "必要时以管理员身份运行。本次操作已保留原文件"
            )
        if isinstance(error, FileExistsError) or error.errno in {17, 39}:
            return InstallConflictError(
                f"{operation}失败：目标 DLC 目录已存在或在安装期间发生变化（{target}）"
            )
        return InstallError(f"{operation}失败：{error}")

    def _completed_backup_exists(
        self, plan: InstallPlan, target: Path, backup: Path
    ) -> bool:
        if not self._path_present(backup):
            return False
        try:
            phase = InstallPhase(
                json.loads(plan.journal_path.read_text(encoding="utf-8"))["phase"]
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            phase = None
        return phase in {
            InstallPhase.BACKUP_COPIED,
            InstallPhase.BACKED_UP,
            InstallPhase.COMMITTING,
        } or not self._path_present(target)

    @staticmethod
    def _expanded_package_size(package_path: Path) -> int:
        try:
            with zipfile.ZipFile(package_path) as archive:
                return sum(
                    int(info.file_size)
                    for info in archive.infolist()
                    if not info.is_dir()
                )
        except (OSError, zipfile.BadZipFile) as error:
            raise InstallError(
                f"无法读取资源包的解压大小：{error}"
            ) from error

    @staticmethod
    def _existing_ancestor(path: Path) -> Path:
        candidate = Path(path).resolve(strict=False)
        while not candidate.exists():
            parent = candidate.parent
            if parent == candidate:
                raise InstallError(f"无法确定磁盘空间检查位置：{path}")
            candidate = parent
        return candidate.resolve(strict=True)

    def _volume_key(self, path: Path) -> object:
        if self._volume_key_override is not None:
            return self._volume_key_override(path)
        if os.name == "nt":
            # Drive/UNC anchors are stable even on Python builds whose st_dev
            # value does not distinguish every Windows volume.
            return ("windows-anchor", path.anchor.casefold())
        try:
            return ("device", path.stat().st_dev)
        except OSError as error:
            raise InstallError(f"无法识别安装磁盘：{path}") from error

    @staticmethod
    def _tree_size(root: Path) -> int:
        if not root.exists():
            return 0
        total = 0
        try:
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
        except OSError as error:
            raise InstallError(f"无法统计目录大小：{root}（{error}）") from error
        return total

    @staticmethod
    def _format_bytes(value: int) -> str:
        amount = float(max(0, value))
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if amount < 1024 or unit == "TiB":
                return f"{amount:.1f} {unit}"
            amount /= 1024
        return f"{amount:.1f} TiB"

    @staticmethod
    def _read_maintenance_journal(path: Path) -> dict:
        if not path.is_file() or path.is_symlink():
            raise InstallError("缺少可信事务日志")
        if path.stat().st_size > 256 * 1024:
            raise InstallError("事务日志过大")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise InstallError("事务日志无法读取") from error
        if not isinstance(payload, dict):
            raise InstallError("事务日志格式无效")
        return payload

    @staticmethod
    def _maintenance_journal_state(
        transaction_root: Path, payload: dict
    ) -> tuple[str, bool, bool]:
        if payload.get("schema_version") not in {1, 2}:
            raise InstallError("不支持的事务日志版本")
        operation = payload.get("operation", "install")
        if operation not in {"install", "uninstall"}:
            raise InstallError("不支持的事务操作类型")
        transaction_id = str(payload["transaction_id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]+", transaction_id):
            raise InstallError("事务编号无效")
        if operation == "uninstall":
            if transaction_root.name != f"uninstall-{transaction_id}":
                raise InstallError("卸载事务目录与日志不匹配")
            phase = str(payload["phase"])
            return transaction_id, phase in {"committed", "rolled_back"}, phase == "rolled_back"
        if transaction_root.name != transaction_id:
            raise InstallError("安装事务目录与日志不匹配")
        phase = InstallPhase(payload["phase"])
        return (
            transaction_id,
            phase in {InstallPhase.COMMITTED, InstallPhase.ROLLED_BACK},
            phase is InstallPhase.ROLLED_BACK,
        )

    @staticmethod
    def _is_link(path: Path) -> bool:
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()

    @classmethod
    def _tree_has_link(cls, root: Path) -> bool:
        try:
            for current, directories, files in os.walk(root, followlinks=False):
                for name in (*directories, *files):
                    if cls._is_link(Path(current) / name):
                        return True
        except OSError:
            return True
        return False

    @staticmethod
    def _remove_tree(path: Path) -> None:
        def make_writable(function, name, error_info):
            error = error_info[1]
            if not isinstance(error, PermissionError):
                raise error
            os.chmod(name, stat.S_IWRITE)
            function(name)

        shutil.rmtree(path, onerror=make_writable)

    def _write_journal(
        self,
        plan,
        phase,
        replaced_existing,
        *,
        receipt: InstallReceipt | None = None,
    ) -> None:
        plan.journal_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "operation": "install",
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
        if receipt is not None:
            payload["receipt"] = {
                "installed_tree_sha256": receipt.installed_tree_sha256,
                "previous_transaction_id": receipt.previous_transaction_id,
            }
            payload["receipt_persisted"] = False
        self._write_json_atomic(plan.journal_path, payload)

    @staticmethod
    def _write_simple_journal(
        path: Path,
        phase: str,
        receipt: InstallReceipt,
        *,
        removed_path: Path | None = None,
        backup_path: Path | None = None,
    ) -> None:
        payload = {
            "schema_version": 2,
            "operation": "uninstall",
            "phase": phase,
            "transaction_id": receipt.transaction_id,
            "dlc_id": receipt.dlc_id,
            "target_path": str(receipt.target_path),
            "installed_tree_sha256": receipt.installed_tree_sha256,
        }
        if removed_path is not None:
            payload["removed_path"] = str(removed_path)
        if backup_path is not None:
            payload["backup_path"] = str(backup_path)
        StellarisInstallEngine._write_json_atomic(path, payload)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict) -> None:
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
    def _installed_snapshot(
        cls, root: Path
    ) -> tuple[str, tuple[OwnedFile, ...]]:
        """Build the tree hash and owned-file records in one disk pass."""
        tree_digest = hashlib.sha256()
        records = []
        files = sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root).as_posix().casefold(),
        )
        for path in files:
            relative_text = path.relative_to(root).as_posix()
            relative = relative_text.encode("utf-8")
            tree_digest.update(len(relative).to_bytes(4, "big"))
            tree_digest.update(relative)
            file_digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    file_digest.update(block)
                    tree_digest.update(block)
            records.append(OwnedFile(
                relative_path=relative_text,
                size=size,
                sha256=file_digest.hexdigest(),
            ))
        return tree_digest.hexdigest(), tuple(records)

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
