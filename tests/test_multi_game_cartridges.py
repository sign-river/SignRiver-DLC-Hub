from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from signriver_app.adapters.builtin import create_builtin_cartridges
from signriver_app.adapters.common import configured_steam
from signriver_app.infrastructure.catalog import (
    inspect_directory_package,
    inspect_grouped_directory_package,
)
from signriver_publisher import (
    PublisherWorkspace, SteamAppInfo,
    create_builtin_cartridges as publisher_cartridges,
)


def make_directory_package(path: Path, root: str = "dlc001_test_pack") -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{root}/content/payload.bin", b"payload")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_directory_inspector_accepts_trusted_existing_digest(tmp_path: Path) -> None:
    package = tmp_path / "dlc001_test_pack.zip"
    make_directory_package(package)
    known = "b" * 64

    metadata = inspect_directory_package(package, known_sha256=known)

    assert metadata.package_sha256 == known


def test_client_registry_contains_independent_cartridges() -> None:
    cartridges = {
        item.adapter.descriptor.game_id: item
        for item in create_builtin_cartridges(platform="windows")
    }

    assert set(cartridges) == {
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
    civ = cartridges["civilization_6"]
    assert civ.store_app_id == "289070"
    assert civ.release_tag == "civilization_6"
    assert civ.dlc_relative_dir == "DLC"
    assert civ.patch_profile.install_relative_dir == "Base/Binaries/Win64Steam"
    assert civ.patch_profile.appinfo_asset_name == "civilization_6_appinfo.json"
    hoi = cartridges["hearts_of_iron_4"]
    assert hoi.store_app_id == "394360"
    assert hoi.release_tag == "hearts_of_iron_4"
    assert hoi.dlc_relative_dir == "dlc"
    assert hoi.patch_profile.install_relative_dir == "."
    assert hoi.patch_profile.appinfo_asset_name == "hearts_of_iron_4_appinfo.json"
    cities = cartridges["cities_skylines"]
    assert cities.store_app_id == "255710"
    assert cities.dlc_relative_dir == "Files"
    assert cities.patch_profile.appinfo_asset_name == "cities_skylines_appinfo.json"
    rim = cartridges["rimworld"]
    assert rim.store_app_id == "294100"
    assert rim.dlc_relative_dir == "Data"
    assert rim.patch_profile.install_relative_dir == (
        "RimWorldWin64_Data/Plugins/x86_64"
    )
    assert rim.patch_profile.appinfo_asset_name == "rimworld_appinfo.json"
    ck3 = cartridges["crusader_kings_3"]
    assert ck3.store_app_id == "1158310"
    assert ck3.dlc_relative_dir == "game/dlc"
    assert ck3.patch_profile.install_relative_dir == "binaries"
    v3 = cartridges["victoria_3"]
    assert v3.store_app_id == "529340"
    assert v3.dlc_relative_dir == "game/dlc"
    assert v3.patch_profile.install_relative_dir == "binaries"
    workers = cartridges["workers_resources_soviet_republic"]
    assert workers.store_app_id == "784150"
    assert workers.dlc_relative_dir == "media_soviet/sounds"
    assert workers.patch_profile.install_relative_dir == "."
    civ7 = cartridges["civilization_7"]
    assert civ7.store_app_id == "1295660"
    assert civ7.dlc_relative_dir == "DLC"
    assert civ7.patch_profile.install_relative_dir == "Base/Binaries/Win64"
    aow4 = cartridges["age_of_wonders_4"]
    assert aow4.store_app_id == "1669000"
    assert aow4.dlc_relative_dir == "Content"
    assert aow4.patch_profile.install_relative_dir == "."


def test_configured_adapters_validate_each_games_own_layout(tmp_path: Path) -> None:
    cartridges = {
        item.adapter.descriptor.game_id: item
        for item in create_builtin_cartridges(platform="windows")
    }
    civ_root = tmp_path / "Sid Meier's Civilization VI"
    (civ_root / "Base" / "Binaries" / "Win64Steam").mkdir(parents=True)
    (civ_root / "Base" / "Binaries" / "Win64Steam" / "CivilizationVI.exe").write_bytes(b"exe")
    (civ_root / "DLC").mkdir()
    assert cartridges["civilization_6"].adapter.validate(civ_root).valid

    hoi_root = tmp_path / "Hearts of Iron IV"
    hoi_root.mkdir()
    (hoi_root / "hoi4.exe").write_bytes(b"exe")
    (hoi_root / "dlc").mkdir()
    assert cartridges["hearts_of_iron_4"].adapter.validate(hoi_root).valid

    cities_root = tmp_path / "Cities Skylines"
    cities_root.mkdir()
    (cities_root / "Cities.exe").write_bytes(b"exe")
    (cities_root / "Files").mkdir()
    assert cartridges["cities_skylines"].adapter.validate(cities_root).valid

    rim_root = tmp_path / "RimWorld"
    rim_root.mkdir()
    (rim_root / "RimWorldWin64.exe").write_bytes(b"exe")
    (rim_root / "Data").mkdir()
    assert cartridges["rimworld"].adapter.validate(rim_root).valid

    layouts = {
        "crusader_kings_3": ("binaries/ck3.exe", "game/dlc"),
        "victoria_3": ("binaries/victoria3.exe", "game/dlc"),
        "workers_resources_soviet_republic": (
            "SOVIET64.exe", "media_soviet/sounds",
        ),
        "civilization_7": (
            "Base/Binaries/Win64/Civ7_Win64_DX12_FinalRelease.exe", "DLC",
        ),
        "age_of_wonders_4": ("AOW4.exe", "Content"),
    }
    for game_id, (executable, dlc_dir) in layouts.items():
        root = tmp_path / game_id
        (root / executable).parent.mkdir(parents=True, exist_ok=True)
        (root / executable).write_bytes(b"exe")
        (root / dlc_dir).mkdir(parents=True, exist_ok=True)
        assert cartridges[game_id].adapter.validate(root).valid


def test_configured_process_check_has_a_clear_five_second_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(configured_steam.os, "name", "nt")

    def timeout(*_args, **kwargs):
        assert kwargs["timeout"] == 5
        raise subprocess.TimeoutExpired("tasklist", kwargs["timeout"])

    monkeypatch.setattr(configured_steam.subprocess, "run", timeout)

    with pytest.raises(OSError, match="tasklist.*5 秒"):
        configured_steam._is_process_running(Path("CivilizationVI.exe"))


def test_generic_package_installs_to_each_cartridge_dlc_directory(tmp_path: Path) -> None:
    package = tmp_path / "dlc001_test_pack.zip"
    digest = make_directory_package(package, root="Expansion1")
    metadata = inspect_directory_package(package)
    assert metadata.dlc_id == "dlc001"

    cartridges = {
        item.adapter.descriptor.game_id: item
        for item in create_builtin_cartridges(platform="windows")
    }
    civ = cartridges["civilization_6"]
    game = tmp_path / "Civ6"
    (game / "Base" / "Binaries" / "Win64Steam").mkdir(parents=True)
    (game / "Base" / "Binaries" / "Win64Steam" / "CivilizationVI.exe").write_bytes(b"exe")
    (game / "DLC").mkdir()
    engine = civ.create_install_engine(tmp_path / "data")
    receipt = engine.install(engine.plan(package, game, expected_sha256=digest))
    assert receipt.game_id == "civilization_6"
    assert receipt.target_path.parent == (game / "DLC").resolve()
    assert receipt.target_path.name == "Expansion1"
    installed = civ.discover_installed_dlc(
        game, (SimpleNamespace(dlc_id="dlc001", slug="expansion1"),)
    )
    assert installed["dlc001"] == receipt.target_path
    civ.remove_installed_dlc(game, "dlc001")
    assert not receipt.target_path.exists()


def test_grouped_package_overlays_multiple_paths_and_uninstall_restores_predecessor(
    tmp_path: Path,
) -> None:
    package = tmp_path / "dlc001_alpinetunes.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "AlpineTunes/Radio/Blurb/AlpineTunes/intro.bank", b"intro"
        )
        archive.writestr(
            "AlpineTunes/Radio/Music/AlpineTunes/music.bank", b"new-music"
        )
        archive.writestr(
            "AlpineTunes/Radio/Talk/AlpineTunes/talk.bank", b"talk"
        )
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    metadata = inspect_grouped_directory_package(package)
    assert metadata.install_mode == "overlay"

    cities = {
        item.adapter.descriptor.game_id: item
        for item in create_builtin_cartridges(platform="windows")
    }["cities_skylines"]
    game = tmp_path / "Cities"
    game.mkdir()
    (game / "Cities.exe").write_bytes(b"exe")
    old = game / "Files" / "Radio" / "Music" / "AlpineTunes" / "music.bank"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"original-music")

    engine = cities.create_install_engine(tmp_path / "data")
    plan = engine.plan(package, game, expected_sha256=digest)
    receipt = engine.install(plan)

    assert receipt.install_mode == "overlay"
    assert receipt.target_path == (game / "Files").resolve()
    assert old.read_bytes() == b"new-music"
    assert (game / "Files" / "Radio" / "Talk" / "AlpineTunes" / "talk.bank").is_file()
    assert engine.verify(receipt, game)

    engine.uninstall(receipt, game)

    assert old.read_bytes() == b"original-music"
    assert not (game / "Files" / "Radio" / "Talk" / "AlpineTunes").exists()
    assert engine.uninstall_committed(receipt)


