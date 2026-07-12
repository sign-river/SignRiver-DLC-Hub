"""Application service that turns release assets into a DLC library."""

from __future__ import annotations

import re

from ..domain import CatalogSnapshot, CatalogTrust, DlcCatalogEntry
from ..infrastructure.catalog.manifest import parse_catalog_manifest

_STELLARIS_ASSET = re.compile(r"^(dlc\d{3})_([a-z0-9_]+)\.zip$", re.I)


class StellarisCatalogService:
    def __init__(self, release_source, *, release_tag: str = "ste", manifest_loader=None, signature_verifier=None) -> None:
        self.release_source = release_source
        self.release_tag = release_tag
        self.manifest_loader = manifest_loader
        self.signature_verifier = signature_verifier

    def refresh(self) -> tuple[DlcCatalogEntry, ...]:
        return self.refresh_snapshot().entries

    def refresh_snapshot(self) -> CatalogSnapshot:
        release = self.release_source.get_release_by_tag(self.release_tag)
        entries: list[DlcCatalogEntry] = []
        for asset in release.assets:
            match = _STELLARIS_ASSET.fullmatch(asset.name)
            if not match:
                continue
            slug = match.group(2).lower()
            entries.append(DlcCatalogEntry(
                dlc_id=match.group(1).lower(), slug=slug,
                display_name=slug.replace("_", " ").title(), asset=asset,
                release_tag=release.tag,
            ))
        normalized = tuple(sorted(entries, key=lambda item: item.dlc_id))
        manifest_assets = [
            asset for asset in release.assets if asset.name == "dlc-catalog.json"
        ]
        if not manifest_assets:
            return CatalogSnapshot(
                normalized, CatalogTrust.MANIFEST_MISSING,
                "Release 未提供 dlc-catalog.json；允许浏览和下载，但禁止自动安装",
            )
        if len(manifest_assets) != 1 or self.manifest_loader is None:
            return CatalogSnapshot(
                normalized, CatalogTrust.INVALID,
                "可信清单数量异常或未配置清单读取器",
            )
        try:
            parsed = parse_catalog_manifest(
                self.manifest_loader(manifest_assets[0]),
                verify_signature=self.signature_verifier,
            )
        except ValueError as error:
            return CatalogSnapshot(normalized, CatalogTrust.INVALID, str(error))
        if parsed.game_id != "stellaris":
            return CatalogSnapshot(normalized, CatalogTrust.INVALID, "清单 game_id 与 Stellaris 不匹配")
        release_assets = {entry.asset.name: entry for entry in normalized}
        trusted_names = {asset.asset_name for asset in parsed.assets}
        if trusted_names != set(release_assets):
            return CatalogSnapshot(normalized, CatalogTrust.INVALID, "可信清单与 Release DLC 附件集合不一致")
        return CatalogSnapshot(
            normalized, parsed.trust, parsed.trust_reason, parsed.assets
        )
