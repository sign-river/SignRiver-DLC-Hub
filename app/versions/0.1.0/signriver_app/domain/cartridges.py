"""Remote game-cartridge documents and the hub index that lists them.

The desktop shell no longer ships game-specific cartridges in code.  A small
hub index is downloaded first; each game cartridge is fetched only when the
user selects that game (or when it is the configured default).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_ENGINES = frozenset({"steam_configured_v1"})
_SUPPORTED_INSPECTORS = frozenset({"directory", "stellaris_zip"})
CARTRIDGE_INDEX_SCHEMA = 1
CARTRIDGE_DOCUMENT_SCHEMA = 1
HUB_RELEASE_TAG = "hub"
INDEX_ASSET_NAME = "cartridges_index.json"


def _require_id(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID.fullmatch(text):
        raise ValueError(f"{field} must be a lowercase id")
    return text


def _require_sha256(value: object, *, field: str = "sha256") -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return text


def _require_nonempty(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


@dataclass(frozen=True, slots=True)
class CartridgeIndexEntry:
    """One selectable game listed by the remote hub index."""

    game_id: str
    display_name: str
    asset_name: str
    sha256: str
    size_bytes: int | None = None
    min_client_version: str | None = None

    @property
    def selection_name(self) -> str:
        return self.display_name

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CartridgeIndexEntry":
        size = value.get("size_bytes")
        size_bytes = None if size in (None, "") else int(size)
        if size_bytes is not None and size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")
        min_version = value.get("min_client_version")
        return cls(
            game_id=_require_id(value.get("game_id"), field="game_id"),
            display_name=_require_nonempty(value.get("display_name"), field="display_name"),
            asset_name=_require_nonempty(value.get("asset_name"), field="asset_name"),
            sha256=_require_sha256(value.get("sha256")),
            size_bytes=size_bytes,
            min_client_version=(
                None if min_version in (None, "") else str(min_version).strip()
            ),
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "game_id": self.game_id,
            "display_name": self.display_name,
            "asset_name": self.asset_name,
            "sha256": self.sha256,
        }
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.min_client_version:
            payload["min_client_version"] = self.min_client_version
        return payload


@dataclass(frozen=True, slots=True)
class CartridgeIndex:
    """Hub master table describing every publishable client cartridge."""

    schema_version: int
    default_game_id: str
    cartridges: tuple[CartridgeIndexEntry, ...]
    repository_owner: str = "signriver"
    repository_name: str = "signriver-dlc-assets"
    release_tag: str = HUB_RELEASE_TAG

    def __post_init__(self) -> None:
        if self.schema_version != CARTRIDGE_INDEX_SCHEMA:
            raise ValueError(
                f"unsupported cartridge index schema {self.schema_version}"
            )
        if not self.cartridges:
            raise ValueError("cartridge index must list at least one game")
        ids = [item.game_id for item in self.cartridges]
        if len(ids) != len(set(ids)):
            raise ValueError("cartridge index contains duplicate game_id values")
        if self.default_game_id not in {item.game_id for item in self.cartridges}:
            raise ValueError("default_game_id is not present in the index")

    def entry_for(self, game_id: str) -> CartridgeIndexEntry:
        for item in self.cartridges:
            if item.game_id == game_id:
                return item
        raise KeyError(game_id)

    def default_entry(self) -> CartridgeIndexEntry:
        return self.entry_for(self.default_game_id)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CartridgeIndex":
        raw_items = value.get("cartridges")
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("cartridges must be a non-empty list")
        entries = tuple(
            CartridgeIndexEntry.from_dict(item)
            for item in raw_items
            if isinstance(item, dict)
        )
        repository = value.get("repository")
        owner = "signriver"
        name = "signriver-dlc-assets"
        if isinstance(repository, dict):
            owner = str(repository.get("owner") or owner)
            name = str(repository.get("repository") or name)
        return cls(
            schema_version=int(value.get("schema_version") or 0),
            default_game_id=_require_id(
                value.get("default_game_id"), field="default_game_id"
            ),
            cartridges=entries,
            repository_owner=owner,
            repository_name=name,
            release_tag=str(value.get("release_tag") or HUB_RELEASE_TAG),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "default_game_id": self.default_game_id,
            "release_tag": self.release_tag,
            "repository": {
                "owner": self.repository_owner,
                "repository": self.repository_name,
            },
            "cartridges": [item.to_dict() for item in self.cartridges],
        }


@dataclass(frozen=True, slots=True)
class CartridgeFreshness:
    """Publisher-authored snapshot of when packaged resources were last updated."""

    resources_updated_at: str
    package_count: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CartridgeFreshness":
        stamp = str(
            value.get("resources_updated_at") or value.get("checked_at") or ""
        ).strip()
        return cls(
            resources_updated_at=stamp,
            package_count=max(
                0,
                int(value.get("package_count") or value.get("local_package_count") or 0),
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "resources_updated_at": self.resources_updated_at,
            "package_count": self.package_count,
        }

    def client_summary(self) -> str:
        if not self.resources_updated_at:
            return "资源提交时间：未知"
        extra = f" · 收录 {self.package_count} 个包" if self.package_count else ""
        return f"资源提交于 {self.resources_updated_at}{extra}"


@dataclass(frozen=True, slots=True)
class CartridgeDocument:
    """Complete declarative description of one Steam game cartridge."""

    schema_version: int
    engine: str
    game_id: str
    display_name: str
    store_app_id: str
    release_tag: str
    executable_relative_path: str
    dlc_relative_dir: str
    package_inspector: str
    unlocker_dll_name: str
    original_backup_dll_name: str
    appinfo_asset_name: str
    patch_install_relative_dir: str
    ini_target_name: str = "cream_api.ini"
    language: str = "schinese"
    unlock_all: bool = True
    extra_protection: bool = False
    force_offline: bool = False
    install_directory_from_slug: bool = False
    repository_owner: str = "signriver"
    repository_name: str = "signriver-dlc-assets"
    repositories: dict[str, dict[str, str]] = field(default_factory=dict)
    freshness: CartridgeFreshness | None = None

    def __post_init__(self) -> None:
        if self.schema_version != CARTRIDGE_DOCUMENT_SCHEMA:
            raise ValueError(
                f"unsupported cartridge schema {self.schema_version}"
            )
        if self.engine not in _SUPPORTED_ENGINES:
            raise ValueError(f"unsupported cartridge engine: {self.engine}")
        if self.package_inspector not in _SUPPORTED_INSPECTORS:
            raise ValueError(
                f"unsupported package_inspector: {self.package_inspector}"
            )

    @property
    def selection_name(self) -> str:
        return self.display_name

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CartridgeDocument":
        repository = value.get("repository")
        owner = "signriver"
        name = "signriver-dlc-assets"
        if isinstance(repository, dict):
            owner = str(repository.get("owner") or owner)
            name = str(repository.get("repository") or name)
        repositories: dict[str, dict[str, str]] = {}
        raw_repositories = value.get("repositories")
        if isinstance(raw_repositories, dict):
            for provider, coords in raw_repositories.items():
                if not isinstance(coords, dict):
                    continue
                provider_owner = str(coords.get("owner") or "").strip()
                provider_repo = str(coords.get("repository") or "").strip()
                if provider_owner and provider_repo:
                    repositories[str(provider)] = {
                        "owner": provider_owner,
                        "repository": provider_repo,
                    }
        if "gitlink" not in repositories:
            repositories["gitlink"] = {"owner": owner, "repository": name}
        if "github" not in repositories:
            repositories["github"] = {
                "owner": "sign-river",
                "repository": name,
            }
        patch = value.get("patch")
        if not isinstance(patch, dict):
            raise ValueError("patch object is required")
        freshness = None
        raw_freshness = value.get("freshness")
        if isinstance(raw_freshness, dict):
            freshness = CartridgeFreshness.from_dict(raw_freshness)
        return cls(
            schema_version=int(value.get("schema_version") or 0),
            engine=str(value.get("engine") or "").strip(),
            game_id=_require_id(value.get("game_id"), field="game_id"),
            display_name=_require_nonempty(
                value.get("display_name"), field="display_name"
            ),
            store_app_id=_require_nonempty(
                value.get("store_app_id"), field="store_app_id"
            ),
            release_tag=_require_nonempty(
                value.get("release_tag"), field="release_tag"
            ),
            executable_relative_path=_require_nonempty(
                value.get("executable_relative_path"),
                field="executable_relative_path",
            ),
            dlc_relative_dir=_require_nonempty(
                value.get("dlc_relative_dir"), field="dlc_relative_dir"
            ),
            package_inspector=str(value.get("package_inspector") or "directory"),
            unlocker_dll_name=_require_nonempty(
                patch.get("unlocker_dll_name"), field="unlocker_dll_name"
            ),
            original_backup_dll_name=_require_nonempty(
                patch.get("original_backup_dll_name"),
                field="original_backup_dll_name",
            ),
            appinfo_asset_name=_require_nonempty(
                patch.get("appinfo_asset_name"), field="appinfo_asset_name"
            ),
            patch_install_relative_dir=str(
                patch.get("install_relative_dir") or "."
            ),
            ini_target_name=str(patch.get("ini_target_name") or "cream_api.ini"),
            language=str(patch.get("language") or "schinese"),
            unlock_all=bool(patch.get("unlock_all", True)),
            extra_protection=bool(patch.get("extra_protection", False)),
            force_offline=bool(patch.get("force_offline", False)),
            install_directory_from_slug=bool(
                value.get("install_directory_from_slug", False)
            ),
            repository_owner=owner,
            repository_name=name,
            repositories=repositories,
            freshness=freshness,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "engine": self.engine,
            "game_id": self.game_id,
            "display_name": self.display_name,
            "store_app_id": self.store_app_id,
            "release_tag": self.release_tag,
            "executable_relative_path": self.executable_relative_path,
            "dlc_relative_dir": self.dlc_relative_dir,
            "package_inspector": self.package_inspector,
            "install_directory_from_slug": self.install_directory_from_slug,
            "repository": {
                "owner": self.repository_owner,
                "repository": self.repository_name,
            },
            "repositories": self.repositories,
            "patch": {
                "unlocker_dll_name": self.unlocker_dll_name,
                "original_backup_dll_name": self.original_backup_dll_name,
                "appinfo_asset_name": self.appinfo_asset_name,
                "install_relative_dir": self.patch_install_relative_dir,
                "ini_target_name": self.ini_target_name,
                "language": self.language,
                "unlock_all": self.unlock_all,
                "extra_protection": self.extra_protection,
                "force_offline": self.force_offline,
            },
        }
        if self.freshness is not None:
            payload["freshness"] = self.freshness.to_dict()
        return payload


__all__ = [
    "CARTRIDGE_DOCUMENT_SCHEMA",
    "CARTRIDGE_INDEX_SCHEMA",
    "HUB_RELEASE_TAG",
    "INDEX_ASSET_NAME",
    "CartridgeDocument",
    "CartridgeFreshness",
    "CartridgeIndex",
    "CartridgeIndexEntry",
]
