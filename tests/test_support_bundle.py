from __future__ import annotations


import json
from pathlib import Path
from types import SimpleNamespace

from signriver_app.infrastructure.diagnostics import (
    GAME_SUPPORT_PROFILES,
    GameSupportProfile,
    SupportBundleCollector,
    SupportPathSpec,
)
from signriver_app.infrastructure.diagnostics import support_bundle


def _use_home(monkeypatch, home: Path) -> None:
    monkeypatch.setattr(
        support_bundle.Path, "home", classmethod(lambda _cls: home)
    )


def test_support_collection_copies_redacted_files_and_skips_dumps(
    tmp_path: Path, monkeypatch
) -> None:
    app_root = tmp_path / "app"
    data_root = tmp_path / "data"
    home = tmp_path / "home"
    game_root = tmp_path / "game"
    log = data_root / "logs" / "launcher.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        f"root={app_root} token=launcher-secret https://example.test/log?id=private\n",
        encoding="utf-8",
    )
    (game_root / "system.log").parent.mkdir(parents=True)
    (game_root / "system.log").write_text("Authorization: game-secret\n", encoding="utf-8")
    paradox = home / "Documents" / "Paradox Interactive" / "Stellaris"
    (paradox / "logs").mkdir(parents=True)
    (paradox / "logs" / "error.log").write_text("password=game-secret\n", encoding="utf-8")
    (paradox / "settings.txt").write_text("setting=true\n", encoding="utf-8")
    (paradox / "crashes").mkdir()
    (paradox / "crashes" / "crash-report.txt").write_text(
        "crash token=crash-secret\n", encoding="utf-8"
    )
    dump = paradox / "crashes" / "crash.dmp"
    dump.write_bytes(b"binary dump")
    _use_home(monkeypatch, home)

    def run_dxdiag(command, **_kwargs):
        Path(command[-1]).write_text("Display Devices\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    collector = SupportBundleCollector(
        app_root,
        data_root,
        dxdiag_runner=run_dxdiag,
    )
    result = collector.collect(
        app_version="0.2.0",
        launcher_version="0.1.7",
        game_id="stellaris",
        game_root=game_root,
        problems=({"technical_details": "token=problem-secret"},),
        host_platform="windows",
    )

    assert result.output_dir.parent == data_root / "helper-tools" / "support-collections"
    assert result.output_dir.name.startswith("日志资料收集-")
    assert (result.output_dir / "系统-DxDiag.txt").is_file()
    assert (result.output_dir / "程序-runtime.json").is_file()
    assert (result.output_dir / "游戏-stellaris-system.log").is_file()
    assert (result.output_dir / "游戏-stellaris-error.log").is_file()
    assert (result.output_dir / "游戏-stellaris-settings.txt").is_file()
    assert (result.output_dir / "游戏-stellaris-crash-report.txt").is_file()
    assert not [path for path in result.output_dir.iterdir() if path.is_dir()]
    assert not list(result.output_dir.rglob("*.dmp"))
    assert result.skipped_dumps == (str(dump),)
    copied_log = (result.output_dir / "程序-launcher.log").read_text(encoding="utf-8")
    copied_game_log = (result.output_dir / "游戏-stellaris-system.log").read_text(encoding="utf-8")
    problems = json.loads((result.output_dir / "程序-problems.json").read_text(encoding="utf-8"))
    assert "launcher-secret" not in copied_log
    assert "id=private" not in copied_log
    assert str(app_root) not in copied_log
    assert "game-secret" not in copied_game_log
    assert "crash-secret" not in (result.output_dir / "游戏-stellaris-crash-report.txt").read_text(
        encoding="utf-8"
    )
    assert problems[0]["technical_details"] == "token=<REDACTED>"


def test_support_collection_records_dxdiag_failure_and_non_windows_skip(
    tmp_path: Path,
) -> None:
    collector = SupportBundleCollector(
        tmp_path / "app",
        tmp_path / "data",
        dxdiag_runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
        dxdiag_retry_delay=0,
    )
    failed = collector.collect(
        app_version="0.2.0",
        launcher_version="0.1.7",
        game_id=None,
        game_root=None,
        host_platform="windows",
    )
    assert any("dxdiag 返回 1" in item for item in failed.failed)
    assert any("未选择游戏" in item for item in failed.skipped)

    skipped = collector.collect(
        app_version="0.2.0",
        launcher_version="0.1.7",
        game_id=None,
        game_root=None,
        host_platform="linux",
    )
    assert "DxDiag.txt（当前平台不适用）" in skipped.skipped


