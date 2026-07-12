"""SQLite persistence services used by the application module."""

from .database import Database
from .errors import (
    InstallationNotFoundError,
    MigrationError,
    PersistenceConflictError,
    PersistenceError,
    PersistenceSerializationError,
)
from .game_installations import GameInstallationRepository
from .migrations import LATEST_SCHEMA_VERSION
from .download_tasks import DownloadTaskRepository
from .install_receipts import InstallReceiptRepository
from .settings import UserSettingsRepository

__all__ = [
    "Database",
    "GameInstallationRepository",
    "InstallationNotFoundError",
    "LATEST_SCHEMA_VERSION",
    "DownloadTaskRepository",
    "InstallReceiptRepository",
    "UserSettingsRepository",
    "MigrationError",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceSerializationError",
]
