"""User-configurable application settings."""

from __future__ import annotations

from dataclasses import dataclass


_DOWNLOAD_SOURCES = frozenset({"gitlink", "github"})


@dataclass(frozen=True, slots=True)
class UserSettings:
    download_concurrency: int = 1
    bandwidth_limit_kib: int | None = None
    onboarding_completed: bool = False
    download_never_timeout: bool = False
    download_source: str = "gitlink"
    announcement_mute_until_update: bool = False
    announcement_muted_id: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.download_concurrency <= 8:
            raise ValueError("download concurrency must be between 1 and 8")
        if self.bandwidth_limit_kib is not None and self.bandwidth_limit_kib < 1:
            raise ValueError("bandwidth limit must be positive")
        if not isinstance(self.onboarding_completed, bool):
            raise TypeError("onboarding_completed must be boolean")
        if not isinstance(self.download_never_timeout, bool):
            raise TypeError("download_never_timeout must be boolean")
        if not isinstance(self.announcement_mute_until_update, bool):
            raise TypeError("announcement_mute_until_update must be boolean")
        muted_id = str(self.announcement_muted_id or "").strip()
        object.__setattr__(self, "announcement_muted_id", muted_id)
        source = str(self.download_source or "gitlink").strip().lower()
        if source not in _DOWNLOAD_SOURCES:
            raise ValueError("download_source must be gitlink or github")
        object.__setattr__(self, "download_source", source)
