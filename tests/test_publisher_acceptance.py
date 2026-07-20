from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_publisher import AcceptanceError, AcceptanceManager, PublisherWorkspace
from signriver_publisher.acceptance import FAILED, PASSED
from signriver_launcher.product import RELEASE_EXE_NAME


def manager_for(tmp_path: Path) -> tuple[PublisherWorkspace, AcceptanceManager]:
    workspace = PublisherWorkspace(tmp_path / "publisher-workspace")
    workspace.initialize()
    return workspace, AcceptanceManager(workspace, project_root=tmp_path)


def profile_by_id(workspace: PublisherWorkspace, game_id: str):
    return next(profile for profile in workspace.list_games() if profile.game_id == game_id)


def test_acceptance_checklist_adds_mapping_case_only_to_mapping_cartridges(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)

    civilization = {case.case_id for case in manager.cases_for(profile_by_id(workspace, "civilization_6"))}
    stellaris = {case.case_id for case in manager.cases_for(profile_by_id(workspace, "stellaris"))}

    assert "dlc.mapped-directory-names" in civilization
    assert "dlc.mapped-directory-names" not in stellaris
    assert "recovery.safe-restore" in civilization
    assert "download.multipart" in stellaris


def test_patch_failure_scenarios_cover_auto_and_manual_cases() -> None:
    scenarios = AcceptanceManager.patch_failure_scenarios()
    ids = {item.scenario_id for item in scenarios}
    assert "patch.current-missing" in ids
    assert "patch.backup-missing" in ids
    assert "patch.ini-missing" in ids
    assert "patch.current-mismatch" in ids
    assert "patch.clean-original" in ids
    quarantine = AcceptanceManager.patch_failure_scenario("patch.security-quarantine")
    assert quarantine.auto_buildable is False
    assert AcceptanceManager.patch_failure_scenario(
        "patch.current-missing"
    ).variant_id == "patch.current-missing"


def test_acceptance_fingerprint_binds_client_cartridge_and_publish_assets(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "stellaris")
    client_root = tmp_path / "client"
    client = client_root / RELEASE_EXE_NAME
    module = client_root / "app" / "versions" / "0.1.0" / "app_entry.py"
    module.parent.mkdir(parents=True)
    client.write_bytes(b"launcher")
    module.write_text("VERSION = 1\n", encoding="utf-8")
    output = workspace.output_dir / profile.game_id
    output.mkdir(parents=True)
    (output / profile.appinfo_name).write_text("{}", encoding="utf-8")

    first = manager.fingerprint(profile, client)
    module.write_text("VERSION = 22\n", encoding="utf-8")
    second = manager.fingerprint(profile, client)
    (output / profile.appinfo_name).write_text('{"changed": true}', encoding="utf-8")
    third = manager.fingerprint(profile, client)

    assert first.value != second.value
    assert second.value != third.value
    assert third.asset_count == 1
    assert third.client_path == str(client.resolve())


def test_acceptance_results_are_persisted_and_reject_stale_builds(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "stellaris")
    client = tmp_path / "client.exe"
    client.write_bytes(b"one")
    fingerprint = manager.fingerprint(profile, client)
    session = manager.new_session(profile, fingerprint)

    saved = manager.record_result(
        profile,
        "basic.game-detection",
        PASSED,
        fingerprint,
        note="路径和卡带切换正常",
    )

    assert saved.results["basic.game-detection"].note == "路径和卡带切换正常"
    assert manager.current_session(profile).results["basic.game-detection"].status == PASSED

    client.write_bytes(b"a different client")
    changed = manager.fingerprint(profile, client)
    with pytest.raises(AcceptanceError, match="开始新一轮"):
        manager.record_result(
            profile, "download.cache-reuse", FAILED, changed, note="旧轮次不应复用"
        )

    replacement = manager.new_session(profile, changed)
    history = workspace.root / "acceptance" / profile.game_id / "history" / f"{session.session_id}.json"
    assert replacement.results == {}
    assert history.is_file()


def test_acceptance_paths_are_isolated_per_game(tmp_path: Path) -> None:
    workspace, manager = manager_for(tmp_path)
    stellaris = profile_by_id(workspace, "stellaris")
    civilization = profile_by_id(workspace, "civilization_6")
    stellaris_game = tmp_path / "Stellaris"
    civilization_game = tmp_path / "CivilizationVI"
    stellaris_game.mkdir()
    civilization_game.mkdir()

    manager.save_paths(stellaris, game_path=stellaris_game, keep_game=False)
    manager.save_paths(civilization, game_path=civilization_game, keep_game=False)

    assert manager.configured_paths(stellaris).game_path == stellaris_game.resolve()
    assert manager.configured_paths(civilization).game_path == civilization_game.resolve()


