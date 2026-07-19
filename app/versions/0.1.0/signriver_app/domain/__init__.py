"""Immutable domain models for the SignRiver application module."""

from .games import (
    AdapterCapability,
    AdapterDescriptor,
    GameInstallation,
    GameState,
    InstallationCandidate,
    Metadata,
    PathInput,
    ValidationResult,
)
from .catalog import DlcCatalogEntry, NormalizedRelease, ReleaseAsset
from .downloads import DownloadSnapshot, DownloadSpec, DownloadState
from .installs import (
    DiskSpaceRequirement,
    InstallAudit,
    InstallHealth,
    InstallMaintenanceEntry,
    InstallMaintenancePreview,
    InstallMaintenanceResult,
    InstallPhase,
    InstallPlan,
    InstallReceipt,
    InstallSpaceEstimate,
    OwnedFile,
)
from .patches import (
    PatchAssetRole,
    PatchAudit,
    PatchBundle,
    PatchHealth,
    PatchProfile,
    PatchReceipt,
    PatchTemplate,
)
from .settings import UserSettings
from .paths import game_relative_path, normalize_game_relative_directory, resolve_game_directory

__all__ = [
    "AdapterCapability",
    "AdapterDescriptor",
    "GameInstallation",
    "GameState",
    "InstallationCandidate",
    "Metadata",
    "PathInput",
    "ValidationResult",
    "DlcCatalogEntry",
    "NormalizedRelease",
    "ReleaseAsset",
    "DownloadSnapshot",
    "DownloadSpec",
    "DownloadState",
    "InstallPhase",
    "InstallHealth",
    "InstallAudit",
    "DiskSpaceRequirement",
    "InstallSpaceEstimate",
    "InstallMaintenanceEntry",
    "InstallMaintenancePreview",
    "InstallMaintenanceResult",
    "OwnedFile",
    "PatchAssetRole",
    "PatchAudit",
    "PatchBundle",
    "PatchHealth",
    "PatchProfile",
    "PatchReceipt",
    "PatchTemplate",
    "UserSettings",
    "InstallPlan",
    "InstallReceipt",
    "game_relative_path",
    "normalize_game_relative_directory",
    "resolve_game_directory",
]
