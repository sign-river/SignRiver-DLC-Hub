"""Collect a bounded, redacted support folder for the selected game."""

from __future__ import annotations

import json
import os
import platform as platform_module
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from .exporter import DiagnosticExporter


@dataclass(frozen=True, slots=True)
class SupportPathSpec:
    """One explicitly allowed support-file pattern.

    ``pattern`` only expands the documented root placeholders and may contain a
    filename glob.  Recursive globs are deliberately unsupported.
    """

    pattern: str
    label: str


@dataclass(frozen=True, slots=True)
class GameSupportProfile:
    game_id: str
    paths: tuple[SupportPathSpec, ...]
    dump_patterns: tuple[SupportPathSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class SupportCollectionResult:
    output_dir: Path
    copied: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]
    skipped_dumps: tuple[str, ...]

    @property
    def summary(self) -> str:
        return (
            f"已整理 {len(self.copied)} 个文件；"
            f"跳过 {len(self.skipped)} 项；"
            f"失败 {len(self.failed)} 项。"
        )


_PARADOX_LOG_NAMES = ("error.log", "exceptions.log", "game.log", "system.log")
_GAME_ROOT_NAMES = (
    "system.log", "error.log", "exceptions.log", "settings.txt", "Player.log",
    "output_log.txt", "AppOptions.txt", "Prefs.xml", "crash-report.txt",
)


def _paths(*patterns: str) -> tuple[SupportPathSpec, ...]:
    return tuple(SupportPathSpec(pattern, Path(pattern).name) for pattern in patterns)


def _paradox_profile(game_id: str, folder: str) -> GameSupportProfile:
    roots = (
        "{documents}/Paradox Interactive/" + folder,
        "{application_support}/Paradox Interactive/" + folder,
        "{local_share}/Paradox Interactive/" + folder,
    )
    log_paths = tuple(
        path
        for root in roots
        for path in (
            *(f"{root}/logs/{name}" for name in _PARADOX_LOG_NAMES),
            f"{root}/settings.txt",
            f"{root}/crashes/*.txt",
        )
    )
    dump_paths = tuple(
        path
        for root in roots
        for path in (f"{root}/crashes/*.dmp", f"{root}/logs/*.dmp")
    )
    return GameSupportProfile(
        game_id,
        _paths(*log_paths),
        _paths(*dump_paths),
    )


# These are intentionally application-owned rather than remote cartridge data:
# the collector must stay available even when a newly downloaded cartridge is
# malformed or when the network is unavailable.
GAME_SUPPORT_PROFILES: dict[str, GameSupportProfile] = {
    "age_of_wonders_4": GameSupportProfile(
        "age_of_wonders_4",
        _paths(
            "{documents}/Paradox Interactive/Age of Wonders 4/Logs/system.log",
            "{documents}/Paradox Interactive/Age of Wonders 4/Logs/error.log",
            "{documents}/Paradox Interactive/Age of Wonders 4/Logs/exceptions.log",
            "{documents}/Paradox Interactive/Age of Wonders 4/settings.txt",
            "{documents}/Paradox Interactive/Age of Wonders 4/crashes/*.txt",
        ),
        _paths("{documents}/Paradox Interactive/Age of Wonders 4/crashes/*.dmp"),
    ),
    "cities_skylines": GameSupportProfile(
        "cities_skylines",
        _paths(
            "{local_app_data}/Colossal Order/Cities_Skylines/Player.log",
            "{local_app_data}/Colossal Order/Cities_Skylines/output_log.txt",
            "{local_low}/Colossal Order/Cities_Skylines/Player.log",
            "{local_low}/Colossal Order/Cities_Skylines/output_log.txt",
            "{local_low}/Colossal Order/Cities_Skylines/Crashes/*.txt",
        ),
        _paths("{local_low}/Colossal Order/Cities_Skylines/*.dmp"),
    ),
    "civilization_6": GameSupportProfile(
        "civilization_6",
        _paths(
            "{documents}/My Games/Sid Meier's Civilization VI/Logs/*.log",
            "{documents}/My Games/Sid Meier's Civilization VI/AppOptions.txt",
            "{documents}/My Games/Sid Meier's Civilization VI/Crashes/*.txt",
        ),
        _paths("{documents}/My Games/Sid Meier's Civilization VI/Crashes/*.dmp"),
    ),
    "civilization_7": GameSupportProfile(
        "civilization_7",
        _paths(
            "{documents}/My Games/Sid Meier's Civilization VII/Logs/*.log",
            "{documents}/My Games/Sid Meier's Civilization VII/AppOptions.txt",
            "{documents}/My Games/Sid Meier's Civilization VII/Crashes/*.txt",
        ),
        _paths("{documents}/My Games/Sid Meier's Civilization VII/Crashes/*.dmp"),
    ),
    "crusader_kings_3": _paradox_profile("crusader_kings_3", "Crusader Kings III"),
    "hearts_of_iron_4": _paradox_profile("hearts_of_iron_4", "Hearts of Iron IV"),
    "rimworld": GameSupportProfile(
        "rimworld",
        _paths(
            "{local_low}/Ludeon Studios/RimWorld by Ludeon Studios/Player.log",
            "{local_low}/Ludeon Studios/RimWorld by Ludeon Studios/Config/Prefs.xml",
            "{local_low}/Ludeon Studios/RimWorld by Ludeon Studios/Crashes/*.txt",
        ),
        _paths("{local_low}/Ludeon Studios/RimWorld by Ludeon Studios/*.dmp"),
    ),
    "stellaris": _paradox_profile("stellaris", "Stellaris"),
    "victoria_3": _paradox_profile("victoria_3", "Victoria 3"),
    "workers_resources_soviet_republic": GameSupportProfile(
        "workers_resources_soviet_republic",
        _paths(
            "{documents}/My Games/Workers & Resources Soviet Republic/logs/*.log",
            "{documents}/My Games/Workers & Resources Soviet Republic/settings.txt",
            "{documents}/My Games/Workers & Resources Soviet Republic/crashes/*.txt",
        ),
        _paths("{documents}/My Games/Workers & Resources Soviet Republic/crashes/*.dmp"),
    ),
}


