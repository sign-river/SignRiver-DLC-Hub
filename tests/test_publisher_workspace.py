from __future__ import annotations

import json
import random
import shutil
import threading
import time
from types import SimpleNamespace
import zipfile
from pathlib import Path

import pytest

from signriver_publisher import GameProfile, PublisherCartridge, PublishAsset, PublisherSettings, PublisherWorkspace, SteamApiError, SteamAppInfo, SteamDlc, SteamStoreClient, WorkspaceError, create_builtin_cartridges, discover_settings_path, generate_cream_api_ini, load_steam_appinfo
from signriver_publisher.gitlink import GitLinkAttachmentClient, GitLinkCli, GitLinkRepository, UploadControl, UploadPaused, find_release_id
from signriver_publisher.gitlink import GitLinkError
from signriver_publisher.remote import RemoteAsset, RemoteResourceManager, parse_release


def sample_appinfo(app_id: str = "281990") -> SteamAppInfo:
    return SteamAppInfo(
        app_id,
        "Stellaris",
        "2026-06-15 21:07:12",
        (SteamDlc("498870", "Stellaris: Plantoids Species Pack"),),
    )


def test_initializes_stellaris_workspace(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")

    profile = workspace.initialize()

    assert profile == GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990")
    assert (workspace.game_dir("stellaris") / "dlc").is_dir()
    assert (workspace.game_dir("stellaris") / "patches").is_dir()


def test_large_release_archive_is_split_without_changing_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "dlc001_large.zip"
    payload = bytes(range(256)) * 50
    archive.write_bytes(payload)

    parts = PublisherWorkspace._ensure_release_parts(archive, 4096)

    assert [part.name for part in parts] == [
        "dlc001_large.zip.part001-of-004",
        "dlc001_large.zip.part002-of-004",
        "dlc001_large.zip.part003-of-004",
        "dlc001_large.zip.part004-of-004",
    ]
    assert b"".join(part.read_bytes() for part in parts) == payload
    assert all(part.stat().st_size <= 4096 for part in parts)


def test_build_removes_large_full_zip_and_reuses_only_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("signriver_publisher.workspace.RELEASE_PART_SIZE", 4096)
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    dlc = workspace.game_dir(profile.game_id) / "dlc" / "dlc001_large"
    dlc.mkdir()
    (dlc / "payload.bin").write_bytes(random.Random(7).randbytes(20000))
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / profile.patch_unlocker_name).write_bytes(b"new")
    (patches / profile.patch_original_backup_name).write_bytes(b"old")

    workspace.build(profile)
    output = workspace.output_dir / profile.game_id
    parts = tuple(sorted(output.glob("dlc001_large.zip.part*-of-*")))

    assert len(parts) > 1
    assert not (output / "dlc001_large.zip").exists()
    assert all(path.name != "dlc001_large.zip" for path in workspace.publish_files(profile))

    monkeypatch.setattr(
        workspace,
        "_zip_directory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("parts should be reused")),
    )
    workspace.build(profile)
    assert tuple(sorted(output.glob("dlc001_large.zip.part*-of-*"))) == parts


def test_other_game_uses_its_own_appinfo_name_and_output_directory(tmp_path: Path) -> None:
    def provider(app_id: str) -> SteamAppInfo:
        return SteamAppInfo(app_id, "Europa Universalis IV", "2026-07-14", ())

    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=provider)
    workspace.initialize()
    profile = GameProfile.create("europa_universalis_4", "Europa Universalis IV", "236850")
    workspace.save_game(profile)

    workspace.refresh_appinfo(profile)

    assert profile.appinfo_name == "europa_universalis_4_appinfo.json"
    assert (workspace.output_dir / "europa_universalis_4" / profile.appinfo_name).is_file()
    assert not (workspace.output_dir / "stellaris" / profile.appinfo_name).exists()


