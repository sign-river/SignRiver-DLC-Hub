from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .full_update import FullUpdateManager
from .paths import RuntimePaths
from .product import RELEASE_EXE_NAME


def _wait_for_parent(pid: int, timeout_seconds: int = 60) -> None:
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
            subprocess.Popen([str(executable), "--confirm-full-update", transaction_id], cwd=root)
