from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from signriver_common.platforms import HostPlatform, detect_host_platform


@dataclass(frozen=True)
class RuntimePaths:
    """Writable runtime state plus the immutable/native installation root."""

    root: Path
    install_root: Path | None = None
    host_platform: HostPlatform | None = None
    cache_root: Path | None = None

    @classmethod
    def discover(cls) -> "RuntimePaths":
        platform = detect_host_platform()
        source_root = Path(__file__).resolve().parents[2]
        if not getattr(sys, "frozen", False):
            return cls(source_root, source_root, platform, source_root / "cache")
        executable = Path(sys.executable).resolve()
        if platform is HostPlatform.WINDOWS:
            install = executable.parent
            return cls(install, install, platform, install / "cache")
        if platform is HostPlatform.MACOS:
            install = next(
                (parent for parent in executable.parents if parent.suffix == ".app"),
                executable.parent,
            )
            data_home = Path.home() / "Library" / "Application Support" / "SignRiver DLC Hub"
            cache = Path.home() / "Library" / "Caches" / "SignRiver DLC Hub"
            return cls(data_home, install, platform, cache)
        install = executable.parent
        data_home = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        ) / "signriver-dlc-hub"
        cache = Path(
            os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
        ) / "signriver-dlc-hub"
        return cls(data_home, install, platform, cache)

    @property
    def platform(self) -> HostPlatform:
        return self.host_platform or detect_host_platform()

    @property
    def resources_root(self) -> Path:
        install = Path(self.install_root or self.root)
        mac_runtime = install / "Contents" / "Resources" / "runtime"
        if self.platform is HostPlatform.MACOS and mac_runtime.is_dir():
            return mac_runtime
        return install

    @property
    def launcher_relative_path(self) -> Path:
        if self.platform is HostPlatform.WINDOWS:
            from .product import RELEASE_EXE_NAME
            return Path(RELEASE_EXE_NAME)
        if self.platform is HostPlatform.MACOS:
            return Path("Contents/MacOS/SignRiver-DLC-Hub")
        return Path("SignRiver-DLC-Hub")

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
    def update_defaults_config_file(self) -> Path:
        return self.root / "config" / "defaults" / "update.json"

    @property
    def user_update_config_file(self) -> Path:
        return self.data_dir / "config" / "update.json"

    @property
    def cache_dir(self) -> Path:
        return Path(self.cache_root or (self.root / "cache"))

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def update_data_dir(self) -> Path:
        return self.data_dir / "update"

    @property
    def full_update_staging_dir(self) -> Path:
        return self.cache_dir / "update-staging"

    @property
    def full_update_backup_dir(self) -> Path:
        return self.cache_dir / "update-backup"

    @property
    def update_cache_dir(self) -> Path:
        return self.cache_dir / "updates"

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
            self.update_data_dir,
            self.full_update_staging_dir,
            self.full_update_backup_dir,
            self.update_cache_dir,
            self.update_config_file.parent,
            self.user_update_config_file.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._seed_packaged_runtime()

    def managed_target(self, relative: str) -> Path:
        """Map app/config state to the writable root and binaries to install."""
        normalized = relative.replace("\\", "/")
        mac_prefix = "Contents/Resources/runtime/"
        if normalized.startswith(mac_prefix):
            logical = normalized[len(mac_prefix):]
            if logical.split("/", 1)[0] in {"app", "config"}:
                return self.root.joinpath(*logical.split("/"))
        first = normalized.split("/", 1)[0]
        base = self.root if first in {"app", "config"} else Path(self.install_root or self.root)
        return base.joinpath(*normalized.split("/"))

    def _seed_packaged_runtime(self) -> None:
        source = self.resources_root
        if source.resolve(strict=False) == self.root.resolve(strict=False):
            return
        for relative in (Path("app") / "state.json", Path("config") / "update.json"):
            origin = source / relative
            target = self.root / relative
            if origin.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, target)
        packaged_versions = source / "app" / "versions"
        if packaged_versions.is_dir():
            for origin in packaged_versions.iterdir():
                if not origin.is_dir():
                    continue
                target = self.versions_dir / origin.name
                if not target.exists():
                    shutil.copytree(origin, target)
        for relative in (
            Path("config") / "defaults",
            Path("config") / "cartridges",
        ):
            origin = source / relative
            target = self.root / relative
            if origin.is_dir() and not target.exists():
                shutil.copytree(origin, target)
        announcement = source / "config" / "announcement.json"
        if announcement.is_file() and not (self.root / "config" / announcement.name).exists():
            shutil.copy2(announcement, self.root / "config" / announcement.name)
        for icon_name in ("app.ico", "app.png"):
            icon = source / "config" / icon_name
            if icon.is_file() and not (self.root / "config" / icon_name).exists():
                shutil.copy2(icon, self.root / "config" / icon_name)
