"""Compatibility helpers that materialise cartridges from bootstrap documents.

Production startup no longer hard-codes game cartridges in Python.  Tests and
offline smoke paths can still build every game listed in the packaged
``config/cartridges`` index.
"""

from __future__ import annotations

import json
from pathlib import Path

from .cartridge import GameCartridge
from .document_cartridge import build_cartridge_from_document
from .protocol import GameAdapter
from ..domain import CartridgeDocument, CartridgeIndex


def bootstrap_cartridges_dir() -> Path:
    """Resolve the packaged bootstrap cartridge directory next to the app root."""
    # app/versions/0.1.0/signriver_app/adapters/builtin.py -> repo root / config
    return Path(__file__).resolve().parents[5] / "config" / "cartridges"


def load_bootstrap_index(directory: Path | None = None) -> CartridgeIndex:
    root = directory or bootstrap_cartridges_dir()
    payload = json.loads((root / "cartridges_index.json").read_text(encoding="utf-8"))
    return CartridgeIndex.from_dict(payload)


def create_builtin_cartridges(
    directory: Path | None = None,
) -> tuple[GameCartridge, ...]:
    root = directory or bootstrap_cartridges_dir()
    index = load_bootstrap_index(root)
    cartridges = []
    for entry in index.cartridges:
        document = CartridgeDocument.from_dict(
            json.loads((root / entry.asset_name).read_text(encoding="utf-8"))
        )
        cartridges.append(build_cartridge_from_document(document))
    return tuple(cartridges)


def create_builtin_adapters(
    directory: Path | None = None,
) -> tuple[GameAdapter, ...]:
    return tuple(
        cartridge.adapter for cartridge in create_builtin_cartridges(directory)
    )


__all__ = [
    "bootstrap_cartridges_dir",
    "create_builtin_adapters",
    "create_builtin_cartridges",
    "load_bootstrap_index",
]