def test_environment_inspection_is_read_only_and_collects_evidence(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "stellaris")
    client_root = tmp_path / "client"
    client = client_root / RELEASE_EXE_NAME
    log = client_root / "data" / "logs" / "launcher.log"
    log.parent.mkdir(parents=True)
    client.write_bytes(b"client")
    log.write_text("manual acceptance log", encoding="utf-8")
    game = tmp_path / "game"
    dlc = game / profile.dlc_relative_dir / "dlc001_example"
    patch = game / profile.patch_relative_dir
    dlc.mkdir(parents=True)
    (patch / profile.patch_unlocker_name).write_bytes(b"patch")
    before = sorted(str(path.relative_to(game)) for path in game.rglob("*"))
    paths = manager.save_paths(
        profile,
        client_path=client,
        game_path=game,
        keep_client=False,
        keep_game=False,
    )
    fingerprint = manager.fingerprint(profile, client)
    session = manager.new_session(profile, fingerprint)

    report_path, report = manager.inspect_environment(profile, paths, session)
    log_copy = manager.collect_client_log(profile, paths, session)
    after = sorted(str(path.relative_to(game)) for path in game.rglob("*"))

    assert before == after
    assert report["dlc_folder_count"] == 1
    assert report["patch_files"][profile.patch_unlocker_name]["exists"] is True
    assert json.loads(report_path.read_text(encoding="utf-8"))["game_id"] == profile.game_id
    assert log_copy.read_text(encoding="utf-8") == "manual acceptance log"


def test_patch_test_environment_can_be_previewed_applied_and_restored(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "stellaris")
    client = tmp_path / "client.exe"
    client.write_bytes(b"client")
    game = tmp_path / "game"
    game.mkdir()
    unlocker = game / profile.patch_unlocker_name
    backup = game / profile.patch_original_backup_name
    ini = game / "cream_api.ini"
    unlocker.write_bytes(b"current dll")
    backup.write_bytes(b"original dll")
    ini.write_text("[steam]\nappid=281990\n", encoding="utf-8")
    paths = manager.save_paths(
        profile,
        client_path=client,
        game_path=game,
        keep_client=False,
        keep_game=False,
    )
    fingerprint = manager.fingerprint(profile, client)
    session = manager.new_session(profile, fingerprint)

    baseline = manager.capture_patch_baseline(profile, paths, session, fingerprint)
    preview = manager.preview_preparation(
        profile,
        paths,
        session,
        fingerprint,
        "patch.damaged-state",
        "patch.current-mismatch",
    )
    applied = manager.apply_preparation(
        profile,
        paths,
        session,
        fingerprint,
        "patch.damaged-state",
        "patch.current-mismatch",
    )

    assert baseline.is_file()
    assert preview.actions == applied.actions
    assert unlocker.read_bytes().startswith(b"SIGNRIVER ACCEPTANCE TEST FILE")
    assert manager.active_preparation(profile)["variant_id"] == "patch.current-mismatch"
    assert len(manager.active_preparations()) == 1

    restored = manager.restore_prepared_environment(profile)

    assert restored == 3
    assert unlocker.read_bytes() == b"current dll"
    assert backup.read_bytes() == b"original dll"
    assert ini.read_text(encoding="utf-8") == "[steam]\nappid=281990\n"
    assert manager.active_preparation(profile) is None


def test_patch_baseline_restore_removes_files_that_did_not_exist_before_test(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "stellaris")
    client = tmp_path / "client.exe"
    client.write_bytes(b"client")
    game = tmp_path / "game"
    game.mkdir()
    unlocker = game / profile.patch_unlocker_name
    unlocker.write_bytes(b"original only")
    paths = manager.save_paths(
        profile,
        client_path=client,
        game_path=game,
        keep_client=False,
        keep_game=False,
    )
    fingerprint = manager.fingerprint(profile, client)
    session = manager.new_session(profile, fingerprint)
    manager.capture_patch_baseline(profile, paths, session, fingerprint)
    manager.apply_preparation(
        profile,
        paths,
        session,
        fingerprint,
        "patch.clean-install",
        "patch.clean-original",
    )
    backup = game / profile.patch_original_backup_name
    ini = game / "cream_api.ini"
    backup.write_bytes(b"created during test")
    ini.write_text("created during test", encoding="utf-8")

    manager.restore_prepared_environment(profile)

    assert unlocker.read_bytes() == b"original only"
    assert not backup.exists()
    assert not ini.exists()


