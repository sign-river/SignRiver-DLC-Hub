"""Atomic application use cases combining install transactions and receipts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ..domain import InstallAudit, InstallReceipt


class InstallServiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuditedInstallation:
    receipt: InstallReceipt
    audit: InstallAudit


class DlcInstallService:
    def __init__(self, engine, repository) -> None:
        self.engine = engine
        self.repository = repository

    def install(
        self,
        package_path: Path,
        game_root: Path,
        *,
        expected_sha256: str,
    ) -> InstallReceipt:
        previous = self.repository.find_active("stellaris", self._package_dlc_id(package_path))
        plan = self.engine.plan(
            package_path, game_root, expected_sha256=expected_sha256
        )
        receipt = self.engine.install(plan)
        if previous is not None:
            receipt = replace(
                receipt, previous_transaction_id=previous.transaction_id
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
            raise InstallServiceError(
                "receipt persistence failed; installation was rolled back"
            ) from error
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

    def _package_dlc_id(self, package_path: Path) -> str:
        # Planning performs the authoritative package validation. This lookup
        # only finds a possible predecessor for the same descriptor ID.
        from ..infrastructure.catalog import inspect_stellaris_package
        return inspect_stellaris_package(Path(package_path)).dlc_id
