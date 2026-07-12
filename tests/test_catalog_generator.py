from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from signriver_app.domain import CatalogTrust
from signriver_app.infrastructure.catalog import parse_catalog_manifest
from tools.generate_dlc_catalog import generate


def make_package(path: Path) -> None:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("content.txt", "payload")
    with zipfile.ZipFile(path, "w") as archive:
        root = "dlc001_symbols_of_domination/"
        archive.writestr(root + "dlc001.dlc", 'name="Symbols"\narchive="dlc/dlc001_symbols_of_domination/dlc001.zip"')
        archive.writestr(root + "dlc001.zip", nested.getvalue())


def test_generator_creates_safe_unsigned_draft(tmp_path: Path) -> None:
    source = tmp_path / "packages"
    source.mkdir()
    make_package(source / "dlc001_symbols_of_domination.zip")
    output = tmp_path / "dlc-catalog.json"
    manifest = generate(
        source, output, catalog_id="stellaris-ste", revision=2,
        min_game_version="4.4.0", max_game_version="4.4.99",
    )
    assert manifest["assets"][0]["distribution_authorized"] is False
    assert manifest["assets"][0]["size"] > 0
    parsed = parse_catalog_manifest(output.read_bytes())
    assert parsed.trust is CatalogTrust.INVALID
    assert "未授权" in parsed.trust_reason


def test_generator_requires_explicit_authorization_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "packages"
    source.mkdir()
    make_package(source / "dlc001_symbols_of_domination.zip")
    output = tmp_path / "catalog.json"
    manifest = generate(
        source, output, catalog_id="stellaris-ste", revision=1,
        min_game_version=None, max_game_version=None,
        distribution_authorized=True,
    )
    assert manifest["assets"][0]["distribution_authorized"] is True
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
