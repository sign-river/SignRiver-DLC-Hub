from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from errno import EACCES, EXDEV
from pathlib import Path

import pytest

from signriver_app.domain import InstallHealth, InstallPhase
from signriver_app.infrastructure.installs import (
    InstallAccessError,
    InstallConflictError,
    InstallError,
    StellarisInstallEngine,
)


def make_game(root: Path) -> Path:
    root.mkdir()
    (root / "stellaris.exe").write_bytes(b"exe")
    (root / "dlc").mkdir()
    return root


def make_package(path: Path, *, root: str = "dlc001_symbols_of_domination") -> str:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as payload:
        payload.writestr("events/example.txt", "content")
    descriptor = '\n'.join([
        'name = "Symbols of Domination"',
        'archive = "dlc/dlc001_symbols_of_domination/dlc001.zip"',
        'steam_id = 447680',
    ])
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(f"{root}/dlc001.dlc", descriptor)
        package.writestr(f"{root}/dlc001.zip", nested.getvalue())
        package.writestr(f"{root}/thumbnail.png", b"image")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_install_new_dlc_commits_journal_and_receipt(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    plan = engine.plan(package, game, expected_sha256=digest, transaction_id="txn-new")
    receipt = engine.install(plan)

    assert (receipt.target_path / "dlc001.dlc").is_file()
    assert receipt.replaced_existing is False
    assert receipt.backup_path is None
    journal = json.loads(plan.journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == InstallPhase.COMMITTED
    assert journal["target"] == "dlc/dlc001_symbols_of_domination"


def test_single_pass_installed_snapshot_preserves_receipt_hash_semantics(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    (root / "nested").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"alpha")
    (root / "nested" / "b.bin").write_bytes(b"beta")

    engine = StellarisInstallEngine(tmp_path / "data")
    tree_sha256, owned_files = engine._installed_snapshot(root)

    assert tree_sha256 == engine._tree_sha256(root)
    assert owned_files == engine._owned_files(root)


def test_install_uses_cartridge_owned_nested_dlc_directory(tmp_path: Path) -> None:
    game = tmp_path / "OtherGame"
    game.mkdir()
    (game / "other.exe").write_bytes(b"exe")
    (game / "content" / "addons").mkdir(parents=True)
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(
        tmp_path / "data",
        dlc_relative_dir="content/addons",
        executable_name="other.exe",
    )

    plan = engine.plan(package, game, expected_sha256=digest, transaction_id="nested")
    receipt = engine.install(plan)

    assert receipt.target_path.parent == (game / "content" / "addons").resolve()
    assert plan.relative_target.as_posix() == "content/addons/dlc001_symbols_of_domination"
    assert engine.verify(receipt, game)


def test_install_rejects_unsafe_cartridge_dlc_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="game root"):
        StellarisInstallEngine(tmp_path / "data", dlc_relative_dir="../outside")


def test_install_replaces_existing_dlc_and_keeps_backup(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    existing = game / "dlc" / "dlc001_symbols_of_domination"
    existing.mkdir()
    (existing / "old.txt").write_text("old", encoding="utf-8")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    receipt = engine.install(engine.plan(package, game, expected_sha256=digest, transaction_id="txn-update"))

    assert not (receipt.target_path / "old.txt").exists()
    assert receipt.backup_path is not None
    assert (receipt.backup_path / "old.txt").read_text(encoding="utf-8") == "old"


def test_commit_failure_restores_previous_installation(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    existing = game / "dlc" / "dlc001_symbols_of_domination"
    existing.mkdir()
    (existing / "old.txt").write_text("old", encoding="utf-8")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected commit failure")
        os.replace(source, target)

    engine = StellarisInstallEngine(tmp_path / "data", replace=fail_second)
    plan = engine.plan(package, game, expected_sha256=digest, transaction_id="txn-rollback")
    with pytest.raises(InstallError, match="提交 DLC 目录失败"):
        engine.install(plan)

    assert (existing / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (existing / "dlc001.dlc").exists()
    journal = json.loads(plan.journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == InstallPhase.ROLLED_BACK


def test_commit_retries_transient_windows_access_denied(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    sleeps = []
    commit_attempts = 0
    plan = None

    def transient_denial(source: Path, target: Path) -> None:
        nonlocal commit_attempts
        if plan is not None and source.parent == plan.staging_root:
            commit_attempts += 1
            if commit_attempts == 1:
                raise PermissionError(EACCES, "injected transient lock", str(target))
        os.replace(source, target)

    engine = StellarisInstallEngine(
        tmp_path / "data",
        replace=transient_denial,
        sleep=sleeps.append,
        replace_retry_delays=(0.2, 0.4),
    )
    plan = engine.plan(
        package, game, expected_sha256=digest, transaction_id="txn-retry"
    )
    receipt = engine.install(plan)

    assert receipt.target_path.is_dir()
    assert commit_attempts == 2
    assert sleeps == [0.2]


def test_commit_uses_verified_target_side_copy_after_move_denied(
    tmp_path: Path,
) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    plan = None

    def deny_data_root_move(source: Path, target: Path) -> None:
        if plan is not None and source.parent == plan.staging_root:
            raise PermissionError(EACCES, "injected persistent move denial", str(target))
        os.replace(source, target)

    engine = StellarisInstallEngine(
        tmp_path / "data",
        replace=deny_data_root_move,
        sleep=lambda _delay: None,
        replace_retry_delays=(0.0,),
    )
    plan = engine.plan(
        package, game, expected_sha256=digest, transaction_id="txn-local-copy"
    )
    receipt = engine.install(plan)

    assert (receipt.target_path / "dlc001.dlc").is_file()
    assert not tuple((game / "dlc").glob(".signriver-*.tmp"))


def test_commit_uses_target_side_copy_across_filesystems(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    plan = None

    def cross_device_move(source: Path, target: Path) -> None:
        if plan is not None and source.parent == plan.staging_root:
            raise OSError(EXDEV, "injected cross-device move", str(target))
        os.replace(source, target)

    engine = StellarisInstallEngine(tmp_path / "data", replace=cross_device_move)
    plan = engine.plan(
        package, game, expected_sha256=digest, transaction_id="txn-cross-device"
    )
    receipt = engine.install(plan)

    assert engine.verify(receipt, game)


def test_existing_target_access_denial_is_classified_and_preserved(
    tmp_path: Path,
) -> None:
    game = make_game(tmp_path / "Stellaris")
    existing = game / "dlc" / "dlc001_symbols_of_domination"
    existing.mkdir()
    (existing / "old.txt").write_text("keep", encoding="utf-8")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)

    def deny_existing_move(source: Path, target: Path) -> None:
        if source == existing:
            raise PermissionError(EACCES, "injected lock", str(target))
        os.replace(source, target)

    engine = StellarisInstallEngine(
        tmp_path / "data",
        replace=deny_existing_move,
        sleep=lambda _delay: None,
        replace_retry_delays=(0.0,),
    )
    plan = engine.plan(
        package, game, expected_sha256=digest, transaction_id="txn-denied"
    )
    with pytest.raises(InstallAccessError, match="拒绝访问或正被占用"):
        engine.install(plan)

    assert (existing / "old.txt").read_text(encoding="utf-8") == "keep"
    assert not (existing / "dlc001.dlc").exists()
    journal = json.loads(plan.journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == InstallPhase.ROLLED_BACK


def test_new_destination_race_does_not_delete_foreign_directory(
    tmp_path: Path,
) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    plan = None

    def create_conflict(source: Path, target: Path) -> None:
        if plan is not None and source.parent == plan.staging_root:
            target.mkdir()
            (target / "foreign.txt").write_text("keep", encoding="utf-8")
            raise FileExistsError(17, "injected destination race", str(target))
        os.replace(source, target)

    engine = StellarisInstallEngine(tmp_path / "data", replace=create_conflict)
    plan = engine.plan(
        package, game, expected_sha256=digest, transaction_id="txn-conflict"
    )
    with pytest.raises(InstallConflictError, match="目标 DLC 目录"):
        engine.install(plan)

    assert (plan.target_path / "foreign.txt").read_text(encoding="utf-8") == "keep"
    assert not (plan.target_path / "dlc001.dlc").exists()


def test_plan_rejects_changed_hash_and_wrong_game(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    with pytest.raises(InstallError, match="SHA-256 changed"):
        engine.plan(package, game, expected_sha256="0" * 64)
    (game / "stellaris.exe").unlink()
    with pytest.raises(InstallError, match="当前卡带已验证的游戏安装目录"):
        engine.plan(package, game, expected_sha256=digest)


def test_plan_rejects_mismatched_package_directory(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "bad.zip"
    digest = make_package(package, root="dlc999_wrong")
    with pytest.raises(InstallError, match="descriptor DLC ID"):
        StellarisInstallEngine(tmp_path / "data").plan(
            package, game, expected_sha256=digest
        )


def test_recover_incomplete_restores_backup_for_allowed_game(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    plan = engine.plan(package, game, expected_sha256=digest, transaction_id="txn-crash")
    target = plan.target_path
    target.mkdir()
    (target / "new.txt").write_text("new", encoding="utf-8")
    backup = plan.backup_root / target.name
    backup.mkdir(parents=True)
    (backup / "old.txt").write_text("old", encoding="utf-8")
    engine._write_journal(plan, InstallPhase.BACKED_UP, True)

    assert engine.recover_incomplete([game]) == ("txn-crash",)
    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (target / "new.txt").exists()
    journal = json.loads(plan.journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == InstallPhase.ROLLED_BACK


def test_recovery_ignores_transaction_for_unapproved_game_root(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    plan = engine.plan(package, game, expected_sha256=digest, transaction_id="txn-other")
    engine._write_journal(plan, InstallPhase.STAGED, False)
    assert engine.recover_incomplete([]) == ()
    assert json.loads(plan.journal_path.read_text(encoding="utf-8"))["phase"] == InstallPhase.STAGED


def test_verify_and_uninstall_unchanged_installation(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    receipt = engine.install(
        engine.plan(package, game, expected_sha256=digest, transaction_id="txn-remove")
    )
    assert engine.verify(receipt, game) is True
    assert engine.assess(receipt, game) is InstallHealth.HEALTHY
    engine.uninstall(receipt, game)
    assert not receipt.target_path.exists()
    journal = json.loads(
        (tmp_path / "data" / "transactions" / "uninstall-txn-remove" / "journal.json").read_text(encoding="utf-8")
    )
    assert journal["phase"] == "committed"


def test_uninstall_refuses_user_modified_files(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    receipt = engine.install(
        engine.plan(package, game, expected_sha256=digest, transaction_id="txn-modified")
    )
    (receipt.target_path / "user-file.txt").write_text("keep", encoding="utf-8")
    assert engine.verify(receipt, game) is False
    assert engine.assess(receipt, game) is InstallHealth.MODIFIED
    with pytest.raises(InstallError, match="modified"):
        engine.uninstall(receipt, game)
    assert (receipt.target_path / "user-file.txt").is_file()


def test_assess_reports_missing_installation(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    receipt = engine.install(
        engine.plan(package, game, expected_sha256=digest, transaction_id="txn-missing")
    )
    import shutil
    shutil.rmtree(receipt.target_path)
    assert engine.assess(receipt, game) is InstallHealth.MISSING


def test_audit_classifies_missing_modified_and_unknown_files(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    receipt = engine.install(
        engine.plan(package, game, expected_sha256=digest, transaction_id="txn-audit")
    )
    (receipt.target_path / "thumbnail.png").unlink()
    (receipt.target_path / "dlc001.dlc").write_text("changed", encoding="utf-8")
    (receipt.target_path / "notes.txt").write_text("user", encoding="utf-8")
    audit = engine.audit(receipt, game)
    assert audit.health is InstallHealth.MODIFIED
    assert audit.missing == ("thumbnail.png",)
    assert audit.modified == ("dlc001.dlc",)
    assert audit.unknown == ("notes.txt",)


def test_repair_restores_only_missing_owned_files(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    receipt = engine.install(
        engine.plan(package, game, expected_sha256=digest, transaction_id="txn-repair")
    )
    (receipt.target_path / "thumbnail.png").unlink()
    (receipt.target_path / "dlc001.dlc").write_text("user change", encoding="utf-8")
    (receipt.target_path / "notes.txt").write_text("keep", encoding="utf-8")
    after = engine.repair_missing(receipt, package, game)
    assert (receipt.target_path / "thumbnail.png").read_bytes() == b"image"
    assert (receipt.target_path / "dlc001.dlc").read_text(encoding="utf-8") == "user change"
    assert (receipt.target_path / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert after.missing == ()
    assert after.modified == ("dlc001.dlc",)
    assert after.unknown == ("notes.txt",)


def test_uninstall_restores_pre_install_backup(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    existing = game / "dlc" / "dlc001_symbols_of_domination"
    existing.mkdir()
    (existing / "old.txt").write_text("old", encoding="utf-8")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    receipt = engine.install(
        engine.plan(package, game, expected_sha256=digest, transaction_id="txn-restore")
    )
    engine.uninstall(receipt, game)
    assert (existing / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (existing / "dlc001.dlc").exists()
