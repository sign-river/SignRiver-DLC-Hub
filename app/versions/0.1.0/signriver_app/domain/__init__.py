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
from .installs import InstallPhase, InstallPlan, InstallReceipt

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
    "InstallPlan",
    "InstallReceipt",
]