def test_grouped_cartridge_discovers_and_removes_all_matching_branches(
    tmp_path: Path,
) -> None:
    cities = {
        item.adapter.descriptor.game_id: item
        for item in create_builtin_cartridges(platform="windows")
    }["cities_skylines"]
    game = tmp_path / "Cities"
    game.mkdir()
    (game / "Cities.exe").write_bytes(b"exe")
    for branch in ("Blurb", "Music", "Talk"):
        leaf = game / "Files" / "Radio" / branch / "AlpineTunes"
        leaf.mkdir(parents=True)
        (leaf / "payload.bank").write_bytes(branch.encode())
    entry = SimpleNamespace(dlc_id="dlc001", slug="alpinetunes")

    installed = cities.discover_installed_dlc(game, (entry,))
    assert "dlc001" in installed

    cities.remove_installed_dlc(game, "dlc001")
    assert not tuple((game / "Files" / "Radio").glob("*/AlpineTunes"))


def test_generic_package_verifies_temporary_download_name_with_asset_name(
    tmp_path: Path,
) -> None:
    temporary = tmp_path / "hearts_of_iron_4-dlc045.part"
    make_directory_package(temporary, root="ExpansionPass1SupporterPack")

    metadata = inspect_directory_package(
        temporary, asset_name="dlc045_expansion_pass_1_supporter_pack.zip"
    )

    assert metadata.dlc_id == "dlc045"
    assert metadata.install_directory == "ExpansionPass1SupporterPack"


