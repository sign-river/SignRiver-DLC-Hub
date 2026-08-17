from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from signriver_common.platforms import HostPlatform
from signriver_common.problems import ProblemCode

from .full_update import FullUpdateManager
from .paths import RuntimePaths
from .problem_reporting import record_update_problem
from .state import StateStore


def _active_version(paths: RuntimePaths) -> str | None:
    try:
        return StateStore(paths.state_file).load().active_version
    except Exception:
        return None


def frozen_child_environment() -> dict[str, str]:
    """Force a newly launched frozen executable to unpack independently.

    PyInstaller child processes inherit the current onefile extraction directory by
    default. Update helpers and restarted launchers outlive their parent, so sharing
    that directory can make binary modules disappear while the child is still booting.
    """
    environment = os.environ.copy()
    if getattr(sys, "frozen", False):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


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


def apply_full_update(
    root: Path,
    transaction_id: str,
    parent_pid: int,
    restart: bool = True,
    *,
    install_root: Path | None = None,
    platform: str | None = None,
    cache_root: Path | None = None,
) -> None:
    _wait_for_parent(parent_pid)
    paths = RuntimePaths(
        root.resolve(),
        install_root.resolve() if install_root else None,
        HostPlatform(platform) if platform else None,
        cache_root.resolve() if cache_root else None,
    )
    manager = FullUpdateManager(paths)
    try:
        manager.apply(transaction_id)
    except Exception as error:
        transaction = manager.load()
        record_update_problem(
            paths,
            code=ProblemCode.UPDATE_APPLY_FAILED,
            stage="update.helper_apply",
            error=error,
            app_version=_active_version(paths),
            target_version=transaction.version if transaction else None,
            filename=None,
            expected_sha256=None,
        )
        if transaction is not None and transaction.stage == "rolled_back":
            record_update_problem(
                paths,
                code=ProblemCode.UPDATE_ROLLED_BACK,
                stage="update.helper_apply_rollback",
                error=error,
                app_version=_active_version(paths),
                target_version=transaction.version,
                filename=None,
                expected_sha256=None,
            )
        raise
    if restart:
        if getattr(sys, "frozen", False):
            executable = paths.resources_root / paths.launcher_relative_path
            if paths.platform is HostPlatform.MACOS:
                executable = (
                    Path(paths.install_root or root) / paths.launcher_relative_path
                )
            subprocess.Popen(
                [str(executable), "--confirm-full-update", transaction_id],
                cwd=paths.resources_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=frozen_child_environment(),
            )


def rollback_full_update(
    root: Path,
    transaction_id: str,
    parent_pid: int,
    restart: bool = True,
    *,
    install_root: Path | None = None,
    platform: str | None = None,
    cache_root: Path | None = None,
) -> None:
    """Roll back a swapped update after the failed launcher process exits.

    Windows keeps a running executable locked. A newly swapped launcher therefore
    cannot restore its own previous executable in-process; the detached helper must
    wait for it to exit before moving the backup into place.
    """
    _wait_for_parent(parent_pid)
    paths = RuntimePaths(
        root.resolve(),
        install_root.resolve() if install_root else None,
        HostPlatform(platform) if platform else None,
        cache_root.resolve() if cache_root else None,
    )
    transaction = FullUpdateManager(paths).rollback(transaction_id)
    record_update_problem(
        paths,
        code=ProblemCode.UPDATE_ROLLED_BACK,
        stage="update.helper_rollback",
        error=RuntimeError(
            f"full update {transaction_id} rolled back after launcher failure"
        ),
        app_version=_active_version(paths),
        target_version=getattr(transaction, "version", None),
        filename=None,
        expected_sha256=None,
    )
    if restart and getattr(sys, "frozen", False):
        executable = paths.resources_root / paths.launcher_relative_path
        if paths.platform is HostPlatform.MACOS:
            executable = Path(paths.install_root or root) / paths.launcher_relative_path
        subprocess.Popen(
            [
                str(executable),
                "--cleanup-full-update-helper",
                sys.executable,
                str(os.getpid()),
            ],
            cwd=paths.resources_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=frozen_child_environment(),
        )


def cleanup_full_update_helper(
    helper_path: Path, parent_pid: int, restart: bool = True
) -> None:
    """Remove a detached Windows helper after it exits, then restart normally."""
    _wait_for_parent(parent_pid)
    helper_path.unlink(missing_ok=True)
    try:
        helper_path.parent.rmdir()
    except OSError:
        pass
    if restart and getattr(sys, "frozen", False):
        subprocess.Popen(
            [sys.executable],
            cwd=Path(sys.executable).resolve().parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=frozen_child_environment(),
        )