def test_server_cartridge_owns_release_and_patch_contract(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    cartridge = PublisherCartridge(
        "other_game", "Other Game", "other_game", "other_game_appinfo.json",
        "281990", "custom_api64.dll", "custom_api64_original.dll",
        "content/addons", "bin/win64",
    )
    workspace.save_game(cartridge)
    patches = workspace.game_dir(cartridge.game_id) / "patches"
    (patches / cartridge.patch_unlocker_name).write_bytes(b"new")
    (patches / cartridge.patch_original_backup_name).write_bytes(b"old")

    workspace.build(cartridge)

    output_names = {path.name for path in workspace.publish_files(cartridge)}
    assert output_names == {
        "custom_api64.dll", "custom_api64_original.dll", "other_game_appinfo.json",
    }
    restored = workspace.list_games()[0]
    assert restored.patch_asset_names == cartridge.patch_asset_names
    assert restored.release_tag == "other_game"
    assert restored.dlc_relative_dir == "content/addons"
    assert restored.patch_relative_dir == "bin/win64"


def test_server_cartridge_rejects_unsafe_install_directories(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    cartridge = PublisherCartridge.create("other_game", "Other Game", "123")
    unsafe = PublisherCartridge(
        cartridge.game_id, cartridge.display_name, cartridge.release_tag,
        cartridge.appinfo_name, cartridge.steam_app_id,
        dlc_relative_dir="../outside",
    )
    with pytest.raises(WorkspaceError, match="DLC 安装目录"):
        workspace.save_game(unsafe)


def test_empty_server_workspace_is_seeded_from_builtin_cartridge_registry(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")

    selected = workspace.initialize()

    assert selected == create_builtin_cartridges()[0]
    assert selected.patch_asset_names == ("steam_api64.dll", "steam_api64_o.dll")
    builtins = {item.game_id: item for item in workspace.list_games()}
    assert builtins["civilization_6"].dlc_import_naming_mode == "auto_prefix"
    assert builtins["civilization_6"].dlc_import_layout_mode == "children_if_root"
    assert builtins["stellaris"].dlc_import_naming_mode == "manual_prefixed"
    assert builtins["stellaris"].dlc_import_layout_mode == "single_directory"
    assert builtins["hearts_of_iron_4"].dlc_import_naming_mode == "manual_prefixed"


def test_rejects_appinfo_name_that_does_not_match_game_id(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")

    with pytest.raises(WorkspaceError, match="other_game_appinfo.json"):
        workspace.save_game(GameProfile("other_game", "Other Game", "other_game", "stellaris_appinfo.json", "123"))


def test_legacy_stellaris_profile_gets_steam_app_id(tmp_path: Path) -> None:
    game = tmp_path / "publisher" / "games" / "stellaris"
    game.mkdir(parents=True)
    (game / "game.json").write_text(json.dumps({"game_id": "stellaris", "display_name": "Stellaris", "release_tag": "stellaris", "appinfo_name": "stellaris_appinfo.json"}), encoding="utf-8")

    profile = PublisherWorkspace(tmp_path / "publisher").initialize()

    assert profile.steam_app_id == "281990"


def test_builds_each_dlc_and_patch_and_generates_appinfo(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    game = workspace.game_dir(profile.game_id)
    dlc = game / "dlc" / "dlc001_symbols_of_domination"
    dlc.mkdir()
    (dlc / "dlc001.dlc").write_text('name="Symbols of Domination"', encoding="utf-8")
    (dlc / "dlc001.zip").write_bytes(b"nested archive")
    patches = game / "patches"
    (patches / "steam_api64.dll").write_bytes(b"patched dll")
    (patches / "steam_api64_o.dll").write_bytes(b"original dll")
    appinfo_payload = {
        "app_id": "281990",
        "name": "Stellaris",
        "update_time": "2026-06-15 21:07:12",
        "dlcs": [{"id": "498870", "name": "Stellaris: Plantoids Species Pack"}],
    }
    (patches / "unlock_patch.txt").write_text("patch", encoding="utf-8")

    records = workspace.build(profile)

    assert [record.asset_name for record in records] == [
        "dlc001_symbols_of_domination.zip",
        "stellaris_appinfo.json",
        "steam_api64.dll",
        "steam_api64_o.dll",
        "unlock_patch.txt",
    ]
    package = workspace.output_dir / "stellaris" / "dlc001_symbols_of_domination.zip"
    with zipfile.ZipFile(package) as archive:
        assert archive.namelist() == [
            "dlc001_symbols_of_domination/dlc001.dlc",
            "dlc001_symbols_of_domination/dlc001.zip",
        ]
        assert all(item.compress_type == zipfile.ZIP_DEFLATED for item in archive.infolist())
    appinfo = json.loads((workspace.output_dir / "stellaris" / "stellaris_appinfo.json").read_text(encoding="utf-8"))
    assert appinfo == appinfo_payload


def test_rebuild_removes_stale_output(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    output = workspace.output_dir / profile.game_id
    output.mkdir(parents=True)
    (output / "old.zip").write_bytes(b"old")
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")

    workspace.build(profile)

    assert not (output / "old.zip").exists()
    assert (output / profile.appinfo_name).is_file()


def test_build_reuses_unchanged_dlc_zip_and_rebuilds_changed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    source = workspace.game_dir(profile.game_id) / "dlc" / "dlc001_example"
    source.mkdir()
    content = source / "content.txt"
    content.write_text("first", encoding="utf-8")
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")
    workspace.build(profile)
    original_zip = workspace._zip_directory
    calls: list[str] = []

    def tracked_zip(
        source_path: Path, destination: Path, *, include_root: bool,
        archive_root: str | None = None,
    ) -> None:
        calls.append(source_path.name)
        original_zip(
            source_path, destination, include_root=include_root,
            archive_root=archive_root,
        )

    monkeypatch.setattr(workspace, "_zip_directory", tracked_zip)

    workspace.build(profile)
    assert calls == []

    content.write_text("changed and longer", encoding="utf-8")
    workspace.build(profile)
    assert calls == ["dlc001_example"]


def test_build_compresses_multiple_changed_dlc_in_parallel_with_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = PublisherWorkspace(
        tmp_path / "publisher", appinfo_provider=sample_appinfo
    )
    profile = workspace.initialize()
    dlc_root = workspace.game_dir(profile.game_id) / "dlc"
    for index in range(1, 5):
        source = dlc_root / f"dlc{index:03d}_example{index}"
        source.mkdir()
        (source / "content.bin").write_bytes(bytes([index]) * 64 * 1024)
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")

    original_zip = workspace._zip_directory
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def tracked_zip(*args, **kwargs) -> None:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.05)
            original_zip(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(workspace, "_zip_directory", tracked_zip)
    monkeypatch.setattr(workspace, "compression_worker_count", lambda: 4)
    events: list[tuple[str, int, int, str, str]] = []

    workspace.build(profile, progress=lambda *event: events.append(event))

    assert maximum_active >= 2
    assert any(event[0] == "并行压缩准备" and "4 个并行任务" in event[4] for event in events)
    assert sum(event[0] == "开始压缩" for event in events) == 4
    assert sum(event[0] == "压缩完成" for event in events) == 4


def test_build_adopts_existing_zip_from_older_publisher_without_recompressing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    source = workspace.game_dir(profile.game_id) / "dlc" / "dlc001_existing"
    source.mkdir()
    (source / "content.txt").write_text("already packed", encoding="utf-8")
    output = workspace.output_dir / profile.game_id / "dlc001_existing.zip"
    output.parent.mkdir(parents=True)
    workspace._zip_directory(source, output, include_root=True)
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")

    def should_not_recompress(*_args, **_kwargs) -> None:
        raise AssertionError("matching legacy ZIP should be adopted")

    monkeypatch.setattr(workspace, "_zip_directory", should_not_recompress)

    workspace.build(profile)

    assert output.is_file()
    assert (workspace.game_dir(profile.game_id) / ".build-state.json").is_file()


def test_build_rejects_stale_appinfo_when_steam_is_temporarily_unavailable(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")
    workspace.build(profile)

    def unavailable(_app_id: str) -> SteamAppInfo:
        raise SteamApiError("HTTP Error 500")

    workspace._appinfo_provider = unavailable
    with pytest.raises(WorkspaceError, match="HTTP Error 500"):
        workspace.build(profile)

    assert not (workspace.output_dir / "stellaris" / "stellaris_appinfo.json").exists()
    with pytest.raises(WorkspaceError, match="请先生成发布包"):
        workspace.publish_files(profile)


def test_every_build_fetches_and_rewrites_appinfo(tmp_path: Path) -> None:
    calls = 0

    def provider(app_id: str) -> SteamAppInfo:
        nonlocal calls
        calls += 1
        return SteamAppInfo(app_id, "Stellaris", f"revision-{calls}", ())

    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=provider)
    profile = workspace.initialize()
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")

    workspace.build(profile)
    workspace.build(profile)

    payload = json.loads((workspace.output_dir / "stellaris" / "stellaris_appinfo.json").read_text(encoding="utf-8"))
    assert calls == 2
    assert payload["update_time"] == "revision-2"


def test_import_and_remove_are_restricted_to_resource_root(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = workspace.initialize()
    source = tmp_path / "dlc002_arachnoid"
    source.mkdir()
    (source / "dlc002.dlc").write_text("x", encoding="utf-8")

    imported = workspace.import_dlc(profile, source)
    workspace.remove_source(profile, "dlc", imported.name)

    assert not imported.exists()
    with pytest.raises(WorkspaceError):
        workspace.remove_source(profile, "dlc", "../game.json")


def test_clear_local_sources_resets_dlc_import_state_without_touching_patches(
    tmp_path: Path,
) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = workspace.initialize()
    dlc = workspace.game_dir(profile.game_id) / "dlc" / "dlc001_example"
    dlc.mkdir()
    (dlc / "content.dat").write_bytes(b"dlc")
    patch = workspace.game_dir(profile.game_id) / "patches" / "steam_api64.dll"
    patch.write_bytes(b"patch")
    (workspace.game_dir(profile.game_id) / ".dlc-import-state.json").write_text(
        '{"version": 1, "next_number": 9}', encoding="utf-8"
    )

    count = workspace.clear_sources(profile, "dlc")

    assert count == 1
    assert not tuple((workspace.game_dir(profile.game_id) / "dlc").iterdir())
    assert patch.is_file()
    assert workspace._next_dlc_import_number(profile) == 1


def test_auto_prefix_cartridge_imports_raw_folder_with_monotonic_number(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    profile = next(
        item for item in workspace.list_games() if item.game_id == "civilization_6"
    )
    first = tmp_path / "Expansion1"
    first.mkdir()
    (first / "content.dat").write_bytes(b"first")

    imported_first = workspace.import_dlc(profile, first)
    workspace.remove_source(profile, "dlc", imported_first.name)

    second = tmp_path / "VikingsScenario"
    second.mkdir()
    (second / "content.dat").write_bytes(b"second")
    imported_second = workspace.import_dlc(profile, second)

    assert imported_first.name == "dlc001_Expansion1"
    assert imported_second.name == "dlc002_VikingsScenario"
    assert (imported_second / "content.dat").read_bytes() == b"second"


def test_manual_prefix_cartridge_still_rejects_raw_folder(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = workspace.initialize()
    source = tmp_path / "Expansion1"
    source.mkdir()
    (source / "content.dat").write_bytes(b"x")

    with pytest.raises(WorkspaceError, match="dlc001"):
        workspace.import_dlc(profile, source)


def test_civilization_root_import_splits_immediate_children(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    profile = next(
        item for item in workspace.list_games() if item.game_id == "civilization_6"
    )
    source = tmp_path / "DLC"
    for name in ("Expansion1", "Australia", "KublaiKhan_Vietnam"):
        child = source / name
        child.mkdir(parents=True)
        (child / "content.dat").write_text(name, encoding="utf-8")
    progress: list[tuple[int, int, str]] = []

    imported = workspace.import_dlc_collection(
        profile,
        source,
        progress=lambda index, total, name: progress.append((index, total, name)),
    )

    assert [path.name for path in imported] == [
        "dlc001_Australia",
        "dlc002_Expansion1",
        "dlc003_KublaiKhan_Vietnam",
    ]
    assert not (workspace.game_dir(profile.game_id) / "dlc" / "dlc001_DLC").exists()
    assert progress[-1] == (3, 3, "KublaiKhan_Vietnam")


def test_collection_copy_failure_rolls_back_files_and_number_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    profile = next(
        item for item in workspace.list_games() if item.game_id == "civilization_6"
    )
    source = tmp_path / "DLC"
    for name in ("Australia", "Expansion1"):
        child = source / name
        child.mkdir(parents=True)
        (child / "content.dat").write_text(name, encoding="utf-8")
    calls = 0

    def unreliable_copy(child: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated transient copy failure")
        shutil.copytree(child, destination)

    monkeypatch.setattr(workspace, "_copy_directory", unreliable_copy)

    with pytest.raises(WorkspaceError, match="Expansion1"):
        workspace.import_dlc_collection(profile, source)

    dlc_root = workspace.game_dir(profile.game_id) / "dlc"
    assert not tuple(dlc_root.iterdir())
    assert workspace._next_dlc_import_number(profile) == 1
    staging = workspace._import_staging_root(profile)
    assert not staging.exists() or not tuple(staging.iterdir())


def test_detects_and_discards_legacy_wrapped_collection_import(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    profile = next(
        item for item in workspace.list_games() if item.game_id == "civilization_6"
    )
    source = tmp_path / "DLC"
    for name in ("Expansion1", "Australia"):
        child = source / name
        child.mkdir(parents=True)
        (child / "content.dat").write_text(name, encoding="utf-8")
    wrapped = workspace.game_dir(profile.game_id) / "dlc" / "dlc001_DLC"
    shutil.copytree(source, wrapped)

    assert workspace.wrapped_collection_import(profile, source) == wrapped
    workspace.discard_wrapped_collection_import(profile, source)
    imported = workspace.import_dlc_collection(profile, source)

    assert not wrapped.exists()
    assert [path.name for path in imported] == [
        "dlc001_Australia",
        "dlc002_Expansion1",
    ]


def test_splits_legacy_wrapped_collection_without_copying_again(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    profile = next(
        item for item in workspace.list_games() if item.game_id == "civilization_6"
    )
    source = tmp_path / "DLC"
    for name in ("Expansion1", "Australia"):
        child = source / name
        child.mkdir(parents=True)
        (child / "content.dat").write_text(name, encoding="utf-8")
    wrapped = workspace.game_dir(profile.game_id) / "dlc" / "dlc001_DLC"
    shutil.copytree(source, wrapped)

    imported = workspace.split_wrapped_collection_import(profile, source)

    assert not wrapped.exists()
    assert [path.name for path in imported] == [
        "dlc001_Australia",
        "dlc002_Expansion1",
    ]
    assert (imported[1] / "content.dat").read_text(encoding="utf-8") == "Expansion1"
    state = json.loads(
        (workspace.game_dir(profile.game_id) / ".dlc-import-state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["next_number"] == 3


def test_rejects_invalid_dlc_folder_and_symlink(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = workspace.initialize()
    invalid = workspace.game_dir(profile.game_id) / "dlc" / "random"
    invalid.mkdir()
    (invalid / "file.txt").write_text("x", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="dlc001"):
        workspace.build(profile)


def test_appinfo_generates_expected_cream_api_ini(tmp_path: Path) -> None:
    path = tmp_path / "stellaris_appinfo.json"
    path.write_text(
        json.dumps(
            {
                "app_id": "281990",
                "name": "Stellaris",
                "update_time": "2026-06-15 21:07:12",
                "dlcs": [
                    {"id": "498870", "name": "Stellaris: Plantoids Species Pack"},
                    {"id": "518910", "name": "Stellaris: Leviathans Story Pack"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = generate_cream_api_ini(load_steam_appinfo(path, expected_app_id="281990"))

    assert result == (
        "[steam]\n"
        "appid = 281990\n"
        "language = schinese\n"
        "unlockall = True\n"
        "extraprotection = False\n"
        "forceoffline = False\n"
        "\n"
        "[dlc]\n"
        "498870 = Stellaris: Plantoids Species Pack\n"
        "518910 = Stellaris: Leviathans Story Pack\n"
    )


def test_build_requires_dlls_and_rejects_wrong_steam_app(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=lambda _app_id: sample_appinfo("123"))
    profile = workspace.initialize()

    with pytest.raises(WorkspaceError, match="steam_api64.dll"):
        workspace.build(profile)

    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"patched")
    (patches / "steam_api64_o.dll").write_bytes(b"original")
    with pytest.raises(WorkspaceError, match="当前游戏要求 281990"):
        workspace.build(profile)


def test_steam_store_client_combines_names_and_sorts_ids() -> None:
    def fetch(url: str, _timeout: float, _limit: int) -> bytes:
        if "/api/appdetails" in url:
            return json.dumps({"281990": {"success": True, "data": {"name": "Stellaris", "dlc": [20, 10]}}}).encode()
        if "/api/dlcforapp/" in url:
            return json.dumps({"status": 1, "appid": 281990, "name": "Stellaris", "dlc": [{"id": 10, "name": "First"}, {"id": 20, "name": "Second"}]}).encode()
        raise AssertionError(url)

    result = SteamStoreClient(fetch=fetch).fetch_appinfo("281990")

    assert result.app_id == "281990"
    assert result.name == "Stellaris"
    assert [(item.app_id, item.name) for item in result.dlcs] == [("10", "First"), ("20", "Second")]


def test_steam_store_client_retries_transient_request_failure() -> None:
    attempts = 0

    def fetch(url: str, _timeout: float, _limit: int) -> bytes:
        nonlocal attempts
        if "/api/appdetails" in url:
            attempts += 1
            if attempts < 3:
                raise OSError("HTTP Error 500")
            return json.dumps({"281990": {"success": True, "data": {"name": "Stellaris", "dlc": []}}}).encode()
        return json.dumps({"dlc": []}).encode()

    result = SteamStoreClient(fetch=fetch, retries=2, retry_delay=0, sleep=lambda _delay: None).fetch_appinfo("281990")

    assert result.app_id == "281990"
    assert attempts == 3


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"data": {"releases": [{"id": 7, "tag_name": "stellaris"}]}}, "7"),
        ({"releases": [{"id": 7, "version_id": 2318, "tag_name": "stellaris"}]}, "2318"),
        ({"releases": [{"version_gid": "abc", "tag_name": "stellaris"}]}, "abc"),
        ({"data": {"releases": [{"id": 7, "tag_name": "other"}]}}, None),
    ],
)
def test_find_release_id_handles_cli_response_shapes(payload: dict[str, object], expected: str | None) -> None:
    assert find_release_id(payload, "stellaris") == expected


def test_attachment_upload_streams_file_and_returns_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "dlc001.zip"
    source.write_bytes(b"package-data")

    class Response:
        status = 200

        @staticmethod
        def read(_limit: int) -> bytes:
            return b'{"id":"attachment-123"}'

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.headers: dict[str, str] = {}
            self.sent = bytearray()

        def putrequest(self, *_args) -> None: pass
        def putheader(self, name: str, value: str) -> None: self.headers[name] = value
        def endheaders(self) -> None: pass
        def send(self, value: bytes) -> None: self.sent.extend(value)
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    attachment_id = GitLinkAttachmentClient("secret-token").upload(source)

    assert attachment_id == "attachment-123"
    assert Connection.instance.headers["Authorization"] == "Bearer secret-token"
    assert b"package-data" in Connection.instance.sent


def test_attachment_upload_can_pause_between_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "large.zip"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    control = UploadControl()

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.closed = False

        def putrequest(self, *_args) -> None: pass
        def putheader(self, *_args) -> None: pass
        def endheaders(self) -> None: pass
        def send(self, _value: bytes) -> None: pass
        def close(self) -> None: self.closed = True

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    with pytest.raises(UploadPaused):
        GitLinkAttachmentClient("secret-token").upload(
            source,
            progress=lambda *_args: control.request_pause(),
            control=control,
        )

    assert Connection.instance.closed is True


def test_cli_uses_temporary_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout='{"data":{"releases":[]}}', stderr="")

    monkeypatch.setattr("signriver_publisher.gitlink.subprocess.run", fake_run)
    GitLinkCli("gitlink-cli").list_releases(GitLinkRepository(), token="temporary-token")

    assert captured["environment"]["GITLINK_TOKEN"] == "temporary-token"  # type: ignore[index]
    assert "temporary-token" not in captured["command"]  # type: ignore[operator]


def test_release_api_uses_bearer_token_without_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        @staticmethod
        def read(_limit: int) -> bytes:
            return b'{"releases":[]}'

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.request_args = None

        def request(self, *args, **kwargs) -> None: self.request_args = (args, kwargs)
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    result = GitLinkAttachmentClient("secret-token").list_releases(GitLinkRepository())

    assert result == {"releases": []}
    args, kwargs = Connection.instance.request_args
    assert args[:2] == ("GET", "/api/signriver/signriver-dlc-assets/releases.json?page=1&limit=100")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


def test_release_api_rejects_application_level_404(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        @staticmethod
        def read(_limit: int) -> bytes:
            return '{"status":404,"message":"仓库不存在"}'.encode()

    class Connection:
        def __init__(self, *_args, **_kwargs) -> None: pass
        def request(self, *_args, **_kwargs) -> None: pass
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    with pytest.raises(GitLinkError, match="404.*仓库不存在"):
        GitLinkAttachmentClient("secret-token").list_releases(GitLinkRepository())


def test_attachment_delete_accepts_empty_success_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 204

        @staticmethod
        def read(_limit: int) -> bytes:
            return b""

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.request_args = None

        def request(self, *args, **kwargs) -> None: self.request_args = (args, kwargs)
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    GitLinkAttachmentClient("secret-token").delete_attachment("attachment-123")

    args, kwargs = Connection.instance.request_args
    assert args[:2] == ("DELETE", "/api/attachments/attachment-123.json")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


def test_attachment_head_matches_uploaded_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        @staticmethod
        def getheader(name: str, default: str = "") -> str:
            return 'attachment; filename="dlc001.zip"' if name == "Content-Disposition" else default

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.request_args = None

        def request(self, *args, **kwargs) -> None: self.request_args = (args, kwargs)
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    assert GitLinkAttachmentClient("secret-token").attachment_matches("attachment-123", "dlc001.zip") is True
    args, kwargs = Connection.instance.request_args
    assert args[:2] == ("HEAD", "/api/attachments/attachment-123.json")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


def test_publisher_settings_loads_private_config(tmp_path: Path) -> None:
    path = tmp_path / "publisher.local.json"
    path.write_text(
        json.dumps({"gitlink": {"owner": "owner", "repository": "assets", "token": "local-secret"}}),
        encoding="utf-8",
    )

    settings = PublisherSettings.load(path)

    assert settings == PublisherSettings("owner", "assets", "local-secret")


def test_settings_path_honors_environment_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "private.json"
    monkeypatch.setenv("SIGNRIVER_PUBLISHER_CONFIG", str(path))

    assert discover_settings_path() == path.resolve()


def test_parse_remote_release_assets() -> None:
    payload = {"releases": [{"id": 9, "version_id": 2318, "tag_name": "stellaris", "name": "Stellaris", "body": "body", "attachments": [{"id": 1, "title": "a.zip", "filesize": "1 MB", "url": "/a"}]}]}

    release = parse_release(payload, "stellaris")

    assert release is not None
    assert release.release_id == "2318"
    assert [(item.asset_id, item.name, item.display_size) for item in release.assets] == [("1", "a.zip", "1 MB")]


def test_manual_remote_dlc_can_be_adopted_and_reused_without_upload(
    tmp_path: Path,
) -> None:
    dlc = tmp_path / "dlc012_expansion1.zip"
    dlc.write_bytes(b"x" * 1024 * 1024)
    asset = PublishAsset(dlc, dlc.name, dlc.stat().st_size, "a" * 64)

    class Client:
        updated_ids: list[str] = []

        def list_releases(self, _repo):
            return {
                "releases": [{
                    "id": 9,
                    "tag_name": "civilization_6",
                    "name": "Civilization VI",
                    "attachments": [{
                        "id": 42,
                        "title": dlc.name,
                        "filesize": "1 MB",
                    }],
                }]
            }

        def upload(self, _path):
            raise AssertionError("adopted DLC must not be uploaded again")

        def update_release(self, _repo, **kwargs):
            self.updated_ids = kwargs["attachment_ids"]

        def delete_attachment(self, _value):
            raise AssertionError("adoption must not delete remote files")

    client = Client()
    manager = RemoteResourceManager(client, GitLinkRepository())
    profile = GameProfile.create("civilization_6", "Civilization VI", "289070")

    adoption = manager.adopt_matching_release_assets(profile, (asset,), {})
    sync = manager.sync_release(profile, (asset,), adoption.state)

    assert adoption.adopted == (dlc.name,)
    assert adoption.skipped == ()
    assert sync.uploaded == 0
    assert sync.reused == 1
    assert client.updated_ids == ["42"]


def test_manual_remote_adoption_skips_mismatched_size(tmp_path: Path) -> None:
    dlc = tmp_path / "dlc012_expansion1.zip"
    dlc.write_bytes(b"x" * 1024 * 1024)
    asset = PublishAsset(dlc, dlc.name, dlc.stat().st_size, "a" * 64)

    class Client:
        def list_releases(self, _repo):
            return {
                "releases": [{
                    "id": 9,
                    "tag_name": "civilization_6",
                    "attachments": [{
                        "id": 42,
                        "title": dlc.name,
                        "filesize": "2 MB",
                    }],
                }]
            }

    result = RemoteResourceManager(
        Client(), GitLinkRepository()
    ).adopt_matching_release_assets(
        GameProfile.create("civilization_6", "Civilization VI", "289070"),
        (asset,),
        {},
    )

    assert result.adopted == ()
    assert result.skipped == (
        f"{dlc.name}：远程大小 2 MB 与本地不符",
    )


def test_remote_upload_replaces_same_name_and_keeps_other_assets(tmp_path: Path) -> None:
    source = tmp_path / "same.zip"
    source.write_bytes(b"new")

    class Client:
        deleted: list[str] = []
        updated_ids: list[str] = []

        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "body": "body", "attachments": [{"id": "old", "title": "same.zip"}, {"id": "keep", "title": "other.zip"}]}]}
        def upload(self, _path): return "new"
        def update_release(self, _repo, **kwargs): self.updated_ids = kwargs["attachment_ids"]
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    result = RemoteResourceManager(client, GitLinkRepository()).upload_file(GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990"), source)

    assert result.action == "替换"
    assert client.updated_ids == ["keep", "new"]
    assert client.deleted == ["old"]


def test_remote_delete_can_remove_last_release_asset() -> None:
    class Client:
        deleted: list[str] = []
        exists = True

        def list_releases(self, _repo):
            attachments = [{"id": "only", "title": "only.zip"}] if self.exists else []
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "attachments": attachments}]}
        def delete_attachment(self, value):
            self.deleted.append(value)
            self.exists = False

    client = Client()
    result = RemoteResourceManager(client, GitLinkRepository()).delete_asset(
        GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990"),
        "only",
        "upload-uuid",
    )

    assert result.action == "删除"
    assert client.deleted == ["upload-uuid"]


def test_remote_delete_rejects_false_success_when_asset_remains() -> None:
    class Client:
        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "attachments": [{"id": "7", "title": "same.zip"}]}]}
        def delete_attachment(self, _value): pass

    with pytest.raises(GitLinkError, match="附件仍然存在"):
        RemoteResourceManager(Client(), GitLinkRepository()).delete_asset(
            GameProfile.create("stellaris", "Stellaris", "281990"),
            "7",
            "upload-uuid",
        )


def test_remote_delete_all_reports_deleted_and_unmanaged_assets() -> None:
    class Client:
        def __init__(self) -> None:
            self.deleted = False
        def list_releases(self, _repo):
            attachments = [{"id": "2", "title": "manual.zip"}]
            if not self.deleted:
                attachments.insert(0, {"id": "1", "title": "managed.zip"})
            return {"releases": [{"id": 9, "tag_name": "stellaris", "attachments": attachments}]}
        def delete_attachment(self, value):
            assert value == "managed-uuid"
            self.deleted = True

    result = RemoteResourceManager(Client(), GitLinkRepository()).delete_all_assets(
        GameProfile.create("stellaris", "Stellaris", "281990"),
        {"managed.zip": "managed-uuid", "manual.zip": ""},
    )

    assert [asset.name for asset in result.deleted] == ["managed.zip"]
    assert result.failures == ("manual.zip：缺少可删除的上传 UUID",)


def test_remote_upload_cleans_new_attachment_if_release_update_fails(tmp_path: Path) -> None:
    source = tmp_path / "new.zip"
    source.write_bytes(b"new")

    class Client:
        deleted: list[str] = []

        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "attachments": []}]}
        def upload(self, _path): return "orphan"
        def update_release(self, _repo, **_kwargs): raise GitLinkError("update failed")
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    with pytest.raises(GitLinkError, match="update failed"):
        RemoteResourceManager(client, GitLinkRepository()).upload_file(GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990"), source)

    assert client.deleted == ["orphan"]


def test_release_sync_reuses_unchanged_asset_but_always_replaces_appinfo(tmp_path: Path) -> None:
    dlc = tmp_path / "dlc001.zip"
    appinfo = tmp_path / "stellaris_appinfo.json"
    dlc.write_bytes(b"dlc")
    appinfo.write_bytes(b"appinfo")
    assets = (
        PublishAsset(dlc, dlc.name, dlc.stat().st_size, "a" * 64),
        PublishAsset(appinfo, appinfo.name, appinfo.stat().st_size, "b" * 64),
    )

    class Client:
        def __init__(self) -> None:
            self.attachments: list[dict[str, object]] = []
            self.names_by_id: dict[str, str] = {}
            self.deleted: list[str] = []
            self.counter = 0

        def list_releases(self, _repo):
            if not self.attachments:
                return {"releases": []}
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "attachments": self.attachments}]}
        def upload(self, path):
            self.counter += 1
            value = f"attachment-{self.counter}"
            self.names_by_id[value] = path.name
            return value
        def create_release(self, _repo, **kwargs):
            self.attachments = [{"id": value, "title": self.names_by_id[value]} for value in kwargs["attachment_ids"]]
        def update_release(self, _repo, **kwargs):
            old_names = {str(item["id"]): str(item["title"]) for item in self.attachments}
            self.attachments = [{"id": value, "title": self.names_by_id.get(value) or old_names[value]} for value in kwargs["attachment_ids"]]
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    manager = RemoteResourceManager(client, GitLinkRepository())
    profile = GameProfile.create("stellaris", "Stellaris", "281990")

    first = manager.sync_release(profile, assets, {}, force_upload=frozenset({profile.appinfo_name}))
    second = manager.sync_release(profile, assets, first.state, force_upload=frozenset({profile.appinfo_name}))

    assert (first.uploaded, first.reused, first.removed) == (2, 0, 0)
    assert (second.uploaded, second.reused, second.removed) == (1, 1, 1)
    assert client.deleted == ["attachment-2"]
    assert [item["id"] for item in client.attachments] == ["attachment-1", "attachment-3"]


def test_release_sync_rolls_back_new_uploads_when_update_fails(tmp_path: Path) -> None:
    appinfo = tmp_path / "stellaris_appinfo.json"
    appinfo.write_bytes(b"new")
    asset = PublishAsset(appinfo, appinfo.name, appinfo.stat().st_size, "c" * 64)

    class Client:
        deleted: list[str] = []

        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "attachments": [{"id": "old", "title": "stellaris_appinfo.json"}]}]}
        def upload(self, _path): return "new"
        def update_release(self, _repo, **_kwargs): raise GitLinkError("update failed")
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    with pytest.raises(GitLinkError, match="update failed"):
        RemoteResourceManager(client, GitLinkRepository()).sync_release(
            GameProfile.create("stellaris", "Stellaris", "281990"),
            (asset,),
            {},
            force_upload=frozenset({asset.name}),
        )

    assert client.deleted == ["new"]


