from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_app.adapters import AdapterRegistry, GameAdapter
from signriver_app.adapters.builtin import create_builtin_adapters
from signriver_app.adapters.common import (
    SteamInstallationLocator,
    VdfError,
    parse_vdf,
)
from signriver_app.adapters.stellaris import (
    STELLARIS_STEAM_APP_ID,
    StellarisSteamAdapter,
    discover_installed_dlc,
)
from signriver_app.application import GameDiscoveryService
from signriver_app.domain import GameInstallation
from signriver_app.infrastructure.persistence import Database, GameInstallationRepository


def vdf_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\")


def test_discover_installed_dlc_reads_only_valid_package_directories(tmp_path: Path) -> None:
    dlc_root = tmp_path / "dlc"
    (dlc_root / "dlc001_symbols_of_domination").mkdir(parents=True)
    (dlc_root / "DLC042_VIPRA_THE_VAPOR").mkdir()
    (dlc_root / "dlc_bad").mkdir()
    (dlc_root / "dlc002_file_only").write_text("not a directory", encoding="utf-8")

    installed = discover_installed_dlc(tmp_path)

    assert set(installed) == {"dlc001", "dlc042"}


def test_dlc_discovery_and_removal_use_cartridge_directory(tmp_path: Path) -> None:
    from signriver_app.adapters.stellaris import remove_installed_dlc

    target = tmp_path / "content" / "addons" / "dlc001_symbols"
    target.mkdir(parents=True)
    installed = discover_installed_dlc(tmp_path, "content/addons")
    assert installed == {"dlc001": target}

    removed = remove_installed_dlc(tmp_path, "dlc001", "content/addons")
    assert removed == target.resolve()
    assert not target.exists()


def write_steam_fixture(
    base: Path,
    *,
    app_id: str = STELLARIS_STEAM_APP_ID,
    install_dir: str = "Stellaris",
    build_id: str = "23859066",
) -> tuple[Path, Path]:
    steam_root = base / "Steam"
    library_root = base / "Library"
    (steam_root / "steamapps").mkdir(parents=True)
    (library_root / "steamapps" / "common").mkdir(parents=True)
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n'
        "{\n"
        f'  "0" {{ "path" "{vdf_path(steam_root)}" }}\n'
        f'  "1" {{ "path" "{vdf_path(library_root)}" }}\n'
        "}\n",
        encoding="utf-8",
    )
    (library_root / "steamapps" / f"appmanifest_{app_id}.acf").write_text(
        '"AppState"\n'
        "{\n"
        f'  "appid" "{app_id}"\n'
        '  "name" "Stellaris"\n'
        f'  "installdir" "{install_dir}"\n'
        f'  "buildid" "{build_id}"\n'
        '  "StateFlags" "4"\n'
        "}\n",
        encoding="utf-8",
    )
    game_root = library_root / "steamapps" / "common" / install_dir
    game_root.mkdir()
    return steam_root, game_root


def write_stellaris_files(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "common").mkdir(exist_ok=True)
    (root / "dlc").mkdir(exist_ok=True)
    (root / "stellaris.exe").write_bytes(b"fixture")
    (root / "steam_appid.txt").write_text(
        STELLARIS_STEAM_APP_ID,
        encoding="utf-8",
    )
    (root / "launcher-settings.json").write_text(
        json.dumps(
            {
                "gameId": "stellaris",
                "version": "Pegasus v4.4.4 (5505)",
                "modsCompatibilityVersion": "4.4",
                "rawVersion": "v4.4.4",
                "distPlatform": "steam",
                "exePath": "./stellaris.exe",
            }
        ),
        encoding="utf-8",
    )


def test_parse_vdf_supports_nested_objects_comments_and_escapes() -> None:
    document = parse_vdf(
        '// fixture\n"root" { "path" "D:\\\\Steam" "apps" { "281990" "1" } }'
    )

    assert document["root"]["path"] == r"D:\Steam"
    assert document["root"]["apps"]["281990"] == "1"

    with pytest.raises(VdfError, match="unterminated"):
        parse_vdf('"root" { "key" "value"')


def test_steam_locator_reads_libraries_and_app_manifest(tmp_path: Path) -> None:
    steam_root, game_root = write_steam_fixture(tmp_path)
    locator = SteamInstallationLocator((steam_root,))

    installations = locator.find_app(STELLARIS_STEAM_APP_ID)

    assert len(installations) == 1
    installation = installations[0]
    assert installation.app_id == STELLARIS_STEAM_APP_ID
    assert installation.root == game_root.resolve()
    assert installation.build_id == "23859066"
    assert installation.manifest_path.name == "appmanifest_281990.acf"
    assert locator.last_issues == ()