def test_publisher_seeds_all_game_cartridges_without_overwriting_existing(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    selected = workspace.initialize()
    profiles = {item.game_id: item for item in workspace.list_games()}

    assert selected.game_id == "stellaris"
    assert set(profiles) == {
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
    assert profiles["civilization_6"].patch_relative_dir == "Base/Binaries/Win64Steam"
    assert profiles["hearts_of_iron_4"].steam_app_id == "394360"
    assert profiles["cities_skylines"].steam_app_id == "255710"
    assert profiles["rimworld"].dlc_relative_dir == "Data"
    assert profiles["rimworld"].patch_relative_dir == (
        "RimWorldWin64_Data/Plugins/x86_64"
    )
    assert profiles["crusader_kings_3"].patch_relative_dir == "binaries"
    assert profiles["victoria_3"].dlc_relative_dir == "game/dlc"
    assert profiles["workers_resources_soviet_republic"].steam_app_id == "784150"
    assert profiles["civilization_7"].patch_relative_dir == "Base/Binaries/Win64"
    assert profiles["age_of_wonders_4"].dlc_relative_dir == "Content"
    assert len(publisher_cartridges()) == 10


def test_civilization_publisher_keeps_asset_id_but_strips_install_prefix(tmp_path: Path) -> None:
    def provider(app_id):
        return SteamAppInfo(app_id, "Civilization VI", "2026-07-15", ())

    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=provider)
    workspace.initialize()
    profile = next(item for item in workspace.list_games() if item.game_id == "civilization_6")
    game = workspace.game_dir(profile.game_id)
    source = game / "dlc" / "dlc001_Expansion1"
    source.mkdir()
    (source / "payload.bin").write_bytes(b"content")
    patches = game / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")

    workspace.build(profile)

    package = workspace.output_dir / profile.game_id / "dlc001_Expansion1.zip"
    with zipfile.ZipFile(package) as archive:
        assert {Path(name).parts[0] for name in archive.namelist()} == {"Expansion1"}
