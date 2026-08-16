from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tools import collect_steam_api64 as collector


def _write_manifest(library: Path, app_id: str, name: str, install_dir: str) -> None:
    steamapps = library / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{app_id}.acf").write_text(
        f'''"AppState"
{{
    "appid" "{app_id}"
    "name" "{name}"
    "installdir" "{install_dir}"
}}''',
        encoding="utf-8",
    )


def test_main_collects_all_dlls_preserves_relative_paths_and_creates_zip(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    library = tmp_path / "SteamLibrary"
    first = library / "steamapps" / "common" / "First Game"
    second = library / "steamapps" / "common" / "Second Game"
    (first / "bin" / "win64").mkdir(parents=True)
    (first / "plugins").mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "bin" / "win64" / "steam_api64.dll").write_bytes(b"first")
    (first / "plugins" / "STEAM_API64.DLL").write_bytes(b"second")
    (first / "steam_api.dll").write_bytes(b"not-64-bit")
    (second / "readme.txt").write_text("no dll", encoding="utf-8")
    _write_manifest(library, "100", "First: Game", "First Game")
    _write_manifest(library, "200", "Second Game", "Second Game")
    output = tmp_path / "output"

    def fail_if_rescanned(*_args, **_kwargs):
        raise AssertionError("融合流程不应为了收集 DLL 再次扫描游戏目录")

    monkeypatch.setattr(collector, "_find_game_dlls", fail_if_rescanned)
    result = collector.main(
        ["--library", str(library), "--out", str(output), "--no-pause"]
    )

    assert result == 0
    console = capsys.readouterr().out
    assert "以下 1 个游戏未找到 steam_api64.dll" in console
    assert "Second Game（AppID 200）" in console
    assert str(second) in console
    collected_dirs = [
        path for path in output.glob(f"{collector.OUTPUT_PREFIX}_*") if path.is_dir()
    ]
    assert len(collected_dirs) == 1
    collected = collected_dirs[0]
    game_dir = collected / "First_ Game"
    assert (game_dir / "bin" / "win64" / "steam_api64.dll").read_bytes() == b"first"
    assert (game_dir / "plugins" / "steam_api64.dll").read_bytes() == b"second"
    assert not (game_dir / "steam_api.dll").exists()
    assert not (collected / "Second Game").exists()

    report_txt = list(collected.glob("Steam游戏路径诊断报告_*.txt"))
    report_json = list(collected.glob("Steam游戏路径诊断报告_*.json"))
    assert len(report_txt) == 1
    assert len(report_json) == 1
    directory_report = json.loads(report_json[0].read_text(encoding="utf-8"))
    assert directory_report["game_count"] == 2
    assert directory_report["games"][0]["name"] == "First: Game"

    manifest = json.loads((collected / "收集清单.json").read_text(encoding="utf-8"))
    assert manifest["copied_dll_count"] == 2
    assert manifest["game_count_with_dll"] == 1
    assert manifest["games_without_steam_api64_dll"][0]["app_id"] == "200"

    archive = collected.with_suffix(".zip")
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zipped:
        names = set(zipped.namelist())
    prefix = f"{collected.name}/First_ Game"
    assert f"{prefix}/bin/win64/steam_api64.dll" in names
    assert f"{prefix}/plugins/steam_api64.dll" in names
    assert f"{collected.name}/收集清单.json" in names
    assert any(
        name.startswith(f"{collected.name}/Steam游戏路径诊断报告_")
        and name.endswith(".txt")
        for name in names
    )
    assert any(
        name.startswith(f"{collected.name}/Steam游戏路径诊断报告_")
        and name.endswith(".json")
        for name in names
    )


def test_collect_dlls_uses_unique_safe_game_folder_names(tmp_path: Path) -> None:
    games: list[collector.SteamGame] = []
    for app_id, install_dir in (("10", "One"), ("20", "Two")):
        root = tmp_path / install_dir
        root.mkdir()
        (root / "steam_api64.dll").write_bytes(app_id.encode())
        games.append(
            collector.SteamGame(
                app_id=app_id,
                name="Same/Game",
                install_dir=install_dir,
                root=root,
                library_root=tmp_path,
                manifest_path=tmp_path / f"appmanifest_{app_id}.acf",
            )
        )

    output = tmp_path / "collected"
    records, issues, missing = collector.collect_dlls(games, output)

    assert issues == []
    assert missing == []
    assert len(records) == 2
    assert (output / "Same_Game" / "steam_api64.dll").read_bytes() == b"10"
    assert (
        output / "Same_Game (AppID 20)" / "steam_api64.dll"
    ).read_bytes() == b"20"


def test_main_returns_error_without_any_steam_api64_dll(tmp_path: Path) -> None:
    library = tmp_path / "SteamLibrary"
    game = library / "steamapps" / "common" / "No DLL"
    game.mkdir(parents=True)
    (game / "game.exe").write_bytes(b"exe")
    _write_manifest(library, "300", "No DLL", "No DLL")
    output = tmp_path / "output"

    result = collector.main(
        ["--library", str(library), "--out", str(output), "--no-pause"]
    )

    assert result == 1
    assert not list(output.glob(f"{collector.OUTPUT_PREFIX}_*"))
    assert not list(output.glob("*.zip"))
