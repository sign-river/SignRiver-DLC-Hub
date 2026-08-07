from __future__ import annotations

import sys
from pathlib import Path


# Git only tracks app/versions/0.1.0 as the canonical module source; later
# version directories are restored from release archives on CI and may not
# contain freshly added modules (e.g. StaticManifestReleaseSource).  Tests must
# import from the tracked source directory instead of a restored archive.
VERSION_ROOT = Path(__file__).resolve().parents[1] / "app" / "versions" / "0.1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_root = str(PROJECT_ROOT)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
version_root = str(VERSION_ROOT)
if version_root not in sys.path:
    sys.path.insert(0, version_root)