def test_release_sync_checkpoints_each_confirmed_file_before_later_failure(tmp_path: Path) -> None:
    first_path = tmp_path / "dlc001_first.zip"
    second_path = tmp_path / "dlc002_second.zip"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    assets = (
        PublishAsset(first_path, first_path.name, first_path.stat().st_size, "a" * 64),
        PublishAsset(second_path, second_path.name, second_path.stat().st_size, "b" * 64),
    )

    class Client:
        def __init__(self) -> None:
            self.updated_ids: list[list[str]] = []

        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "attachments": []}]}

        def upload(self, path, *, progress=None, control=None):
            if path.name == second_path.name:
                raise GitLinkError("second upload failed")
            if progress:
                progress(path.stat().st_size, path.stat().st_size)
            return "first-upload-id"

        def update_release(self, _repo, **kwargs):
            self.updated_ids.append(list(kwargs["attachment_ids"]))

        def delete_attachment(self, _value):
            raise AssertionError("confirmed first attachment must not be rolled back")

    checkpoints: list[dict[str, object]] = []
    client = Client()
    with pytest.raises(GitLinkError, match="second upload failed"):
        RemoteResourceManager(client, GitLinkRepository()).sync_release(
            GameProfile.create("stellaris", "Stellaris", "281990"),
            assets,
            {},
            upload_progress=lambda *_args: None,
            upload_control=UploadControl(),
            checkpoint=checkpoints.append,
        )

    assert client.updated_ids == [["first-upload-id"]]
    assert checkpoints[-1]["assets"][first_path.name]["attachment_id"] == "first-upload-id"
    assert second_path.name not in checkpoints[-1]["assets"]


