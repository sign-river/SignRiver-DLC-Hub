"""Application use cases coordinating domain and infrastructure services."""

from .game_discovery import (
    DiscoveryIssue,
    DiscoveryReport,
    DiscoveryStage,
    GameDiscoveryError,
    GameDiscoveryService,
    GamePathValidationError,
    InstallationAvailability,
    InstallationOrigin,
    InstallationStatus,
    InvalidAdapterResultError,
)
from .dlc_catalog import CatalogSnapshot, ReleaseCatalogService, StellarisCatalogService
from .download_queue import DownloadQueue
from .install_service import AuditedInstallation, DlcInstallService, InstallServiceError

__all__ = [
    "DiscoveryIssue",
    "DiscoveryReport",
    "DiscoveryStage",
    "GameDiscoveryError",
    "GameDiscoveryService",
    "GamePathValidationError",
    "InstallationAvailability",
    "InstallationOrigin",
    "InstallationStatus",
    "InvalidAdapterResultError",
    "CatalogSnapshot",
    "StellarisCatalogService",
    "ReleaseCatalogService",
    "DownloadQueue",
    "AuditedInstallation",
    "DlcInstallService",
    "InstallServiceError",
]
