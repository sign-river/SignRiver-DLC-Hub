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
from .catalog import CatalogSnapshot, CatalogTrust, DlcCatalogEntry, NormalizedRelease, ReleaseAsset, TrustedCatalogAsset
from .downloads import DownloadSnapshot, DownloadSpec, DownloadState
from .installs import InstallAudit, InstallHealth, InstallPhase, InstallPlan, InstallReceipt, OwnedFile
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
    "CatalogSnapshot",
    "CatalogTrust",
    "TrustedCatalogAsset",
    "DownloadSnapshot",
    "DownloadSpec",
    "DownloadState",
    "InstallPhase",
    "InstallHealth",
    "InstallAudit",
    "OwnedFile",
    "UserSettings",
    "InstallPlan",
    "InstallReceipt",
]
