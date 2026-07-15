"""Unit tests for the CreamAPI-style PatchEngine and helpers."""

from __future__ import annotations

import json
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


UNLOCKER_BODY = b"MZ" + b"\x00" * 254 + b"our-unlocker-payload"
BACKUP_BODY = b"MZ" + b"\x00" * 254 + b"our-backup-original-payload"
FOREIGN_UNLOCKER = b"MZ" + b"\x11" * 100 + b"some-other-unlocker"
FOREIGN_BACKUP = b"MZ" + b"\x22" * 100 + b"some-other-backup"
VANILLA_GAME_DLL = b"MZ" + b"\xff" * 200 + b"vanilla-steam-api-64"


APPINFO_PAYLOAD = {
    "app_id": "281990",
    "name": "Stellaris",
    "update_time": "2026-07-01",
    "dlcs": [
        {"id": "281991", "name": "Plantoids Species Pack"},
        {"id": "281992", "name": "Leviathans Story Pack"},
    ],
}


def write_patch_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    unlocker = tmp_path / "release" / "steam_api64.dll"
    backup = tmp_path / "release" / "steam_api64_o.dll"
    appinfo = tmp_path / "release" / "stellaris_appinfo.json"
    unlocker.parent.mkdir(parents=True, exist_ok=True)
    unlocker.write_bytes(UNLOCKER_BODY)
    backup.write_bytes(BACKUP_BODY)
    appinfo.write_text(json.dumps(APPINFO_PAYLOAD), encoding="utf-8")
    return unlocker, backup, appinfo


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
    unlocker, backup, appinfo = write_patch_sources(tmp_path)
    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    # The vanilla DLL must have been moved to steam_api64_o.dll, not deleted.
    assert (game_root / "steam_api64_o.dll").read_bytes() == VANILLA_GAME_DLL
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    ini_bytes = (game_root / "cream_api.ini").read_bytes()
    assert ini_bytes.startswith(b"\xef\xbb\xbf")
    assert result.backup_created is True
    assert result.audit_after.health is PatchHealth.MODIFIED
    # audit still returns MODIFIED because the backup came from the game itself
    # rather than our packaged copy; the important thing is the safety property.


def test_patch_operations_use_cartridge_owned_nested_directory(tmp_path: Path) -> None:
    profile = PatchProfile(
        unlocker_dll_name="custom_api.dll",
        original_backup_dll_name="custom_api_o.dll",
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
    unlocker, backup, appinfo = write_patch_sources(tmp_path)

    result = engine.apply(
        game,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
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


def test_patch_profile_rejects_unsafe_install_directory() -> None:
    with pytest.raises(ValueError, match="game root"):
        PatchProfile(
            unlocker_dll_name="a.dll",
            original_backup_dll_name="b.dll",
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
    unlocker, backup, appinfo = write_patch_sources(tmp_path)
    # Existing ini already matches what would be rendered.
    from signriver_app.infrastructure.patching import render_cream_api_ini
    expected_ini = render_cream_api_ini(APPINFO_PAYLOAD, STELLARIS_PATCH_PROFILE.template)
    (game_root / "cream_api.ini").write_bytes(b"\xef\xbb\xbf" + expected_ini.encode())
    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    assert result.unlocker_replaced is False
    assert result.backup_created is False
    assert result.ini_written is False
    assert result.audit_after.health is PatchHealth.HEALTHY


def test_apply_replaces_broken_patch_dll(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(FOREIGN_UNLOCKER)
    (game_root / "steam_api64_o.dll").write_bytes(BACKUP_BODY)
    unlocker, backup, appinfo = write_patch_sources(tmp_path)
    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    # The trusted backup was untouched.
    assert (game_root / "steam_api64_o.dll").read_bytes() == BACKUP_BODY
    assert result.unlocker_replaced is True
    assert result.backup_replaced is False
    assert result.audit_after.health is PatchHealth.HEALTHY


def test_apply_replaces_foreign_backup_only_when_needed(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    # Backup size differs → previous patcher may have left something else.
    (game_root / "steam_api64_o.dll").write_bytes(FOREIGN_BACKUP)
    unlocker, backup, appinfo = write_patch_sources(tmp_path)
    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    assert (game_root / "steam_api64_o.dll").read_bytes() == BACKUP_BODY
    assert result.backup_replaced is True
    assert result.audit_after.health is PatchHealth.HEALTHY


def test_apply_installs_from_scratch_on_empty_directory(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    unlocker, backup, appinfo = write_patch_sources(tmp_path)
    result = engine.apply(
        game_root,
        unlocker_dll_source=unlocker,
        original_backup_dll_source=backup,
        appinfo_json_source=appinfo,
        game_id="stellaris",
    )
    assert (game_root / "steam_api64.dll").read_bytes() == UNLOCKER_BODY
    assert (game_root / "steam_api64_o.dll").read_bytes() == BACKUP_BODY
    assert result.audit_after.health is PatchHealth.HEALTHY


# ---- remove & reset --------------------------------------------------------


def test_remove_restores_original_when_backup_is_present(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "steam_api64_o.dll").write_bytes(VANILLA_GAME_DLL)
    (game_root / "cream_api.ini").write_bytes(b"\xef\xbb\xbf[steam]\n")
    touched = engine.remove(game_root)
    assert "cream_api.ini" in touched
    assert "steam_api64_o.dll" in touched
    assert not (game_root / "steam_api64_o.dll").exists()
    assert (game_root / "steam_api64.dll").read_bytes() == VANILLA_GAME_DLL
    assert not (game_root / "cream_api.ini").exists()


def test_remove_deletes_patch_when_no_backup_available(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "steam_api64.dll").write_bytes(UNLOCKER_BODY)
    (game_root / "cream_api.ini").write_bytes(b"[steam]\n")
    touched = engine.remove(game_root)
    assert set(touched) == {"steam_api64.dll", "cream_api.ini"}
    assert not (game_root / "steam_api64.dll").exists()


def test_remove_is_noop_when_directory_is_pristine(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    touched = engine.remove(game_root)
    assert touched == ()


def test_reset_wipes_every_patch_file(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    for name in ("steam_api64.dll", "steam_api64_o.dll", "cream_api.ini"):
        (game_root / name).write_bytes(b"payload")
    removed = engine.reset(game_root)
    assert set(removed) == {"steam_api64.dll", "steam_api64_o.dll", "cream_api.ini"}
    for name in removed:
        assert not (game_root / name).exists()


# ---- profile guardrails ----------------------------------------------------


def test_patch_profile_rejects_conflicting_names() -> None:
    with pytest.raises(ValueError):
        PatchProfile(
            unlocker_dll_name="same.dll",
            original_backup_dll_name="same.dll",
            appinfo_asset_name="stellaris_appinfo.json",
            template=PatchTemplate(ini_target_name="cream_api.ini"),
        )


def test_patch_profile_rejects_traversal_in_names() -> None:
    with pytest.raises(ValueError):
        PatchProfile(
            unlocker_dll_name="../evil.dll",
            original_backup_dll_name="steam_api64_o.dll",
            appinfo_asset_name="stellaris_appinfo.json",
            template=PatchTemplate(ini_target_name="cream_api.ini"),
        )


def test_stellaris_patch_profile_matches_publisher_expectations() -> None:
    profile = STELLARIS_PATCH_PROFILE
    assert profile.unlocker_dll_name == "steam_api64.dll"
    assert profile.original_backup_dll_name == "steam_api64_o.dll"
    assert profile.appinfo_asset_name == "stellaris_appinfo.json"
    assert profile.template.ini_target_name == "cream_api.ini"
