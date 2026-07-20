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
from .cartridge_catalog import (
    CartridgeCatalogError,
    CartridgeCatalogService,
    LoadedCartridge,
)
from .download_queue import DownloadQueue
from .install_service import AuditedInstallation, DlcInstallService, InstallServiceError
from .original_restore import (
    OriginalStateRestoreService,
    RestoreOriginalError,
    RestorePreview,
    RestoreResult,
)

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
    "CartridgeCatalogError",
    "CartridgeCatalogService",
    "LoadedCartridge",
    "DownloadQueue",
    "AuditedInstallation",
    "DlcInstallService",
    "InstallServiceError",
    "OriginalStateRestoreService",
    "RestoreOriginalError",
    "RestorePreview",
    "RestoreResult",
]
