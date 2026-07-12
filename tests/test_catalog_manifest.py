from __future__ import annotations

import json

import pytest

from signriver_app.domain import CatalogTrust
from signriver_app.infrastructure.catalog import CatalogManifestError, parse_catalog_manifest


def manifest(*, authorized: bool = True) -> dict:
    return {
        "schema_version": 1,
        "catalog_id": "stellaris-ste",
        "game_id": "stellaris",
        "revision": 1,
        "assets": [{
            "dlc_id": "dlc001",
            "asset_name": "dlc001_symbols_of_domination.zip",
            "size": 77375,
            "sha256": "e1acdb9592b7b8525802f046ccb40def9ce334720b7e6a45be01467d5295c3c5",
            "min_game_version": "4.4.0",
            "max_game_version": "4.4.99",
            "distribution_authorized": authorized,
        }],
        "signature": {"key_id": "signriver-2026", "value": "A" * 64},
    }


def encode(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode()


def test_manifest_requires_configured_publisher_key() -> None:
    parsed = parse_catalog_manifest(encode(manifest()))
    assert parsed.trust is CatalogTrust.UNSIGNED
    assert parsed.assets[0].size == 77375


def test_manifest_accepts_valid_signature_verifier() -> None:
    calls = []
    parsed = parse_catalog_manifest(
        encode(manifest()),
        verify_signature=lambda key, content, signature: calls.append((key, content, signature)) or True,
    )
    assert parsed.trust is CatalogTrust.VERIFIED
    assert calls[0][0] == "signriver-2026"
    assert b'"signature"' not in calls[0][1]


def test_manifest_blocks_unauthorized_distribution_even_with_valid_signature() -> None:
    parsed = parse_catalog_manifest(
        encode(manifest(authorized=False)), verify_signature=lambda *_args: True
    )
    assert parsed.trust is CatalogTrust.INVALID
    assert "未授权" in parsed.trust_reason


def test_manifest_rejects_unknown_fields_and_duplicate_assets() -> None:
    extra = manifest()
    extra["unexpected"] = True
    with pytest.raises(CatalogManifestError, match="fields"):
        parse_catalog_manifest(encode(extra))
    duplicate = manifest()
    duplicate["assets"].append(dict(duplicate["assets"][0]))
    with pytest.raises(CatalogManifestError, match="duplicate"):
        parse_catalog_manifest(encode(duplicate))
