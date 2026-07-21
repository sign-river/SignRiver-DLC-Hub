"""Fetch, cache and materialise remote game cartridges on demand."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..adapters.cartridge import GameCartridge
from ..domain import (
    HUB_RELEASE_TAG,
    INDEX_ASSET_NAME,
    CartridgeDocument,
    CartridgeIndex,
    CartridgeIndexEntry,
)
from ..infrastructure.catalog import (
    create_hub_release_source,
    normalize_download_source,
)

LOGGER = logging.getLogger(__name__)


class CartridgeCatalogError(RuntimeError):
    """Raised when the hub index or a cartridge document cannot be loaded."""


@dataclass(frozen=True, slots=True)
class LoadedCartridge:
    entry: CartridgeIndexEntry
    document: CartridgeDocument
    cartridge: GameCartridge
    source: str


def _build_cartridge(document: CartridgeDocument) -> GameCartridge:
    from ..adapters.document_cartridge import build_cartridge_from_document

    return build_cartridge_from_document(document)


class CartridgeCatalogService:
    """Own the hub index and lazily downloaded per-game cartridge documents."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        bootstrap_dir: Path | None = None,
        download_source: str = "gitlink",
        source=None,
        opener: Callable[[str, float], bytes] | None = None,
        timeout: float = 20,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.bootstrap_dir = Path(bootstrap_dir) if bootstrap_dir else None
        self.download_source = normalize_download_source(download_source)
        self.source = source or create_hub_release_source(self.download_source)
        self._open = opener or self._download_bytes
        self.timeout = timeout
        self.index: CartridgeIndex | None = None
        self.index_source: str | None = None
        self._loaded: dict[str, LoadedCartridge] = {}

    def set_download_source(self, download_source: str) -> None:
        """Switch hub provider and drop in-memory cartridges from the old host."""
        normalized = normalize_download_source(download_source)
        if normalized == self.download_source:
            return
        self.download_source = normalized
        self.source = create_hub_release_source(normalized)
        self.index = None
        self.index_source = None
        self._loaded.clear()

    @property
    def loaded_cartridges(self) -> dict[str, object]:
        return {
            item.cartridge.selection_name: item.cartridge
            for item in self._loaded.values()
        }

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def refresh_index(self, *, allow_network: bool = True) -> CartridgeIndex:
        """Load the hub index, preferring a fresh remote copy when possible."""
        self.ensure_dirs()
        remote_error: Exception | None = None
        if allow_network:
            try:
                index = self._fetch_remote_index()
                self._write_json(self._index_cache_path(), index.to_dict())
                self.index = index
                self.index_source = "remote"
                return index
            except Exception as error:
                remote_error = error
                LOGGER.warning("Remote cartridge index refresh failed: %s", error)
        for label, path in (
            ("cache", self._index_cache_path()),
            ("bootstrap", self._index_bootstrap_path()),
        ):
            if path is None or not path.is_file():
                continue
            try:
                index = CartridgeIndex.from_dict(self._read_json(path))
                self.index = index
                self.index_source = label
                return index
            except Exception as error:
                LOGGER.warning("Ignoring unusable %s cartridge index: %s", label, error)
        if remote_error is not None:
            raise CartridgeCatalogError(
                f"无法加载游戏卡带主表：{remote_error}"
            ) from remote_error
        raise CartridgeCatalogError("未找到可用的游戏卡带主表")

    def load_cartridge(
        self,
        game_id: str,
        *,
        allow_network: bool = True,
        prefer_cached: bool = False,
    ) -> LoadedCartridge:
        """Download or reuse one game cartridge described by the current index."""
        if self.index is None:
            self.refresh_index(allow_network=allow_network)
        assert self.index is not None
        entry = self.index.entry_for(game_id)
        existing = self._loaded.get(game_id)
        if existing is not None and existing.entry.sha256 == entry.sha256:
            return existing
        self.ensure_dirs()
        cache_path = self._cartridge_cache_path(game_id)
        bootstrap_path = self._cartridge_bootstrap_path(entry.asset_name)
        document: CartridgeDocument | None = None
        source = "cache"
        if prefer_cached or not allow_network:
            document = self._load_local_document(entry, cache_path, bootstrap_path)
        if document is None and allow_network:
            try:
                payload = self._fetch_remote_asset(entry.asset_name)
                digest = hashlib.sha256(payload).hexdigest()
                if digest != entry.sha256:
                    raise CartridgeCatalogError(
                        f"卡带 {entry.asset_name} 摘要不匹配："
                        f"期望 {entry.sha256}，实际 {digest}"
                    )
                cache_path.write_bytes(payload)
                document = CartridgeDocument.from_dict(json.loads(payload.decode("utf-8")))
                source = "remote"
            except Exception as error:
                if document is None:
                    document = self._load_local_document(
                        entry, cache_path, bootstrap_path
                    )
                if document is None:
                    raise CartridgeCatalogError(
                        f"无法加载游戏卡带 {game_id}：{error}"
                    ) from error
                source = "cache-fallback"
                LOGGER.warning(
                    "Using local cartridge for %s after remote failure: %s",
                    game_id, error,
                )
        if document is None:
            document = self._load_local_document(entry, cache_path, bootstrap_path)
        if document is None:
            raise CartridgeCatalogError(f"本地也没有可用的游戏卡带：{game_id}")
        if document.game_id != entry.game_id:
            raise CartridgeCatalogError(
                f"卡带 game_id 与主表不一致：{document.game_id} != {entry.game_id}"
            )
        loaded = LoadedCartridge(
            entry=entry,
            document=document,
            cartridge=_build_cartridge(document),
            source=source,
        )
        self._loaded[game_id] = loaded
        return loaded

    def load_default_cartridge(self, *, allow_network: bool = True) -> LoadedCartridge:
        if self.index is None:
            self.refresh_index(allow_network=allow_network)
        assert self.index is not None
        return self.load_cartridge(
            self.index.default_game_id, allow_network=allow_network,
        )

    def get_loaded(self, game_id: str) -> LoadedCartridge | None:
        return self._loaded.get(game_id)

    def selection_records(self) -> tuple[dict[str, str], ...]:
        if self.index is None:
            return ()
        return tuple(
            {
                "selection_name": item.selection_name,
                "game_id": item.game_id,
                "platform": "Steam",
                "store_app_id": "",
                "display_name": item.display_name,
            }
            for item in self.index.cartridges
        )

    def _fetch_remote_index(self) -> CartridgeIndex:
        payload = self._fetch_remote_asset(INDEX_ASSET_NAME)
        index = CartridgeIndex.from_dict(json.loads(payload.decode("utf-8")))
        return index

    def _fetch_remote_asset(self, asset_name: str) -> bytes:
        release = self.source.get_release_by_tag(HUB_RELEASE_TAG)
        for asset in release.assets:
            if asset.name == asset_name:
                return self._open(asset.download_url, self.timeout)
        raise CartridgeCatalogError(
            f"hub Release 中缺少资源：{asset_name}"
        )

    def _load_local_document(
        self,
        entry: CartridgeIndexEntry,
        cache_path: Path,
        bootstrap_path: Path | None,
    ) -> CartridgeDocument | None:
        for path in (cache_path, bootstrap_path):
            if path is None or not path.is_file():
                continue
            try:
                payload = path.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                if digest != entry.sha256 and path == cache_path:
                    # Stale cache from an older index revision.
                    continue
                document = CartridgeDocument.from_dict(
                    json.loads(payload.decode("utf-8"))
                )
                if document.game_id == entry.game_id:
                    if path == bootstrap_path and digest != entry.sha256:
                        # Bootstrap may lag the remote index during development.
                        LOGGER.info(
                            "Using bootstrap cartridge %s despite digest mismatch",
                            entry.game_id,
                        )
                    return document
            except Exception as error:
                LOGGER.warning("Ignoring unusable cartridge file %s: %s", path, error)
        return None

    def _index_cache_path(self) -> Path:
        return self.cache_dir / INDEX_ASSET_NAME

    def _cartridge_cache_path(self, game_id: str) -> Path:
        return self.cache_dir / f"cartridge_{game_id}.json"

    def _index_bootstrap_path(self) -> Path | None:
        if self.bootstrap_dir is None:
            return None
        return self.bootstrap_dir / INDEX_ASSET_NAME

    def _cartridge_bootstrap_path(self, asset_name: str) -> Path | None:
        if self.bootstrap_dir is None:
            return None
        return self.bootstrap_dir / asset_name

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object")
        return payload

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _download_bytes(url: str, timeout: float) -> bytes:
        from ..infrastructure.net_errors import describe_network_error

        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise CartridgeCatalogError("cartridge downloads must use HTTPS")
        request = Request(
            url,
            headers={
                "Accept": "application/json,application/octet-stream",
                "User-Agent": "SignRiver-DLC-Hub/0.1",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError) as error:
            raise OSError(
                describe_network_error(error, url=url, action="下载卡带资源")
            ) from error


__all__ = [
    "CartridgeCatalogError",
    "CartridgeCatalogService",
    "LoadedCartridge",
]
