"""Immutable contracts for transactional DLC installation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class InstallPhase(StrEnum):
    PLANNED = "planned"
    STAGED = "staged"
    BACKED_UP = "backed_up"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class InstallPlan:
    transaction_id: str
    game_id: str
    dlc_id: str
    package_path: Path
    package_sha256: str
    game_root: Path
    relative_target: Path
    staging_root: Path
    backup_root: Path
    journal_path: Path

    @property
    def target_path(self) -> Path:
        return self.game_root / self.relative_target


@dataclass(frozen=True, slots=True)
class InstallReceipt:
    transaction_id: str
    game_id: str
    dlc_id: str
    target_path: Path
    package_sha256: str
    replaced_existing: bool
    backup_path: Path | None