def test_release_sync_recovers_existing_orphan_attachments_from_local_state(tmp_path: Path) -> None:
    dlc = tmp_path / "dlc001.zip"
    appinfo = tmp_path / "stellaris_appinfo.json"
    dlc.write_bytes(b"dlc")
    appinfo.write_bytes(b"appinfo")
    assets = (
        PublishAsset(dlc, dlc.name, dlc.stat().st_size, "a" * 64),
        PublishAsset(appinfo, appinfo.name, appinfo.stat().st_size, "b" * 64),
    )
    previous = {
        "assets": {
            dlc.name: {"sha256": "a" * 64, "size_bytes": dlc.stat().st_size, "attachment_id": "old-dlc"},
            appinfo.name: {"sha256": "b" * 64, "size_bytes": appinfo.stat().st_size, "attachment_id": "old-appinfo"},
        }
    }

    class Client:
        deleted: list[str] = []
        updated_release_id = ""
        updated_ids: list[str] = []

        def list_releases(self, _repo):
            return {"releases": [{"id": 99, "version_id": 2318, "tag_name": "stellaris", "name": "Stellaris", "attachments": []}]}
        def attachment_matches(self, attachment_id, name): return attachment_id == "old-dlc" and name == "dlc001.zip"
        def upload(self, _path): return "new-appinfo"
        def update_release(self, _repo, **kwargs):
            self.updated_release_id = kwargs["release_id"]
            self.updated_ids = kwargs["attachment_ids"]
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    result = RemoteResourceManager(client, GitLinkRepository()).sync_release(
        GameProfile.create("stellaris", "Stellaris", "281990"),
        assets,
        previous,
        force_upload=frozenset({appinfo.name}),
    )

    assert (result.uploaded, result.reused) == (1, 1)
    assert client.updated_release_id == "2318"
    assert client.updated_ids == ["old-dlc", "new-appinfo"]
    assert client.deleted == ["old-appinfo"]


