"""SQLite repository for validated game installations."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...domain import GameInstallation
from .database import Database
from .errors import (
    InstallationNotFoundError,
    PersistenceConflictError,
    PersistenceError,
    PersistenceSerializationError,
)


_UPSERT = """
    INSERT INTO game_installations (
        installation_id,
        game_id,
        adapter_id,
        root,
        executable,
        platform,
        source,
        store,
        selected,
        last_seen,
        metadata_json,
        created_at,
        updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(installation_id) DO UPDATE SET
        game_id = excluded.game_id,
        adapter_id = excluded.adapter_id,
        root = excluded.root,
        executable = excluded.executable,
        platform = excluded.platform,
        source = excluded.source,
        store = excluded.store,
        selected = excluded.selected,
        last_seen = excluded.last_seen,
        metadata_json = excluded.metadata_json,
        updated_at = excluded.updated_at
"""


class GameInstallationRepository:
    """Persist :class:`GameInstallation` values in a SQLite database."""

    def __init__(self, database: Database) -> None:
        if not isinstance(database, Database):
            raise TypeError("database must be a Database")
        self._database = database
        # Database migrations are idempotent, so a repository is immediately
        # ready for use even when it is the first persistence service created.
        self._database.initialize()

    @property
    def database(self) -> Database:
        """Database used by this repository."""

        return self._database

    def save(self, installation: GameInstallation) -> GameInstallation:
        """Insert or replace one installation and return the stored value."""

        self.save_many((installation,))
        return installation

    def save_many(
        self,
        installations: Iterable[GameInstallation],
    ) -> tuple[GameInstallation, ...]:
        """Upsert a batch atomically.

        A batch cannot contain the same installation twice or select more than
        one installation for the same game.  Selecting an installation clears
        the previous selection for that game in the same transaction.
        """

        try:
            items = tuple(installations)
        except TypeError as exc:
            raise TypeError("installations must be an iterable") from exc

        seen_installations: set[str] = set()
        selected_games: set[str] = set()
        for installation in items:
            if not isinstance(installation, GameInstallation):
                raise TypeError("installations must contain GameInstallation values")
            if installation.installation_id in seen_installations:
                raise PersistenceConflictError(
                    "duplicate installation_id in batch: "
                    f"{installation.installation_id}"
                )
            seen_installations.add(installation.installation_id)
            if installation.selected:
                if installation.game_id in selected_games:
                    raise PersistenceConflictError(
                        "multiple selected installations in batch for game_id: "
                        f"{installation.game_id}"
                    )
                selected_games.add(installation.game_id)

        if not items:
            return ()

        timestamp = _utc_now_text()
        rows = tuple(_installation_to_row(item, timestamp) for item in items)

        try:
            with self._database.transaction() as connection:
                for game_id in selected_games:
                    connection.execute(
                        """
                        UPDATE game_installations
                        SET selected = 0, updated_at = ?
                        WHERE game_id = ? AND selected = 1
                        """,
                        (timestamp, game_id),
                    )
                connection.executemany(_UPSERT, rows)
        except sqlite3.IntegrityError as exc:
            raise PersistenceConflictError(
                "game installation write violated a persistence constraint"
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError("could not save game installations") from exc
        return items

    def get(self, installation_id: str) -> GameInstallation | None:
        """Return an installation by id, or ``None`` when it is absent."""

        try:
            with self._database.connection() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM game_installations
                    WHERE installation_id = ?
                    """,
                    (installation_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not read game installation {installation_id!r}"
            ) from exc
        return None if row is None else _row_to_installation(row)

    def list(
        self,
        game_id: str | None = None,
        adapter_id: str | None = None,
        selected_only: bool = False,
    ) -> tuple[GameInstallation, ...]:
        """List installations matching all supplied filters."""

        if not isinstance(selected_only, bool):
            raise TypeError("selected_only must be a bool")

        predicates: list[str] = []
        parameters: list[object] = []
        if game_id is not None:
            predicates.append("game_id = ?")
            parameters.append(game_id)
        if adapter_id is not None:
            predicates.append("adapter_id = ?")
            parameters.append(adapter_id)
        if selected_only:
            predicates.append("selected = 1")

        where_clause = ""
        if predicates:
            where_clause = " WHERE " + " AND ".join(predicates)
        query = (
            "SELECT * FROM game_installations"
            + where_clause
            + " ORDER BY game_id, installation_id"
        )

        try:
            with self._database.connection() as connection:
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError("could not list game installations") from exc
        return tuple(_row_to_installation(row) for row in rows)

    def get_selected(self, game_id: str) -> GameInstallation | None:
        """Return the selected installation for a game, if there is one."""

        try:
            with self._database.connection() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM game_installations
                    WHERE game_id = ? AND selected = 1
                    """,
                    (game_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not read selected installation for game {game_id!r}"
            ) from exc
        return None if row is None else _row_to_installation(row)

    def select(self, game_id: str, installation_id: str) -> GameInstallation:
        """Make one installation the sole selection for its game."""

        timestamp = _utc_now_text()
        try:
            with self._database.transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT installation_id
                    FROM game_installations
                    WHERE game_id = ? AND installation_id = ?
                    """,
                    (game_id, installation_id),
                ).fetchone()
                if existing is None:
                    raise InstallationNotFoundError(
                        f"installation {installation_id!r} was not found for game "
                        f"{game_id!r}"
                    )

                connection.execute(
                    """
                    UPDATE game_installations
                    SET selected = 0, updated_at = ?
                    WHERE game_id = ?
                      AND selected = 1
                      AND installation_id <> ?
                    """,
                    (timestamp, game_id, installation_id),
                )
                connection.execute(
                    """
                    UPDATE game_installations
                    SET selected = 1, updated_at = ?
                    WHERE game_id = ? AND installation_id = ?
                    """,
                    (timestamp, game_id, installation_id),
                )
                row = connection.execute(
                    """
                    SELECT *
                    FROM game_installations
                    WHERE game_id = ? AND installation_id = ?
                    """,
                    (game_id, installation_id),
                ).fetchone()
        except InstallationNotFoundError:
            raise
        except sqlite3.IntegrityError as exc:
            raise PersistenceConflictError(
                f"could not select installation {installation_id!r}"
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not select installation {installation_id!r}"
            ) from exc

        # The target was checked and updated inside the same write transaction.
        assert row is not None
        return _row_to_installation(row)

    def delete(self, installation_id: str) -> bool:
        """Delete an installation and report whether a row was removed."""

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    "DELETE FROM game_installations WHERE installation_id = ?",
                    (installation_id,),
                )
                deleted = cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not delete game installation {installation_id!r}"
            ) from exc
        return deleted


