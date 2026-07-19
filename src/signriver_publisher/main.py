from __future__ import annotations

import argparse
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
    settings = PublisherSettings.load(discover_settings_path())
    application = PublisherApplication(PublisherWorkspace(arguments.workspace), settings=settings)
    application.mainloop()
    return 0