def test_release_sync_maps_numeric_release_ids_to_upload_uuids_by_filename(tmp_path: Path) -> None:
    dlc = tmp_path / "dlc001.zip"
    appinfo = tmp_path / "stellaris_appinfo.json"
    dlc.write_bytes(b"dlc")
    appinfo.write_bytes(b"appinfo")
    assets = (
        PublishAsset(dlc, dlc.name, dlc.stat().st_size, "a" * 64),
        PublishAsset(appinfo, appinfo.name, appinfo.stat().st_size, "b" * 64),
    )
    previous = {
        "assets": {
            dlc.name: {"sha256": "a" * 64, "size_bytes": dlc.stat().st_size, "attachment_id": "dlc-upload-uuid"},
            appinfo.name: {"sha256": "b" * 64, "size_bytes": appinfo.stat().st_size, "attachment_id": "appinfo-upload-uuid"},
        }
    }

    class Client:
        deleted: list[str] = []
        updated_ids: list[str] = []

        def list_releases(self, _repo):
            return {
                "releases": [{
                    "id": 99,
                    "version_id": 2318,
                    "tag_name": "stellaris",
                    "name": "Stellaris",
                    "attachments": [
                        {"id": 485806, "title": dlc.name},
                        {"id": 485807, "title": appinfo.name},
                    ],
                }]
            }
        def attachment_matches(self, *_args): raise AssertionError("filename mapping should avoid HEAD recovery")
        def upload(self, path):
            assert path.name == appinfo.name
            return "new-appinfo-uuid"
        def update_release(self, _repo, **kwargs): self.updated_ids = kwargs["attachment_ids"]
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    result = RemoteResourceManager(client, GitLinkRepository()).sync_release(
        GameProfile.create("stellaris", "Stellaris", "281990"),
        assets,
        previous,
        force_upload=frozenset({appinfo.name}),
    )

    assert (result.uploaded, result.reused, result.removed) == (1, 1, 1)
    assert result.warnings == ()
    assert client.updated_ids == ["485806", "new-appinfo-uuid"]
    assert client.deleted == ["appinfo-upload-uuid"]
    assert result.state["assets"][dlc.name]["attachment_id"] == "dlc-upload-uuid"


def test_remote_numeric_asset_cleanup_is_skipped_after_release_detach() -> None:
    class Client:
        def delete_attachment(self, _value): raise AssertionError("numeric release ID must not be deleted as an attachment UUID")

    manager = RemoteResourceManager(Client(), GitLinkRepository())

    assert manager._cleanup_assets((RemoteAsset("485806", "dlc001.zip", "", ""),)) == ()


def test_publish_state_is_scoped_to_repository_and_release(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = workspace.initialize()
    state = {"version": 1, "owner": "signriver", "repository": "assets", "release_tag": "stellaris", "assets": {}}

    workspace.save_publish_state(profile, state)

    assert workspace.load_publish_state(profile, "signriver", "assets") == state
    assert workspace.load_publish_state(profile, "signriver", "other") == {}
