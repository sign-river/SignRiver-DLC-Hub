"""只读显卡驱动探测与更新入口。"""

from __future__ import annotations

import datetime as _datetime
import json
import os
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
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "未知显卡").strip()
        vendor = str(item.get("AdapterCompatibility") or "").strip()
        version = str(item.get("DriverVersion") or "未知").strip()
        date_value = str(item.get("DriverDate") or "").strip()
        year = None
        if len(date_value) >= 4 and date_value[:4].isdigit():
            year = int(date_value[:4])
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
