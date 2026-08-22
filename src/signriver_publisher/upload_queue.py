"""Persistent FIFO queue for game-content uploads.

The publisher used to expose ``ReleasePlan`` directly as a UI concept.  Plans
are still the durable execution record, but this module deliberately presents
them as ordinary upload items: operators enqueue a prepared game and let the
queue process it in order.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .release_models import ReleasePlan


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UploadQueueStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NEEDS_REBUILD = "needs_rebuild"


_ACTIVE_STATUSES = frozenset(
    {
        UploadQueueStatus.QUEUED,
        UploadQueueStatus.RUNNING,
        UploadQueueStatus.PAUSED,
        UploadQueueStatus.FAILED,
        UploadQueueStatus.NEEDS_REBUILD,
    }
)


@dataclass(slots=True)
class UploadQueueItem:
    item_id: str
    game_id: str
    display_name: str
    release_tag: str
    release_id: str
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    status: UploadQueueStatus = UploadQueueStatus.QUEUED
    total_bytes: int = 0
    artifact_count: int = 0
    completed_bytes: int = 0
    current_filename: str | None = None
    current_source: str | None = None
    bytes_per_second: float = 0.0
    error: str | None = None
    mirror_delete_confirmed: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "UploadQueueItem":
        payload = dict(value)
        payload["status"] = UploadQueueStatus(str(payload.get("status", "queued")))
        return cls(**payload)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class UploadQueueError(RuntimeError):
    """Raised when an upload queue operation would be unsafe."""


class ContentUploadQueue:
    """Atomic persistent queue, intentionally independent from Tk widgets."""

    schema_version = 1

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.path = self.workspace_root / "upload-queue.json"
        self._recover_interrupted_items()

    def list_items(self) -> tuple[UploadQueueItem, ...]:
        return tuple(self._load())

    def get(self, item_id: str) -> UploadQueueItem:
        for item in self._load():
            if item.item_id == item_id:
                return item
        raise UploadQueueError("找不到上传项")

    def enqueue(self, plan: ReleasePlan, *, display_name: str) -> UploadQueueItem:
        if str(plan.target.get("game_id") or "").strip() == "":
            raise UploadQueueError("上传项缺少游戏标识")
        game_id = str(plan.target["game_id"])
        items = self._load()
        artifacts = tuple(plan.artifacts)
        duplicate = next((item for item in items if item.game_id == game_id), None)
        if duplicate is not None:
            duplicate.display_name = display_name.strip() or game_id
            duplicate.release_tag = str(plan.target.get("release_tag") or "")
            duplicate.release_id = plan.batch_id
            duplicate.total_bytes = sum(max(0, int(artifact.size or 0)) for artifact in artifacts)
            duplicate.artifact_count = len(artifacts)
            duplicate.completed_bytes = 0
            duplicate.current_filename = None
            duplicate.current_source = None
            duplicate.bytes_per_second = 0.0
            duplicate.mirror_delete_confirmed = bool(plan.options.get("mirror_delete_confirmed"))
            duplicate.updated_at = _utc_now()
            if duplicate.status is UploadQueueStatus.RUNNING:
                duplicate.error = "已保留最新提交；当前安全上传步骤结束后将上传新提交。"
            else:
                duplicate.status = UploadQueueStatus.QUEUED
                duplicate.error = "已舍弃旧提交，等待上传最新提交。"
            self._replace(duplicate)
            return duplicate
        item = UploadQueueItem(
            item_id=uuid4().hex,
            game_id=game_id,
            display_name=display_name.strip() or game_id,
            release_tag=str(plan.target.get("release_tag") or ""),
            release_id=plan.batch_id,
            total_bytes=sum(max(0, int(artifact.size or 0)) for artifact in artifacts),
            artifact_count=len(artifacts),
            mirror_delete_confirmed=bool(plan.options.get("mirror_delete_confirmed")),
        )
        items.append(item)
        self._save(items)
        return item

    def enqueue_built_game(
        self,
        *,
        game_id: str,
        display_name: str,
        release_tag: str,
        artifact_count: int,
        total_bytes: int,
    ) -> UploadQueueItem:
        """Add a completed local build without recreating its release record yet."""
        game_id = game_id.strip()
        if not game_id:
            raise UploadQueueError("上传项缺少游戏标识")
        items = self._load()
        duplicate = next((item for item in items if item.game_id == game_id), None)
        if duplicate is not None:
            duplicate.display_name = display_name.strip() or game_id
            duplicate.release_tag = release_tag
            duplicate.release_id = ""
            duplicate.artifact_count = max(0, artifact_count)
            duplicate.total_bytes = max(0, total_bytes)
            duplicate.completed_bytes = 0
            duplicate.current_filename = None
            duplicate.current_source = None
            duplicate.bytes_per_second = 0.0
            duplicate.mirror_delete_confirmed = False
            duplicate.updated_at = _utc_now()
            if duplicate.status is UploadQueueStatus.RUNNING:
                duplicate.error = "已保留最新构建；当前安全上传步骤结束后将上传新构建。"
            else:
                duplicate.status = UploadQueueStatus.QUEUED
                duplicate.error = "已替换为最新构建，等待上传。"
            self._replace(duplicate)
            return duplicate
        item = UploadQueueItem(
            item_id=uuid4().hex,
            game_id=game_id,
            display_name=display_name.strip() or game_id,
            release_tag=release_tag,
            release_id="",
            artifact_count=max(0, artifact_count),
            total_bytes=max(0, total_bytes),
        )
        items.append(item)
        self._save(items)
        return item

    def requeue_latest(self, item_id: str) -> UploadQueueItem:
        item = self._set_status(item_id, UploadQueueStatus.QUEUED)
        item.completed_bytes = 0
        item.current_filename = None
        item.current_source = None
        item.bytes_per_second = 0.0
        item.error = "已保留最新提交，等待上传。"
        self._replace(item)
        return item

    def remove(self, item_id: str) -> UploadQueueItem:
        items = self._load()
        for index, item in enumerate(items):
            if item.item_id != item_id:
                continue
            if item.status is UploadQueueStatus.RUNNING:
                raise UploadQueueError("正在上传的项目请先暂停，再删除。")
            removed = items.pop(index)
            self._save(items)
            return removed
        raise UploadQueueError("找不到上传项")

    def clear(self) -> tuple[UploadQueueItem, ...]:
        """Remove all non-running queue records without touching local artifacts."""
        items = self._load()
        running = next((item for item in items if item.status is UploadQueueStatus.RUNNING), None)
        if running is not None:
            raise UploadQueueError(f"“{running.display_name}”正在上传，请先暂停后再清空队列")
        self._save([])
        return tuple(items)

    def move(self, item_id: str, offset: int) -> tuple[UploadQueueItem, ...]:
        """Move a non-running item while keeping the queue strictly FIFO."""
        items = self._load()
        index = next((i for i, item in enumerate(items) if item.item_id == item_id), None)
        if index is None:
            raise UploadQueueError("找不到上传项")
        item = items[index]
        if item.status is UploadQueueStatus.RUNNING:
            raise UploadQueueError("正在上传的项目不能调整顺序。")
        target = max(0, min(len(items) - 1, index + offset))
        if target == index:
            return tuple(items)
        items.pop(index)
        items.insert(target, item)
        self._save(items)
        return tuple(items)

    def mark_running(self, item_id: str) -> UploadQueueItem:
        items = self._load()
        index = next((i for i, value in enumerate(items) if value.item_id == item_id), None)
        if index is None:
            raise UploadQueueError("找不到上传项")
        item = items[index]
        if item.status not in {
            UploadQueueStatus.QUEUED,
            UploadQueueStatus.PAUSED,
            UploadQueueStatus.FAILED,
        }:
            raise UploadQueueError("当前上传项不能开始或继续。")
        # 失败或需要重新构建的项可以稍后单独处理，不能让一个过期发布
        # 快照堵住后续已经准备好的游戏；仍禁止跳过尚待处理或用户暂停的项。
        pending_before = next(
            (
                value
                for value in items[:index]
                if value.status
                in {
                    UploadQueueStatus.QUEUED,
                    UploadQueueStatus.RUNNING,
                    UploadQueueStatus.PAUSED,
                }
            ),
            None,
        )
        if pending_before is not None:
            raise UploadQueueError(
                f"请先处理队列前面的“{pending_before.display_name}”，上传将按顺序执行。"
            )
        item.status = UploadQueueStatus.RUNNING
        item.error = None
        item.updated_at = _utc_now()
        items[index] = item
        self._save(items)
        return item

    def mark_paused(self, item_id: str) -> UploadQueueItem:
        return self._set_status(item_id, UploadQueueStatus.PAUSED)

    def mark_failed(self, item_id: str, error: str) -> UploadQueueItem:
        item = self._set_status(item_id, UploadQueueStatus.FAILED)
        item.error = error.strip() or "上传失败，请查看日志后重试。"
        self._replace(item)
        return item

    def mark_completed(self, item_id: str) -> UploadQueueItem:
        item = self._set_status(item_id, UploadQueueStatus.COMPLETED)
        item.completed_bytes = item.total_bytes
        item.bytes_per_second = 0.0
        item.current_filename = None
        item.current_source = None
        self._replace(item)
        return item

    def mark_needs_rebuild(self, item_id: str, reason: str) -> UploadQueueItem:
        item = self._set_status(item_id, UploadQueueStatus.NEEDS_REBUILD)
        item.error = reason.strip() or "本地发布文件已变化，请重新构建后再加入队列。"
        self._replace(item)
        return item

    def sync_progress(self, item_id: str, plan: ReleasePlan) -> UploadQueueItem:
        """Copy the throttled provider sample persisted by ``ReleaseService``.

        The provider uploads each source serially.  We expose a conservative
        total that counts both sources, so an overnight upload never appears
        finished after only GitLink or GitHub has completed.
        """
        item = self.get(item_id)
        sample = plan.options.get("upload_progress")
        if not isinstance(sample, dict):
            return item
        sent = max(0, int(sample.get("sent") or 0))
        source = str(sample.get("source") or "")
        filename = str(sample.get("filename") or "")
        speed = max(0.0, float(sample.get("bytes_per_second") or 0.0))
        ordered_sources = ("gitlink", "github")
        source_offset = item.total_bytes * (ordered_sources.index(source) if source in ordered_sources else 0)
        # Pipeline order is meaningful: content attachments are uploaded before
        # catalog.json, even if alphabetical ordering would put the catalog
        # first.  Preserve it for the visible aggregate progress.
        artifacts = tuple(plan.artifacts)
        before = 0
        for artifact in artifacts:
            if artifact.filename == filename:
                break
            before += max(0, int(artifact.size or 0))
        item.completed_bytes = min(item.total_bytes * 2, source_offset + before + sent)
        item.current_filename = filename or None
        item.current_source = source or None
        item.bytes_per_second = speed
        item.updated_at = _utc_now()
        self._replace(item)
        return item

    def next_runnable(self) -> UploadQueueItem | None:
        for item in self._load():
            if item.status is UploadQueueStatus.QUEUED:
                return item
        return None

    def active_for_game(self, game_id: str) -> UploadQueueItem | None:
        return next(
            (item for item in self._load() if item.game_id == game_id and item.status in _ACTIVE_STATUSES),
            None,
        )

    def _set_status(self, item_id: str, status: UploadQueueStatus) -> UploadQueueItem:
        item = self.get(item_id)
        item.status = status
        item.updated_at = _utc_now()
        self._replace(item)
        return item

    def _replace(self, replacement: UploadQueueItem) -> None:
        items = self._load()
        for index, item in enumerate(items):
            if item.item_id == replacement.item_id:
                items[index] = replacement
                self._save(items)
                return
        raise UploadQueueError("找不到上传项")

    def _load(self) -> list[UploadQueueItem]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.schema_version:
                raise UploadQueueError("上传队列版本不受支持")
            values = payload.get("items")
            if not isinstance(values, list):
                raise UploadQueueError("上传队列文件无效")
            return [UploadQueueItem.from_dict(value) for value in values if isinstance(value, dict)]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            if isinstance(error, UploadQueueError):
                raise
            raise UploadQueueError(f"无法读取上传队列：{error}") from error

    def _save(self, items: Iterable[UploadQueueItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "items": [item.to_dict() for item in items],
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def _recover_interrupted_items(self) -> None:
        """A process cannot keep uploading after restart; expose a safe resume."""
        if not self.path.exists():
            return
        items = self._load()
        changed = False
        for item in items:
            if item.status is not UploadQueueStatus.RUNNING:
                continue
            item.status = UploadQueueStatus.PAUSED
            item.error = "上次关闭时上传未完成；可继续上传，已完成文件会先校验并跳过。"
            item.current_filename = None
            item.current_source = None
            item.bytes_per_second = 0.0
            item.updated_at = _utc_now()
            changed = True
        if changed:
            self._save(items)
