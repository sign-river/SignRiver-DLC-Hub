from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest

from signriver_app.domain import GameInstallation
from signriver_app.infrastructure.persistence import (
    Database,
    GameInstallationRepository,
    InstallationNotFoundError,
    LATEST_SCHEMA_VERSION,
    MigrationError,
    PersistenceConflictError,
    PersistenceSerializationError,
)


def make_installation(
    base: Path,
    installation_id: str,
    *,
    game_id: str = "alpha",
    adapter_id: str | None = None,
    selected: bool = False,
    last_seen: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> GameInstallation:
    root = base / installation_id
    return GameInstallation(
        installation_id=installation_id,
        game_id=game_id,
        adapter_id=adapter_id or f"{game_id}.mock",
        root=root,
        executable=root / f"{game_id}.exe",
        platform="windows",
        source="manual",
        store="mock",
        selected=selected,
        last_seen=last_seen,
        metadata={} if metadata is None else metadata,
    )


def test_database_initializes_schema_and_connection_pragmas(tmp_path: Path) -> None:
    database = Database(tmp_path / "nested" / "hub.sqlite3")

    assert database.initialize() == LATEST_SCHEMA_VERSION == 7
    assert database.path.is_file()
    assert database.schema_version() == LATEST_SCHEMA_VERSION

    with database.connection() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("game_installations",),
        ).fetchone()

    assert journal_mode.lower() == "wal"
    assert foreign_keys == 1
    assert table is not None


def test_database_initialization_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "hub.sqlite3")

    first = database.initialize()
    second = database.initialize()

    assert first == second == LATEST_SCHEMA_VERSION
    with database.connection() as connection:
        table_count = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'game_installations'"
        ).fetchone()[0]
    assert table_count == 1


def test_database_initialization_is_safe_under_concurrency(tmp_path: Path) -> None:
    path = tmp_path / "hub.sqlite3"
    worker_count = 4
    barrier = Barrier(worker_count)

    def initialize() -> int:
        barrier.wait()
        return Database(path).initialize()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        versions = tuple(executor.map(lambda _: initialize(), range(worker_count)))

    assert versions == (LATEST_SCHEMA_VERSION,) * worker_count
    assert Database(path).schema_version() == LATEST_SCHEMA_VERSION


def test_database_transaction_rolls_back_all_changes(tmp_path: Path) -> None:
    database = Database(tmp_path / "hub.sqlite3")
    database.initialize()

    with pytest.raises(RuntimeError, match="abort transaction"):
        with database.transaction() as connection:
            connection.execute(
                "CREATE TABLE rollback_probe (id INTEGER PRIMARY KEY, value TEXT)"
            )
            connection.execute(
                "INSERT INTO rollback_probe(value) VALUES (?)", ("uncommitted",)
            )
            raise RuntimeError("abort transaction")

    with database.connection() as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("rollback_probe",),
        ).fetchone()
    assert table is None


