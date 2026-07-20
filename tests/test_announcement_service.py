"""Tests for remote startup announcements."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_app.application import AnnouncementError, AnnouncementService
from signriver_app.domain import Announcement, ANNOUNCEMENT_ASSET_NAME


BOOTSTRAP = (
    Path(__file__).parents[1] / "config" / "announcement.json"
)


class _FakeAsset:
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.download_url = url


class _FakeRelease:
    def __init__(self, assets: list[_FakeAsset]) -> None:
        self.assets = assets


class _FakeSource:
    def __init__(self, release: _FakeRelease) -> None:
        self.release = release
        self.calls: list[str] = []

    def get_release_by_tag(self, tag: str):
        self.calls.append(tag)
        return self.release


def test_bootstrap_announcement_parses() -> None:
    payload = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    announcement = Announcement.from_dict(payload)
    assert announcement.announcement_id
    assert announcement.title
    assert "使用提示" in announcement.body


def test_service_prefers_remote_and_caches(tmp_path: Path) -> None:
    remote = {
        "schema_version": 1,
        "id": "remote-1",
        "title": "远程公告",
        "body": "来自 hub",
        "updated_at": "2026-07-21",
    }
    source = _FakeSource(
        _FakeRelease([_FakeAsset(ANNOUNCEMENT_ASSET_NAME, "https://example.test/a")])
    )

    def opener(url: str, timeout: float) -> bytes:
        assert url == "https://example.test/a"
        assert timeout == 15
        return json.dumps(remote).encode("utf-8")

    service = AnnouncementService(
        tmp_path / "cache",
        bootstrap_path=BOOTSTRAP,
        source=source,
        opener=opener,
    )
    announcement = service.refresh(allow_network=True)
    assert announcement.announcement_id == "remote-1"
    assert service.source_label == "remote"
    cached = json.loads(
        (tmp_path / "cache" / ANNOUNCEMENT_ASSET_NAME).read_text(encoding="utf-8")
    )
    assert cached["id"] == "remote-1"


def test_service_falls_back_to_bootstrap(tmp_path: Path) -> None:
    source = _FakeSource(_FakeRelease([]))

    def opener(url: str, timeout: float) -> bytes:
        raise AssertionError("network should not be used")

    service = AnnouncementService(
        tmp_path / "cache",
        bootstrap_path=BOOTSTRAP,
        source=source,
        opener=opener,
    )
    announcement = service.refresh(allow_network=False)
    assert announcement.announcement_id
    assert service.source_label == "bootstrap"


def test_service_requires_announcement_asset(tmp_path: Path) -> None:
    source = _FakeSource(_FakeRelease([]))
    service = AnnouncementService(
        tmp_path / "cache",
        bootstrap_path=None,
        source=source,
        opener=lambda url, timeout: b"{}",
    )
    with pytest.raises(AnnouncementError, match="缺少资源"):
        service.refresh(allow_network=True)


def test_should_display_respects_mute_until_id_changes() -> None:
    service = AnnouncementService(Path("unused"))
    announcement = Announcement(
        schema_version=1,
        announcement_id="notice-a",
        title="标题",
        body="正文",
    )
    assert service.should_display(
        announcement, mute_until_update=False, muted_id="notice-a"
    )
    assert not service.should_display(
        announcement, mute_until_update=True, muted_id="notice-a"
    )
    assert service.should_display(
        announcement, mute_until_update=True, muted_id="notice-old"
    )
