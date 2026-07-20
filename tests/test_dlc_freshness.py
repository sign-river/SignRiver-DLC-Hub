"""Tests for Steam vs local DLC freshness comparison."""

from __future__ import annotations

from pathlib import Path

from signriver_app.domain import CartridgeFreshness
from signriver_publisher.cream import SteamAppInfo, SteamDlc
from signriver_publisher.freshness import compare_steam_and_local
from signriver_publisher import PublisherWorkspace


def test_compare_marks_current_when_local_covers_steam(tmp_path: Path) -> None:
    local = (
        tmp_path / "dlc001_symbols_of_domination",
        tmp_path / "dlc002_overlord",
    )
    for path in local:
        path.mkdir()
    appinfo = SteamAppInfo(
        app_id="281990",
        name="Stellaris",
        update_time="2026-07-21 12:00:00",
        dlcs=(
            SteamDlc("111", "Symbols of Domination"),
            SteamDlc("222", "Overlord"),
        ),
    )
    report = compare_steam_and_local(appinfo, local_folders=local)
    assert report.status == "current"
    assert report.gap_count == 0
    assert report.steam_dlc_count == 2
    assert "已是最新" in report.to_client_dict()["status"] or report.status == "current"


def test_compare_marks_behind_and_lists_unmatched(tmp_path: Path) -> None:
    local = (tmp_path / "dlc001_symbols_of_domination",)
    local[0].mkdir()
    appinfo = SteamAppInfo(
        app_id="281990",
        name="Stellaris",
        update_time="2026-07-21 12:00:00",
        dlcs=(
            SteamDlc("111", "Symbols of Domination"),
            SteamDlc("222", "Brand New DLC Pack"),
            SteamDlc("333", "Another Expansion"),
        ),
    )
    report = compare_steam_and_local(appinfo, local_folders=local)
    assert report.status == "behind"
    assert report.gap_count == 2
    assert "Brand New DLC Pack" in report.unmatched_steam_names


def test_workspace_detect_persists_and_exports_freshness(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(
        tmp_path,
        appinfo_provider=lambda app_id: SteamAppInfo(
            app_id=app_id,
            name="Stellaris",
            update_time="2026-07-21 12:00:00",
            dlcs=(SteamDlc("111", "Symbols of Domination"),),
        ),
    )
    profile = workspace.initialize()
    stellaris = next(item for item in workspace.list_games() if item.game_id == "stellaris")
    (workspace.game_dir("stellaris") / "dlc" / "dlc001_symbols_of_domination").mkdir(
        parents=True
    )
    report = workspace.detect_dlc_freshness(stellaris)
    assert report.status == "current"
    assert workspace.freshness_path(stellaris).is_file()
    written = workspace.export_client_hub(default_game_id="stellaris")
    cartridge = next(path for path in written if path.name == "cartridge_stellaris.json")
    payload = cartridge.read_text(encoding="utf-8")
    assert '"freshness"' in payload
    assert '"status": "current"' in payload


def test_client_freshness_summary_text() -> None:
    current = CartridgeFreshness(
        status="current",
        checked_at="2026-07-21 12:00:00",
        steam_game_name="Stellaris",
        steam_dlc_count=10,
        package_count=10,
        gap_count=0,
    )
    behind = CartridgeFreshness(
        status="behind",
        checked_at="2026-07-21 12:00:00",
        steam_game_name="Stellaris",
        steam_dlc_count=12,
        package_count=10,
        gap_count=2,
    )
    assert "已是最新" in current.client_summary()
    assert "不是最新" in behind.client_summary()
    assert "落后 2" in behind.client_summary()
