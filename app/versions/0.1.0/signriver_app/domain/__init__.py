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
from .installs import InstallAudit, InstallHealth, InstallPhase, InstallPlan, InstallReceipt, OwnedFile
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
]
