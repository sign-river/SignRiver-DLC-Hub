from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_publisher.announcements import (
    AnnouncementDraft,
    AnnouncementValidationError,
)
from signriver_publisher.workspace import PublisherWorkspace


def test_enabled_announcement_is_exported_with_hub(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    draft = AnnouncementDraft(
        announcement_id="2026-07-23-release",
        title="版本公告",
        updated_at="2026-07-23",
        body="本次更新已完成。",
        enabled=True,
    )

    workspace.save_announcement_draft(draft)
    assets = workspace.export_client_hub(default_game_id="stellaris")

    assert workspace.load_announcement_draft() == draft
    assert workspace.announcement_status() == "已启用：版本公告"
    assert (workspace.announcement_path).is_file()
    assert (workspace.announcement_draft_path).is_file()
    assert "announcement.json" in {path.name for path in assets}
    exported = json.loads(
        (workspace.output_dir / "hub" / "announcement.json").read_text(
            encoding="utf-8"
        )
    )
    assert exported == draft.to_announcement_dict()
    assert "enabled" not in exported


def test_disabling_announcement_keeps_draft_and_removes_published_source(
    tmp_path: Path,
) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()
    enabled = AnnouncementDraft(
        announcement_id="notice-1",
        title="测试公告",
        updated_at="2026-07-23",
        body="正文",
        enabled=True,
    )
    workspace.save_announcement_draft(enabled)
    workspace.export_client_hub()

    disabled = AnnouncementDraft(
        announcement_id=enabled.announcement_id,
        title=enabled.title,
        updated_at=enabled.updated_at,
        body=enabled.body,
        enabled=False,
    )
    workspace.save_announcement_draft(disabled)
    assets = workspace.export_client_hub()

    assert not workspace.announcement_path.exists()
    assert workspace.announcement_draft_path.is_file()
    assert workspace.load_announcement_draft() == disabled
    assert workspace.announcement_status() == "草稿已停用"
    assert "announcement.json" not in {path.name for path in assets}
    assert not (workspace.output_dir / "hub" / "announcement.json").exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("announcement_id", "含空格的 ID", "公告版本 ID"),
        ("title", "", "公告标题"),
        ("body", "", "公告正文"),
        ("updated_at", "2026/07/23", "YYYY-MM-DD"),
    ],
)
def test_enabled_announcement_validation(
    field: str, value: str, message: str
) -> None:
    values = {
        "announcement_id": "notice-1",
        "title": "标题",
        "updated_at": "2026-07-23",
        "body": "正文",
        "enabled": True,
    }
    values[field] = value

    with pytest.raises(AnnouncementValidationError, match=message):
        AnnouncementDraft(**values).validate()


def test_disabled_incomplete_announcement_can_be_saved_as_draft(
    tmp_path: Path,
) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    workspace.initialize()

    workspace.save_announcement_draft(AnnouncementDraft(enabled=False))

    payload = json.loads(
        workspace.announcement_draft_path.read_text(encoding="utf-8")
    )
    assert payload["enabled"] is False
    assert not workspace.announcement_path.exists()
