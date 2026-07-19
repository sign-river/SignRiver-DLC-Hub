"""Bounded helpers for displaying potentially long-running application logs."""

from __future__ import annotations

from pathlib import Path


def read_tail_lines(
    path: Path,
    *,
    max_lines: int = 500,
    max_bytes: int = 2 * 1024 * 1024,
) -> list[str]:
    """Read only the newest portion of a UTF-8 log file.

    Launcher logs can live for months. Reading the whole file on every search
    keystroke makes the Tk thread pause even though the UI only displays the
    newest entries. The byte cap also bounds memory for pre-rotation logs.
    """

    if max_lines < 1:
        raise ValueError("max_lines must be positive")
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    with Path(path).open("rb") as source:
        source.seek(0, 2)
        size = source.tell()
        start = max(0, size - max_bytes)
        previous = b""
        if start:
            source.seek(start - 1)
            previous = source.read(1)
        source.seek(start)
        raw = source.read(max_bytes)

    lines = raw.decode("utf-8", errors="replace").splitlines()
    # A bounded read can begin in the middle of a UTF-8 sequence or log line.
    # Discard that one incomplete line; all later entries are intact.
    if start and lines:
        if previous not in {b"\n", b"\r"}:
            lines.pop(0)
        elif raw.startswith((b"\n", b"\r")) and lines[0] == "":
            lines.pop(0)
    return lines[-max_lines:]


__all__ = ["read_tail_lines"]
