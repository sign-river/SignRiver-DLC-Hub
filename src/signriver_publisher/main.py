from __future__ import annotations

import argparse
from pathlib import Path

from .ui import PublisherApplication
from .settings import PublisherSettings, discover_settings_path
from .workspace import PublisherWorkspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SignRiver DLC release publisher")
    parser.add_argument("--workspace", type=Path, default=Path.cwd() / "publisher-workspace")
    arguments = parser.parse_args(argv)
    settings = PublisherSettings.load(discover_settings_path())
    application = PublisherApplication(PublisherWorkspace(arguments.workspace), settings=settings)
    application.mainloop()
    return 0
