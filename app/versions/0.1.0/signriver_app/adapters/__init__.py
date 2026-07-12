"""Public game-adapter contracts, registry, and development fixtures."""

from .errors import (
    AdapterError,
    AdapterNotFoundError,
    AdapterRegistrationError,
    DuplicateAdapterError,
    InvalidAdapterError,
)
from .mock import MockGameAdapter
from .protocol import GameAdapter
from .registry import AdapterRegistry

__all__ = [
    "AdapterError",
    "AdapterNotFoundError",
    "AdapterRegistrationError",
    "AdapterRegistry",
    "DuplicateAdapterError",
    "GameAdapter",
    "InvalidAdapterError",
    "MockGameAdapter",
]
