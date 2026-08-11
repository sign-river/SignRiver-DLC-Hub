from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from .ui import PublisherApplication
from .settings import PublisherSettings, discover_settings_path
from .workspace import PublisherWorkspace


def default_workspace_path() -> Path:
    """Keep packaged publisher data beside its executable, not caller CWD."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "publisher-workspace"
    return Path.cwd() / "publisher-workspace"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SignRiver DLC release publisher")
    parser.add_argument("--workspace", type=Path, default=default_workspace_path())
    arguments = parser.parse_args(argv)
    settings_path = discover_settings_path()
    settings = PublisherSettings.load(settings_path)
    workspace = PublisherWorkspace(arguments.workspace)
    log_dir = arguments.workspace / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "publisher.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    application = PublisherApplication(
        workspace,
        settings=settings,
        settings_path=settings_path,
    )
    application.mainloop()
    return 0
