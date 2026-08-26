from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


_REPLACE_RETRY_DELAYS = (0.1, 0.25, 0.5, 1.0, 2.0)
_WINDOWS_RETRYABLE_WINERRORS = {5, 32, 33}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        _replace_with_retry(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _replace_with_retry(source: str, destination: Path) -> None:
    """Replace a file, tolerating short-lived Windows sharing violations."""
    for attempt, delay in enumerate((0.0, *_REPLACE_RETRY_DELAYS)):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            winerror = getattr(error, "winerror", None)
            if (
                os.name != "nt"
                or winerror not in _WINDOWS_RETRYABLE_WINERRORS
                or attempt == len(_REPLACE_RETRY_DELAYS)
            ):
                raise
            time.sleep(delay if delay else _REPLACE_RETRY_DELAYS[0])
