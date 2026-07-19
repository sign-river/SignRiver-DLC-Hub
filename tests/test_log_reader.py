from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from signriver_launcher.main import _configure_logging
from signriver_app.infrastructure.log_reader import read_tail_lines


def test_read_tail_lines_limits_legacy_log_without_returning_partial_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "launcher.log"
    path.write_text(
        "".join(f"line-{index:04d}-payload\n" for index in range(1000)),
        encoding="utf-8",
    )

    lines = read_tail_lines(path, max_lines=5, max_bytes=256)

    assert lines == [f"line-{index:04d}-payload" for index in range(995, 1000)]


@pytest.mark.parametrize("max_lines,max_bytes", [(0, 10), (1, 0)])
def test_read_tail_lines_rejects_non_positive_limits(
    tmp_path: Path, max_lines: int, max_bytes: int
) -> None:
    path = tmp_path / "launcher.log"
    path.write_text("entry\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_tail_lines(path, max_lines=max_lines, max_bytes=max_bytes)


def test_launcher_uses_bounded_rotating_log(tmp_path: Path) -> None:
    logger = logging.getLogger("signriver")
    previous_handlers = tuple(logger.handlers)
    for handler in previous_handlers:
        logger.removeHandler(handler)
    try:
        configured = _configure_logging(tmp_path)
        rotating = next(
            handler
            for handler in configured.handlers
            if isinstance(handler, RotatingFileHandler)
        )
        assert rotating.maxBytes == 5 * 1024 * 1024
        assert rotating.backupCount == 3
    finally:
        for handler in tuple(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            logger.addHandler(handler)