def _installation_to_row(
    installation: GameInstallation,
    timestamp: str,
) -> tuple[object, ...]:
    last_seen = (
        None if installation.last_seen is None else _datetime_to_utc_text(installation.last_seen)
    )
    return (
        installation.installation_id,
        installation.game_id,
        installation.adapter_id,
        _validated_text(str(installation.root), "root"),
        (
            None
            if installation.executable is None
            else _validated_text(str(installation.executable), "executable")
        ),
        installation.platform,
        installation.source,
        installation.store,
        int(installation.selected),
        last_seen,
        _encode_metadata(installation.metadata),
        timestamp,
        timestamp,
    )


def _row_to_installation(row: sqlite3.Row) -> GameInstallation:
    try:
        selected_value = row["selected"]
        if selected_value not in (0, 1):
            raise PersistenceSerializationError(
                f"invalid selected value in row: {selected_value!r}"
            )
        last_seen_value = row["last_seen"]
        last_seen = (
            None
            if last_seen_value is None
            else _datetime_from_text(last_seen_value, "last_seen")
        )
        metadata = _decode_metadata(row["metadata_json"])
        return GameInstallation(
            installation_id=row["installation_id"],
            game_id=row["game_id"],
            adapter_id=row["adapter_id"],
            root=Path(row["root"]),
            executable=(
                None if row["executable"] is None else Path(row["executable"])
            ),
            platform=row["platform"],
            source=row["source"],
            store=row["store"],
            selected=bool(selected_value),
            last_seen=last_seen,
            metadata=metadata,
        )
    except PersistenceSerializationError:
        raise
    except (
        IndexError,
        KeyError,
        OSError,
        OverflowError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise PersistenceSerializationError(
            "could not deserialize a game installation row"
        ) from exc


def _encode_metadata(metadata: Mapping[str, Any]) -> str:
    try:
        normalized = _normalize_json_value(metadata, active=set())
        return json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except PersistenceSerializationError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise PersistenceSerializationError("metadata is not valid JSON data") from exc


def _decode_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        raise PersistenceSerializationError("metadata_json must be text")

    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-finite JSON number: {constant}")

    def parse_finite_float(number: str) -> float:
        parsed = float(number)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {number}")
        return parsed

    try:
        decoded = json.loads(
            value,
            parse_constant=reject_constant,
            parse_float=parse_finite_float,
        )
        decoded = _normalize_json_value(decoded, active=set())
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistenceSerializationError("metadata_json is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise PersistenceSerializationError("metadata_json must contain a JSON object")
    return decoded


def _normalize_json_value(value: Any, *, active: set[int]) -> Any:
    value_type = type(value)
    if value is None or value_type in (bool, int):
        return value
    if value_type is str:
        return _validated_text(value, "metadata string")
    if value_type is float:
        if not math.isfinite(value):
            raise PersistenceSerializationError(
                "metadata cannot contain NaN or infinite numbers"
            )
        return value

    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise PersistenceSerializationError("metadata cannot contain cycles")
        active.add(identity)
        try:
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise PersistenceSerializationError(
                        "metadata object keys must be strings"
                    )
                normalized_key = _validated_text(key, "metadata key")
                normalized[normalized_key] = _normalize_json_value(item, active=active)
            return normalized
        finally:
            active.remove(identity)

    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise PersistenceSerializationError("metadata cannot contain cycles")
        active.add(identity)
        try:
            return [_normalize_json_value(item, active=active) for item in value]
        finally:
            active.remove(identity)

    raise PersistenceSerializationError(
        f"metadata contains unsupported value type: {type(value).__name__}"
    )


def _validated_text(value: str, field_name: str) -> str:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise PersistenceSerializationError(
            f"{field_name} must contain valid Unicode text"
        ) from exc
    return value


def _utc_now_text() -> str:
    return _datetime_to_utc_text(datetime.now(timezone.utc))


def _datetime_to_utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PersistenceSerializationError("datetime values must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _datetime_from_text(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise PersistenceSerializationError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise PersistenceSerializationError(
                f"{field_name} must include a timezone"
            )
        return parsed.astimezone(timezone.utc)
    except PersistenceSerializationError:
        raise
    except (OSError, OverflowError, ValueError) as exc:
        raise PersistenceSerializationError(
            f"{field_name} is not a valid ISO-8601 datetime"
        ) from exc


__all__ = ["GameInstallationRepository"]
