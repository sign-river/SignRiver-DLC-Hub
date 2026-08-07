from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .constants import HOST_API_VERSION, LAUNCHER_VERSION
from .models import ReleaseInfo
from .updater import ProgressCallback, UpdateClient


@dataclass(frozen=True)
class PublicPaths:
    root: Path
    data: Path
    cache: Path


class UpdateService:
    """Stable facade exposed to application modules."""

    def __init__(self, client: UpdateClient, current_version: str) -> None:
        self._client = client
        self.current_version = current_version

    @property
    def enabled(self) -> bool:
        return self._client.enabled

    @property
    def check_on_startup(self) -> bool:
        return self._client.settings.check_on_startup

    @property
    def download_source(self) -> str:
        return self._client.settings.download_source

    @property
    def manifest_url(self) -> str:
        return self._client.settings.active_manifest_url

    def set_download_source(self, source: str) -> None:
        self._client.set_download_source(source)

    def check(self) -> ReleaseInfo | None:
        return self._client.check(self.current_version)

    def install(
        self,
        release: ReleaseInfo,
        progress: ProgressCallback | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> str:
        return self._client.install(release, progress, cancel)

    def start_full_update(
        self,
        release: ReleaseInfo,
        progress: ProgressCallback | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> str:
        return self._client.start_full_update(release, progress, cancel).version


@dataclass(frozen=True)
class HostContext:
    app_version: str
    launcher_version: str
    api_version: int
    paths: PublicPaths
    updates: UpdateService
    logger: logging.Logger

    def restart(self) -> None:
        """Restart through the stable host so modules do not manage process details."""
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable], cwd=self.paths.root)
            os._exit(0)
        launcher = self.paths.root / "launcher.py"
        os.execl(sys.executable, sys.executable, str(launcher))

    def exit_for_full_update(self) -> None:
        """Exit without spawning the current launcher again; the helper starts the new one."""
        os._exit(0)

    @classmethod
    def create(
        cls,
        app_version: str,
        root: Path,
        data: Path,
        cache: Path,
        updater: UpdateClient,
        logger: logging.Logger,
    ) -> "HostContext":
        return cls(
            app_version=app_version,
            launcher_version=LAUNCHER_VERSION,
            api_version=HOST_API_VERSION,
            paths=PublicPaths(root=root, data=data, cache=cache),
            updates=UpdateService(updater, app_version),
            logger=logger,
        )
