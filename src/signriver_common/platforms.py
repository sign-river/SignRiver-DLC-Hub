"""Cross-platform host detection and desktop integration helpers."""

from __future__ import annotations

import os
import platform as platform_module
import subprocess
import sys
from enum import StrEnum
from pathlib import Path


class HostPlatform(StrEnum):
    WINDOWS = "windows"
    STEAMOS = "steamos"
    MACOS = "macos"


def detect_host_platform(value: str | None = None) -> HostPlatform:
    current = sys.platform if value is None else str(value)
    if current.startswith("win"):
        return HostPlatform.WINDOWS
    if current == "darwin":
        return HostPlatform.MACOS
    if current.startswith("linux"):
        return HostPlatform.STEAMOS
    raise RuntimeError(f"unsupported operating system: {current}")


def normalize_architecture(value: str | None = None) -> str:
    machine = (platform_module.machine() if value is None else str(value)).lower()
    if machine in {"amd64", "x86_64", "x64"}:
        return "x64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    raise RuntimeError(f"unsupported processor architecture: {machine}")


def platform_package_key(
    host: HostPlatform | str | None = None,
    architecture: str | None = None,
) -> str:
    selected = detect_host_platform() if host is None else HostPlatform(str(host))
    return f"{selected.value}-{normalize_architecture(architecture)}"


def open_directory(path: Path, host: HostPlatform | str | None = None) -> None:
    target = Path(path).expanduser().resolve(strict=False)
    selected = detect_host_platform() if host is None else HostPlatform(str(host))
    if selected is HostPlatform.WINDOWS:
        os.startfile(target)  # type: ignore[attr-defined]
        return
    command = "open" if selected is HostPlatform.MACOS else "xdg-open"
    subprocess.Popen(
        [command, str(target)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def is_process_running(
    executable: Path,
    host: HostPlatform | str | None = None,
) -> bool:
    target = Path(executable).expanduser().resolve(strict=False)
    selected = detect_host_platform() if host is None else HostPlatform(str(host))
    if selected is HostPlatform.WINDOWS:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {target.name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise OSError(result.stderr.strip() or "tasklist process check failed")
        return target.name.casefold() in result.stdout.casefold()
    if selected is HostPlatform.STEAMOS:
        proc = Path("/proc")
        if not proc.is_dir():
            return False
        for item in proc.iterdir():
            if not item.name.isdigit():
                continue
            try:
                candidate = (item / "exe").resolve(strict=True)
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if candidate == target:
                return True
        return False
    result = subprocess.run(
        ["ps", "-axo", "command="],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "ps process check failed")
    target_text = str(target)
    return any(
        line.strip() == target_text or line.lstrip().startswith(f"{target_text} ")
        for line in result.stdout.splitlines()
    )


__all__ = [
    "HostPlatform",
    "detect_host_platform",
    "is_process_running",
    "normalize_architecture",
    "open_directory",
    "platform_package_key",
]
