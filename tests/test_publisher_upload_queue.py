from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from signriver_publisher.release_models import ReleaseArtifact, ReleaseKind, ReleasePlan
from signriver_publisher.release_service import ReleaseService
from signriver_publisher.upload_queue import (
    ContentUploadQueue,
    UploadQueueError,
    UploadQueueStatus,
)
from signriver_publisher.build_queue import (
    BuildQueueStatus,
    ContentBuildQueue,
)


def _plan(game_id: str, *, batch_id: str = "batch") -> ReleasePlan:
    plan = ReleasePlan.create(
        ReleaseKind.GAME_CONTENT,
        {"game_id": game_id, "release_tag": f"{game_id}-v1"},
        batch_id=batch_id,
    )
    plan.artifacts = [
        ReleaseArtifact(role="content_attachment", filename="dlc.zip", size=100),
        ReleaseArtifact(role="catalog", filename="catalog.json", size=20),
    ]
    return plan


def test_queue_replaces_same_game_submission_in_its_original_position(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    first = queue.enqueue(_plan("game-a", batch_id="a"), display_name="游戏 A")
    second = queue.enqueue(_plan("game-b", batch_id="b"), display_name="游戏 B")

    assert [item.item_id for item in queue.list_items()] == [first.item_id, second.item_id]
    assert ContentUploadQueue(tmp_path).next_runnable().item_id == first.item_id
    replacement = queue.enqueue(_plan("game-a", batch_id="other"), display_name="游戏 A")

    assert replacement.item_id == first.item_id
    assert replacement.release_id == "other"
    assert [item.game_id for item in queue.list_items()] == ["game-a", "game-b"]


def test_queue_allows_requeue_after_completed_or_deleted_item(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    first = queue.enqueue(_plan("game-a", batch_id="a"), display_name="游戏 A")
    queue.mark_completed(first.item_id)

    second = queue.enqueue(_plan("game-a", batch_id="b"), display_name="游戏 A")
    assert second.status is UploadQueueStatus.QUEUED
    queue.remove(second.item_id)
    third = queue.enqueue(_plan("game-a", batch_id="c"), display_name="游戏 A")
    assert third.release_id == "c"


def test_running_upload_keeps_one_row_and_requeues_the_latest_submission(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    first = queue.enqueue(_plan("game-a", batch_id="old"), display_name="游戏 A")
    queue.mark_running(first.item_id)

    replacement = queue.enqueue(_plan("game-a", batch_id="new"), display_name="游戏 A")

    assert replacement.item_id == first.item_id
    assert replacement.status is UploadQueueStatus.RUNNING
    assert replacement.release_id == "new"
    assert len([item for item in queue.list_items() if item.game_id == "game-a"]) == 1
    assert queue.requeue_latest(first.item_id).status is UploadQueueStatus.QUEUED


def test_queue_progress_tracks_the_current_file_only(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    plan = _plan("game-a", batch_id="a")
    item = queue.enqueue(plan, display_name="游戏 A")
    plan.options["upload_progress"] = {
        "source": "github",
        "filename": "dlc.zip",
        "sent": 30,
        "total": 100,
        "bytes_per_second": 12.5,
    }

    updated = queue.sync_progress(item.item_id, plan)

    assert updated.current_file_bytes == 30
    assert updated.current_file_total_bytes == 100
    assert updated.current_file_index == 1
    assert updated.current_file_count == 2
    assert updated.current_source == "github"
    assert updated.bytes_per_second == 12.5


def test_running_item_must_be_paused_before_removal(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    item = queue.enqueue(_plan("game-a"), display_name="游戏 A")
    queue.mark_running(item.item_id)

    with pytest.raises(UploadQueueError, match="先暂停"):
        queue.remove(item.item_id)
    queue.mark_paused(item.item_id)
    assert queue.remove(item.item_id).item_id == item.item_id


def test_clear_removes_queue_records_but_refuses_running_upload(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    first = queue.enqueue(_plan("game-a", batch_id="a"), display_name="游戏 A")
    second = queue.enqueue(_plan("game-b", batch_id="b"), display_name="游戏 B")

    assert [item.item_id for item in queue.clear()] == [first.item_id, second.item_id]
    assert queue.list_items() == ()

    running = queue.enqueue(_plan("game-a"), display_name="游戏 A")
    queue.mark_running(running.item_id)
    with pytest.raises(UploadQueueError, match="先暂停"):
        queue.clear()


def test_queue_cannot_start_a_later_item_before_pending_predecessor(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    first = queue.enqueue(_plan("game-a", batch_id="a"), display_name="游戏 A")
    second = queue.enqueue(_plan("game-b", batch_id="b"), display_name="游戏 B")

    with pytest.raises(UploadQueueError, match="游戏 A"):
        queue.mark_running(second.item_id)

    queue.mark_running(first.item_id)
    queue.mark_failed(first.item_id, "网络临时错误")
    assert queue.mark_running(second.item_id).status is UploadQueueStatus.RUNNING


def test_queue_allows_later_game_when_previous_item_needs_rebuild(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    stale = queue.enqueue(_plan("game-a", batch_id="old"), display_name="过期游戏")
    ready = queue.enqueue(_plan("game-b", batch_id="ready"), display_name="已就绪游戏")

    queue.mark_needs_rebuild(stale.item_id, "旧发布记录与当前构建文件不一致")

    assert queue.mark_running(ready.item_id).status is UploadQueueStatus.RUNNING


def test_queue_recovers_interrupted_running_item_as_resumable_pause(tmp_path: Path) -> None:
    queue = ContentUploadQueue(tmp_path)
    item = queue.enqueue(_plan("game-a"), display_name="游戏 A")
    queue.mark_running(item.item_id)

    recovered = ContentUploadQueue(tmp_path).get(item.item_id)

    assert recovered.status is UploadQueueStatus.PAUSED
    assert "上次关闭" in str(recovered.error)


def test_build_queue_replaces_running_submission_and_keeps_one_game_row(tmp_path: Path) -> None:
    queue = ContentBuildQueue(tmp_path)
    first = queue.enqueue(SimpleNamespace(game_id="game-a", display_name="游戏 A"))
    queue.enqueue(SimpleNamespace(game_id="game-b", display_name="游戏 B"))

    assert queue.next_runnable().item_id == first.item_id
    queue.mark_running(first.item_id)
    replacement = queue.enqueue(SimpleNamespace(game_id="game-a", display_name="新游戏 A"))

    assert replacement.item_id == first.item_id
    assert replacement.status is BuildQueueStatus.RUNNING
    assert replacement.rerun_requested is True
    assert len([item for item in queue.list_items() if item.game_id == "game-a"]) == 1
    queued = queue.requeue_latest(first.item_id)
    assert queued.status is BuildQueueStatus.QUEUED
    assert ContentBuildQueue(tmp_path).next_runnable().item_id == first.item_id


def test_build_queue_allows_rebuild_after_completion(tmp_path: Path) -> None:
    queue = ContentBuildQueue(tmp_path)
    first = queue.enqueue(SimpleNamespace(game_id="game-a", display_name="游戏 A"))
    queue.mark_completed(first.item_id, resource_count=2, artifact_count=3, total_bytes=512)

    second = queue.enqueue(SimpleNamespace(game_id="game-a", display_name="游戏 A"))

    assert second.status is BuildQueueStatus.QUEUED


class _BaselineProvider:
    def __init__(self, assets: list[str]) -> None:
        self.assets = assets

    def read_baseline(self) -> dict[str, object]:
        return {"assets": [{"name": name} for name in self.assets]}


def test_release_service_persists_remote_mirror_preview(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    attachment = tmp_path / "dlc.zip"
    catalog = tmp_path / "catalog.json"
    attachment.write_bytes(b"dlc")
    catalog.write_text("{}", encoding="utf-8")
    plan = service.create_game_content_batch(
        game_id="game-a",
        release_tag="game-a-v1",
        attachments=[attachment],
        catalog=catalog,
        remote_targets={"gitlink": {}, "github": {}},
    )

    result = service.preview_game_content_mirror(
        plan.batch_id,
        {"gitlink": _BaselineProvider(["dlc.zip", "old.zip"]), "github": _BaselineProvider([])},
    )

    assert result.options["remote_mirror_preview"]["extra_files"] == {
        "gitlink": ["old.zip"], "github": []
    }
