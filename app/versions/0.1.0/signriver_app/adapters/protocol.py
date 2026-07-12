"""Public contract implemented by game-specific adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain import (
    AdapterDescriptor,
    GameInstallation,
    GameState,
    InstallationCandidate,
    ValidationResult,
)


@runtime_checkable
class GameAdapter(Protocol):
    """Translate game-specific discovery and inspection into domain models.

    Adapters only describe a game's local installation.  Downloading packages
    and mutating game files belong to higher-level services so those operations
    can share the same safety and transaction policies for every game.
    """

    @property
    def descriptor(self) -> AdapterDescriptor:
        """Return immutable identity metadata that must remain stable."""

        ...

    def discover(self) -> list[InstallationCandidate]:
        """Return installation candidates found on the current machine."""

        ...

    def validate(self, root: Path) -> ValidationResult:
        """Validate a discovered or user-selected game root."""

        ...

    def inspect(self, installation: GameInstallation) -> GameState:
        """Inspect the current state of a validated game installation."""

        ...
