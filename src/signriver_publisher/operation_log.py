"""Durable, credential-free operation history for the publisher UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from time import sleep
from typing import Iterable
from uuid import uuid4


class OperationLog:
    """Keep the most recent user-visible events across publisher restarts."""

    max_lines = 500

    def __init__(self, workspace_root: Path | str) -> None:
        self.path = Path(workspace_root).resolve() / "operation-log.jsonl"
        self._lock = Lock()

    def load(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            lines: list[str] = []
            for raw in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                message = value.get("message") if isinstance(value, dict) else None
                if isinstance(message, str) and message.strip():
                    lines.append(message)
            return lines[-self.max_lines :]
        except OSError:
            return []

    def append(self, line: str) -> None:
        """Atomically retain one bounded history without storing credentials."""
        with self._lock:
            lines = [*self.load(), line][-self.max_lines :]
            self._write(lines)

    def replace(self, lines: Iterable[str]) -> None:
        """Test/support helper for explicitly replacing the retained history."""
        kept = [str(line) for line in lines if str(line).strip()][-self.max_lines :]
        with self._lock:
            self._write(kept)

    def _write(self, lines: Iterable[str]) -> None:
        """Write history safely when Windows briefly locks the destination."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for value in lines:
                    handle.write(json.dumps({"message": value}, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(4):
                try:
                    os.replace(temporary, self.path)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    sleep(0.05 * (2**attempt))
        finally:
            temporary.unlink(missing_ok=True)