class SupportBundleCollector:
    """Create a folder of explicitly listed logs without scanning user files."""

    def __init__(
        self,
        app_root: Path,
        data_root: Path,
        *,
        now: Callable[[], datetime] | None = None,
        dxdiag_runner: Callable[..., object] | None = None,
        system_runner: Callable[..., object] | None = None,
        sleep: Callable[[float], None] | None = None,
        dxdiag_retry_delay: float = 1.0,
    ) -> None:
        self.app_root = Path(app_root).resolve(strict=False)
        self.data_root = Path(data_root).resolve(strict=False)
        self._now = now or datetime.now
        self._dxdiag_runner = dxdiag_runner or subprocess.run
        self._system_runner = system_runner or subprocess.run
        self._sleep = sleep or time.sleep
        self._dxdiag_retry_delay = max(0.0, dxdiag_retry_delay)
        self._sanitizer = DiagnosticExporter(self.app_root, self.data_root)

    @property
    def output_root(self) -> Path:
        return self.data_root / "helper-tools" / "support-collections"

    def collect(
        self,
        *,
        app_version: str,
        launcher_version: str,
        game_id: str | None,
        game_root: Path | None,
        problems: Iterable[object] = (),
        host_platform: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> SupportCollectionResult:
        report = progress or (lambda _message: None)
        timestamp = self._now().strftime("%Y%m%d-%H%M%S")
        output_dir = self._unique_output_dir(f"日志资料收集-{timestamp}")
        report("已创建收集目录")
        copied: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []
        skipped_dumps: list[str] = []
        detected_platform = (host_platform or platform_module.system()).casefold()

        system_label = {
            "windows": "DxDiag",
            "win32": "DxDiag",
            "steamos": "SteamOS 系统信息",
            "linux": "SteamOS 系统信息",
            "macos": "macOS 系统信息",
            "darwin": "macOS 系统信息",
        }.get(detected_platform, "系统信息")
        report(f"正在收集系统信息（{system_label}）")
        self._collect_system_info(output_dir, detected_platform, copied, skipped, failed)
        report("系统信息收集完成")
        report("正在收集程序运行日志和问题记录")
        self._collect_signriver(
            output_dir,
            app_version, launcher_version, problems,
            copied, skipped, failed,
        )
        report("程序运行日志和问题记录收集完成")
        report("正在收集当前游戏日志与配置")
        self._collect_game(
            output_dir, game_id, game_root, copied, skipped, failed,
            skipped_dumps,
        )
        report("当前游戏日志与配置收集完成")
        report("正在汇总收集结果")
        return SupportCollectionResult(
            output_dir=output_dir,
            copied=tuple(copied),
            skipped=tuple(skipped),
            failed=tuple(failed),
            skipped_dumps=tuple(skipped_dumps),
        )

    def _unique_output_dir(self, timestamp: str) -> Path:
        root = self.output_root
        root.mkdir(parents=True, exist_ok=True)
        candidate = root / timestamp
        suffix = 2
        while candidate.exists():
            candidate = root / f"{timestamp}-{suffix}"
            suffix += 1
        candidate.mkdir()
        return candidate

    def latest_output_dir(self) -> Path | None:
        """Return the latest completed collection directory, if one exists."""
        root = self.output_root
        if not root.is_dir():
            return None
        resolved_root = root.resolve(strict=False)
        directories = sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir()
                and path.resolve(strict=False).is_relative_to(resolved_root)
            ),
            key=lambda path: path.name,
            reverse=True,
        )
        return directories[0] if directories else None

    def _collect_dxdiag(
        self,
        destination: Path,
        host_platform: str,
        copied: list[str],
        skipped: list[str],
        failed: list[str],
    ) -> None:
        if host_platform not in {"windows", "win32"}:
            skipped.append("DxDiag.txt（当前平台不适用）")
            return
        target = self._available_target(destination, "系统-DxDiag.txt")
        failure_detail = ""
        for attempt in range(2):
            try:
                # A failed dxdiag launch can leave a partial target behind.  Remove
                # only this controlled output before the retry so it is never reused.
                target.unlink(missing_ok=True)
                completed = self._dxdiag_runner(
                    ["dxdiag", "/whql:off", "/t", str(target)],
                    check=False,
                    capture_output=True,
                    timeout=120,
                )
                return_code = getattr(completed, "returncode", 0)
                if not return_code and target.is_file():
                    copied.append(target.name)
                    return
                failure_detail = f"dxdiag 返回 {return_code}"
            except (OSError, subprocess.SubprocessError) as error:
                failure_detail = str(error)

            if attempt == 0:
                self._sleep(self._dxdiag_retry_delay)

        failed.append(f"DxDiag.txt（{failure_detail}；已自动重试 1 次）")

    def _collect_system_info(
        self,
        destination: Path,
        host_platform: str,
        copied: list[str],
        skipped: list[str],
        failed: list[str],
    ) -> None:
        if host_platform in {"windows", "win32"}:
            self._collect_dxdiag(destination, host_platform, copied, skipped, failed)
            return
        normalized = "macos" if host_platform in {"darwin", "mac"} else host_platform
        if normalized not in {"steamos", "linux", "macos"}:
            skipped.append("系统信息（当前平台不适用）")
            return
        commands = (
            (
                ["system_profiler", "SPSoftwareDataType", "SPDisplaysDataType", "-detailLevel", "mini"],
                "系统-macOS-system-profiler.txt",
            ),
        ) if normalized == "macos" else (
            (["uname", "-a"], "系统-SteamOS-uname.txt"),
            (["cat", "/etc/os-release"], "系统-SteamOS-os-release.txt"),
        )
        for command, filename in commands:
            target = self._available_target(destination, filename)
            try:
                completed = self._system_runner(
                    command, check=False, capture_output=True, text=True, timeout=30,
                )
                stdout = str(getattr(completed, "stdout", "") or "")
                stderr = str(getattr(completed, "stderr", "") or "")
                return_code = int(getattr(completed, "returncode", 0) or 0)
                content = stdout.strip()
                if stderr.strip():
                    content = f"{content}\n{stderr.strip()}".strip()
                if return_code != 0 or not content:
                    failed.append(f"{filename}（返回码 {return_code}）")
                    continue
                target.write_text(self._sanitizer.sanitize(content) + "\n", encoding="utf-8")
                copied.append(filename)
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as error:
                failed.append(f"{filename}（{error}）")

    def _collect_signriver(
        self,
        destination: Path,
        app_version: str,
        launcher_version: str,
        problems: Iterable[object],
        copied: list[str],
        skipped: list[str],
        failed: list[str],
    ) -> None:
        log_path = self.data_root / "logs" / "launcher.log"
        self._copy_sanitized_text(
            log_path, self._available_target(destination, "程序-launcher.log"), "程序-launcher.log",
            copied, skipped, failed,
        )
        runtime = {
            "app_version": app_version,
            "launcher_version": launcher_version,
            "platform": platform_module.system(),
        }
        try:
            runtime_target = self._available_target(destination, "程序-runtime.json")
            runtime_target.write_text(
                json.dumps(runtime, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            copied.append(runtime_target.name)
        except OSError as error:
            failed.append(f"程序-runtime.json（{error}）")

        serialized_problems = []
        for problem in problems:
            to_dict = getattr(problem, "to_dict", None)
            payload = to_dict() if callable(to_dict) else dict(problem)
            payload["technical_details"] = self._sanitizer.sanitize(
                str(payload.get("technical_details", ""))
            )
            serialized_problems.append(payload)
        try:
            problems_target = self._available_target(destination, "程序-problems.json")
            problems_target.write_text(
                json.dumps(serialized_problems, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            copied.append(problems_target.name)
        except (OSError, TypeError, ValueError) as error:
            failed.append(f"程序-problems.json（{error}）")

    def _collect_game(
        self,
        destination: Path,
        game_id: str | None,
        game_root: Path | None,
        copied: list[str],
        skipped: list[str],
        failed: list[str],
        skipped_dumps: list[str],
    ) -> None:
        if not game_id:
            skipped.append("当前游戏资料（未选择游戏）")
            return
        profile = GAME_SUPPORT_PROFILES.get(game_id)
        if profile is None:
            skipped.append(f"当前游戏资料（{game_id} 暂无路径配置）")
            return
        values = self._path_values(game_root)
        for spec in (*_paths(*(f"{{game_root}}/{name}" for name in _GAME_ROOT_NAMES)), *profile.paths):
            matches = self._expand_pattern(spec.pattern, values)
            if not matches:
                skipped.append(spec.label)
                continue
            for source in matches:
                label = f"游戏-{game_id}-{source.name}"
                target = self._available_target(destination, label)
                self._copy_sanitized_text(source, target, label, copied, skipped, failed)
        for spec in profile.dump_patterns:
            for source in self._expand_pattern(spec.pattern, values):
                skipped_dumps.append(str(source))

    def _path_values(self, game_root: Path | None) -> dict[str, Path]:
        user_home = Path.home()
        app_data = Path(os.environ.get("APPDATA", user_home / "AppData" / "Roaming"))
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA", user_home / "AppData" / "Local")
        )
        return {
            "game_root": Path(game_root) if game_root is not None else self.app_root / "__missing_game_root__",
            "documents": user_home / "Documents",
            "app_data": app_data,
            "local_app_data": local_app_data,
            "local_low": local_app_data / "Low",
            "application_support": user_home / "Library" / "Application Support",
            "local_share": user_home / ".local" / "share",
        }

    @staticmethod
    def _expand_pattern(pattern: str, values: dict[str, Path]) -> tuple[Path, ...]:
        expanded = pattern.format(**{key: str(value) for key, value in values.items()})
        candidate = Path(expanded)
        parent = candidate.parent
        if not parent.is_dir():
            return ()
        resolved_parent = parent.resolve(strict=False)
        return tuple(
            path
            for path in parent.glob(candidate.name)
            if path.is_file() and path.resolve(strict=False).is_relative_to(resolved_parent)
        )

    @staticmethod
    def _available_target(destination: Path, name: str) -> Path:
        safe_name = Path(name).name
        candidate = destination / safe_name
        suffix = 2
        while candidate.exists():
            candidate = destination / f"{Path(safe_name).stem}-{suffix}{Path(safe_name).suffix}"
            suffix += 1
        if not candidate.resolve(strict=False).is_relative_to(destination.resolve(strict=False)):
            raise ValueError("support collection target escaped its destination")
        return candidate

    def _copy_sanitized_text(
        self,
        source: Path,
        target: Path,
        label: str,
        copied: list[str],
        skipped: list[str],
        failed: list[str],
    ) -> None:
        if not source.is_file():
            skipped.append(label)
            return
        try:
            if not target.resolve(strict=False).is_relative_to(target.parent.resolve(strict=False)):
                raise ValueError("support collection target escaped its destination")
            text = source.read_bytes().decode("utf-8", errors="replace")
            target.write_text(self._sanitizer.sanitize(text), encoding="utf-8")
            copied.append(label)
        except (OSError, ValueError) as error:
            failed.append(f"{label}（{error}）")


__all__ = [
    "GAME_SUPPORT_PROFILES",
    "GameSupportProfile",
    "SupportBundleCollector",
    "SupportCollectionResult",
    "SupportPathSpec",
]
