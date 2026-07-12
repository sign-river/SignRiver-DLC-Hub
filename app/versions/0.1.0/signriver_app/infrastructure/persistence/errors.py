"""Exceptions raised by the SQLite persistence subsystem."""

from __future__ import annotations


class PersistenceError(Exception):
    """Base class for persistence failures exposed to application services."""


class MigrationError(PersistenceError):
    """Raised when a database schema cannot be inspected or migrated safely."""


class PersistenceConflictError(PersistenceError):
    """Raised when a write conflicts with an existing persisted record."""


class InstallationNotFoundError(PersistenceError, LookupError):
    """Raised when a requested game installation does not exist."""


class PersistenceSerializationError(PersistenceError, ValueError):
    """Raised when a domain value cannot be serialized or deserialized."""


__all__ = [
    "InstallationNotFoundError",
    "MigrationError",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceSerializationError",
]
