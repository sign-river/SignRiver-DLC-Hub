"""Application service that turns release assets into a DLC library."""

from __future__ import annotations

import re

from ..domain import DlcCatalogEntry

_STELLARIS_ASSET = re.compile(r"^(dlc\d{3})_([a-z0-9_]+)\.zip$", re.I)


class StellarisCatalogService:
    def __init__(self, release_source, *, release_tag: str = "ste") -> None:
        self.release_source = release_source
        self.release_tag = release_tag

    def refresh(self) -> tuple[DlcCatalogEntry, ...]:
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
        return tuple(sorted(entries, key=lambda item: item.dlc_id))
