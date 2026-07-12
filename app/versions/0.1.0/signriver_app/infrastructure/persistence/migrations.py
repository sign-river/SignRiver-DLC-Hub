"""Versioned, transactional SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from .errors import MigrationError


LATEST_SCHEMA_VERSION = 2

_MIGRATIONS: dict[int, Sequence[str]] = {
    1: (
        """
        CREATE TABLE game_installations (
            installation_id TEXT PRIMARY KEY NOT NULL,
            game_id TEXT NOT NULL,
            adapter_id TEXT NOT NULL,
            root TEXT NOT NULL,
            executable TEXT,
            platform TEXT NOT NULL,
            source TEXT NOT NULL,
            store TEXT,
            selected INTEGER NOT NULL CHECK (selected IN (0, 1)),
            last_seen TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX idx_game_installations_game_id
        ON game_installations (game_id)
        """,
        """
        CREATE INDEX idx_game_installations_adapter_id
        ON game_installations (adapter_id)
        """,
        """
        CREATE UNIQUE INDEX ux_game_installations_selected_game
        ON game_installations (game_id)
        WHERE selected = 1
        """,
    ),
    2: (
        """
        CREATE TABLE download_tasks (
            task_id TEXT PRIMARY KEY NOT NULL,
            url TEXT NOT NULL,
            filename TEXT NOT NULL,
            expected_size INTEGER,
            expected_sha256 TEXT,
            supports_range INTEGER NOT NULL CHECK (supports_range IN (0, 1)),
            state TEXT NOT NULL,
            bytes_downloaded INTEGER NOT NULL,
            total_bytes INTEGER,
            attempt INTEGER NOT NULL,
            result_path TEXT,
            actual_sha256 TEXT,
            error TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX idx_download_tasks_state ON download_tasks (state)
        """,
    ),
}


def schema_version(connection: sqlite3.Connection) -> int:
    """Return the schema version recorded in SQLite's ``user_version``."""

    try:
        row = connection.execute("PRAGMA user_version").fetchone()
    except sqlite3.Error as exc:
        raise MigrationError("could not read the database schema version") from exc

    if row is None:
        raise MigrationError("SQLite did not return a database schema version")
    version = int(row[0])
    if version < 0:
        raise MigrationError(f"invalid negative database schema version: {version}")
    return version


def migrate(connection: sqlite3.Connection) -> int:
    """Apply every pending migration atomically and return the final version.

    Statements are deliberately executed one by one.  ``executescript`` issues
    an implicit commit in SQLite and would therefore undermine the migration
    transaction and its rollback guarantee.
    """

    current_version: int | None = None
    try:
        # Read ``user_version`` only after taking the write reservation.  This
        # closes the race where two processes both observe an old version and
        # the second process repeats a migration after waiting for the first.
        connection.execute("BEGIN IMMEDIATE")
        current_version = schema_version(connection)
        if current_version > LATEST_SCHEMA_VERSION:
            raise MigrationError(
                "database schema version "
                f"{current_version} is newer than supported version "
                f"{LATEST_SCHEMA_VERSION}"
            )

        for target_version in range(current_version + 1, LATEST_SCHEMA_VERSION + 1):
            try:
                statements = _MIGRATIONS[target_version]
            except KeyError as exc:
                raise MigrationError(
                    f"no migration is registered for schema version {target_version}"
                ) from exc

            for statement in statements:
                connection.execute(statement)
            # PRAGMA assignment cannot use a bound parameter.  The value is an
            # internal integer migration key, never caller-controlled input.
            connection.execute(f"PRAGMA user_version = {target_version}")
        connection.commit()
    except Exception as exc:
        if connection.in_transaction:
            connection.rollback()
        if isinstance(exc, MigrationError):
            raise
        source_version = "unknown" if current_version is None else str(current_version)
        raise MigrationError(
            f"could not migrate database from schema version {source_version}"
        ) from exc

    return schema_version(connection)


__all__ = ["LATEST_SCHEMA_VERSION", "migrate", "schema_version"]