def test_patch_preparation_refuses_environment_changed_after_baseline(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "stellaris")
    client = tmp_path / "client.exe"
    client.write_bytes(b"client")
    game = tmp_path / "game"
    game.mkdir()
    unlocker = game / profile.patch_unlocker_name
    unlocker.write_bytes(b"before")
    paths = manager.save_paths(
        profile,
        client_path=client,
        game_path=game,
        keep_client=False,
        keep_game=False,
    )
    fingerprint = manager.fingerprint(profile, client)
    session = manager.new_session(profile, fingerprint)
    manager.capture_patch_baseline(profile, paths, session, fingerprint)
    unlocker.write_bytes(b"changed after baseline")

    with pytest.raises(AcceptanceError, match="重新记录基线"):
        manager.apply_preparation(
            profile,
            paths,
            session,
            fingerprint,
            "patch.damaged-state",
            "patch.current-missing",
        )

    assert unlocker.read_bytes() == b"changed after baseline"
    assert manager.active_preparation(profile) is None


def test_patch_preparation_failure_restores_baseline_and_clears_active_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "stellaris")
    client = tmp_path / "client.exe"
    client.write_bytes(b"client")
    game = tmp_path / "game"
    game.mkdir()
    unlocker = game / profile.patch_unlocker_name
    unlocker.write_bytes(b"must survive")
    paths = manager.save_paths(
        profile,
        client_path=client,
        game_path=game,
        keep_client=False,
        keep_game=False,
    )
    fingerprint = manager.fingerprint(profile, client)
    session = manager.new_session(profile, fingerprint)
    manager.capture_patch_baseline(profile, paths, session, fingerprint)
    original_atomic_json = manager._atomic_json

    def fail_final_marker(path: Path, value: object) -> None:
        if path.name == "prepared.json" and isinstance(value, dict) and value.get("status") == "applied":
            raise OSError("simulated final marker failure")
        original_atomic_json(path, value)

    monkeypatch.setattr(manager, "_atomic_json", fail_final_marker)

    with pytest.raises(AcceptanceError, match="已恢复基线"):
        manager.apply_preparation(
            profile,
            paths,
            session,
            fingerprint,
            "patch.damaged-state",
            "patch.current-missing",
        )

    assert unlocker.read_bytes() == b"must survive"
    assert manager.active_preparation(profile) is None


def test_patch_environment_tools_follow_each_cartridge_patch_directory(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "civilization_6")
    client = tmp_path / "client.exe"
    client.write_bytes(b"client")
    game = tmp_path / "CivilizationVI"
    patch_dir = game / Path(profile.patch_relative_dir)
    patch_dir.mkdir(parents=True)
    nested_unlocker = patch_dir / profile.patch_unlocker_name
    nested_backup = patch_dir / profile.patch_original_backup_name
    root_decoy = game / profile.patch_original_backup_name
    nested_unlocker.write_bytes(b"nested current")
    nested_backup.write_bytes(b"nested backup")
    root_decoy.write_bytes(b"must not be touched")
    paths = manager.save_paths(
        profile,
        client_path=client,
        game_path=game,
        keep_client=False,
        keep_game=False,
    )
    fingerprint = manager.fingerprint(profile, client)
    session = manager.new_session(profile, fingerprint)

    manager.capture_patch_baseline(profile, paths, session, fingerprint)
    manager.apply_preparation(
        profile,
        paths,
        session,
        fingerprint,
        "patch.damaged-state",
        "patch.backup-missing",
    )

    assert not nested_backup.exists()
    assert root_decoy.read_bytes() == b"must not be touched"

    manager.restore_prepared_environment(profile)

    assert nested_backup.read_bytes() == b"nested backup"
    assert root_decoy.read_bytes() == b"must not be touched"


def test_patch_directory_rejects_escape_and_names_active_cartridge(
    tmp_path: Path,
) -> None:
    workspace, manager = manager_for(tmp_path)
    profile = profile_by_id(workspace, "civilization_6")
    root = tmp_path / "wrong-game"
    root.mkdir()

    with pytest.raises(AcceptanceError, match="Civilization VI 卡带配置"):
        manager.patch_directory(profile, root, require_exists=True)

    unsafe = type(profile)(
        **{
            **profile.to_dict(),
            "patch_relative_dir": "../outside",
        }
    )
    with pytest.raises(AcceptanceError, match="超出了游戏根目录"):
        manager.patch_directory(unsafe, root)


def test_publisher_ui_exposes_manual_acceptance_controls() -> None:
    source = (Path(__file__).parents[1] / "src" / "signriver_publisher" / "ui.py").read_text(
        encoding="utf-8"
    )

    assert 'self.tabs.add("发布验收")' in source
    assert "开始新一轮" in source
    assert "检查并记录" in source
    assert "标记通过" in source
    assert "启动客户端" in source
    assert "记录补丁基线" in source
    assert "构建该环境" in source
    assert "def build_acceptance_failure_environment" in source
    assert "acceptance_scenario_list" in source
    assert "恢复测试环境" in source
    assert 'uniform="acceptance_paths"' in source
    assert 'uniform="acceptance_env"' in source
    assert 'uniform="acceptance_results"' in source
