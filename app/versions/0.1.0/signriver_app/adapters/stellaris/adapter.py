"""Windows Steam adapter for Stellaris."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from ..common import SteamInstallationLocator
from ...domain import (
    AdapterCapability,
    AdapterDescriptor,
    GameInstallation,
    GameState,
    InstallationCandidate,
    ValidationResult,
    normalize_game_relative_directory,
    resolve_game_directory,
)


STELLARIS_STEAM_APP_ID = "281990"
MAX_LAUNCHER_SETTINGS_BYTES = 1024 * 1024
_DLC_DIRECTORY = re.compile(r"^(dlc\d{3})_[a-z0-9_]+$", re.I)


def discover_installed_dlc(game_root: Path, dlc_relative_dir: str = "dlc") -> dict[str, Path]:
    """Return DLC IDs whose package directory exists in a Stellaris install."""
    try:
        dlc_root = resolve_game_directory(
            game_root, dlc_relative_dir,
            field_name="DLC install directory", strict_root=False,
        )
    except (OSError, ValueError):
        return {}
    try:
        children = tuple(dlc_root.iterdir())
    except OSError:
        return {}
    installed = {}
    for path in children:
        match = _DLC_DIRECTORY.fullmatch(path.name)
        if match is not None and path.is_dir():
            installed[match.group(1).casefold()] = path
    return installed


def remove_installed_dlc(
    game_root: Path, dlc_id: str, dlc_relative_dir: str = "dlc"
) -> Path:
    """Remove one recognized DLC directory without escaping the game DLC root."""
    if not re.fullmatch(r"dlc\d{3}", dlc_id, re.I):
        raise ValueError("invalid Stellaris DLC ID")
    root = Path(game_root).resolve(strict=True)
    dlc_root = resolve_game_directory(
        root, dlc_relative_dir, field_name="DLC install directory"
    ).resolve(strict=True)
    target = discover_installed_dlc(root, dlc_relative_dir).get(dlc_id.casefold())
    if target is None:
        raise FileNotFoundError(f"installed DLC directory not found: {dlc_id}")
    resolved = target.resolve(strict=True)
    if resolved.parent != dlc_root or _DLC_DIRECTORY.fullmatch(resolved.name) is None:
        raise ValueError("refusing to remove an unsafe DLC directory")
    shutil.rmtree(resolved)
    return resolved


class StellarisSteamAdapter:
    """Discover and validate the Windows Steam edition of Stellaris."""

    _descriptor = AdapterDescriptor(
        adapter_id="stellaris.steam",
        adapter_version="1.0.0",
        game_id="stellaris",
        display_name="Stellaris",
        platforms=("windows",),
        stores=("steam",),
        capabilities=frozenset(
            {
                AdapterCapability.AUTO_DISCOVERY,
                AdapterCapability.LAUNCH,
            }
        ),
    )

    def __init__(
        self,
        locator: SteamInstallationLocator | None = None,
        process_checker: Callable[[Path], bool] | None = None,
        dlc_relative_dir: str = "dlc",
        executable_name: str = "stellaris.exe",
    ) -> None:
        self._locator = SteamInstallationLocator() if locator is None else locator
        self._process_checker = (
            _is_process_running if process_checker is None else process_checker
        )
        self._dlc_relative_dir = normalize_game_relative_directory(
            dlc_relative_dir, field_name="DLC install directory"
        )
        if not executable_name or Path(executable_name).name != executable_name:
            raise ValueError("game executable must be a plain filename")
        self._executable_name = executable_name

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    @property
    def locator(self) -> SteamInstallationLocator:
        return self._locator

    def discover(self) -> list[InstallationCandidate]:
        candidates: list[InstallationCandidate] = []
        for installation in self._locator.find_app(STELLARIS_STEAM_APP_ID):
            metadata: dict[str, object] = {
                "steam_app_id": installation.app_id,
                "steam_manifest": str(installation.manifest_path),
                "steam_library": str(installation.library_root),
            }
            if installation.build_id is not None:
                metadata["steam_build_id"] = installation.build_id
            if installation.state_flags is not None:
                metadata["steam_state_flags"] = installation.state_flags
            candidates.append(
                InstallationCandidate(
                    root=installation.root,
                    executable=installation.root / self._executable_name,
                    source="steam",
                    platform="windows",
                    store="steam",
                    metadata=metadata,
                )
            )
        return candidates

    def validate(self, root: Path) -> ValidationResult:
        try:
            normalized_root = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return ValidationResult.failure(f"无法规范化游戏路径：{exc}")

        errors: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, object] = {"steam_app_id": STELLARIS_STEAM_APP_ID}
        if not normalized_root.is_dir():
            errors.append("游戏目录不存在")

        executable = normalized_root / self._executable_name
        launcher_settings_path = normalized_root / "launcher-settings.json"
        steam_appid_path = normalized_root / "steam_appid.txt"
        if not executable.is_file():
            errors.append("未找到 stellaris.exe")
        for directory_name in ("common",):
            if not (normalized_root / directory_name).is_dir():
                errors.append(f"未找到必要目录：{directory_name}")

        try:
            dlc_root = resolve_game_directory(
                normalized_root,
                self._dlc_relative_dir,
                field_name="DLC install directory",
                strict_root=False,
            )
            if not dlc_root.is_dir():
                errors.append(f"未找到必要目录：{self._dlc_relative_dir}")
        except ValueError as error:
            errors.append(str(error))

        settings: Mapping[str, object] | None = None
        if not launcher_settings_path.is_file():
            errors.append("未找到 launcher-settings.json")
        else:
            try:
                settings = _read_launcher_settings(launcher_settings_path)
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(f"无法读取 launcher-settings.json：{exc}")

        if settings is not None:
            if settings.get("gameId") != "stellaris":
                errors.append("launcher-settings.json 的 gameId 不是 stellaris")
            if str(settings.get("distPlatform", "")).casefold() != "steam":
                errors.append("当前目录不是 Stellaris Steam 版本")
            configured_executable = settings.get("exePath")
            if isinstance(configured_executable, str) and configured_executable:
                try:
                    configured_path = (
                        normalized_root / configured_executable
                    ).resolve(strict=False)
                    configured_path.relative_to(normalized_root)
                    if (
                        os.path.normcase(str(configured_path))
                        != os.path.normcase(str(executable.resolve(strict=False)))
                        or not configured_path.is_file()
                    ):
                        errors.append("启动器配置未指向 stellaris.exe")
                except (OSError, RuntimeError, ValueError):
                    errors.append("启动器配置的 exePath 不安全")
            else:
                errors.append("启动器配置缺少 exePath")

            for key in ("version", "rawVersion", "modsCompatibilityVersion"):
                value = settings.get(key)
                if isinstance(value, str) and value:
                    metadata[key] = value

        if not steam_appid_path.is_file():
            errors.append("未找到 steam_appid.txt")
        else:
            try:
                declared_app_id = steam_appid_path.read_text(
                    encoding="utf-8-sig"
                ).strip()
            except (OSError, UnicodeError) as exc:
                errors.append(f"无法读取 steam_appid.txt：{exc}")
            else:
                if declared_app_id != STELLARIS_STEAM_APP_ID:
                    errors.append(
                        "steam_appid.txt 与 Stellaris Steam App ID 不一致"
                    )

        if errors:
            return ValidationResult.failure(
                errors,
                normalized_root=normalized_root,
                executable=(executable if executable.is_file() else None),
                platform="windows",
                source="steam",
                store="steam",
                warnings=warnings,
                metadata=metadata,
            )

        raw_version = metadata.get("rawVersion")
        game_version = (
            raw_version.removeprefix("v")
            if isinstance(raw_version, str)
            else None
        )
        return ValidationResult.success(
            normalized_root,
            executable=executable,
            platform="windows",
            source="steam",
            store="steam",
            game_version=game_version,
            warnings=warnings,
            metadata=metadata,
        )

    def inspect(self, installation: GameInstallation) -> GameState:
        if installation.game_id != self.descriptor.game_id:
            raise ValueError("installation game_id does not belong to Stellaris")
        if installation.adapter_id != self.descriptor.adapter_id:
            raise ValueError("installation adapter_id does not belong to this adapter")

        validation = self.validate(installation.root)
        warnings = list(validation.warnings)
        running = False
        if validation.executable is not None:
            try:
                running = bool(self._process_checker(validation.executable))
            except Exception as exc:
                warnings.append(f"无法检查游戏进程：{exc}")
        if not validation.valid:
            warnings.extend(validation.errors)
        return GameState(
            game_version=validation.game_version,
            running=running,
            healthy=validation.valid,
            warnings=tuple(warnings),
            metadata=validation.metadata,
        )


def _read_launcher_settings(path: Path) -> Mapping[str, object]:
    with path.open("rb") as file:
        raw = file.read(MAX_LAUNCHER_SETTINGS_BYTES + 1)
    if len(raw) > MAX_LAUNCHER_SETTINGS_BYTES:
        raise ValueError("launcher-settings.json 过大")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("launcher-settings.json 根节点必须是对象")
    return value


def _is_process_running(executable: Path) -> bool:
    if os.name != "nt":
        return False
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [
            "tasklist",
            "/FI",
            f"IMAGENAME eq {executable.name}",
            "/FO",
            "CSV",
            "/NH",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        creationflags=creation_flags,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "tasklist 执行失败")
    return executable.name.casefold() in result.stdout.casefold()


__all__ = [
    "STELLARIS_STEAM_APP_ID", "StellarisSteamAdapter",
    "discover_installed_dlc", "remove_installed_dlc",
]
