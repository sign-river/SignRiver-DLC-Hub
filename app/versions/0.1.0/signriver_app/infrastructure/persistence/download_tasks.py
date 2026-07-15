"""SQLite repository for restart-safe download task snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from ...domain import DownloadSnapshot, DownloadSpec, DownloadState
from .database import Database
from .errors import PersistenceError


class DownloadTaskRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.database.initialize()

    def save(self, snapshot: DownloadSnapshot) -> None:
        values = (
            snapshot.spec.task_id, self._stored_url(snapshot.spec), snapshot.spec.filename,
            snapshot.spec.expected_size, snapshot.spec.expected_sha256,
            int(snapshot.spec.supports_range), snapshot.state.value,
            snapshot.bytes_downloaded, snapshot.total_bytes, snapshot.attempt,
            str(snapshot.result_path) if snapshot.result_path else None,
            snapshot.sha256, snapshot.error,
            datetime.now(timezone.utc).isoformat(),
        )
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO download_tasks (
                        task_id, url, filename, expected_size, expected_sha256,
                        supports_range, state, bytes_downloaded, total_bytes,
                        attempt, result_path, actual_sha256, error, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        url=excluded.url, filename=excluded.filename,
                        expected_size=excluded.expected_size,
                        expected_sha256=excluded.expected_sha256,
                        supports_range=excluded.supports_range, state=excluded.state,
                        bytes_downloaded=excluded.bytes_downloaded,
                        total_bytes=excluded.total_bytes, attempt=excluded.attempt,
                        result_path=excluded.result_path,
                        actual_sha256=excluded.actual_sha256, error=excluded.error,
                        updated_at=excluded.updated_at""",
                    values,
                )
        except Exception as error:
            raise PersistenceError("could not save download task") from error

    def list_all(self) -> tuple[DownloadSnapshot, ...]:
        try:
            with self.database.connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM download_tasks ORDER BY updated_at, task_id"
                ).fetchall()
            return tuple(self._from_row(row) for row in rows)
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise PersistenceError("could not load download tasks") from error

    def recoverable(self) -> tuple[DownloadSnapshot, ...]:
        terminal = {
            DownloadState.READY, DownloadState.CANCELLED,
            DownloadState.FAILED, DownloadState.CORRUPT,
        }
        return tuple(item for item in self.list_all() if item.state not in terminal)

    def delete_terminal(self) -> int:
        terminal = tuple(state.value for state in (
            DownloadState.CANCELLED, DownloadState.FAILED, DownloadState.CORRUPT,
        ))
        placeholders = ",".join("?" for _ in terminal)
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    f"DELETE FROM download_tasks WHERE state IN ({placeholders})",
                    terminal,
                )
                return cursor.rowcount
        except Exception as error:
            raise PersistenceError("could not clear completed download tasks") from error

    def delete_all(self) -> int:
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute("DELETE FROM download_tasks")
                return cursor.rowcount
        except Exception as error:
            raise PersistenceError("could not clear download task history") from error

    def delete(self, task_id: str) -> bool:
        """Drop a single task record; returns True when a row was removed."""
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "DELETE FROM download_tasks WHERE task_id = ?", (task_id,)
                )
                return cursor.rowcount > 0
        except Exception as error:
            raise PersistenceError("could not delete download task") from error

    @staticmethod
    def _from_row(row) -> DownloadSnapshot:
        raw_url = str(row["url"])
        part_urls: tuple[str, ...] = ()
        url = raw_url
        if raw_url.startswith("multipart:"):
            try:
                value = json.loads(raw_url.removeprefix("multipart:"))
                if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
                    part_urls = tuple(value)
                    url = part_urls[0]
            except json.JSONDecodeError:
                pass
        spec = DownloadSpec(
            task_id=row["task_id"], url=url, filename=row["filename"],
            expected_size=row["expected_size"],
            expected_sha256=row["expected_sha256"],
            supports_range=bool(row["supports_range"]),
            part_urls=part_urls,
        )
        return DownloadSnapshot(
            spec=spec, state=DownloadState(row["state"]),
            bytes_downloaded=row["bytes_downloaded"],
            total_bytes=row["total_bytes"], attempt=row["attempt"],
            result_path=Path(row["result_path"]) if row["result_path"] else None,
            sha256=row["actual_sha256"], error=row["error"],
        )

    @staticmethod
    def _stored_url(spec: DownloadSpec) -> str:
        if not spec.part_urls:
            return spec.url
        return "multipart:" + json.dumps(spec.part_urls, ensure_ascii=True, separators=(",", ":"))
