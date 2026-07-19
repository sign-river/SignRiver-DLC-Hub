"""Atomic application use cases combining install transactions and receipts."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from ..domain import (
    InstallAudit,
    InstallMaintenancePreview,
    InstallMaintenanceResult,
    InstallReceipt,
)


class InstallServiceError(RuntimeError):
    pass


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditedInstallation:
    receipt: InstallReceipt
    audit: InstallAudit


class DlcInstallService:
    def __init__(
        self, engine, repository, *, game_id: str = "stellaris",
        package_inspector=None,
    ) -> None:
        self.engine = engine
        self.repository = repository
        self.game_id = game_id
        self.package_inspector = package_inspector

    def install(
        self,
        package_path: Path,
        game_root: Path,
        *,
        expected_sha256: str,
    ) -> InstallReceipt:
        plan = self.engine.plan(
            package_path, game_root, expected_sha256=expected_sha256
        )
        previous = self.repository.find_active(self.game_id, plan.dlc_id)
        receipt = self.engine.install(
            plan,
            previous_transaction_id=(
                previous.transaction_id if previous is not None else None
            ),
        )
        try:
            self.repository.save_installed(receipt)
        except Exception as error:
            try:
                self.engine.uninstall(receipt, game_root)
            except Exception as compensation_error:
                raise InstallServiceError(
                    "install committed but receipt persistence and compensation both failed"
                ) from compensation_error
            try:
                self.engine.mark_install_compensated(receipt.transaction_id)
            except Exception as marker_error:
                LOGGER.warning(
                    "Could not mark compensated install %s: %s",
                    receipt.transaction_id,
                    marker_error,
                )
            raise InstallServiceError(
                "receipt persistence failed; installation was rolled back"
            ) from error
        try:
            self.engine.mark_receipt_persisted(receipt.transaction_id)
        except Exception as marker_error:
            # The database commit is authoritative.  Startup reconciliation
            # recognizes the existing transaction and repairs this marker.
            LOGGER.warning(
                "Could not mark persisted install receipt %s: %s",
                receipt.transaction_id,
                marker_error,
            )
        return receipt

    def uninstall(self, game_id: str, dlc_id: str, game_root: Path) -> None:
        receipt = self.repository.find_active(game_id, dlc_id)
        if receipt is None:
            raise InstallServiceError(f"DLC is not recorded as installed: {dlc_id}")
        self.engine.uninstall(receipt, game_root)
        try:
            self.repository.mark_uninstalled(
                receipt.transaction_id,
                restore_previous=receipt.previous_transaction_id is not None,
            )
        except Exception as error:
            raise InstallServiceError(
                "uninstall committed but receipt status requires reconciliation"
            ) from error

    def audit(self, game_id: str, game_root: Path) -> tuple[AuditedInstallation, ...]:
        return tuple(
            AuditedInstallation(receipt, self.engine.audit(receipt, game_root))
            for receipt in self.repository.active(game_id)
        )

    def repair_missing(
        self,
        game_id: str,
        dlc_id: str,
        package_path: Path,
        game_root: Path,
    ) -> InstallAudit:
        receipt = self.repository.find_active(game_id, dlc_id)
        if receipt is None:
            raise InstallServiceError(f"DLC is not recorded as installed: {dlc_id}")
        return self.engine.repair_missing(receipt, package_path, game_root)

    def reconcile_committed_uninstalls(self, game_id: str) -> tuple[str, ...]:
        reconciled = []
        for receipt in self.repository.active(game_id):
            if self.engine.uninstall_committed(receipt):
                self.repository.mark_uninstalled(
                    receipt.transaction_id,
                    restore_previous=receipt.previous_transaction_id is not None,
                )
                reconciled.append(receipt.transaction_id)
        return tuple(reconciled)

    def recover_incomplete(self, allowed_game_roots) -> tuple[str, ...]:
        """Recover interrupted installs only under caller-trusted game roots."""
        roots = tuple(Path(item) for item in allowed_game_roots)
        try:
            recovered = self.engine.recover_incomplete(roots)
            committed = self._reconcile_committed_installs(roots)
            reconciled = self.reconcile_committed_uninstalls(self.game_id)
            return tuple(dict.fromkeys((*recovered, *committed, *reconciled)))
        except Exception as error:
            raise InstallServiceError(
                f"could not recover incomplete install transactions: {error}"
            ) from error

    def _reconcile_committed_installs(
        self, allowed_game_roots: tuple[Path, ...]
    ) -> tuple[str, ...]:
        loader = getattr(self.engine, "pending_committed_receipts", None)
        if not callable(loader):
            return ()
        reconciled = []
        contains = getattr(self.repository, "has_transaction", None)
        for receipt in loader(allowed_game_roots):
            if callable(contains) and contains(receipt.transaction_id):
                self.engine.mark_receipt_persisted(receipt.transaction_id)
                reconciled.append(receipt.transaction_id)
                continue
            active = self.repository.find_active(
                receipt.game_id, receipt.dlc_id
            )
            if active is not None and active.transaction_id == receipt.transaction_id:
                self.engine.mark_receipt_persisted(receipt.transaction_id)
                reconciled.append(receipt.transaction_id)
                continue
            expected_previous = receipt.previous_transaction_id
            if (
                (active is None and expected_previous is not None)
                or (
                    active is not None
                    and active.transaction_id != expected_previous
                )
            ):
                raise InstallServiceError(
                    "committed install conflicts with current receipt state: "
                    f"{receipt.game_id}/{receipt.dlc_id}"
                )
            self.repository.save_installed(receipt)
            self.engine.mark_receipt_persisted(receipt.transaction_id)
            reconciled.append(receipt.transaction_id)
        return tuple(reconciled)

    def preview_install_maintenance(
        self,
        *,
        min_age_seconds: float = 24 * 60 * 60,
        now: float | None = None,
    ) -> InstallMaintenancePreview:
        """Preview reclaimable terminal transaction data without deleting it."""
        protected, retired = self._maintenance_transaction_ids()
        try:
            return self.engine.preview_maintenance(
                protected_transaction_ids=protected,
                retired_transaction_ids=retired,
                min_age_seconds=min_age_seconds,
                now=now,
            )
        except Exception as error:
            raise InstallServiceError(
                f"could not inspect install transaction storage: {error}"
            ) from error

    def execute_install_maintenance(
        self,
        *,
        min_age_seconds: float = 24 * 60 * 60,
        now: float | None = None,
    ) -> InstallMaintenanceResult:
        """Re-scan references and remove only proven-retired transaction data."""
        protected, retired = self._maintenance_transaction_ids()
        try:
            return self.engine.execute_maintenance(
                protected_transaction_ids=protected,
                retired_transaction_ids=retired,
                min_age_seconds=min_age_seconds,
                now=now,
            )
        except Exception as error:
            raise InstallServiceError(
                f"could not clean install transaction storage: {error}"
            ) from error

    def _maintenance_transaction_ids(
        self,
    ) -> tuple[frozenset[str], frozenset[str]]:
        loader = getattr(self.repository, "maintenance_transaction_ids", None)
        if callable(loader):
            return loader()
        # Compatibility for lightweight adapters: active references are still
        # protected, while no transaction is guessed to be retired.
        active_loader = getattr(self.repository, "active", None)
        if not callable(active_loader):
            return frozenset(), frozenset()
        active = tuple(active_loader(self.game_id))
        protected = {
            value
            for receipt in active
            for value in (receipt.transaction_id, receipt.previous_transaction_id)
            if value is not None
        }
        return frozenset(protected), frozenset()

    def _package_dlc_id(
        self, package_path: Path, *, known_sha256: str | None = None
    ) -> str:
        # Planning performs the authoritative package validation. This lookup
        # only finds a possible predecessor for the same descriptor ID.
        if self.package_inspector is None:
            from ..infrastructure.catalog import inspect_stellaris_package
            inspector = inspect_stellaris_package
        else:
            inspector = self.package_inspector
        return inspector(
            Path(package_path), known_sha256=known_sha256
        ).dlc_id
