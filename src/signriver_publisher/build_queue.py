"""Persistent FIFO queue for local DLC / patch package builds."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .models import GameProfile


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BuildQueueStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class BuildQueueItem:
    item_id: str
    game_id: str
    display_name: str
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    status: BuildQueueStatus = BuildQueueStatus.QUEUED
    resource_count: int = 0
    artifact_count: int = 0
    total_bytes: int = 0
    error: str | None = None
    rerun_requested: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "BuildQueueItem":
        payload = dict(value)
        payload["status"] = BuildQueueStatus(str(payload.get("status", "queued")))
        return cls(**payload)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BuildQueueError(RuntimeError):
    pass


class ContentBuildQueue:
    """Atomic local build queue; a build is always processed one game at a time."""

    schema_version = 1

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.path = self.workspace_root / "build-queue.json"
        self._recover_interrupted_items()

    def list_items(self) -> tuple[BuildQueueItem, ...]:
        return tuple(self._load())

    def enqueue(self, profile: GameProfile) -> BuildQueueItem:
        items = self._load()
        existing = next((item for item in items if item.game_id == profile.game_id), None)
        if existing is not None:
            existing.display_name = profile.display_name
            existing.updated_at = _utc_now()
            existing.resource_count = 0
            existing.artifact_count = 0
            existing.total_bytes = 0
            if existing.status is BuildQueueStatus.RUNNING:
                existing.rerun_requested = True
                existing.error = "已保留最新提交；当前构建完成后将自动重新构建。"
            else:
                existing.status = BuildQueueStatus.QUEUED
                existing.rerun_requested = False
                existing.error = "已舍弃旧提交，等待构建最新提交。"
            self._replace(existing)
            return existing
        item = BuildQueueItem(
            item_id=uuid4().hex,
            game_id=profile.game_id,
            display_name=profile.display_name,
        )
        items.append(item)
        self._save(items)
        return item

    def requeue_latest(self, item_id: str) -> BuildQueueItem:
        item = self._set_status(item_id, BuildQueueStatus.QUEUED)
        item.resource_count = 0
        item.artifact_count = 0
        item.total_bytes = 0
        item.rerun_requested = False
        item.error = "已保留最新提交，等待重新构建。"
        self._replace(item)
        return item

    def next_runnable(self) -> BuildQueueItem | None:
        return next(
            (item for item in self._load() if item.status is BuildQueueStatus.QUEUED),
            None,
        )

    def mark_running(self, item_id: str) -> BuildQueueItem:
        return self._set_status(item_id, BuildQueueStatus.RUNNING)

    def mark_completed(
        self, item_id: str, *, resource_count: int, artifact_count: int, total_bytes: int
    ) -> BuildQueueItem:
        item = self._set_status(item_id, BuildQueueStatus.COMPLETED)
        item.resource_count = max(0, resource_count)
        item.artifact_count = max(0, artifact_count)
        item.total_bytes = max(0, total_bytes)
        item.error = None
        self._replace(item)
        return item

    def mark_failed(self, item_id: str, error: str) -> BuildQueueItem:
        item = self._set_status(item_id, BuildQueueStatus.FAILED)
        item.error = error.strip() or "构建失败，请查看日志后重试。"
        self._replace(item)
        return item

    def remove(self, item_id: str) -> BuildQueueItem:
        items = self._load()
        for index, item in enumerate(items):
            if item.item_id != item_id:
                continue
            if item.status is BuildQueueStatus.RUNNING:
                raise BuildQueueError("正在构建的项目不能删除。")
            removed = items.pop(index)
            self._save(items)
            return removed
        raise BuildQueueError("找不到构建项")

    def get(self, item_id: str) -> BuildQueueItem:
        return next(
            item for item in self._load() if item.item_id == item_id
        )

    def _set_status(self, item_id: str, status: BuildQueueStatus) -> BuildQueueItem:
        item = self.get(item_id)
        item.status = status
        item.updated_at = _utc_now()
        self._replace(item)
        return item

    def _replace(self, replacement: BuildQueueItem) -> None:
        items = self._load()
        for index, item in enumerate(items):
            if item.item_id == replacement.item_id:
                items[index] = replacement
                self._save(items)
                return
        raise BuildQueueError("找不到构建项")

    def _load(self) -> list[BuildQueueItem]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.schema_version:
                raise BuildQueueError("构建队列版本不受支持")
            values = payload.get("items")
            if not isinstance(values, list):
                raise BuildQueueError("构建队列文件无效")
            return [BuildQueueItem.from_dict(value) for value in values if isinstance(value, dict)]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            if isinstance(error, BuildQueueError):
                raise
            raise BuildQueueError(f"无法读取构建队列：{error}") from error

    def _save(self, items: Iterable[BuildQueueItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schema_version": self.schema_version, "items": [item.to_dict() for item in items]},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def _recover_interrupted_items(self) -> None:
        if not self.path.exists():
            return
        items = self._load()
        changed = False
        for item in items:
            if item.status is BuildQueueStatus.RUNNING:
                item.status = BuildQueueStatus.QUEUED
                item.error = "上次关闭时构建未完成，已重新排队。"
                changed = True
        if changed:
            self._save(items)
