"""Persistence for auditable install receipts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ...domain import InstallReceipt, OwnedFile
from .database import Database
from .errors import PersistenceError


class InstallReceiptRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.database.initialize()

    def save_installed(self, receipt: InstallReceipt) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.database.transaction() as connection:
                if receipt.previous_transaction_id is not None:
                    cursor = connection.execute(
                        "UPDATE install_receipts SET status='uninstalled', updated_at=? "
                        "WHERE transaction_id=? AND status='installed'",
                        (now, receipt.previous_transaction_id),
                    )
                    if cursor.rowcount != 1:
                        raise PersistenceError("previous active install receipt was not found")
                connection.execute(
                    """INSERT INTO install_receipts (
                        transaction_id, game_id, dlc_id, target_path,
                        package_sha256, replaced_existing, backup_path,
                        installed_tree_sha256, status, created_at, updated_at,
                        previous_transaction_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'installed', ?, ?, ?)
                    ON CONFLICT(transaction_id) DO UPDATE SET
                        target_path=excluded.target_path,
                        package_sha256=excluded.package_sha256,
                        replaced_existing=excluded.replaced_existing,
                        backup_path=excluded.backup_path,
                        installed_tree_sha256=excluded.installed_tree_sha256,
                        status='installed', updated_at=excluded.updated_at,
                        previous_transaction_id=excluded.previous_transaction_id""",
                    (
                        receipt.transaction_id, receipt.game_id, receipt.dlc_id,
                        str(receipt.target_path), receipt.package_sha256,
                        int(receipt.replaced_existing),
                        str(receipt.backup_path) if receipt.backup_path else None,
                        receipt.installed_tree_sha256, now, now,
                        receipt.previous_transaction_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM install_owned_files WHERE transaction_id=?",
                    (receipt.transaction_id,),
                )
                connection.executemany(
                    "INSERT INTO install_owned_files "
                    "(transaction_id, relative_path, size, sha256) VALUES (?, ?, ?, ?)",
                    (
                        (receipt.transaction_id, item.relative_path, item.size, item.sha256)
                        for item in receipt.owned_files
                    ),
                )
        except Exception as error:
            raise PersistenceError("could not save install receipt") from error

    def mark_uninstalled(self, transaction_id: str, *, restore_previous: bool = False) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE install_receipts SET status='uninstalled', updated_at=? "
                    "WHERE transaction_id=? AND status='installed'",
                    (now, transaction_id),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError("active install receipt was not found")
                if restore_previous:
                    row = connection.execute(
                        "SELECT previous_transaction_id FROM install_receipts "
                        "WHERE transaction_id=?",
                        (transaction_id,),
                    ).fetchone()
                    previous = row[0] if row else None
                    if previous is not None:
                        restored = connection.execute(
                            "UPDATE install_receipts SET status='installed', updated_at=? "
                            "WHERE transaction_id=? AND status='uninstalled'",
                            (now, previous),
                        )
                        if restored.rowcount != 1:
                            raise PersistenceError("previous install receipt could not be restored")
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise PersistenceError("could not mark install receipt uninstalled") from error

    def active(self, game_id: str | None = None) -> tuple[InstallReceipt, ...]:
        query = "SELECT * FROM install_receipts WHERE status='installed'"
        parameters = ()
        if game_id is not None:
            query += " AND game_id=?"
            parameters = (game_id,)
        query += " ORDER BY game_id, dlc_id, created_at"
        try:
            with self.database.connection() as connection:
                rows = connection.execute(query, parameters).fetchall()
                receipts = []
                for row in rows:
                    files = connection.execute(
                        "SELECT relative_path, size, sha256 FROM install_owned_files "
                        "WHERE transaction_id=? ORDER BY relative_path",
                        (row["transaction_id"],),
                    ).fetchall()
                    receipts.append(self._from_row(row, files))
            return tuple(receipts)
        except Exception as error:
            raise PersistenceError("could not load install receipts") from error

    def find_active(self, game_id: str, dlc_id: str) -> InstallReceipt | None:
        matches = tuple(
            item for item in self.active(game_id) if item.dlc_id == dlc_id
        )
        if len(matches) > 1:
            raise PersistenceError(
                f"multiple active install receipts exist for {game_id}/{dlc_id}"
            )
        return matches[0] if matches else None

    @staticmethod
    def _from_row(row, files) -> InstallReceipt:
        return InstallReceipt(
            transaction_id=row["transaction_id"], game_id=row["game_id"],
            dlc_id=row["dlc_id"], target_path=Path(row["target_path"]),
            package_sha256=row["package_sha256"],
            replaced_existing=bool(row["replaced_existing"]),
            backup_path=Path(row["backup_path"]) if row["backup_path"] else None,
            installed_tree_sha256=row["installed_tree_sha256"],
            owned_files=tuple(
                OwnedFile(item["relative_path"], item["size"], item["sha256"])
                for item in files
            ),
            previous_transaction_id=row["previous_transaction_id"],
        )
