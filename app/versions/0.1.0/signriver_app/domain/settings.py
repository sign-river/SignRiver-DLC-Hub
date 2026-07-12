"""User-configurable application settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserSettings:
    download_concurrency: int = 2
    bandwidth_limit_kib: int | None = None
    onboarding_completed: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.download_concurrency <= 8:
            raise ValueError("download concurrency must be between 1 and 8")
        if self.bandwidth_limit_kib is not None and self.bandwidth_limit_kib < 1:
            raise ValueError("bandwidth limit must be positive")
        if not isinstance(self.onboarding_completed, bool):
            raise TypeError("onboarding_completed must be boolean")
