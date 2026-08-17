"""Tests for the persistent one-click repair journal."""

from __future__ import annotations

import json
from pathlib import Path

from signriver_app.infrastructure.patching import RepairJournal


def test_repair_journal_update_load_and_complete(tmp_path: Path) -> None:
    game_root = tmp_path / "game"
    game_root.mkdir()
    journal = RepairJournal(tmp_path / "data", clock=lambda: 1234.5)

    journal.update(
        "stellaris",
        game_root,
        phase="installing",
        requested_dlc_ids=("1", "2", "1"),
        completed_dlc_ids=("1",),
        message="resume",
    )

    state = journal.load("stellaris", game_root)
    assert state is not None
    assert state.phase == "installing"
    assert state.requested_dlc_ids == ("1", "2")
    assert state.completed_dlc_ids == ("1",)
    assert state.updated_at == 1234.5

    journal.complete("stellaris", game_root)
    assert journal.load("stellaris", game_root) is None


def test_repair_journal_atomically_overwrites_existing_state(tmp_path: Path) -> None:
    game_root = tmp_path / "game"
    game_root.mkdir()
    journal = RepairJournal(tmp_path / "data")

    journal.update("stellaris", game_root, phase="preparing", requested_dlc_ids=("1",))
    journal.update(
        "stellaris", game_root, phase="failed", requested_dlc_ids=("1",),
        status="failed", message="download failed",
    )

    state = journal.load("stellaris", game_root)
    assert state is not None
    assert state.phase == "failed"
    assert state.status == "failed"
    assert state.message == "download failed"
    assert not list(journal.root.glob("*.tmp"))


def test_repair_journal_ignores_corrupt_document(tmp_path: Path) -> None:
    game_root = tmp_path / "game"
    game_root.mkdir()
    journal = RepairJournal(tmp_path / "data")
    path = journal.path_for("stellaris", game_root)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    assert journal.load("stellaris", game_root) is None

    path.write_text(json.dumps({"schema": 99}), encoding="utf-8")
    assert journal.load("stellaris", game_root) is None
