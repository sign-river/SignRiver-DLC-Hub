"""Regression: offline startup must not fail when the hub default_game_id
is not present in the local bootstrap (e.g. a newer game shipped only in the
remote hub index). The service falls back to the first locally available
cartridge instead of raising CartridgeCatalogError.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from signriver_app.application.cartridge_catalog import CartridgeCatalogService
from signriver_app.domain import INDEX_ASSET_NAME

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "config" / "cartridges"


def _build_bootstrap_with_missing_default(tmp_path: Path) -> Path:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    for source in BOOTSTRAP.glob("cartridge_*.json"):
        if source.name == INDEX_ASSET_NAME:
            continue
        shutil.copy2(source, bootstrap / source.name)
    index_payload = json.loads(
        (BOOTSTRAP / INDEX_ASSET_NAME).read_text(encoding="utf-8")
    )
    # Simulate a published hub index whose default points to a cartridge this
    # installation does not carry locally.
    index_payload["default_game_id"] = "cities_skylines_2"
    index_payload["cartridges"].insert(
        0,
        {
            "game_id": "cities_skylines_2",
            "display_name": "Cities: Skylines II",
            "asset_name": "cartridge_cities_skylines_2.json",
            "sha256": "0" * 64,
            "size_bytes": 123,
        },
    )
    (bootstrap / INDEX_ASSET_NAME).write_text(
        json.dumps(index_payload, ensure_ascii=False), encoding="utf-8"
    )
    return bootstrap


def test_default_cartridge_falls_back_when_default_missing_locally(
    tmp_path: Path,
) -> None:
    bootstrap = _build_bootstrap_with_missing_default(tmp_path)
    service = CartridgeCatalogService(
        tmp_path / "cache",
        bootstrap_dir=bootstrap,
        source=object(),  # network must not be touched
    )
    index = service.refresh_index(allow_network=False)
    assert index.default_game_id == "cities_skylines_2"

    loaded = service.load_default_cartridge(allow_network=False)

    assert loaded.document.game_id != "cities_skylines_2"
    assert loaded.source in {"bootstrap", "cache"}