def test_support_collection_retries_dxdiag_once_after_initial_failure(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []
    delays: list[float] = []

    def run_dxdiag(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            return SimpleNamespace(returncode=1)
        Path(command[-1]).write_text("Display Devices\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    collector = SupportBundleCollector(
        tmp_path / "app",
        tmp_path / "data",
        dxdiag_runner=run_dxdiag,
        sleep=delays.append,
        dxdiag_retry_delay=1.0,
    )
    result = collector.collect(
        app_version="0.2.0",
        launcher_version="0.1.7",
        game_id=None,
        game_root=None,
        host_platform="windows",
    )

    assert len(calls) == 2
    assert calls[0][-1] == calls[1][-1]
    assert delays == [1.0]
    assert "系统-DxDiag.txt" in result.copied
    assert not result.failed


def test_support_collection_keeps_output_contained_and_avoids_name_collisions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    game_root = tmp_path / "game"
    (game_root / "system.log").parent.mkdir(parents=True)
    (game_root / "system.log").write_text("root system\n", encoding="utf-8")
    (game_root / "logs").mkdir()
    (game_root / "logs" / "system.log").write_text("nested system\n", encoding="utf-8")
    profile = GameSupportProfile(
        "test_game",
        (SupportPathSpec("{game_root}/logs/system.log", "nested system log"),),
    )
    monkeypatch.setitem(GAME_SUPPORT_PROFILES, "test_game", profile)
    collector = SupportBundleCollector(tmp_path / "app", tmp_path / "data")

    result = collector.collect(
        app_version="0.2.0",
        launcher_version="0.1.7",
        game_id="test_game",
        game_root=game_root,
        host_platform="linux",
    )

    game_files = sorted(path.name for path in result.output_dir.iterdir() if path.is_file())
    assert game_files.count("游戏-test_game-system.log") == 1
    assert "游戏-test_game-system-2.log" in game_files
    assert all(
        path.resolve().is_relative_to(result.output_dir.resolve())
        for path in result.output_dir.rglob("*")
    )
    safe_target = collector._available_target(result.output_dir / "game", "../outside.log")
    assert safe_target.parent == result.output_dir / "game"
    assert safe_target.name == "outside.log"
    assert not (result.output_dir.parent / "outside.log").exists()
    assert SupportBundleCollector(tmp_path / "app", tmp_path / "data").latest_output_dir() == result.output_dir


def test_support_collection_keeps_going_when_a_registered_file_is_unreadable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    game_root = tmp_path / "game"
    readable = game_root / "system.log"
    unreadable = game_root / "error.log"
    game_root.mkdir()
    readable.write_text("safe\n", encoding="utf-8")
    unreadable.write_text("private\n", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def read_bytes_with_denial(path: Path) -> bytes:
        if path == unreadable:
            raise PermissionError("access denied")
        return original_read_bytes(path)

    monkeypatch.setattr(support_bundle.Path, "read_bytes", read_bytes_with_denial)
    collector = SupportBundleCollector(tmp_path / "app", tmp_path / "data")
    result = collector.collect(
        app_version="0.2.0",
        launcher_version="0.1.7",
        game_id="civilization_6",
        game_root=game_root,
        host_platform="linux",
    )

    assert (result.output_dir / "游戏-civilization_6-system.log").is_file()
    assert any("游戏-civilization_6-error.log" in item and "access denied" in item for item in result.failed)


def test_all_bootstrap_games_have_support_collection_profiles() -> None:
    root = Path(__file__).parents[1] / "config" / "cartridges"
    game_ids = {
        json.loads(path.read_text(encoding="utf-8"))["game_id"]
        for path in root.glob("cartridge_*.json")
    }
    assert game_ids == set(GAME_SUPPORT_PROFILES)


def test_support_collection_reports_background_stages(tmp_path: Path) -> None:
    progress: list[str] = []
    collector = SupportBundleCollector(tmp_path / "app", tmp_path / "data")

    collector.collect(
        app_version="0.2.0",
        launcher_version="0.1.2",
        game_id=None,
        game_root=None,
        host_platform="linux",
        progress=progress.append,
    )

    assert progress == [
        "已创建收集目录",
        "正在收集系统信息（DxDiag）",
        "系统信息收集完成",
        "正在收集程序运行日志和问题记录",
        "程序运行日志和问题记录收集完成",
        "正在收集当前游戏日志与配置",
        "当前游戏日志与配置收集完成",
        "正在汇总收集结果",
    ]
