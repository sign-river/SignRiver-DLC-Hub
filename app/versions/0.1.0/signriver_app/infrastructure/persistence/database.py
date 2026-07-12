"""SQLite connection, transaction, and schema lifecycle management."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike
from pathlib import Path
from time import monotonic, sleep

from .errors import PersistenceError
from .migrations import migrate, schema_version


class Database:
    """Own SQLite configuration while giving each operation its own connection."""

    def __init__(
        self,
        path: str | PathLike[str],
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if isinstance(path, str) and not path.strip():
            raise ValueError("path must be a non-empty filesystem path")
        try:
            path_object = Path(path)
        except (TypeError, ValueError) as exc:
            raise TypeError("path must be path-like") from exc
        try:
            database_path = path_object.expanduser().resolve(strict=False)
        except OSError as exc:
            raise PersistenceError(f"could not resolve database path {path_object}") from exc
        if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int):
            raise TypeError("busy_timeout_ms must be an integer")
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")

        self._path = database_path
        self._busy_timeout_ms = busy_timeout_ms

    @property
    def path(self) -> Path:
        """Filesystem path of the SQLite database."""

        return self._path

    def initialize(self) -> int:
        """Create the database, enable WAL, and apply pending migrations."""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PersistenceError(
                f"could not create database directory {self._path.parent}"
            ) from exc

        with self.connection() as connection:
            self._enable_wal(connection)
            return migrate(connection)

    def schema_version(self) -> int:
        """Return the current database schema version without migrating it."""

        with self.connection() as connection:
            return schema_version(connection)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured connection and always close it afterwards."""

        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(
        self,
        immediate: bool = True,
    ) -> Iterator[sqlite3.Connection]:
        """Yield a transaction that commits on success and rolls back on error."""

        with self.connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise

    def _open_connection(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self._path,
                timeout=self._busy_timeout_ms / 1_000,
            )
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not open database {self._path}") from exc

        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            # PRAGMA assignment cannot use a bound parameter.  The value has
            # already been validated as a non-negative integer.
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        except sqlite3.Error as exc:
            connection.close()
            raise PersistenceError("could not configure SQLite connection") from exc
        return connection

    def _enable_wal(self, connection: sqlite3.Connection) -> None:
        """Enable WAL, retrying lock races up to the configured busy timeout.

        SQLite's journal-mode transition can return ``database is locked``
        without invoking the connection's busy handler on some platforms.
        Concurrent first-run initialization therefore needs a small explicit
        retry loop in addition to ``PRAGMA busy_timeout``.
        """

        deadline = monotonic() + (self._busy_timeout_ms / 1_000)
        while True:
            try:
                row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
                mode = None if row is None else str(row[0]).casefold()
                if mode != "wal":
                    raise PersistenceError(
                        f"could not enable SQLite WAL mode (SQLite reported {mode!r})"
                    )
                return
            except sqlite3.OperationalError as exc:
                locked = "locked" in str(exc).casefold()
                remaining = deadline - monotonic()
                if not locked or remaining <= 0:
                    raise PersistenceError("could not enable SQLite WAL mode") from exc
                sleep(min(0.05, remaining))
            except sqlite3.Error as exc:
                raise PersistenceError("could not enable SQLite WAL mode") from exc


__all__ = ["Database"]
