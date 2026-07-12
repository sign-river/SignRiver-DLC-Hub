from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from signriver_app.application import DlcInstallService, InstallServiceError
from signriver_app.domain import InstallHealth
from signriver_app.infrastructure.installs import StellarisInstallEngine
from signriver_app.infrastructure.persistence import Database, InstallReceiptRepository


def fixture(tmp_path: Path):
    game = tmp_path / "Stellaris"
    game.mkdir()
    (game / "stellaris.exe").write_bytes(b"exe")
    (game / "dlc").mkdir()
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("content.txt", "payload")
    package = tmp_path / "dlc001.zip"
    with zipfile.ZipFile(package, "w") as archive:
        root = "dlc001_symbols_of_domination/"
        archive.writestr(root + "dlc001.dlc", 'name="Symbols"\narchive="dlc/dlc001_symbols_of_domination/dlc001.zip"')
        archive.writestr(root + "dlc001.zip", nested.getvalue())
        archive.writestr(root + "thumbnail.png", b"image")
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    repository = InstallReceiptRepository(Database(tmp_path / "data" / "hub.db"))
    engine = StellarisInstallEngine(tmp_path / "data")
    return game, package, digest, engine, repository


def test_install_audit_repair_and_uninstall_use_case(tmp_path: Path) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    service = DlcInstallService(engine, repository)
    receipt = service.install(package, game, expected_sha256=digest)
    assert repository.find_active("stellaris", "dlc001") == receipt
    assert service.audit("stellaris", game)[0].audit.health is InstallHealth.HEALTHY

    (receipt.target_path / "thumbnail.png").unlink()
    repaired = service.repair_missing("stellaris", "dlc001", package, game)
    assert repaired.health is InstallHealth.HEALTHY
    service.uninstall("stellaris", "dlc001", game)
    assert repository.find_active("stellaris", "dlc001") is None
    assert not receipt.target_path.exists()


def test_receipt_save_failure_compensates_installed_files(tmp_path: Path) -> None:
    game, package, digest, engine, _repository = fixture(tmp_path)

    class BrokenRepository:
        def find_active(self, _game_id, _dlc_id):
            return None

        def save_installed(self, _receipt):
            raise OSError("database full")

    service = DlcInstallService(engine, BrokenRepository())
    with pytest.raises(InstallServiceError, match="rolled back"):
        service.install(package, game, expected_sha256=digest)
    assert not (game / "dlc" / "dlc001_symbols_of_domination").exists()


def test_reconcile_committed_uninstall_after_database_failure(tmp_path: Path) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    service = DlcInstallService(engine, repository)
    receipt = service.install(package, game, expected_sha256=digest)
    engine.uninstall(receipt, game)
    assert repository.find_active("stellaris", "dlc001") is not None
    assert service.reconcile_committed_uninstalls("stellaris") == (receipt.transaction_id,)
    assert repository.find_active("stellaris", "dlc001") is None


def test_update_chain_reactivates_previous_receipt_when_new_version_removed(tmp_path: Path) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    service = DlcInstallService(engine, repository)
    first = service.install(package, game, expected_sha256=digest)
    second = service.install(package, game, expected_sha256=digest)
    assert second.previous_transaction_id == first.transaction_id
    assert repository.find_active("stellaris", "dlc001") == second

    service.uninstall("stellaris", "dlc001", game)
    assert repository.find_active("stellaris", "dlc001") == first
    assert engine.verify(first, game)
