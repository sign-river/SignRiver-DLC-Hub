from __future__ import annotations

import sys
from pathlib import Path


VERSION_ROOT = Path(__file__).resolve().parents[1] / "app" / "versions" / "0.1.0"
version_root = str(VERSION_ROOT)
if version_root not in sys.path:
    sys.path.insert(0, version_root)
