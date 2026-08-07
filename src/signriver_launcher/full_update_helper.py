from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .full_update import FullUpdateManager
from .paths import RuntimePaths
from .product import RELEASE_EXE_NAME


def _wait_for_parent_windows(pid: int, timeout_seconds: int) -> None:
    """Wait for a Windows process without signalling or terminating it."""
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    wait_failed = 0xFFFFFFFF
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return
        raise ctypes.WinError(error)
    try:
        timeout_ms = min(max(int(timeout_seconds * 1000), 0), 0xFFFFFFFE)
        result = kernel32.WaitForSingleObject(handle, timeout_ms)
        if result == wait_object_0:
            return
        if result == wait_timeout:
            raise RuntimeError(
                "the application did not exit before the full update timeout"
            )
        if result == wait_failed:
            raise ctypes.WinError(ctypes.get_last_error())
        raise RuntimeError(f"unexpected Windows process wait result: {result}")
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_parent(pid: int, timeout_seconds: int = 60) -> None:
    if os.name == "nt":
        _wait_for_parent_windows(pid, timeout_seconds)
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(0.15)
    raise RuntimeError("the application did not exit before the full update timeout")


def apply_full_update(root: Path, transaction_id: str, parent_pid: int, restart: bool = True) -> None:
    _wait_for_parent(parent_pid)
    paths = RuntimePaths(root.resolve())
    manager = FullUpdateManager(paths)
    manager.apply(transaction_id)
    if restart:
        if getattr(sys, "frozen", False):
            executable = root / RELEASE_EXE_NAME
            subprocess.Popen(
                [str(executable), "--confirm-full-update", transaction_id],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
