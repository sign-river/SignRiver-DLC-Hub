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
    fixed_release_asset_url,
    normalize_download_source,
)
from ..infrastructure.net_errors import describe_network_error

LOGGER = logging.getLogger(__name__)


class CartridgeCatalogError(RuntimeError):
    """Raised when the hub index or a cartridge document cannot be loaded."""


@dataclass(frozen=True, slots=True)
class LoadedCartridge:
    entry: CartridgeIndexEntry
    document: CartridgeDocument
    cartridge: GameCartridge
    source: str


def _build_cartridge(
    document: CartridgeDocument,
    platform: str | None = None,
) -> GameCartridge:
    from ..adapters.document_cartridge import build_cartridge_from_document

    return build_cartridge_from_document(document, platform=platform)


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
        platform: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.bootstrap_dir = Path(bootstrap_dir) if bootstrap_dir else None
        self.download_source = normalize_download_source(download_source)
        self.source = source or create_hub_release_source(self.download_source)
        self._open = opener or self._download_bytes
        self.timeout = timeout
        self.platform = platform
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
        candidates: list[tuple[str, CartridgeIndex]] = []
        if allow_network:
            try:
                index = self._fetch_remote_index()
                candidates.append(("remote", index))
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
                candidates.append((label, index))
            except Exception as error:
                LOGGER.warning("Ignoring unusable %s cartridge index: %s", label, error)
        if candidates:
            # A hub may temporarily expose only Windows assets while a client
            # already bundles native platform metadata.  Prefer the first
            # current-platform-compatible candidate so a fresh but incomplete
            # remote index cannot overwrite the bundled macOS/SteamOS path.
            label, index = next(
                (
                    candidate
                    for candidate in candidates
                    if self._index_supports_current_platform(candidate[1])
                ),
                candidates[0],
            )
            if label == "remote":
                self._write_json(self._index_cache_path(), index.to_dict())
            self.index = index
            self.index_source = label
            return index
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
        allow_fallback: bool = True,
    ) -> LoadedCartridge:
        """Download or reuse one game cartridge described by the current index."""
        if self.index is None:
            self.refresh_index(allow_network=allow_network)
        assert self.index is not None
        entry = self.index.entry_for(game_id)
        if not entry.is_available_on(self._current_platform_name()):
            raise CartridgeCatalogError(
                f"游戏卡带 {entry.display_name} 当前平台暂无已发布的 DLC 或补丁资源"
            )
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
                document = self._document_from_payload(
                    payload, entry, bootstrap_path
                )
                source = "remote"
            except Exception as error:
                if not allow_fallback:
                    raise CartridgeCatalogError(
                        f"无法从远端加载游戏卡带 {game_id}：{error}"
                    ) from error
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
                    game_id,
                    error,
                )
        if document is None:
            document = self._load_local_document(entry, cache_path, bootstrap_path)
        if document is None:
            raise CartridgeCatalogError(f"本地也没有可用的游戏卡带：{game_id}")
        if document.game_id != entry.game_id:
            raise CartridgeCatalogError(
                f"卡带 game_id 与主表不一致：{document.game_id} != {entry.game_id}"
            )

        # A published hub index can briefly lag behind a newer client bootstrap.
        # Do not let an otherwise valid cached or remote Windows-only document
        # brick startup on macOS/SteamOS when the bundled document supports the
        # current platform. Bootstrap documents intentionally may have a newer
        # digest than the remote index, so load them through the normal local
        # reader and select the compatible one only for this fallback.
        if not self._supports_current_platform(document):
            bootstrap_document = self._load_bootstrap_document(entry, bootstrap_path)
            if (
                bootstrap_document is not None
                and bootstrap_document.game_id == entry.game_id
                and self._supports_current_platform(bootstrap_document)
            ):
                LOGGER.warning(
                    "Using bootstrap cartridge %s because %s lacks %s support",
                    game_id,
                    source,
                    self._current_platform_name(),
                )
                document = bootstrap_document
                source = "bootstrap-platform-fallback"
        loaded = LoadedCartridge(
            entry=entry,
            document=document,
            cartridge=_build_cartridge(document, platform=self.platform),
            source=source,
        )
        self._loaded[game_id] = loaded
        return loaded

    def load_default_cartridge(self, *, allow_network: bool = True) -> LoadedCartridge:
        if self.index is None:
            self.refresh_index(allow_network=allow_network)
        assert self.index is not None
        default_error: CartridgeCatalogError | None = None
        try:
            return self.load_cartridge(
                self.index.default_game_id,
                allow_network=allow_network,
            )
        except CartridgeCatalogError as error:
            default_error = error
        # The hub index may name a cartridge this installation cannot load
        # (e.g. a newer game absent from the local bootstrap, or a stale
        # default_game_id). Fall back to the first locally available
        # cartridge so offline startup never bricks on the default only.
        for entry in self.index.cartridges:
            if entry.game_id.casefold() == self.index.default_game_id.casefold():
                continue
            try:
                return self.load_cartridge(entry.game_id, allow_network=False)
            except CartridgeCatalogError:
                continue
        assert default_error is not None
        raise CartridgeCatalogError(
            f"无法加载默认游戏卡带 {self.index.default_game_id}：{default_error}"
        ) from default_error

    def get_loaded(self, game_id: str) -> LoadedCartridge | None:
        return self._loaded.get(game_id)

    def selection_records(self) -> tuple[dict[str, str], ...]:
        if self.index is None:
            return ()
        platform = self._current_platform_name()
        return tuple(
            {
                "selection_name": item.selection_name,
                "game_id": item.game_id,
                "platform": "Steam",
                "store_app_id": "",
                "display_name": item.display_name,
            }
            for item in self.index.cartridges
            if item.is_available_on(platform)
        )

    def _fetch_remote_index(self) -> CartridgeIndex:
        payload = self._fetch_remote_asset(INDEX_ASSET_NAME)
        index = CartridgeIndex.from_dict(json.loads(payload.decode("utf-8")))
        return index

    def _fetch_remote_asset(self, asset_name: str) -> bytes:
        return self._open(
            fixed_release_asset_url(self.download_source, HUB_RELEASE_TAG, asset_name),
            self.timeout,
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
                document = self._document_from_payload(
                    payload, entry, bootstrap_path
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

    def _document_from_payload(
        self,
        payload: bytes,
        entry: CartridgeIndexEntry,
        bootstrap_path: Path | None,
    ) -> CartridgeDocument:
        """Parse one cartridge and backfill only absent cleanup declarations.

        Old hub cartridges predate ``interference_files``. A new client must
        still remove stale files declared by its bundled cartridge, while an
        explicit remote empty list remains authoritative.
        """
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("cartridge JSON root must be an object")
        self._backfill_missing_interference_files(value, entry, bootstrap_path)
        return CartridgeDocument.from_dict(value)

    def _backfill_missing_interference_files(
        self,
        value: dict[str, object],
        entry: CartridgeIndexEntry,
        bootstrap_path: Path | None,
    ) -> None:
        """Use bundled cleanup entries only when an older document omits them."""
        if bootstrap_path is None or not bootstrap_path.is_file():
            return
        patch = value.get("patch")
        if not isinstance(patch, dict):
            return
        try:
            bootstrap = self._read_json(bootstrap_path)
        except Exception as error:
            LOGGER.warning(
                "Ignoring bootstrap cleanup fallback for %s: %s",
                entry.game_id,
                error,
            )
            return
        if str(bootstrap.get("game_id") or "") != entry.game_id:
            return
        bootstrap_patch = bootstrap.get("patch")
        if not isinstance(bootstrap_patch, dict):
            return

        platform = self._current_platform_name()
        fallback: object | None = None
        target: dict[str, object] | None = None
        if platform == "windows":
            if "interference_files" in patch:
                return
            fallback = bootstrap_patch.get("interference_files")
            target = patch
        else:
            platforms = patch.get("platforms")
            if not isinstance(platforms, dict):
                return
            target = platforms.get(platform)
            if not isinstance(target, dict) or "interference_files" in target:
                return
            bootstrap_platforms = bootstrap_patch.get("platforms")
            if isinstance(bootstrap_platforms, dict):
                bootstrap_variant = bootstrap_platforms.get(platform)
                if isinstance(bootstrap_variant, dict):
                    fallback = bootstrap_variant.get("interference_files")
            if fallback is None:
                fallback = bootstrap_patch.get("interference_files")
        if not isinstance(fallback, list):
            return
        target["interference_files"] = list(fallback)
        LOGGER.warning(
            "Backfilled missing interference_files for %s from the bundled cartridge",
            entry.game_id,
        )

    def _supports_current_platform(self, document: CartridgeDocument) -> bool:
        try:
            document.patch_fields_for(self._current_platform_name())
        except ValueError:
            return False
        return True

    def _current_platform_name(self) -> str:
        if self.platform:
            return str(self.platform)
        from ..domain import host_patch_platform

        return host_patch_platform().value

    def _index_supports_current_platform(self, index: CartridgeIndex) -> bool:
        platform = self._current_platform_name()
        return any(entry.is_available_on(platform) for entry in index.cartridges)

    @staticmethod
    def _load_bootstrap_document(
        entry: CartridgeIndexEntry,
        bootstrap_path: Path | None,
    ) -> CartridgeDocument | None:
        if bootstrap_path is None or not bootstrap_path.is_file():
            return None
        try:
            document = CartridgeDocument.from_dict(
                json.loads(bootstrap_path.read_text(encoding="utf-8"))
            )
        except Exception as error:
            LOGGER.warning(
                "Ignoring unusable bootstrap cartridge file %s: %s",
                bootstrap_path,
                error,
            )
            return None
        return document if document.game_id == entry.game_id else None

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
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise CartridgeCatalogError("卡带下载必须使用 HTTPS")
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
            raise CartridgeCatalogError(
                describe_network_error(error, url=url, action="下载卡带资源")
            ) from error


__all__ = [
    "CartridgeCatalogError",
    "CartridgeCatalogService",
    "LoadedCartridge",
]
