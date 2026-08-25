"""只读显卡驱动探测与更新入口。"""

from __future__ import annotations

import datetime as _datetime
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GpuDriverInfo:
    name: str
    vendor: str
    version: str
    driver_date: str
    driver_year: int | None
    status: str
    warning: str | None
    vendor_url: str | None


def _vendor_url(vendor: str, name: str) -> str | None:
    value = f"{vendor} {name}".casefold()
    if "nvidia" in value:
        return "https://www.nvidia.com/Download/index.aspx"
    if "amd" in value or "advanced micro" in value or "radeon" in value:
        return "https://www.amd.com/en/support/download/drivers.html"
    if "intel" in value:
        return "https://www.intel.com/content/www/us/en/download-center/home.html"
    return None


_VIRTUAL_ADAPTER_MARKERS = (
    "virtual", "oray", "todesk", "todesk", "indirect display", "idd",
    "remote display", "mirage", "spacedesk", "parsec",
)


def _is_virtual_adapter(name: str, vendor: str) -> bool:
    value = f"{name} {vendor}".casefold()
    return any(marker in value for marker in _VIRTUAL_ADAPTER_MARKERS)


def _driver_year(value: str) -> int | None:
    """解析 CIM 常见的 DMTF /Date(milliseconds)/ 日期格式。"""
    match = re.search(r"/Date\(([-+]?\d+)", value)
    if match:
        try:
            timestamp = int(match.group(1)) / 1000
            return _datetime.datetime.fromtimestamp(timestamp).year
        except (OverflowError, OSError, ValueError):
            return None
    if len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _select_physical_adapters(items: list[dict]) -> list[dict]:
    """最多保留两个真实适配器：优先一块集显和一块独显。"""
    physical = [
        item for item in items
        if not _is_virtual_adapter(
            str(item.get("Name") or ""), str(item.get("AdapterCompatibility") or "")
        )
    ]
    if len(physical) <= 2:
        return physical

    def is_integrated(item: dict) -> bool:
        value = f"{item.get('Name') or ''} {item.get('AdapterCompatibility') or ''}".casefold()
        return any(token in value for token in ("intel", "uhd", "iris", "vega", "apu"))

    integrated = next((item for item in physical if is_integrated(item)), None)
    discrete = next((item for item in physical if item is not integrated), None)
    selected = [item for item in (integrated, discrete) if item is not None]
    return selected[:2]


def discover_gpu_drivers(
    *, runner: Callable[..., object] | None = None,
    now_year: int | None = None,
) -> tuple[GpuDriverInfo, ...]:
    """通过 WMI/CIM 读取显示适配器，不修改系统设置。"""
    if os.name != "nt":
        return ()
    run = runner or subprocess.run
    script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterCompatibility,DriverVersion,DriverDate | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=12, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = json.loads((getattr(completed, "stdout", "") or "").strip() or "[]")
        if isinstance(raw, dict):
            raw = [raw]
    except Exception:
        return ()
    current_year = now_year or _datetime.datetime.now().year
    result: list[GpuDriverInfo] = []
    selected_items = _select_physical_adapters(raw) if isinstance(raw, list) else []
    for item in selected_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "未知显卡").strip()
        vendor = str(item.get("AdapterCompatibility") or "").strip()
        version = str(item.get("DriverVersion") or "未知").strip()
        date_value = str(item.get("DriverDate") or "").strip()
        year = None
        year = _driver_year(date_value)
        warning = None
        status = "正常"
        if year is None:
            status = "无法判断"
            warning = "系统未返回驱动日期，请打开详情页手动检查更新。"
        elif year < current_year - 3:
            status = "建议更新"
            warning = f"驱动日期为 {year} 年，可能偏旧，建议更新后再运行游戏。"
        result.append(GpuDriverInfo(
            name=name, vendor=vendor, version=version, driver_date=date_value,
            driver_year=year, status=status, warning=warning,
            vendor_url=_vendor_url(vendor, name),
        ))
    return tuple(result)
