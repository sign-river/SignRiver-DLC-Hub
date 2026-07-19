"""Immutable contracts for transactional DLC installation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class InstallPhase(StrEnum):
    PLANNED = "planned"
    STAGED = "staged"
    BACKUP_COPIED = "backup_copied"
    BACKED_UP = "backed_up"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


class InstallHealth(StrEnum):
    HEALTHY = "healthy"
    MISSING = "missing"
    MODIFIED = "modified"


@dataclass(frozen=True, slots=True)
class OwnedFile:
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class InstallAudit:
    health: InstallHealth
    missing: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()


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
    installed_tree_sha256: str
    owned_files: tuple[OwnedFile, ...] = ()
    previous_transaction_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiskSpaceRequirement:
    """Conservative free-space requirement for one filesystem."""

    probe_path: Path
    required_bytes: int
    available_bytes: int
    purposes: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        return self.available_bytes >= self.required_bytes


@dataclass(frozen=True, slots=True)
class InstallSpaceEstimate:
    """Space needed before an install starts changing persistent state."""

    expanded_package_bytes: int
    existing_target_bytes: int
    requirements: tuple[DiskSpaceRequirement, ...]

    @property
    def sufficient(self) -> bool:
        return all(item.sufficient for item in self.requirements)


@dataclass(frozen=True, slots=True)
class InstallMaintenanceEntry:
    """One transaction-owned directory proven safe to remove."""

    path: Path
    transaction_id: str
    kind: str
    size_bytes: int
    reason: str


@dataclass(frozen=True, slots=True)
class InstallMaintenancePreview:
    """Read-only result of transaction storage maintenance discovery."""

    candidates: tuple[InstallMaintenanceEntry, ...] = ()
    retained: tuple[str, ...] = ()

    @property
    def reclaimable_bytes(self) -> int:
        return sum(item.size_bytes for item in self.candidates)


@dataclass(frozen=True, slots=True)
class InstallMaintenanceResult:
    """Outcome of an execution pass which re-scanned safety conditions."""

    preview: InstallMaintenancePreview
    removed: tuple[InstallMaintenanceEntry, ...] = ()
    failed: tuple[tuple[InstallMaintenanceEntry, str], ...] = ()
