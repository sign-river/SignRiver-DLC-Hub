"""Tests for local resource timestamp freshness (no Steam comparison)."""

from __future__ import annotations

from pathlib import Path

from signriver_app.domain import CartridgeFreshness
from signriver_publisher.cream import SteamAppInfo, SteamDlc
from signriver_publisher.freshness import build_resource_freshness
from signriver_publisher import PublisherWorkspace


def test_build_resource_freshness_uses_newest_mtime(tmp_path: Path) -> None:
    older = tmp_path / "dlc001_symbols_of_domination"
    newer = tmp_path / "dlc002_overlord"
    older.mkdir()
    newer.mkdir()
    report = build_resource_freshness(local_folders=(older, newer))
    assert report.package_count == 2
    assert report.resources_updated_at
    assert "资源提交于" in report.summary
    assert "不少于" not in report.summary


def test_workspace_refresh_persists_and_exports_stamp(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(
        tmp_path,
        appinfo_provider=lambda app_id: SteamAppInfo(
            app_id=app_id,
            name="Stellaris",
            update_time="2026-07-21 12:00:00",
            dlcs=(SteamDlc("111", "Symbols of Domination"),),
        ),
    )
    workspace.initialize()
    stellaris = next(item for item in workspace.list_games() if item.game_id == "stellaris")
    (workspace.game_dir("stellaris") / "dlc" / "dlc001_symbols_of_domination").mkdir(
        parents=True
    )
    report = workspace.refresh_resource_freshness(stellaris)
    assert report.package_count == 1
    assert report.resources_updated_at
    assert workspace.freshness_path(stellaris).is_file()
    written = workspace.export_client_hub(default_game_id="stellaris")
    cartridge = next(path for path in written if path.name == "cartridge_stellaris.json")
    payload = cartridge.read_text(encoding="utf-8")
    assert '"freshness"' in payload
    assert '"resources_updated_at"' in payload
    assert '"status"' not in payload.split('"freshness"', 1)[1][:200]


def test_client_freshness_summary_text() -> None:
    stamp = CartridgeFreshness(
        resources_updated_at="2026-07-21 12:00:00",
        package_count=12,
    )
    empty = CartridgeFreshness(resources_updated_at="", package_count=0)
    assert "资源提交于 2026-07-21 12:00:00" in stamp.client_summary()
    assert "收录 12 个包" in stamp.client_summary()
    assert "未知" in empty.client_summary()
