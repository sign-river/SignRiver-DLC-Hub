from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from types import SimpleNamespace

from signriver_app.adapters.builtin import create_builtin_cartridges
from signriver_app.infrastructure.catalog import inspect_directory_package
from signriver_publisher import (
    PublisherWorkspace, SteamAppInfo,
    create_builtin_cartridges as publisher_cartridges,
)


def make_directory_package(path: Path, root: str = "dlc001_test_pack") -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{root}/content/payload.bin", b"payload")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_client_registry_contains_three_independent_cartridges() -> None:
    cartridges = {item.adapter.descriptor.game_id: item for item in create_builtin_cartridges()}

    assert set(cartridges) == {"stellaris", "civilization_6", "hearts_of_iron_4"}
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


def test_configured_adapters_validate_each_games_own_layout(tmp_path: Path) -> None:
    cartridges = {item.adapter.descriptor.game_id: item for item in create_builtin_cartridges()}
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


def test_generic_package_installs_to_each_cartridge_dlc_directory(tmp_path: Path) -> None:
    package = tmp_path / "dlc001_test_pack.zip"
    digest = make_directory_package(package, root="Expansion1")
    metadata = inspect_directory_package(package)
    assert metadata.dlc_id == "dlc001"

    cartridges = {item.adapter.descriptor.game_id: item for item in create_builtin_cartridges()}
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


def test_publisher_seeds_all_game_cartridges_without_overwriting_existing(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    selected = workspace.initialize()
    profiles = {item.game_id: item for item in workspace.list_games()}

    assert selected.game_id == "stellaris"
    assert set(profiles) == {"stellaris", "civilization_6", "hearts_of_iron_4"}
    assert profiles["civilization_6"].patch_relative_dir == "Base/Binaries/Win64Steam"
    assert profiles["hearts_of_iron_4"].steam_app_id == "394360"
    assert len(publisher_cartridges()) == 3


def test_civilization_publisher_keeps_asset_id_but_strips_install_prefix(tmp_path: Path) -> None:
    provider = lambda app_id: SteamAppInfo(app_id, "Civilization VI", "2026-07-15", ())
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
