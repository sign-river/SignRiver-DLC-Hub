from pathlib import Path

import pytest

from signriver_app.domain import InstallReceipt, OwnedFile
from signriver_app.infrastructure.persistence import Database, InstallReceiptRepository
from signriver_app.infrastructure.persistence.errors import PersistenceError


def _receipt(tmp_path: Path, transaction_id: str, dlc_id: str) -> InstallReceipt:
    return InstallReceipt(
        transaction_id=transaction_id, game_id="stellaris", dlc_id=dlc_id,
        target_path=tmp_path / "Stellaris" / "dlc" / f"{dlc_id}_symbols",
        package_sha256="a" * 64, replaced_existing=False, backup_path=None,
        installed_tree_sha256="b" * 64,
        owned_files=(OwnedFile(f"{dlc_id}.dlc", 12, "c" * 64),),
    )


def test_install_receipt_lifecycle(tmp_path: Path) -> None:
    repository = InstallReceiptRepository(Database(tmp_path / "hub.db"))
    receipt = _receipt(tmp_path, "txn-1", "dlc001")
    repository.save_installed(receipt)
    assert repository.has_transaction(receipt.transaction_id)
    assert not repository.has_transaction("missing")
    assert repository.active() == (receipt,)
    assert repository.active("stellaris") == (receipt,)
    assert repository.active("other") == ()
    repository.mark_uninstalled("txn-1")
    assert repository.active() == ()


def test_find_active_uses_targeted_lookup(tmp_path: Path, monkeypatch) -> None:
    repository = InstallReceiptRepository(Database(tmp_path / "hub.db"))
    first = _receipt(tmp_path, "txn-1", "dlc001")
    second = _receipt(tmp_path, "txn-2", "dlc002")
    repository.save_installed(first)
    repository.save_installed(second)

    def fail_full_scan(_game_id=None):
        raise AssertionError("find_active must not scan every active receipt")

    monkeypatch.setattr(repository, "active", fail_full_scan)
    assert repository.find_active("stellaris", "dlc002") == second
    assert repository.find_active("stellaris", "missing") is None


def test_active_dlc_ids_does_not_materialize_receipts(tmp_path: Path, monkeypatch) -> None:
    repository = InstallReceiptRepository(Database(tmp_path / "hub.db"))
    repository.save_installed(_receipt(tmp_path, "txn-1", "dlc001"))
    repository.save_installed(_receipt(tmp_path, "txn-2", "dlc002"))

    monkeypatch.setattr(
        repository,
        "active",
        lambda _game_id=None: (_ for _ in ()).throw(
            AssertionError("active_dlc_ids must not materialize receipts")
        ),
    )
    assert repository.active_dlc_ids("stellaris") == frozenset({"dlc001", "dlc002"})
    assert repository.active_dlc_ids("other") == frozenset()


def test_find_active_rejects_duplicate_active_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "hub.db")
    repository = InstallReceiptRepository(database)
    repository.save_installed(_receipt(tmp_path, "txn-1", "dlc001"))
    now = "2026-07-19T00:00:00+00:00"
    with database.transaction() as connection:
        connection.execute("DROP INDEX ux_install_receipts_active_game_dlc")
        connection.execute(
            """INSERT INTO install_receipts (
                transaction_id, game_id, dlc_id, target_path,
                package_sha256, replaced_existing, backup_path,
                installed_tree_sha256, status, created_at, updated_at,
                previous_transaction_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'installed', ?, ?, NULL)""",
            (
                "txn-duplicate", "stellaris", "dlc001",
                str(tmp_path / "duplicate"), "d" * 64, 0, None,
                "e" * 64, now, now,
            ),
        )

    with pytest.raises(PersistenceError, match="multiple active install receipts"):
        repository.find_active("stellaris", "dlc001")
