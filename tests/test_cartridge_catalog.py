from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from signriver_app.adapters.builtin import create_builtin_cartridges
from signriver_app.application.cartridge_catalog import (
    CartridgeCatalogError,
    CartridgeCatalogService,
)
from signriver_app.domain import (
    CartridgeDocument,
    CartridgeIndex,
    INDEX_ASSET_NAME,
)
from signriver_publisher import PublisherWorkspace
from signriver_publisher.client_cartridges import export_hub_cartridges


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "config" / "cartridges"


def test_bootstrap_index_and_documents_round_trip() -> None:
    index = CartridgeIndex.from_dict(
        json.loads((BOOTSTRAP / INDEX_ASSET_NAME).read_text(encoding="utf-8"))
    )
    assert index.default_game_id == "stellaris"
    assert {item.game_id for item in index.cartridges} == {
        "stellaris",
        "civilization_6",
        "hearts_of_iron_4",
        "cities_skylines",
        "rimworld",
        "crusader_kings_3",
        "victoria_3",
        "workers_resources_soviet_republic",
        "civilization_7",
        "age_of_wonders_4",
    }
    for entry in index.cartridges:
        payload = (BOOTSTRAP / entry.asset_name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry.sha256
        document = CartridgeDocument.from_dict(json.loads(payload.decode("utf-8")))
        assert document.game_id == entry.game_id
        # Keep the legacy backup-name spelling for modules already published
        # before the runtime_original_library_name rename.  Otherwise a newer
        # bundled cartridge can make the launcher's rollback target unbootable.
        patch = json.loads(payload.decode("utf-8"))["patch"]
        assert patch["original_backup_dll_name"] == patch["runtime_original_library_name"]


def test_builtin_cartridges_are_built_from_bootstrap_documents() -> None:
    cartridges = {
        item.adapter.descriptor.game_id: item
        for item in create_builtin_cartridges(BOOTSTRAP, platform="windows")
    }
    assert cartridges["stellaris"].release_tag == "stellaris"
    assert cartridges["stellaris"].package_inspector.__name__ == "inspect_directory_package"
    assert cartridges["civilization_6"].dlc_relative_dir == "DLC"
    assert cartridges["hearts_of_iron_4"].store_app_id == "394360"
    assert cartridges["cities_skylines"].store_app_id == "255710"
    assert cartridges["rimworld"].dlc_relative_dir == "Data"
    assert cartridges["civilization_7"].dlc_delivery_mode == "built_in"
    assert cartridges["age_of_wonders_4"].patch_profile.install_relative_dirs == (
        ".",
        "launcher-se/resources/app.asar.unpacked/node_modules/greenworks/lib",
    )
    assert cartridges["rimworld"].patch_profile.install_relative_dir == (
        "RimWorldWin64_Data/Plugins/x86_64"
    )


def test_client_ui_describes_built_in_dlc_as_patch_only_activation() -> None:
    source = (ROOT / "app" / "versions" / "0.1.0" / "app_entry.py").read_text(
        encoding="utf-8"
    )

    assert "def _uses_built_in_dlc_delivery" in source
    assert "DLC 已随游戏本体安装，无需额外下载；安装补丁后即可激活。" in source
    assert 'text = "安装补丁并激活"' in source


def test_catalog_loads_default_from_bootstrap_without_network(tmp_path: Path) -> None:
    service = CartridgeCatalogService(
        tmp_path / "cache",
        bootstrap_dir=BOOTSTRAP,
        source=object(),  # network must not be touched
        platform="windows",
    )
    index = service.refresh_index(allow_network=False)
    loaded = service.load_default_cartridge(allow_network=False)
    assert index.default_game_id == "stellaris"
    assert loaded.document.game_id == "stellaris"
    assert loaded.source in {"bootstrap", "cache"}
    assert "群星 (Stellaris)" in service.loaded_cartridges


def test_catalog_lazy_loads_other_games_from_bootstrap(tmp_path: Path) -> None:
    service = CartridgeCatalogService(
        tmp_path / "cache",
        bootstrap_dir=BOOTSTRAP,
        source=object(),
        platform="windows",
    )
    service.refresh_index(allow_network=False)
    service.load_default_cartridge(allow_network=False)
    loaded = service.load_cartridge("civilization_6", allow_network=False)
    assert loaded.document.display_name == "文明6 (Civilization VI)"
    assert loaded.cartridge.patch_profile.install_relative_dir == (
        "Base/Binaries/Win64Steam"
    )


def test_catalog_uses_platform_compatible_bootstrap_when_cache_lags(
    tmp_path: Path,
) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    for source in BOOTSTRAP.glob("*.json"):
        (bootstrap / source.name).write_bytes(source.read_bytes())

    stale_document = json.loads(
        (bootstrap / "cartridge_stellaris.json").read_text(encoding="utf-8")
    )
    stale_document["patch"].pop("platforms")
    stale_payload = (
        json.dumps(stale_document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "cartridge_stellaris.json").write_bytes(stale_payload)

    stale_index = json.loads((bootstrap / INDEX_ASSET_NAME).read_text(encoding="utf-8"))
    entry = next(
        item for item in stale_index["cartridges"] if item["game_id"] == "stellaris"
    )
    entry["sha256"] = hashlib.sha256(stale_payload).hexdigest()
    entry["size_bytes"] = len(stale_payload)
    (cache / INDEX_ASSET_NAME).write_text(
        json.dumps(stale_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    service = CartridgeCatalogService(
        cache,
        bootstrap_dir=bootstrap,
        source=object(),
        platform="macos",
    )
    service.refresh_index(allow_network=False)
    loaded = service.load_default_cartridge(allow_network=False)

    assert loaded.source == "bootstrap-platform-fallback"
    assert loaded.cartridge.patch_profile.unlocker_dll_name == "libsteam_api.dylib"
    assert loaded.cartridge.executable_name == "stellaris.app/Contents/MacOS/stellaris"


def test_catalog_backfills_omitted_interference_files_from_bootstrap(
    tmp_path: Path,
) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    for source in BOOTSTRAP.glob("*.json"):
        (bootstrap / source.name).write_bytes(source.read_bytes())

    stale_document = json.loads(
        (bootstrap / "cartridge_stellaris.json").read_text(encoding="utf-8")
    )
    stale_document["patch"].pop("interference_files")
    stale_payload = (
        json.dumps(stale_document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "cartridge_stellaris.json").write_bytes(stale_payload)

    stale_index = json.loads((bootstrap / INDEX_ASSET_NAME).read_text(encoding="utf-8"))
    entry = next(
        item for item in stale_index["cartridges"] if item["game_id"] == "stellaris"
    )
    entry["sha256"] = hashlib.sha256(stale_payload).hexdigest()
    entry["size_bytes"] = len(stale_payload)
    (cache / INDEX_ASSET_NAME).write_text(
        json.dumps(stale_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    service = CartridgeCatalogService(
        cache,
        bootstrap_dir=bootstrap,
        source=object(),
        platform="windows",
    )
    service.refresh_index(allow_network=False)
    loaded = service.load_default_cartridge(allow_network=False)

    assert loaded.cartridge.patch_profile.interference_files == (
        "Juuj_Steam.json",
        "Juuj_更新发布地址.html",
        "Juuj_免费分享_请勿在任何渠道受骗付费购买.txt",
        "Juuj_制作_请勿转载_免费声明.txt",
        "steam_api64_org_game.dll",
        "steam_api64_org_launcher.dll",
        "LinkNeverDie_Com_64.dll",
        "Emulator64.dll",
        "SWConfig.ini",
        "SWLoader.txt",
    )


def test_catalog_preserves_explicit_empty_interference_file_list(tmp_path: Path) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    for source in BOOTSTRAP.glob("*.json"):
        (bootstrap / source.name).write_bytes(source.read_bytes())

    document = json.loads(
        (bootstrap / "cartridge_stellaris.json").read_text(encoding="utf-8")
    )
    document["patch"]["interference_files"] = []
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "cartridge_stellaris.json").write_bytes(payload)

    index = json.loads((bootstrap / INDEX_ASSET_NAME).read_text(encoding="utf-8"))
    entry = next(item for item in index["cartridges"] if item["game_id"] == "stellaris")
    entry["sha256"] = hashlib.sha256(payload).hexdigest()
    entry["size_bytes"] = len(payload)
    (cache / INDEX_ASSET_NAME).write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    service = CartridgeCatalogService(
        cache,
        bootstrap_dir=bootstrap,
        source=object(),
        platform="windows",
    )
    service.refresh_index(allow_network=False)

    assert service.load_default_cartridge(
        allow_network=False
    ).cartridge.patch_profile.interference_files == ()


def test_catalog_rejects_tampered_remote_cartridge(tmp_path: Path) -> None:
    index_payload = json.loads(
        (BOOTSTRAP / INDEX_ASSET_NAME).read_text(encoding="utf-8")
    )
    assets = {
        INDEX_ASSET_NAME: json.dumps(index_payload).encode("utf-8"),
        "cartridge_stellaris.json": b'{"not":"a cartridge"}',
    }

    class FakeSource:
        def get_release_by_tag(self, tag: str):
            assert tag == "hub"
            return type(
                "Release",
                (),
                {
                    "assets": [
                        type(
                            "Asset",
                            (),
                            {
                                "name": name,
                                "download_url": f"https://example.test/{name}",
                            },
                        )()
                        for name in assets
                    ],
                },
            )()

    def opener(url: str, _timeout: float) -> bytes:
        name = url.rsplit("/", 1)[-1]
        return assets[name]

    service = CartridgeCatalogService(
        tmp_path / "cache",
        bootstrap_dir=None,
        source=FakeSource(),
        opener=opener,
    )
    service.refresh_index(allow_network=True)
    with pytest.raises(CartridgeCatalogError, match="摘要不匹配|无法加载"):
        service.load_cartridge("stellaris", allow_network=True)


def test_catalog_strict_remote_load_does_not_fall_back_to_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    bootstrap = BOOTSTRAP / "cartridge_stellaris.json"
    (cache / "cartridge_stellaris.json").write_bytes(bootstrap.read_bytes())

    class FailingSource:
        def get_release_by_tag(self, _tag: str):
            raise OSError("remote unavailable")

    service = CartridgeCatalogService(
        cache,
        bootstrap_dir=None,
        source=FailingSource(),
    )
    index = CartridgeIndex.from_dict(
        json.loads((BOOTSTRAP / INDEX_ASSET_NAME).read_text(encoding="utf-8"))
    )
    service.index = index
    with pytest.raises(CartridgeCatalogError, match="无法从远端加载游戏卡带"):
        service.load_cartridge(
            "stellaris", allow_network=True, allow_fallback=False
        )


def test_publisher_exports_hub_cartridges(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path)
    workspace.initialize()
    announcement = {
        "schema_version": 1,
        "id": "export-test",
        "title": "导出公告",
        "body": "正文",
    }
    (tmp_path / "announcement.json").write_text(
        json.dumps(announcement, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    written = workspace.export_client_hub(default_game_id="stellaris")
    names = {path.name for path in written}
    assert INDEX_ASSET_NAME in names
    assert "cartridge_stellaris.json" in names
    assert "announcement.json" in names
    index = CartridgeIndex.from_dict(
        json.loads(
            (tmp_path / "output" / "hub" / INDEX_ASSET_NAME).read_text(encoding="utf-8")
        )
    )
    assert index.default_game_id == "stellaris"
    # Exported documents must also be accepted by the client parser.
    for entry in index.cartridges:
        document = CartridgeDocument.from_dict(
            json.loads(
                (tmp_path / "output" / "hub" / entry.asset_name).read_text(
                    encoding="utf-8"
                )
            )
        )
        assert document.executable_relative_path
    hoi4 = CartridgeDocument.from_dict(
        json.loads(
            (tmp_path / "output" / "hub" / "cartridge_hearts_of_iron_4.json").read_text(
                encoding="utf-8"
            )
        )
    )
    assert hoi4.patch_platforms == ("macos", "steamos", "windows")
    assert hoi4.patch_fields_for("steamos")["unlocker_dll_name"] == "libsteam_api.so"
    unsupported = CartridgeDocument.from_dict(
        json.loads(
            (tmp_path / "output" / "hub" / "cartridge_crusader_kings_3.json").read_text(
                encoding="utf-8"
            )
        )
    )
    with pytest.raises(ValueError, match="不支持当前平台"):
        unsupported.patch_fields_for("steamos")
    exported = json.loads(
        (tmp_path / "output" / "hub" / "announcement.json").read_text(encoding="utf-8")
    )
    assert exported["id"] == "export-test"


def test_publisher_snapshots_complete_hub_as_publish_assets(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path)
    workspace.initialize()

    assets = workspace.hub_publish_assets(default_game_id="stellaris")

    assert assets
    assert assets[-1].name == "cartridges_index.json"
    assert {asset.name for asset in assets} == {
        path.name for path in workspace.export_client_hub(default_game_id="stellaris")
    }
    for asset in assets:
        assert asset.path.parent == tmp_path / "output" / "hub"
        assert asset.size_bytes == asset.path.stat().st_size
        assert asset.sha256 == hashlib.sha256(asset.path.read_bytes()).hexdigest()


def test_hub_publish_state_is_isolated_from_game_cartridges(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path)
    workspace.initialize()
    profile = workspace.hub_release_profile()
    state = {
        "version": 1,
        "owner": "signriver",
        "repository": "assets",
        "release_tag": "hub",
        "assets": {},
    }

    workspace.save_publish_state(profile, state)

    assert workspace.load_publish_state(profile, "signriver", "assets") == state
    assert profile.game_id == "hub"
    assert profile.release_tag == "hub"
    assert {item.game_id for item in workspace.list_games()}.isdisjoint({"hub"})


def test_export_hub_cartridges_helper_writes_digest_index(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path)
    profiles = workspace.initialize() and workspace.list_games()
    output = tmp_path / "hub"
    output.mkdir()
    stale_cartridge = output / "cartridge_removed_game.json"
    stale_announcement = output / "announcement.json"
    unrelated = output / "notes.txt"
    stale_cartridge.write_text("{}", encoding="utf-8")
    stale_announcement.write_text("{}", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")

    written = export_hub_cartridges(profiles, output)
    index_path = next(path for path in written if path.name == INDEX_ASSET_NAME)
    index = CartridgeIndex.from_dict(json.loads(index_path.read_text(encoding="utf-8")))
    for entry in index.cartridges:
        digest = hashlib.sha256(
            (tmp_path / "hub" / entry.asset_name).read_bytes()
        ).hexdigest()
        assert digest == entry.sha256
    assert not stale_cartridge.exists()
    assert not stale_announcement.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
