"""SQLite storage for user settings."""

from __future__ import annotations

from datetime import datetime, timezone

from ...domain import UserSettings
from .database import Database
from .errors import PersistenceError


class UserSettingsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.database.initialize()

    def load(self) -> UserSettings:
        try:
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT download_concurrency, bandwidth_limit_kib, onboarding_completed, "
                    "download_never_timeout "
                    "FROM user_settings WHERE singleton=1"
                ).fetchone()
            if row is None:
                return UserSettings()
            return UserSettings(
                row["download_concurrency"], row["bandwidth_limit_kib"],
                bool(row["onboarding_completed"]),
                bool(row["download_never_timeout"]),
            )
        except Exception as error:
            raise PersistenceError("could not load user settings") from error

    def save(self, settings: UserSettings) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO user_settings (
                        singleton, download_concurrency, bandwidth_limit_kib,
                        updated_at, onboarding_completed, download_never_timeout
                    ) VALUES (1, ?, ?, ?, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        download_concurrency=excluded.download_concurrency,
                        bandwidth_limit_kib=excluded.bandwidth_limit_kib,
                        updated_at=excluded.updated_at,
                        onboarding_completed=excluded.onboarding_completed,
                        download_never_timeout=excluded.download_never_timeout""",
                    (
                        settings.download_concurrency, settings.bandwidth_limit_kib,
                        now, int(settings.onboarding_completed),
                        int(settings.download_never_timeout),
                    ),
                )
        except Exception as error:
            raise PersistenceError("could not save user settings") from error
