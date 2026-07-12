from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from signriver_app.domain import InstallPhase
from signriver_app.infrastructure.installs import InstallError, StellarisInstallEngine


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
    with pytest.raises(InstallError, match="rolled back"):
        engine.install(plan)

    assert (existing / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (existing / "dlc001.dlc").exists()
    journal = json.loads(plan.journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == InstallPhase.ROLLED_BACK


def test_plan_rejects_changed_hash_and_wrong_game(tmp_path: Path) -> None:
    game = make_game(tmp_path / "Stellaris")
    package = tmp_path / "dlc001.zip"
    digest = make_package(package)
    engine = StellarisInstallEngine(tmp_path / "data")
    with pytest.raises(InstallError, match="SHA-256 changed"):
        engine.plan(package, game, expected_sha256="0" * 64)
    (game / "stellaris.exe").unlink()
    with pytest.raises(InstallError, match="validated Stellaris"):
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
