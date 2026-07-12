from pathlib import Path

from signriver_app.domain import InstallReceipt, OwnedFile
from signriver_app.infrastructure.persistence import Database, InstallReceiptRepository


def test_install_receipt_lifecycle(tmp_path: Path) -> None:
    repository = InstallReceiptRepository(Database(tmp_path / "hub.db"))
    receipt = InstallReceipt(
        transaction_id="txn-1", game_id="stellaris", dlc_id="dlc001",
        target_path=tmp_path / "Stellaris" / "dlc" / "dlc001_symbols",
        package_sha256="a" * 64, replaced_existing=False, backup_path=None,
        installed_tree_sha256="b" * 64,
        owned_files=(OwnedFile("dlc001.dlc", 12, "c" * 64),),
    )
    repository.save_installed(receipt)
    assert repository.active() == (receipt,)
    assert repository.active("stellaris") == (receipt,)
    assert repository.active("other") == ()
    repository.mark_uninstalled("txn-1")
    assert repository.active() == ()