def test_database_rejects_a_newer_schema_without_modifying_it(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    future_version = LATEST_SCHEMA_VERSION + 1
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {future_version}")

    database = Database(path)
    with pytest.raises(MigrationError):
        database.initialize()

    assert database.schema_version() == future_version


def test_installation_round_trip_preserves_paths_time_and_metadata(
    tmp_path: Path,
) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    local_time = datetime(
        2026,
        7,
        12,
        8,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )
    installation = make_installation(
        tmp_path / "games",
        "alpha.local",
        selected=True,
        last_seen=local_time,
        metadata={
            "channel": "stable",
            "discovery": {"roots": ["registry", "library"]},
            "flags": [True, False],
        },
    )

    saved = repository.save(installation)
    restored = repository.get(installation.installation_id)

    assert saved == installation
    assert restored is not None
    assert restored == installation
    assert isinstance(restored.root, Path)
    assert isinstance(restored.executable, Path)
    assert restored.root == installation.root
    assert restored.executable == installation.executable
    assert restored.last_seen == datetime(2026, 7, 12, 0, 30, tzinfo=timezone.utc)
    assert restored.last_seen is not None
    assert restored.last_seen.utcoffset() == timedelta(0)
    assert restored.metadata["discovery"]["roots"] == ("registry", "library")
    assert restored.metadata["flags"] == (True, False)


def test_selection_is_unique_per_game_and_switches_atomically(tmp_path: Path) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    alpha_first = make_installation(
        tmp_path, "alpha.first", game_id="alpha", selected=True
    )
    alpha_second = make_installation(
        tmp_path, "alpha.second", game_id="alpha", selected=False
    )
    beta = make_installation(tmp_path, "beta.local", game_id="beta", selected=True)
    repository.save_many((alpha_first, alpha_second, beta))

    assert repository.get_selected("alpha") == alpha_first
    assert repository.get_selected("beta") == beta

    selected = repository.select("alpha", "alpha.second")

    assert selected.installation_id == "alpha.second"
    assert selected.selected is True
    assert repository.get_selected("alpha") == selected
    assert repository.get("alpha.first") == replace(alpha_first, selected=False)
    assert repository.get_selected("beta") == beta
    assert {
        item.installation_id for item in repository.list(selected_only=True)
    } == {"alpha.second", "beta.local"}


def test_save_many_rejects_duplicate_ids_without_partial_writes(
    tmp_path: Path,
) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    first = make_installation(tmp_path, "alpha.local")
    different_root = tmp_path / "different-root"
    duplicate = replace(
        first,
        root=different_root,
        executable=different_root / "alpha.exe",
    )

    with pytest.raises(PersistenceConflictError):
        repository.save_many((first, duplicate))

    assert repository.list() == ()


def test_save_many_rejects_multiple_selected_for_one_game_atomically(
    tmp_path: Path,
) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    first = make_installation(tmp_path, "alpha.first", selected=True)
    second = make_installation(tmp_path, "alpha.second", selected=True)

    with pytest.raises(PersistenceConflictError):
        repository.save_many((first, second))

    assert repository.list() == ()


def test_repository_filters_selects_and_deletes(tmp_path: Path) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    alpha_mock = make_installation(
        tmp_path, "alpha.mock-local", game_id="alpha", adapter_id="alpha.mock"
    )
    alpha_other = make_installation(
        tmp_path, "alpha.other-local", game_id="alpha", adapter_id="alpha.other"
    )
    beta_mock = make_installation(
        tmp_path, "beta.mock-local", game_id="beta", adapter_id="beta.mock"
    )
    repository.save_many((alpha_mock, alpha_other, beta_mock))

    assert set(repository.list(game_id="alpha")) == {alpha_mock, alpha_other}
    assert set(repository.list(adapter_id="alpha.mock")) == {alpha_mock}
    assert repository.list(game_id="missing") == ()
    assert repository.get("missing") is None

    with pytest.raises(InstallationNotFoundError):
        repository.select("alpha", "missing")
    with pytest.raises(InstallationNotFoundError):
        repository.select("beta", alpha_mock.installation_id)

    assert repository.delete(alpha_mock.installation_id) is True
    assert repository.get(alpha_mock.installation_id) is None
    assert repository.delete(alpha_mock.installation_id) is False
    assert set(repository.list()) == {alpha_other, beta_mock}


def test_repository_rejects_non_json_metadata_without_writing(
    tmp_path: Path,
) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    installation = make_installation(
        tmp_path,
        "alpha.local",
        metadata={"not-json": complex(1, 2)},
    )

    with pytest.raises(PersistenceSerializationError):
        repository.save(installation)

    assert repository.get(installation.installation_id) is None


def test_repository_rejects_invalid_unicode_metadata_without_writing(
    tmp_path: Path,
) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    installation = make_installation(
        tmp_path,
        "alpha.local",
        metadata={"invalid": "\ud800"},
    )

    with pytest.raises(PersistenceSerializationError, match="valid Unicode"):
        repository.save(installation)

    assert repository.get(installation.installation_id) is None


def test_repository_rejects_non_finite_numbers_in_persisted_json(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "hub.sqlite3")
    repository = GameInstallationRepository(database)
    installation = make_installation(tmp_path, "alpha.local")
    repository.save(installation)

    with database.transaction() as connection:
        connection.execute(
            "UPDATE game_installations SET metadata_json = ? WHERE installation_id = ?",
            ('{"bad":1e999}', installation.installation_id),
        )

    with pytest.raises(PersistenceSerializationError, match="valid JSON"):
        repository.get(installation.installation_id)


def test_repository_normalizes_corrupt_datetime_errors(tmp_path: Path) -> None:
    database = Database(tmp_path / "hub.sqlite3")
    repository = GameInstallationRepository(database)
    installation = make_installation(tmp_path, "alpha.local")
    repository.save(installation)

    with database.transaction() as connection:
        connection.execute(
            "UPDATE game_installations SET last_seen = ? WHERE installation_id = ?",
            ("9999-12-31T23:59:59-23:59", installation.installation_id),
        )

    with pytest.raises(PersistenceSerializationError, match="ISO-8601"):
        repository.get(installation.installation_id)


def test_repository_normalizes_path_resolution_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    installation = make_installation(tmp_path, "alpha.local")
    repository.save(installation)

    def fail_resolve(self, strict=False):
        raise OSError("fixture path failure")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    with pytest.raises(PersistenceSerializationError, match="deserialize"):
        repository.get(installation.installation_id)
