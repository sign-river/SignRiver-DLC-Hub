from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @classmethod
    def discover(cls) -> "RuntimePaths":
        if getattr(sys, "frozen", False):
            return cls(Path(sys.executable).resolve().parent)
        return cls(Path(__file__).resolve().parents[2])

    @property
    def app_dir(self) -> Path:
        return self.root / "app"

    @property
    def versions_dir(self) -> Path:
        return self.app_dir / "versions"

    @property
    def staging_dir(self) -> Path:
        return self.app_dir / ".staging"

    @property
    def state_file(self) -> Path:
        return self.app_dir / "state.json"

    @property
    def update_config_file(self) -> Path:
        return self.root / "config" / "update.json"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure(self) -> None:
        for directory in (
            self.versions_dir,
            self.staging_dir,
            self.cache_dir,
            self.data_dir,
            self.log_dir,
            self.update_config_file.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
