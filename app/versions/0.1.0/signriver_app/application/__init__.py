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
from .dlc_catalog import StellarisCatalogService
from .download_queue import DownloadQueue

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
    "StellarisCatalogService",
    "DownloadQueue",
]
