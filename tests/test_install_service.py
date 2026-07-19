from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from signriver_app.application import DlcInstallService, InstallServiceError
from signriver_app.domain import InstallHealth, InstallPhase
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
    journals = tuple((tmp_path / "data" / "transactions").glob("*/journal.json"))
    install_journal = next(
        path for path in journals if not path.parent.name.startswith("uninstall-")
    )
    assert json.loads(install_journal.read_text(encoding="utf-8"))["phase"] == (
        InstallPhase.ROLLED_BACK
    )


def test_startup_persists_receipt_for_committed_install_after_crash(
    tmp_path: Path,
) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    plan = engine.plan(
        package, game, expected_sha256=digest,
        transaction_id="committed-before-db",
    )
    receipt = engine.install(plan)
    assert repository.find_active("stellaris", "dlc001") is None

    recovered = DlcInstallService(engine, repository).recover_incomplete([game])

    assert recovered == (receipt.transaction_id,)
    assert repository.find_active("stellaris", "dlc001") == receipt
    payload = json.loads(plan.journal_path.read_text(encoding="utf-8"))
    assert payload["receipt_persisted"] is True


def test_startup_repairs_receipt_marker_without_duplicate_insert(
    tmp_path: Path,
) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    plan = engine.plan(
        package, game, expected_sha256=digest,
        transaction_id="db-saved-marker-missed",
    )
    receipt = engine.install(plan)
    repository.save_installed(receipt)

    recovered = DlcInstallService(engine, repository).recover_incomplete([game])

    assert recovered == (receipt.transaction_id,)
    assert repository.active("stellaris") == (receipt,)
    payload = json.loads(plan.journal_path.read_text(encoding="utf-8"))
    assert payload["receipt_persisted"] is True


def test_startup_refuses_to_persist_changed_committed_target(tmp_path: Path) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    plan = engine.plan(
        package, game, expected_sha256=digest,
        transaction_id="committed-then-changed",
    )
    receipt = engine.install(plan)
    (receipt.target_path / "foreign.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(InstallServiceError, match="发生变化"):
        DlcInstallService(engine, repository).recover_incomplete([game])

    assert repository.find_active("stellaris", "dlc001") is None
    assert (receipt.target_path / "foreign.txt").is_file()


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


def test_service_recovers_only_explicitly_trusted_game_root(tmp_path: Path) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    service = DlcInstallService(engine, repository)
    plan = engine.plan(
        package, game, expected_sha256=digest, transaction_id="service-crash"
    )
    target = plan.target_path
    backup = plan.backup_root / target.name
    backup.mkdir(parents=True)
    (backup / "old.txt").write_text("old", encoding="utf-8")
    engine._write_journal(plan, InstallPhase.BACKED_UP, True)

    assert service.recover_incomplete([]) == ()
    assert not target.exists()
    assert service.recover_incomplete([game]) == ("service-crash",)
    assert (target / "old.txt").read_text(encoding="utf-8") == "old"


def test_maintenance_keeps_active_receipt_and_backup(tmp_path: Path) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    existing = game / "dlc" / "dlc001_symbols_of_domination"
    existing.mkdir()
    (existing / "original.txt").write_text("original", encoding="utf-8")
    service = DlcInstallService(engine, repository)
    receipt = service.install(package, game, expected_sha256=digest)
    assert receipt.backup_path is not None and receipt.backup_path.is_dir()

    preview = service.preview_install_maintenance(
        min_age_seconds=0, now=10**12
    )
    result = service.execute_install_maintenance(
        min_age_seconds=0, now=10**12
    )

    assert not preview.candidates
    assert not result.removed
    assert receipt.backup_path.is_dir()
    assert plan_journal(engine, receipt.transaction_id).is_file()


def test_maintenance_removes_only_known_retired_terminal_storage(
    tmp_path: Path,
) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    service = DlcInstallService(engine, repository)
    receipt = service.install(package, game, expected_sha256=digest)
    service.uninstall("stellaris", "dlc001", game)

    preview = service.preview_install_maintenance(
        min_age_seconds=0, now=10**12
    )
    candidate_paths = {item.path for item in preview.candidates}
    assert plan_journal(engine, receipt.transaction_id).parent.resolve() in candidate_paths
    assert (
        engine.data_root / "transactions" / f"uninstall-{receipt.transaction_id}"
    ).resolve() in candidate_paths

    result = service.execute_install_maintenance(
        min_age_seconds=0, now=10**12
    )
    assert not result.failed
    assert {item.path for item in result.removed} == candidate_paths
    assert all(not path.exists() for path in candidate_paths)


def test_maintenance_protects_entire_active_predecessor_chain(tmp_path: Path) -> None:
    game, package, digest, engine, repository = fixture(tmp_path)
    service = DlcInstallService(engine, repository)
    first = service.install(package, game, expected_sha256=digest)
    second = service.install(package, game, expected_sha256=digest)
    third = service.install(package, game, expected_sha256=digest)

    protected, retired = repository.maintenance_transaction_ids()

    assert protected == {
        first.transaction_id, second.transaction_id, third.transaction_id,
    }
    assert not retired
    assert not service.preview_install_maintenance(
        min_age_seconds=0, now=10**12
    ).candidates


def plan_journal(engine, transaction_id: str) -> Path:
    return engine.data_root / "transactions" / transaction_id / "journal.json"