def test_steam_locator_isolates_malformed_or_unsafe_manifests(
    tmp_path: Path,
) -> None:
    steam_root, game_root = write_steam_fixture(tmp_path)
    manifest = game_root.parents[1] / "appmanifest_281990.acf"
    manifest.write_text(
        '"AppState" { "appid" "281990" "installdir" "../escape" }',
        encoding="utf-8",
    )
    locator = SteamInstallationLocator((steam_root,))

    assert locator.find_app(STELLARIS_STEAM_APP_ID) == ()
    assert len(locator.last_issues) == 1
    assert "safe directory" in locator.last_issues[0].message


def test_stellaris_adapter_discovers_and_validates_steam_installation(
    tmp_path: Path,
) -> None:
    steam_root, game_root = write_steam_fixture(tmp_path)
    write_stellaris_files(game_root)
    adapter = StellarisSteamAdapter(
        SteamInstallationLocator((steam_root,)),
        process_checker=lambda executable: True,
    )

    candidates = adapter.discover()
    validation = adapter.validate(game_root)

    assert isinstance(adapter, GameAdapter)
    assert len(candidates) == 1
    assert candidates[0].root == game_root.resolve()
    assert candidates[0].metadata["steam_build_id"] == "23859066"
    assert validation.valid is True
    assert validation.game_version == "4.4.4"
    assert validation.executable == (game_root / "stellaris.exe").resolve()
    assert validation.metadata["modsCompatibilityVersion"] == "4.4"

    installation = validation.to_installation(
        installation_id="stellaris.fixture",
        game_id="stellaris",
        adapter_id="stellaris.steam",
    )
    state = adapter.inspect(installation)
    assert state.healthy is True
    assert state.running is True
    assert state.game_version == "4.4.4"


def test_stellaris_adapter_runs_through_discovery_and_persistence(
    tmp_path: Path,
) -> None:
    steam_root, game_root = write_steam_fixture(tmp_path)
    write_stellaris_files(game_root)
    adapter = StellarisSteamAdapter(SteamInstallationLocator((steam_root,)))
    repository = GameInstallationRepository(Database(tmp_path / "hub.sqlite3"))
    discovery = GameDiscoveryService(AdapterRegistry((adapter,)), repository)

    report = discovery.scan()

    assert len(report.available) == 1
    installation = report.available[0]
    assert installation.selected is True
    assert installation.root == game_root.resolve()
    assert installation.metadata["steam_build_id"] == "23859066"
    assert installation.metadata["rawVersion"] == "v4.4.4"
    assert repository.get_selected("stellaris") == installation


def test_stellaris_adapter_rejects_wrong_or_incomplete_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Stellaris"
    write_stellaris_files(root)
    (root / "steam_appid.txt").write_text("123", encoding="utf-8")
    settings_path = root / "launcher-settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["gameId"] = "not-stellaris"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    adapter = StellarisSteamAdapter(
        SteamInstallationLocator(()),
        process_checker=lambda executable: False,
    )

    validation = adapter.validate(root)

    assert validation.valid is False
    assert any("gameId" in error for error in validation.errors)
    assert any("App ID" in error for error in validation.errors)


def test_builtin_adapter_set_contains_all_prepared_game_cartridges() -> None:
    adapters = create_builtin_adapters()

    assert {adapter.descriptor.adapter_id for adapter in adapters} == {
        "stellaris.steam",
        "civilization_6.steam",
        "hearts_of_iron_4.steam",
    }


def test_stellaris_inspection_rejects_foreign_installation(tmp_path: Path) -> None:
    adapter = StellarisSteamAdapter(SteamInstallationLocator(()))
    root = tmp_path / "game"
    root.mkdir()
    installation = GameInstallation(
        installation_id="foreign.fixture",
        game_id="foreign",
        adapter_id="foreign.mock",
        root=root,
        executable=None,
        platform="windows",
        source="manual",
    )

    with pytest.raises(ValueError, match="game_id"):
        adapter.inspect(installation)


def test_remove_installed_dlc_only_deletes_requested_recognized_directory(
    tmp_path: Path,
) -> None:
    from signriver_app.adapters.stellaris import remove_installed_dlc

    root = tmp_path / "Stellaris"
    first = root / "dlc" / "dlc001_symbols"
    second = root / "dlc" / "dlc002_arachnoid"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "payload.bin").write_bytes(b"one")
    (second / "payload.bin").write_bytes(b"two")

    removed = remove_installed_dlc(root, "dlc001")

    assert removed.name == "dlc001_symbols"
    assert not first.exists()
    assert second.is_dir()


def test_remove_installed_dlc_rejects_invalid_id(tmp_path: Path) -> None:
    from signriver_app.adapters.stellaris import remove_installed_dlc

    root = tmp_path / "Stellaris"
    (root / "dlc").mkdir(parents=True)
    with pytest.raises(ValueError, match="invalid Stellaris DLC ID"):
        remove_installed_dlc(root, "../dlc001")
