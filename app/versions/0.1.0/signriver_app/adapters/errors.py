"""Exceptions raised by the game-adapter subsystem."""

from __future__ import annotations

from typing import Any


class AdapterError(Exception):
    """Base class for all adapter-related errors."""


class AdapterRegistrationError(AdapterError):
    """Base class for errors that prevent an adapter from being registered."""


class DuplicateAdapterError(AdapterRegistrationError):
    """Raised when an adapter id is already present in a registry."""

    def __init__(self, adapter_id: str) -> None:
        self.adapter_id = adapter_id
        super().__init__(f"adapter {adapter_id!r} is already registered")


class InvalidAdapterError(AdapterRegistrationError):
    """Raised when an object does not satisfy the adapter contract."""

    def __init__(self, reason: str, *, adapter: Any | None = None) -> None:
        self.reason = reason
        self.adapter = adapter
        super().__init__(f"invalid adapter: {reason}")


class AdapterNotFoundError(AdapterError, LookupError):
    """Raised when an adapter id cannot be found in a registry."""

    def __init__(self, adapter_id: str) -> None:
        self.adapter_id = adapter_id
        super().__init__(f"adapter {adapter_id!r} is not registered")
