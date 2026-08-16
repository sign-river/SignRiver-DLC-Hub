"""Tests for cross-platform (SteamOS / macOS) patch support."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from signriver_app.adapters.document_cartridge import build_cartridge_from_document
from signriver_app.domain import (
    CartridgeDocument,
    PatchConfigFormat,
    PatchHealth,
    PatchPlatform,
    PatchProfile,
    PatchTemplate,
    host_patch_platform,
)
from signriver_app.infrastructure.patching import (
    PatchEngine,
    PatchError,
    render_patch_config,
    render_smoke_api_config,
)


APPINFO_PAYLOAD = {
    "app_id": "281990",
    "name": "Stellaris",
    "update_time": "2026-07-01",
    "dlcs": [
        {"id": "281991", "name": "Plantoids Species Pack"},
        {"id": "281992", "name": "Leviathans Story Pack"},
    ],
}


# ---- config rendering ------------------------------------------------------


def test_render_smoke_api_config_unlocks_everything_and_lists_dlcs() -> None:
    body = render_smoke_api_config(
        APPINFO_PAYLOAD,
        PatchTemplate(
            ini_target_name="SmokeAPI.config.json",
            config_format=PatchConfigFormat.SMOKEAPI_JSON,
        ),
    )
    config = json.loads(body)
    assert config["$version"] == 4
    assert config["default_app_status"] == "unlocked"
    assert config["logging"] is False
    assert config["extra_dlcs"]["281990"]["dlcs"] == {
        "281991": "Plantoids Species Pack",
        "281992": "Leviathans Story Pack",
    }


def test_render_patch_config_dispatches_on_template_format() -> None:
    ini = render_patch_config(
        APPINFO_PAYLOAD,
        PatchTemplate(
            ini_target_name="cream_api.ini",
            config_format=PatchConfigFormat.CREAM_INI,
        ),
    )
    assert ini.startswith("[steam]\n")
    smoke = render_patch_config(
        APPINFO_PAYLOAD,
        PatchTemplate(
            ini_target_name="SmokeAPI.config.json",
            config_format=PatchConfigFormat.SMOKEAPI_JSON,
        ),
    )
    assert json.loads(smoke)["default_app_status"] == "unlocked"


def test_render_smoke_api_config_rejects_bad_ids() -> None:
    with pytest.raises(PatchError):
        render_smoke_api_config(
            {"app_id": "bad", "dlcs": []},
            PatchTemplate(
                ini_target_name="SmokeAPI.config.json",
                config_format=PatchConfigFormat.SMOKEAPI_JSON,
            ),
        )


# ---- document platforms ----------------------------------------------------


def _hoi4_document() -> CartridgeDocument:
    return CartridgeDocument.from_dict(
        {
            "schema_version": 1,
            "engine": "steam_configured_v1",
            "game_id": "hearts_of_iron_4",
            "display_name": "Hearts of Iron IV",
            "store_app_id": "394360",
            "release_tag": "hearts_of_iron_4",
            "executable_relative_path": "hoi4",
            "dlc_relative_dir": "dlc",
            "package_inspector": "directory",
            "patch": {
                "unlocker_dll_name": "steam_api64.dll",
                "original_backup_dll_name": "steam_api64_o.dll",
                "appinfo_asset_name": "hearts_of_iron_4_appinfo.json",
                "ini_target_name": "cream_api.ini",
                "platforms": {
                    "steamos": {
                        "unlocker_dll_name": "libsteam_api.so",
                        "original_backup_dll_name": "libsteam_api_o.so",
                        "ini_target_name": "SmokeAPI.config.json",
                        "config_format": "smokeapi_json",
                        "executable_relative_path": "hoi4",
                        "dlc_relative_dir": "dlc",
                    },
                    "macos": {
                        "unlocker_dll_name": "libsteam_api.dylib",
                        "original_backup_dll_name": "libsteam_api_o.dylib",
                        "ini_target_name": "icecream.ini",
                    },
                },
            },
        }
    )


def test_cartridge_document_parses_platform_variants() -> None:
    document = _hoi4_document()
    assert document.patch_platforms == ("macos", "steamos", "windows")
    windows = document.patch_fields_for("windows")
    assert windows["unlocker_dll_name"] == "steam_api64.dll"
    assert windows["ini_target_name"] == "cream_api.ini"
    steamos = document.patch_fields_for("steamos")
    assert steamos["unlocker_dll_name"] == "libsteam_api.so"
    assert steamos["original_backup_dll_name"] == "libsteam_api_o.so"
    assert steamos["ini_target_name"] == "SmokeAPI.config.json"
    assert steamos["config_format"] == "smokeapi_json"
    assert steamos["executable_relative_path"] == "hoi4"
    assert steamos["dlc_relative_dir"] == "dlc"
    assert "executable_relative_path" not in document.patch_fields_for("macos")
    macos = document.patch_fields_for("macos")
    assert macos["unlocker_dll_name"] == "libsteam_api.dylib"
    assert macos["ini_target_name"] == "icecream.ini"


def test_cartridge_document_rejects_unknown_platform() -> None:
    with pytest.raises(ValueError):
        CartridgeDocument.from_dict(
            {
                "schema_version": 1,
                "engine": "steam_configured_v1",
                "game_id": "x",
                "display_name": "X",
                "store_app_id": "1",
                "release_tag": "x",
                "executable_relative_path": "x",
                "dlc_relative_dir": "dlc",
                "package_inspector": "directory",
                "patch": {
                    "unlocker_dll_name": "a.dll",
                    "original_backup_dll_name": "a_o.dll",
                    "appinfo_asset_name": "x_appinfo.json",
                    "platforms": {"solaris": {}},
                },
            }
        )


def test_build_cartridge_selects_platform_profile() -> None:
    document = _hoi4_document()
    macos = build_cartridge_from_document(document, platform="macos")
    assert macos.patch_profile.platform is PatchPlatform.MACOS
    assert macos.patch_profile.unlocker_dll_name == "libsteam_api.dylib"
    assert macos.patch_profile.template.ini_target_name == "icecream.ini"
    steamos = build_cartridge_from_document(document, platform=PatchPlatform.STEAMOS)
    assert steamos.patch_profile.unlocker_dll_name == "libsteam_api.so"
    assert (
        steamos.patch_profile.template.config_format
        is PatchConfigFormat.SMOKEAPI_JSON
    )
    assert steamos.executable_name == "hoi4"
    assert steamos.dlc_relative_dir == "dlc"


def test_host_patch_platform_returns_supported_value() -> None:
    assert host_patch_platform() in (
        PatchPlatform.WINDOWS,
        PatchPlatform.STEAMOS,
        PatchPlatform.MACOS,
    )


# ---- engine integration for a SteamOS-style profile -----------------------


UNLOCKER_SO = b"\x7fELF" + b"\x00" * 16 + b"smoke-api-unlocker"
BACKUP_SO = b"\x7fELF" + b"\x00" * 16 + b"packaged-original-backup"
VANILLA_SO = b"\x7fELF" + b"\x00" * 16 + b"vanilla-libsteam-api"


def _steamos_engine(tmp_path: Path) -> PatchEngine:
    profile = PatchProfile(
        unlocker_dll_name="libsteam_api.so",
        original_backup_dll_name="libsteam_api_o.so",
        appinfo_asset_name="stellaris_appinfo.json",
        template=PatchTemplate(
            ini_target_name="SmokeAPI.config.json",
            config_format=PatchConfigFormat.SMOKEAPI_JSON,
        ),
        platform=PatchPlatform.STEAMOS,
    )
    data_root = tmp_path / "data"
    data_root.mkdir(exist_ok=True)
    return PatchEngine(profile, data_root)


def test_engine_apply_steamos_promotes_elf_original_and_writes_json(
    tmp_path: Path,
) -> None:
    engine = _steamos_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "libsteam_api.so").write_bytes(VANILLA_SO)
    unlocker = tmp_path / "release" / "libsteam_api.so"
    backup = tmp_path / "release" / "libsteam_api_o.so"
    appinfo = tmp_path / "release" / "stellaris_appinfo.json"
    unlocker.parent.mkdir(parents=True, exist_ok=True)
    unlocker.write_bytes(UNLOCKER_SO)
    unlocker.chmod(0o755)
    backup.write_bytes(BACKUP_SO)
    appinfo.write_text(json.dumps(APPINFO_PAYLOAD), encoding="utf-8")

    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )

    assert (game_root / "libsteam_api_o.so").read_bytes() == VANILLA_SO
    assert (game_root / "libsteam_api.so").read_bytes() == UNLOCKER_SO
    config_bytes = (game_root / "SmokeAPI.config.json").read_bytes()
    assert not config_bytes.startswith(b"\xef\xbb\xbf")
    config = json.loads(config_bytes.decode("utf-8"))
    assert config["default_app_status"] == "unlocked"
    assert result.receipt.backup_origin == "promoted_game_original"
    assert result.audit_after.health is PatchHealth.HEALTHY
    if os.name != "nt":
        assert (game_root / "libsteam_api.so").stat().st_mode & 0o777 == 0o755


def test_engine_remove_steamos_restores_original(tmp_path: Path) -> None:
    engine = _steamos_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "libsteam_api.so").write_bytes(VANILLA_SO)
    unlocker = tmp_path / "release" / "libsteam_api.so"
    backup = tmp_path / "release" / "libsteam_api_o.so"
    appinfo = tmp_path / "release" / "stellaris_appinfo.json"
    unlocker.parent.mkdir(parents=True, exist_ok=True)
    unlocker.write_bytes(UNLOCKER_SO)
    backup.write_bytes(BACKUP_SO)
    appinfo.write_text(json.dumps(APPINFO_PAYLOAD), encoding="utf-8")
    engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    engine.remove(game_root)
    assert (game_root / "libsteam_api.so").read_bytes() == VANILLA_SO
    assert not (game_root / "libsteam_api_o.so").exists()
    assert not (game_root / "SmokeAPI.config.json").exists()


# ---- platform-aware game directory validation ------------------------------


def test_steamos_adapter_accepts_dir_with_steam_lib_when_exe_missing(
    tmp_path: Path,
) -> None:
    from signriver_app.adapters.common import ConfiguredSteamAdapter

    adapter = ConfiguredSteamAdapter(
        game_id="hearts_of_iron_4",
        display_name="HOI4",
        steam_app_id="394360",
        executable_relative_path="hoi4.exe",
        required_relative_dirs=("dlc",),
        platform="steamos",
    )
    game_root = tmp_path / "game"
    (game_root / "dlc").mkdir(parents=True)
    (game_root / "libsteam_api.so").write_bytes(b"\x7fELF" + b"\x00" * 8)
    result = adapter.validate(game_root)
    assert result.valid is True
    assert result.warnings


def test_steamos_adapter_still_rejects_dir_without_steam_lib(
    tmp_path: Path,
) -> None:
    from signriver_app.adapters.common import ConfiguredSteamAdapter

    adapter = ConfiguredSteamAdapter(
        game_id="hearts_of_iron_4",
        display_name="HOI4",
        steam_app_id="394360",
        executable_relative_path="hoi4.exe",
        required_relative_dirs=("dlc",),
        platform="steamos",
    )
    game_root = tmp_path / "game"
    (game_root / "dlc").mkdir(parents=True)
    result = adapter.validate(game_root)
    assert result.valid is False


def test_windows_adapter_keeps_strict_executable_check(tmp_path: Path) -> None:
    from signriver_app.adapters.common import ConfiguredSteamAdapter

    adapter = ConfiguredSteamAdapter(
        game_id="hearts_of_iron_4",
        display_name="HOI4",
        steam_app_id="394360",
        executable_relative_path="hoi4.exe",
        required_relative_dirs=("dlc",),
    )
    game_root = tmp_path / "game"
    (game_root / "dlc").mkdir(parents=True)
    (game_root / "steam_api64.dll").write_bytes(b"MZ" + b"\x00" * 8)
    result = adapter.validate(game_root)
    assert result.valid is False
    assert not result.warnings
