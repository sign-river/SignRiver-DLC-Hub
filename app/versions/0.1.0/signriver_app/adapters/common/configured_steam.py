"""Declarative cross-platform Steam adapter used by non-specialized cartridges."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from signriver_common.platforms import HostPlatform, is_process_running

from ...domain import (
    AdapterCapability, AdapterDescriptor, GameInstallation, GameState,
    InstallationCandidate, ValidationResult, game_relative_path,
    normalize_game_relative_directory, resolve_game_directory,
)
from .steam import SteamInstallationLocator


class ConfiguredSteamAdapter:
    def __init__(
        self,
        *,
        game_id: str,
        display_name: str,
        steam_app_id: str,
        executable_relative_path: str,
        required_relative_dirs: Iterable[str] = (),
        locator: SteamInstallationLocator | None = None,
        process_checker: Callable[[Path], bool] | None = None,
        platform: str = "windows",
    ) -> None:
        if not steam_app_id.isdigit():
            raise ValueError("Steam App ID must be numeric")
        if str(platform or "").strip() not in {"windows", "steamos", "macos"}:
            raise ValueError("unsupported Steam adapter platform")
        self.steam_app_id = steam_app_id
        self.platform = str(platform or "windows").strip()
        executable = normalize_game_relative_directory(
            executable_relative_path, field_name="game executable path"
        )
        if executable == ".":
            raise ValueError("game executable path must name a file")
        self.executable_relative_path = executable
        self.required_relative_dirs = tuple(
            normalize_game_relative_directory(item, field_name="required game directory")
            for item in required_relative_dirs
        )
        self._descriptor = AdapterDescriptor(
            adapter_id=f"{game_id}.steam",
            adapter_version="1.0.0",
            game_id=game_id,
            display_name=display_name,
            platforms=(self.platform,),
            stores=("steam",),
            capabilities=frozenset({
                AdapterCapability.AUTO_DISCOVERY,
                AdapterCapability.LAUNCH,
            }),
        )
        self._locator = locator or SteamInstallationLocator()
        self._process_checker = process_checker or (
            _is_process_running
            if self.platform == "windows"
            else lambda executable: is_process_running(
                executable, HostPlatform(self.platform)
            )
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    @property
    def locator(self) -> SteamInstallationLocator:
        return self._locator

    def _executable(self, root: Path) -> Path:
        return root / game_relative_path(
            self.executable_relative_path, field_name="game executable path"
        )

    def discover(self) -> list[InstallationCandidate]:
        candidates: list[InstallationCandidate] = []
        for installation in self._locator.find_app(self.steam_app_id):
            metadata: dict[str, object] = {
                "steam_app_id": installation.app_id,
                "steam_manifest": str(installation.manifest_path),
                "steam_library": str(installation.library_root),
            }
            if installation.build_id is not None:
                metadata["steam_build_id"] = installation.build_id
            candidates.append(InstallationCandidate(
                root=installation.root,
                executable=self._executable(installation.root),
                source="steam", platform=self.platform, store="steam",
                metadata=metadata,
            ))
        return candidates

    def validate(self, root: Path) -> ValidationResult:
        try:
            normalized_root = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            return ValidationResult.failure(f"无法规范化游戏路径：{error}")
        errors: list[str] = []
        warnings: list[str] = []
        if not normalized_root.is_dir():
            errors.append("游戏目录不存在")
        executable = self._executable(normalized_root)
        if not executable.is_file():
            missing_executable = f"未找到启动文件：{self.executable_relative_path}"
            if self.platform == "windows" or not self._has_steam_api_library(normalized_root):
                errors.append(missing_executable)
            else:
                warnings.append(missing_executable)
        for relative in self.required_relative_dirs:
            try:
                directory = resolve_game_directory(
                    normalized_root, relative,
                    field_name="required game directory", strict_root=False,
                )
            except ValueError as error:
                errors.append(str(error))
                continue
            if not directory.is_dir():
                errors.append(f"未找到必要目录：{relative}")
        metadata = {"steam_app_id": self.steam_app_id}
        if errors:
            return ValidationResult.failure(
                errors, normalized_root=normalized_root,
                executable=executable if executable.is_file() else None,
                platform=self.platform, source="steam", store="steam",
                metadata=metadata, warnings=warnings,
            )
        return ValidationResult.success(
            normalized_root, executable=executable,
            platform=self.platform, source="steam", store="steam",
            metadata=metadata, warnings=warnings,
        )

    def inspect(self, installation: GameInstallation) -> GameState:
        if installation.game_id != self.descriptor.game_id:
            raise ValueError("installation game_id does not belong to this cartridge")
        if installation.adapter_id != self.descriptor.adapter_id:
            raise ValueError("installation adapter_id does not belong to this cartridge")
        validation = self.validate(installation.root)
        warnings = list(validation.warnings)
        running = False
        if validation.executable is not None:
            try:
                running = bool(self._process_checker(validation.executable))
            except Exception as error:
                warnings.append(f"无法检查游戏进程：{error}")
        if not validation.valid:
            warnings.extend(validation.errors)
        return GameState(
            game_version=validation.game_version,
            running=running, healthy=validation.valid,
            warnings=tuple(warnings), metadata=validation.metadata,
        )


    @staticmethod
    def _has_steam_api_library(root: Path) -> bool:
        for name in ("libsteam_api.so", "libsteam_api.dylib"):
            if (root / name).is_file():
                return True
        return False


def _is_process_running(executable: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {executable.name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise OSError("tasklist 进程检查超时（5 秒内未响应）") from error
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "tasklist 进程检查失败")
    return executable.name.casefold() in result.stdout.casefold()


__all__ = ["ConfiguredSteamAdapter"]
