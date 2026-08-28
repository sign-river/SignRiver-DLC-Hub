"""受控的 Windows DirectDraw/Direct3D 兼容性诊断与修复。"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


REGISTRY_TARGETS = (
    ("directdraw", r"SOFTWARE\Microsoft\DirectDraw", "EmulationOnly"),
    ("direct3d", r"SOFTWARE\Microsoft\Direct3D\Drivers", "SoftwareOnly"),
    ("directdraw-wow6432", r"SOFTWARE\WOW6432Node\Microsoft\DirectDraw", "EmulationOnly"),
    ("direct3d-wow6432", r"SOFTWARE\WOW6432Node\Microsoft\Direct3D\Drivers", "SoftwareOnly"),
)


@dataclass(frozen=True, slots=True)
class RegistryValueStatus:
    key: str
    value_name: str
    exists: bool
    value: int | None
    value_type: int | None
    error: str | None = None

    @property
    def healthy(self) -> bool:
        return self.exists and self.value == 0 and self.error is None


@dataclass(frozen=True, slots=True)
class GraphicsDiagnostic:
    code: str
    summary: str
    registry: tuple[RegistryValueStatus, ...] = ()
    directdraw: str = "unknown"
    direct3d: str = "unknown"
    dxdiag_error: str | None = None

    @property
    def repairable(self) -> bool:
        return self.code == "graphics_acceleration_disabled"


class GraphicsCompatibilityService:
    """All system mutation is limited to the four fixed registry values."""

    def __init__(self, *, registry_module=None, runner: Callable[..., object] | None = None) -> None:
        self._winreg = registry_module
        self._runner = runner or subprocess.run

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def _registry(self):
        if self._winreg is None and self.supported:
            import winreg
            self._winreg = winreg
        return self._winreg

    def is_admin(self) -> bool:
        if not self.supported:
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def read_registry(self) -> tuple[RegistryValueStatus, ...]:
        winreg = self._registry()
        if winreg is None:
            return tuple(RegistryValueStatus(path, name, False, None, None, "unsupported") for _, path, name in REGISTRY_TARGETS)
        result: list[RegistryValueStatus] = []
        for _, path, name in REGISTRY_TARGETS:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ) as key:
                    value, value_type = winreg.QueryValueEx(key, name)
                    value_int = int(value) if isinstance(value, int) and not isinstance(value, bool) else None
                    error = None if value_int is not None else "not_dword"
                    result.append(RegistryValueStatus(path, name, True, value_int, value_type, error))
            except FileNotFoundError:
                result.append(RegistryValueStatus(path, name, False, None, None))
            except OSError as error:
                result.append(RegistryValueStatus(path, name, False, None, None, f"{type(error).__name__}: {error}"))
        return tuple(result)

    @staticmethod
    def _parse_dxdiag(text: str) -> tuple[str, str]:
        def state(label: str) -> str:
            match = re.search(rf"(?:{label})[^:\r\n]*:\s*(Enabled|Disabled|Not Available|已启用|已禁用|不可用)", text, re.I)
            if not match:
                return "unknown"
            value = match.group(1).casefold()
            return "enabled" if value in {"enabled", "已启用"} else "disabled" if value in {"disabled", "已禁用"} else "unavailable"
        return state("DirectDraw Acceleration|DirectDraw 加速"), state("Direct3D Acceleration|Direct3D 加速")

    def run_dxdiag(self, *, timeout: int = 60, retry_delay: float = 1.0) -> tuple[str, str, str | None]:
        if not self.supported:
            return "unknown", "unknown", "unsupported"
        with tempfile.TemporaryDirectory(prefix="signriver-dxdiag-") as directory:
            target = Path(directory) / "DxDiag.txt"
            last_error = "dxdiag 未生成诊断文件"
            for attempt in range(2):
                target.unlink(missing_ok=True)
                try:
                    completed = self._runner(
                        ["dxdiag", "/whql:off", "/t", str(target)],
                        capture_output=True, text=True, timeout=timeout, check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if getattr(completed, "returncode", 1) != 0 or not target.is_file():
                        last_error = f"dxdiag 返回 {getattr(completed, 'returncode', 1)} 或未生成诊断文件"
                    else:
                        raw = target.read_bytes()
                        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
                        text = raw.decode(encoding, errors="replace")
                        directdraw, direct3d = self._parse_dxdiag(text)
                        return directdraw, direct3d, None
                except subprocess.TimeoutExpired:
                    last_error = f"dxdiag 超时（第 {attempt + 1} 次，每次上限 {timeout} 秒）"
                except Exception as error:
                    last_error = f"{type(error).__name__}: {error}"
                if attempt == 0 and retry_delay > 0:
                    time.sleep(retry_delay)
            return "unknown", "unknown", last_error

    def diagnose(self) -> GraphicsDiagnostic:
        if not self.supported:
            return GraphicsDiagnostic("graphics_not_applicable", "当前平台不适用 Windows 图形设备检查。")
        registry = self.read_registry()
        directdraw, direct3d, dxdiag_error = self.run_dxdiag()
        unreadable = any(item.error for item in registry)
        disabled = any(item.exists and item.value not in (None, 0) for item in registry)
        disabled = disabled or directdraw in {"disabled", "unavailable"} or direct3d in {"disabled", "unavailable"}
        if disabled:
            code = "graphics_acceleration_disabled"
            summary = "检测到 DirectDraw/Direct3D 硬件加速可能被禁用。"
        elif unreadable or dxdiag_error or directdraw == "unknown" or direct3d == "unknown":
            code = "graphics_registry_unreadable"
            summary = "图形设备状态不完整，建议打开详情页手动复查。"
        else:
            code = "graphics_acceleration_ok"
            summary = "未发现 DirectDraw/Direct3D 加速配置异常。"
        return GraphicsDiagnostic(code, summary, registry, directdraw, direct3d, dxdiag_error)

    def _backup_path(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "graphics-compatibility-backup.json"

    def repair(self, directory: Path) -> tuple[bool, str, Path | None]:
        if not self.supported:
            return False, "当前平台不支持 Windows 注册表修复。", None
        if not self.is_admin():
            return False, "需要以管理员身份运行后才能修复图形设备配置。", None
        winreg = self._registry()
        if winreg is None:
            return False, "无法加载 Windows 注册表接口。", None
        snapshot = self.read_registry()
        if any(item.error for item in snapshot):
            return False, "无法安全读取现有图形设备配置，未执行任何写入。", None
        backup = self._backup_path(directory)
        backup.write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(), "values": [asdict(item) for item in snapshot]}, ensure_ascii=False, indent=2), encoding="utf-8")
        changed: list[tuple[str, str, RegistryValueStatus]] = []
        try:
            for key_id, path, name in REGISTRY_TARGETS:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as key:
                    key.SetValueEx(name, 0, winreg.REG_DWORD, 0)
                original = next(item for item in snapshot if item.key == path and item.value_name == name)
                changed.append((path, name, original))
        except Exception as error:
            self._restore_items(changed)
            return False, f"修复失败，已尝试恢复原始值：{type(error).__name__}: {error}", backup
        return True, "图形设备配置已修复，请重启电脑后重新启动游戏。", backup

    def _restore_items(self, items: list[tuple[str, str, RegistryValueStatus]]) -> None:
        winreg = self._registry()
        if winreg is None:
            return
        for path, name, original in reversed(items):
            try:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as key:
                    if original.exists and original.value is not None:
                        key.SetValueEx(name, 0, original.value_type or winreg.REG_DWORD, original.value)
                    else:
                        key.DeleteValue(name)
            except OSError:
                continue

    def restore_backup(self, directory: Path) -> tuple[bool, str]:
        if not self.supported:
            return False, "当前平台不支持 Windows 注册表恢复。"
        if not self.is_admin():
            return False, "需要以管理员身份运行后才能恢复备份。"
        try:
            payload = json.loads(self._backup_path(directory).read_text(encoding="utf-8"))
            items = []
            for raw in payload["values"]:
                original = RegistryValueStatus(**raw)
                items.append((original.key, original.value_name, original))
            self._restore_items(items)
        except Exception as error:
            return False, f"恢复备份失败：{type(error).__name__}: {error}"
        return True, "已恢复修复前的图形设备配置；如游戏仍未恢复，请重启电脑。"
