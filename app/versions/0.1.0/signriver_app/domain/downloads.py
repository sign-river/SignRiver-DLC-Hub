"""Download task contracts shared by the manager, persistence and UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path


class DownloadState(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSING = "pausing"
    PAUSED = "paused"
    RETRYING = "retrying"
    VERIFYING = "verifying"
    READY = "ready"
    CANCELLED = "cancelled"
    FAILED = "failed"
    CORRUPT = "corrupt"


class DownloadPurpose(StrEnum):
    DLC_PACKAGE = "dlc_package"
    PATCH_BINARY = "patch_binary"
    PATCH_METADATA = "patch_metadata"


class DownloadStage(StrEnum):
    PREPARE = "prepare"
    CONNECT = "connect"
    READ = "read"
    WRITE = "write"
    FLUSH = "flush"
    VERIFY = "verify"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True)
class DownloadSpec:
    task_id: str
    url: str
    filename: str
    game_id: str
    expected_size: int | None = None
    expected_sha256: str | None = None
    supports_range: bool = False
    part_urls: tuple[str, ...] = ()
    purpose: DownloadPurpose = DownloadPurpose.DLC_PACKAGE

    @property
    def urls(self) -> tuple[str, ...]:
        return self.part_urls or (self.url,)


@dataclass(frozen=True, slots=True)
class DownloadSnapshot:
    spec: DownloadSpec
    state: DownloadState = DownloadState.QUEUED
    bytes_downloaded: int = 0
    total_bytes: int | None = None
    attempt: int = 0
    result_path: Path | None = None
    sha256: str | None = None
    error: str | None = None
    speed_bytes_per_second: float | None = None
    eta_seconds: float | None = None
    failure_code: str | None = None
    failure_stage: DownloadStage | None = None

    def evolve(self, **changes) -> "DownloadSnapshot":
        return replace(self, **changes)
