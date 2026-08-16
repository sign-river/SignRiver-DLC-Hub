from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "steam_directory_probe.py"
SPEC = importlib.util.spec_from_file_location("steam_directory_probe", SCRIPT)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _write_manifest(library: Path, app_id: str, name: str, install_dir: str) -> None:
    steamapps = library / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{app_id}.acf").write_text(
        f'''"AppState"
{{
    "appid" "{app_id}"
    "name" "{name}"
    "installdir" "{install_dir}"
    "buildid" "12345"
}}''',
        encoding="utf-8",
    )


def test_discovers_all_manifest_games_and_scans_complete_tree(tmp_path: Path) -> None:
    library = tmp_path / "SteamLibrary"
    first = library / "steamapps" / "common" / "First Game"
    second = library / "steamapps" / "common" / "Second Game"
    (first / "Content" / "DLC").mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "game.exe").write_bytes(b"1234")
    (first / "Content" / "DLC" / "pack.bin").write_bytes(b"abcdef")
    (first / "Content" / "DLC" / "steam_api64.dll").write_bytes(b"steam")
    (second / "readme.txt").write_text("hello", encoding="utf-8")
    _write_manifest(library, "100", "First Game", "First Game")
    _write_manifest(library, "200", "Second Game", "Second Game")

    games, issues = probe.discover_games((library,))

    assert issues == []
    assert [(game.app_id, game.name) for game in games] == [
        ("100", "First Game"),
        ("200", "Second Game"),
    ]
    index, scan_issues = probe._scan_tree(first)
    assert scan_issues == []
    assert index["scanned_directory_count"] == 2
    assert index["scanned_file_count"] == 3
    assert index["total_file_bytes"] == 15
    assert index["dlc_directories"] == [
        {
            "path": "Content",
            "reason": "常见内容目录名",
            "child_directories": ["Content/DLC"],
        },
        {
            "path": "Content/DLC",
            "reason": "名称包含 DLC",
            "child_directories": [],
        },
    ]
    assert index["dlc_root_candidates"] == [
        {
            "path": "Content",
            "reasons": ["命中路径的直接父目录", "命中路径的顶层祖先"],
            "evidence_paths": ["Content/DLC"],
            "projected_paths": [],
        }
    ]
    assert index["patch_files"] == [
        {"path": "Content/DLC/steam_api64.dll", "size_bytes": 5}
    ]
    assert index["executables"] == [{"path": "game.exe", "size_bytes": 4}]
    serialized = str(index)
    assert "pack.bin" not in serialized


def test_discovers_secondary_library_from_vdf(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    secondary = tmp_path / "Games"
    (steam_root / "steamapps").mkdir(parents=True)
    (secondary / "steamapps").mkdir(parents=True)
    escaped = str(secondary).replace("\\", "\\\\")
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        f'''"libraryfolders"
{{
    "0" {{ "path" "{steam_root}" }}
    "1" {{ "path" "{escaped}" }}
}}''',
        encoding="utf-8",
    )

    libraries, issues = probe.discover_library_roots((steam_root,))

    assert issues == []
    assert libraries == (steam_root.resolve(), secondary.resolve())


def test_game_filter_matches_name_folder_and_app_id(tmp_path: Path) -> None:
    game = probe.SteamGame(
        app_id="949230",
        name="Cities: Skylines II",
        install_dir="Cities Skylines II",
        root=tmp_path,
        library_root=tmp_path,
        manifest_path=tmp_path / "appmanifest_949230.acf",
    )

    assert probe._matches_game(game, [])
    assert probe._matches_game(game, ["skylines"])
    assert probe._matches_game(game, ["949230"])
    assert not probe._matches_game(game, ["stellaris"])

def test_keeps_nested_dlc_hit_and_infers_multiple_parent_root_candidates(
    tmp_path: Path,
) -> None:
    game = tmp_path / "Workers & Resources"
    nested = game / "media_soviet" / "sounds" / "dlc1"
    nested.mkdir(parents=True)
    (nested / "default.bank").write_bytes(b"sound")

    index, issues = probe._scan_tree(game)

    assert issues == []
    assert index["dlc_directories"] == [
        {
            "path": "media_soviet/sounds/dlc1",
            "reason": "名称包含 DLC",
            "child_directories": [],
        }
    ]
    assert index["dlc_root_candidates"] == [
        {
            "path": "media_soviet",
            "reasons": ["命中路径的顶层祖先"],
            "evidence_paths": ["media_soviet/sounds/dlc1"],
            "projected_paths": ["media_soviet/dlc1"],
        },
        {
            "path": "media_soviet/sounds",
            "reasons": ["命中路径的直接父目录"],
            "evidence_paths": ["media_soviet/sounds/dlc1"],
            "projected_paths": [],
        },
    ]

    report = {
        "generated_at": "2026-08-16T00:00:00+08:00",
        "libraries": [str(tmp_path)],
        "game_count": 1,
        "games": [
            {
                "app_id": "784150",
                "name": "Workers & Resources: Soviet Republic",
                "root": str(game),
                "build_id": None,
                **index,
                "scan_issues": [],
            }
        ],
        "discovery_issues": [],
    }
    rendered = probe._render_text(report)
    assert "[DIR] media_soviet/sounds/dlc1" in rendered
    assert "[ROOT?] media_soviet" in rendered
    assert "推测子路径（未验证存在）：media_soviet/dlc1" in rendered
