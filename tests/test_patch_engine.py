"""Unit tests for the CreamAPI-style PatchEngine and helpers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from signriver_app.adapters.stellaris import STELLARIS_PATCH_PROFILE
from signriver_app.domain import PatchHealth, PatchProfile, PatchTemplate
from signriver_app.infrastructure.patching import (
    PatchEngine,
    PatchError,
    parse_appinfo_document,
    render_cream_api_ini,
)


# ---- fixtures ---------------------------------------------------------------


def pe_x64(payload: bytes = b"") -> bytes:
    data = bytearray(256)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x84] = b"PE\0\0"
    data[0x84:0x86] = (0x8664).to_bytes(2, "little")
    return bytes(data) + payload


UNLOCKER_BODY = pe_x64(b"our-unlocker-payload")
BACKUP_BODY = pe_x64(b"our-backup-original-payload")
FOREIGN_UNLOCKER = pe_x64(b"some-other-unlocker")
FOREIGN_BACKUP = pe_x64(b"some-other-backup")
VANILLA_GAME_DLL = pe_x64(b"vanilla-steam-api-64")


APPINFO_PAYLOAD = {
    "app_id": "281990",
    "name": "Stellaris",
    "update_time": "2026-07-01",
    "dlcs": [
        {"id": "281991", "name": "Plantoids Species Pack"},
        {"id": "281992", "name": "Leviathans Story Pack"},
    ],
}


def write_patch_sources(tmp_path: Path) -> tuple[Path, Path]:
    unlocker = tmp_path / "release" / "steam_api64.dll"
    appinfo = tmp_path / "release" / "stellaris_appinfo.json"
    unlocker.parent.mkdir(parents=True, exist_ok=True)
    unlocker.write_bytes(UNLOCKER_BODY)
    appinfo.write_text(json.dumps(APPINFO_PAYLOAD), encoding="utf-8")
    return unlocker, appinfo


def write_complete_patch_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    unlocker, appinfo = write_patch_sources(tmp_path)
    original = unlocker.parent / "original.dll"
    original.write_bytes(VANILLA_GAME_DLL)
    return unlocker, original, appinfo


def test_apply_deterministically_replaces_unknown_legacy_layout(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game = tmp_path / "game"
    game.mkdir()
    (game / "steam_api64.dll").write_bytes(FOREIGN_UNLOCKER)
    (game / "steam_api64_o.dll").write_bytes(FOREIGN_BACKUP)
    (game / "cream_api.ini").write_text("legacy", encoding="utf-8")
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)

    result = engine.apply(
        game,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )

    assert (game / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    assert (game / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL
    assert result.receipt.original_library_source == "published_original"


def test_apply_deletes_declared_interference_files_and_reports_them(tmp_path: Path) -> None:
    profile = replace(STELLARIS_PATCH_PROFILE, interference_files=("bin/old_proxy.dll",))
    engine = PatchEngine(profile, tmp_path / "data")
    game = tmp_path / "game"
    (game / "bin").mkdir(parents=True)
    (game / "bin" / "old_proxy.dll").write_bytes(b"stale")
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)

    result = engine.apply(
        game,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )

    assert not (game / "bin" / "old_proxy.dll").exists()
    assert result.interference_files_deleted == ("bin/old_proxy.dll",)


def test_apply_rolls_back_deleted_interference_file_when_patch_fails(tmp_path: Path) -> None:
    profile = replace(STELLARIS_PATCH_PROFILE, interference_files=("old_proxy.dll",))
    engine = PatchEngine(profile, tmp_path / "data")
    game = tmp_path / "game"
    game.mkdir()
    stale = game / "old_proxy.dll"
    stale.write_bytes(b"stale")
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    appinfo.write_text("{}", encoding="utf-8")

    with pytest.raises(PatchError):
        engine.apply(
            game,
            unlocker_dll_source=unlocker,
            original_dll_source=original,
            appinfo_json_source=appinfo,
            game_id="stellaris",
        )

    assert stale.read_bytes() == b"stale"
    assert not (game / "steam_api64.dll").exists()


def make_engine(tmp_path: Path) -> PatchEngine:
    data_root = tmp_path / "data"
    data_root.mkdir(exist_ok=True)
    return PatchEngine(STELLARIS_PATCH_PROFILE, data_root)


# ---- ini rendering ---------------------------------------------------------


def test_render_cream_api_ini_matches_publisher_layout() -> None:
    body = render_cream_api_ini(
        APPINFO_PAYLOAD,
        PatchTemplate(ini_target_name="cream_api.ini"),
    )
    assert body.startswith("[steam]\n")
    assert "appid = 281990" in body
    assert "language = schinese" in body
    assert "unlockall = True" in body
    assert "extraprotection = False" in body
    assert "forceoffline = False" in body
    assert "[dlc]" in body
    assert "281991 = Plantoids Species Pack" in body
    assert "281992 = Leviathans Story Pack" in body
    assert body.endswith("\n")


def test_render_cream_api_ini_rejects_bad_ids() -> None:
    with pytest.raises(PatchError):
        render_cream_api_ini(
            {"app_id": "bad", "dlcs": []},
            PatchTemplate(ini_target_name="cream_api.ini"),
        )
    with pytest.raises(PatchError):
        render_cream_api_ini(
            {
                "app_id": "281990",
                "dlcs": [{"id": "abc", "name": "bad"}],
            },
            PatchTemplate(ini_target_name="cream_api.ini"),
        )


def test_parse_appinfo_document_rejects_malformed_input() -> None:
    with pytest.raises(PatchError):
        parse_appinfo_document(b"not json")
    with pytest.raises(PatchError):
        parse_appinfo_document(json.dumps({"app_id": "1"}).encode())
    with pytest.raises(PatchError):
        parse_appinfo_document(
            json.dumps(
                {"app_id": "281990", "dlcs": [{"id": "1", "name": "bad\nname"}]}
            ).encode()
        )


def test_parse_appinfo_document_accepts_utf8_bom() -> None:
    raw = b"\xef\xbb\xbf" + json.dumps(APPINFO_PAYLOAD).encode()
    parsed = parse_appinfo_document(raw)
    assert parsed["app_id"] == "281990"
    assert len(parsed["dlcs"]) == 2


# ---- audit -----------------------------------------------------------------


def test_audit_reports_original_when_directory_is_untouched(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    audit = engine.audit(
        game_root,
        expected_unlocker_size=len(UNLOCKER_BODY),
        expected_backup_size=len(BACKUP_BODY),
    )
    assert audit.health is PatchHealth.ORIGINAL


def test_audit_reports_healthy_when_patch_matches(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "steam_api64_o.dll").write_bytes(BACKUP_BODY)
    (game_root / "cream_api.ini").write_bytes(b"placeholder")
    audit = engine.audit(
        game_root,
        expected_unlocker_size=len(UNLOCKER_BODY),
        expected_backup_size=len(BACKUP_BODY),
    )
    assert audit.health is PatchHealth.HEALTHY


def test_audit_reports_modified_when_sizes_differ(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(FOREIGN_UNLOCKER)
    (game_root / "steam_api64_o.dll").write_bytes(BACKUP_BODY)
    audit = engine.audit(
        game_root,
        expected_unlocker_size=len(UNLOCKER_BODY),
        expected_backup_size=len(BACKUP_BODY),
    )
    assert audit.health is PatchHealth.MODIFIED
    assert "steam_api64.dll" in audit.modified


# ---- apply -----------------------------------------------------------------


def test_apply_promotes_vanilla_dll_to_backup(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    # The vanilla DLL must have been moved to steam_api64_o.dll, not deleted.
    assert (game_root / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    ini_bytes = (game_root / "cream_api.ini").read_bytes()
    assert ini_bytes.startswith(b"\xef\xbb\xbf")
    assert result.backup_created is True
    assert result.audit_after.health is PatchHealth.HEALTHY
    assert result.receipt.backup_origin == "published_original"


def test_apply_rolls_back_when_written_dll_is_quarantined(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    original_path = game_root / "steam_api64.dll"
    original_path.write_bytes(VANILLA_GAME_DLL)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    write_file_atomic = engine._write_file_atomic

    def write_then_quarantine(data, destination, actions, *, mode=None):
        write_file_atomic(data, destination, actions, mode=mode)
        if destination.name == "steam_api64.dll":
            destination.unlink()

    engine._write_file_atomic = write_then_quarantine

    with pytest.raises(PatchError, match="安全软件隔离"):
        engine.apply(
            game_root,
            unlocker_dll_source=unlocker,
            appinfo_json_source=appinfo,
            game_id="stellaris",
        )

    assert original_path.read_bytes() == VANILLA_GAME_DLL
    assert not (game_root / "steam_api64_o.dll").exists()
    assert not (game_root / "cream_api.ini").exists()


def test_patch_operations_use_cartridge_owned_nested_directory(tmp_path: Path) -> None:
    profile = PatchProfile(
        unlocker_dll_name="custom_api.dll",
        runtime_original_library_name="custom_api_o.dll",
        appinfo_asset_name="other_appinfo.json",
        template=PatchTemplate(ini_target_name="custom.ini"),
        install_relative_dir="bin/win64",
    )
    data_root = tmp_path / "data"
    data_root.mkdir()
    engine = PatchEngine(profile, data_root)
    game = tmp_path / "game"
    patch_dir = game / "bin" / "win64"
    patch_dir.mkdir(parents=True)
    (patch_dir / "custom_api.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, appinfo = write_patch_sources(tmp_path)

    result = engine.apply(
        game,
        unlocker_dll_source=unlocker,
        appinfo_json_source=appinfo,
        game_id="other",
    )

    assert (patch_dir / "custom_api.dll").read_bytes() == UNLOCKER_BODY
    assert (patch_dir / "custom_api_o.dll").read_bytes() == VANILLA_GAME_DLL
    assert (patch_dir / "custom.ini").is_file()
    assert all(path.startswith("bin/win64/") for path in result.audit_after.matching)
    touched = engine.remove(game)
    assert "bin/win64/custom_api_o.dll" in touched
    assert (patch_dir / "custom_api.dll").read_bytes() == VANILLA_GAME_DLL


def test_patch_operations_replace_and_restore_every_declared_target(
    tmp_path: Path,
) -> None:
    profile = PatchProfile(
        unlocker_dll_name="steam_api64.dll",
        runtime_original_library_name="steam_api64_o.dll",
        appinfo_asset_name="other_appinfo.json",
        template=PatchTemplate(ini_target_name="cream_api.ini"),
        additional_install_relative_dirs=(
            "launcher-se/resources/app.asar.unpacked/node_modules/greenworks/lib",
        ),
    )
    data_root = tmp_path / "data"
    data_root.mkdir()
    engine = PatchEngine(profile, data_root)
    game = tmp_path / "game"
    secondary = game / "launcher-se/resources/app.asar.unpacked/node_modules/greenworks/lib"
    secondary.mkdir(parents=True)
    (game / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    (secondary / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)

    result = engine.apply(
        game,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="age_of_wonders_4",
    )

    for directory in (game, secondary):
        assert (directory / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
        assert (directory / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL
        assert (directory / "cream_api.ini").is_file()
    assert (
        "launcher-se/resources/app.asar.unpacked/node_modules/greenworks/lib/steam_api64.dll"
        in result.audit_after.matching
    )

    touched = engine.remove(game)
    assert (game / "steam_api64.dll").read_bytes() == VANILLA_GAME_DLL
    assert (secondary / "steam_api64.dll").read_bytes() == VANILLA_GAME_DLL
    assert not (secondary / "steam_api64_o.dll").exists()
    assert (
        "launcher-se/resources/app.asar.unpacked/node_modules/greenworks/lib/steam_api64.dll"
        in touched
    )


def test_patch_profile_rejects_unsafe_install_directory() -> None:
    with pytest.raises(ValueError, match="game root"):
        PatchProfile(
            unlocker_dll_name="a.dll",
            runtime_original_library_name="b.dll",
            appinfo_asset_name="game_appinfo.json",
            template=PatchTemplate(ini_target_name="patch.ini"),
            install_relative_dir="../outside",
        )


def test_apply_is_idempotent_when_files_already_match(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "steam_api64_o.dll").write_bytes(BACKUP_BODY)
    unlocker, _original, appinfo = write_complete_patch_sources(tmp_path)
    original = tmp_path / "release" / "idempotent-original.dll"
    original.write_bytes(BACKUP_BODY)
    # Existing ini already matches what would be rendered.
    from signriver_app.infrastructure.patching import render_cream_api_ini
    expected_ini = render_cream_api_ini(APPINFO_PAYLOAD, STELLARIS_PATCH_PROFILE.template)
    (game_root / "cream_api.ini").write_bytes(b"\xef\xbb\xbf" + expected_ini.encode())
    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    assert result.unlocker_replaced is False
    assert result.backup_created is False
    assert result.ini_written is False
    assert result.audit_after.health is PatchHealth.HEALTHY


def test_apply_deterministically_replaces_ambiguous_legacy_layout(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(FOREIGN_UNLOCKER)
    (game_root / "steam_api64_o.dll").write_bytes(BACKUP_BODY)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    engine.apply(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    assert (game_root / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL

def test_apply_migrates_complete_legacy_patch_without_losing_original(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    expected_ini = render_cream_api_ini(
        APPINFO_PAYLOAD, STELLARIS_PATCH_PROFILE.template
    )
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "steam_api64_o.dll").write_bytes(VANILLA_GAME_DLL)
    (game_root / "cream_api.ini").write_bytes(
        b"\xef\xbb\xbf" + expected_ini.encode("utf-8")
    )

    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )

    assert (game_root / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL
    assert result.backup_replaced is False
    assert result.receipt.backup_origin == "published_original"
    assert engine.audit_recorded(game_root).health is PatchHealth.HEALTHY


def test_apply_replaces_same_size_unknown_primary_with_published_assets(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    foreign_same_size = pe_x64(b"X" * (len(UNLOCKER_BODY) - 256))
    (game_root / "steam_api64.dll").write_bytes(foreign_same_size)
    (game_root / "steam_api64_o.dll").write_bytes(BACKUP_BODY)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    engine.apply(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY

def test_recorded_audit_detects_same_size_tampering_and_bad_ini(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, appinfo = write_patch_sources(tmp_path)
    engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )

    patch_path = game_root / "steam_api64.dll"
    patch_path.write_bytes(b"MZ" + b"Z" * (len(UNLOCKER_BODY) - 2))
    audit = engine.audit_recorded(game_root)
    assert audit.health is PatchHealth.MODIFIED
    assert "steam_api64.dll" in audit.modified

    patch_path.write_bytes(UNLOCKER_BODY)
    ini_path = game_root / "cream_api.ini"
    ini_path.write_bytes(b"x" * ini_path.stat().st_size)
    audit = engine.audit_recorded(game_root)
    assert audit.health is PatchHealth.MODIFIED
    assert "cream_api.ini" in audit.modified


def test_restore_refuses_tampered_runtime_copy_without_trusted_original(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    engine.apply(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )
    runtime_path = game_root / "steam_api64_o.dll"
    tampered = pe_x64(b"tampered-runtime")
    runtime_path.write_bytes(tampered)

    with pytest.raises(PatchError, match="可信原生库缺失"):
        engine.restore_original(game_root)

    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    assert runtime_path.read_bytes() == tampered

def test_reapply_repairs_same_size_tampered_recorded_backup(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    backup_path = game_root / "steam_api64_o.dll"
    backup_path.write_bytes(b"MZ" + b"T" * (len(BACKUP_BODY) - 2))

    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_dll_source=original,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )

    assert backup_path.read_bytes() == VANILLA_GAME_DLL
    assert result.backup_replaced is True
    assert result.audit_after.health is PatchHealth.HEALTHY


def test_apply_replaces_unknown_runtime_with_published_original(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "steam_api64_o.dll").write_bytes(FOREIGN_BACKUP)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    engine.apply(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )
    assert (game_root / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL

def test_apply_can_populate_empty_directory_from_published_assets(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    engine.apply(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    assert (game_root / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL

def test_remove_restores_original_from_managed_install(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    engine.apply(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )

    touched = engine.remove(game_root)

    assert set(touched) == {"steam_api64.dll", "steam_api64_o.dll", "cream_api.ini"}
    assert (game_root / "steam_api64.dll").read_bytes() == VANILLA_GAME_DLL
    assert not (game_root / "steam_api64_o.dll").exists()
    assert not (game_root / "cream_api.ini").exists()

def test_remove_blocks_uncredentialed_patch_without_original(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "cream_api.ini").write_bytes(b"[steam]\n")

    with pytest.raises(PatchError, match="凭据缺失或损坏"):
        engine.remove(game_root)
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    assert (game_root / "cream_api.ini").is_file()

def test_remove_is_noop_when_directory_is_pristine(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    assert engine.remove(game_root) == ()

def test_restore_original_preserves_pristine_loader_without_backup(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    original = game_root / "steam_api64.dll"
    original.write_bytes(VANILLA_GAME_DLL)

    readiness = engine.inspect_original_restore(game_root)
    touched = engine.restore_original(game_root)

    assert readiness.ready is True
    assert readiness.patch_detected is False
    assert touched == ()
    assert original.read_bytes() == VANILLA_GAME_DLL


def test_restore_original_refuses_patch_without_original_backup(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "cream_api.ini").write_bytes(b"[steam]\n")

    readiness = engine.inspect_original_restore(game_root)

    assert readiness.ready is False
    assert "凭据缺失或损坏" in readiness.reason
    with pytest.raises(PatchError, match="凭据缺失或损坏"):
        engine.restore_original(game_root)
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    assert (game_root / "cream_api.ini").is_file()


def test_restore_original_blocks_uncredentialed_runtime_copy(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "steam_api64_o.dll").write_bytes(VANILLA_GAME_DLL)
    (game_root / "cream_api.ini").write_bytes(b"[steam]\n")

    with pytest.raises(PatchError, match="凭据缺失或损坏"):
        engine.restore_original(game_root)
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY

def test_recorded_restore_verifies_backup_and_removes_receipt(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, appinfo = write_patch_sources(tmp_path)
    engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )

    engine.restore_original(game_root)

    assert (game_root / "steam_api64.dll").read_bytes() == VANILLA_GAME_DLL
    assert engine.audit_recorded(game_root).health is PatchHealth.UNKNOWN


def test_installation_lock_blocks_concurrent_operation(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()

    with engine._installation_lock(game_root):
        with pytest.raises(PatchError, match="正在被另一个补丁操作占用"):
            with engine._installation_lock(game_root):
                pass


def test_reset_api_is_removed() -> None:
    assert not hasattr(PatchEngine, "reset")

def test_repair_patch_is_idempotent_and_keeps_receipt(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(VANILLA_GAME_DLL)
    unlocker, original, appinfo = write_complete_patch_sources(tmp_path)
    first = engine.apply(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )
    second = engine.repair_patch(
        game_root, unlocker_dll_source=unlocker,
        original_dll_source=original, appinfo_json_source=appinfo, game_id="stellaris",
    )

    assert first.audit_after.health is PatchHealth.HEALTHY
    assert second.audit_after.health is PatchHealth.HEALTHY
    assert second.unlocker_replaced is False
    assert second.backup_created is False

def test_patch_profile_rejects_conflicting_names() -> None:
    with pytest.raises(ValueError):
        PatchProfile(
            unlocker_dll_name="same.dll",
            runtime_original_library_name="same.dll",
            appinfo_asset_name="stellaris_appinfo.json",
            template=PatchTemplate(ini_target_name="cream_api.ini"),
        )


def test_patch_profile_rejects_traversal_in_names() -> None:
    with pytest.raises(ValueError):
        PatchProfile(
            unlocker_dll_name="../evil.dll",
            runtime_original_library_name="steam_api64_o.dll",
            appinfo_asset_name="stellaris_appinfo.json",
            template=PatchTemplate(ini_target_name="cream_api.ini"),
        )


def test_stellaris_patch_profile_matches_publisher_expectations() -> None:
    profile = STELLARIS_PATCH_PROFILE
    assert profile.unlocker_dll_name == "steam_api64.dll"
    assert profile.runtime_original_library_name == "steam_api64_o.dll"
    assert profile.appinfo_asset_name == "stellaris_appinfo.json"
    assert profile.template.ini_target_name == "cream_api.ini"
