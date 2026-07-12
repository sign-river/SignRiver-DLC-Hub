"""Strict parser for signed DLC catalog manifests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from ...domain import CatalogTrust, TrustedCatalogAsset


class CatalogManifestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCatalogManifest:
    catalog_id: str
    game_id: str
    revision: int
    assets: tuple[TrustedCatalogAsset, ...]
    trust: CatalogTrust
    trust_reason: str


def parse_catalog_manifest(
    content: bytes,
    *,
    verify_signature: Callable[[str, bytes, bytes], bool] | None = None,
) -> ParsedCatalogManifest:
    if len(content) > 2 * 1024 * 1024:
        raise CatalogManifestError("catalog manifest is too large")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogManifestError("catalog manifest is not valid UTF-8 JSON") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CatalogManifestError("unsupported catalog manifest schema")
    required = {"schema_version", "catalog_id", "game_id", "revision", "assets", "signature"}
    if set(value) != required:
        raise CatalogManifestError("catalog manifest fields do not match schema v1")
    catalog_id = _identifier(value["catalog_id"], "catalog_id")
    game_id = _identifier(value["game_id"], "game_id")
    revision = value["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise CatalogManifestError("revision must be a positive integer")
    raw_assets = value["assets"]
    if not isinstance(raw_assets, list) or not raw_assets:
        raise CatalogManifestError("assets must be a non-empty array")
    assets = tuple(_parse_asset(item) for item in raw_assets)
    if len({item.dlc_id for item in assets}) != len(assets):
        raise CatalogManifestError("catalog contains duplicate DLC IDs")
    if len({item.asset_name.casefold() for item in assets}) != len(assets):
        raise CatalogManifestError("catalog contains duplicate asset names")
    signature = value["signature"]
    if not isinstance(signature, dict) or set(signature) != {"key_id", "value"}:
        raise CatalogManifestError("signature object is invalid")
    key_id = _identifier(signature["key_id"], "signature key_id")
    signature_value = signature["value"]
    if not isinstance(signature_value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,256}", signature_value):
        raise CatalogManifestError("signature value is invalid")
    unsigned = dict(value)
    unsigned.pop("signature")
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if verify_signature is None:
        trust = CatalogTrust.UNSIGNED
        reason = "清单包含签名字段，但程序尚未配置受信任发布者公钥"
    else:
        try:
            valid = verify_signature(key_id, canonical, signature_value.encode("ascii"))
        except Exception as error:
            raise CatalogManifestError(f"signature verification failed: {error}") from error
        trust = CatalogTrust.VERIFIED if valid else CatalogTrust.INVALID
        reason = "清单签名验证成功" if valid else "清单签名无效"
    if any(not item.distribution_authorized for item in assets):
        trust = CatalogTrust.INVALID
        reason = "清单中存在未授权分发的资源"
    return ParsedCatalogManifest(catalog_id, game_id, revision, assets, trust, reason)


def _identifier(value, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        raise CatalogManifestError(f"{field} is invalid")
    return value


def _parse_asset(value) -> TrustedCatalogAsset:
    fields = {"dlc_id", "asset_name", "size", "sha256", "min_game_version", "max_game_version", "distribution_authorized"}
    if not isinstance(value, dict) or set(value) != fields:
        raise CatalogManifestError("catalog asset fields do not match schema v1")
    dlc_id = _identifier(value["dlc_id"], "dlc_id")
    name = value["asset_name"]
    if not isinstance(name, str) or not re.fullmatch(r"[^\\/:*?\"<>|\x00-\x1f]{1,255}", name):
        raise CatalogManifestError("asset_name is invalid")
    size = value["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise CatalogManifestError("asset size must be positive")
    sha256 = value["sha256"]
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise CatalogManifestError("asset SHA-256 must be lowercase hexadecimal")
    versions = []
    for field in ("min_game_version", "max_game_version"):
        version = value[field]
        if version is not None and (not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version)):
            raise CatalogManifestError(f"{field} is invalid")
        versions.append(version)
    if not isinstance(value["distribution_authorized"], bool):
        raise CatalogManifestError("distribution_authorized must be boolean")
    return TrustedCatalogAsset(dlc_id, name, size, sha256, versions[0], versions[1], value["distribution_authorized"])
