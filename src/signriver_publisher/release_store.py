"""Persistent storage for publisher release batches."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import sleep
from typing import Any, Iterable
from uuid import uuid4

from .release_models import (
    PreflightCheck,
    ReleaseArtifact,
    ReleaseEvent,
    ReleasePlan,
    ReleaseStageRecord,
    ReleaseStatus,
    SCHEMA_VERSION,
    utc_now,
)

_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_SENSITIVE_KEYS = ("token", "cookie", "password", "secret", "credential", "authorization")


class ReleaseStoreError(RuntimeError):
    """Base error for release storage operations."""


class CorruptReleaseError(ReleaseStoreError):
    """Raised when persisted release data cannot be safely decoded."""


class ReleaseStore:
    """Owns atomic release persistence and append-only audit events."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.releases_root = self.workspace_root / "releases"
        self.corrupt_root = self.releases_root / "_corrupt"
        self.archive_root = self.releases_root / "_archived"
        self.index_path = self.releases_root / "index.json"
        # Upload progress persists from a worker while the UI polls the same
        # batch. On Windows an open JSON handle can briefly block os.replace().
        # Serialize each multi-document save/load to keep it coherent and out
        # of that read/write race.
        self._io_lock = RLock()

    def create(self, plan: ReleasePlan) -> ReleasePlan:
        directory = self._batch_directory(plan.batch_id)
        if directory.exists():
            raise ReleaseStoreError(f"release batch already exists: {plan.batch_id}")
        directory.mkdir(parents=True)
        (directory / "logs").mkdir()
        self.save(plan)
        event = ReleaseEvent(batch_id=plan.batch_id, event_type="release_created")
        self.append_event(event)
        plan.event_ids.append(event.event_id)
        self.save(plan)
        self._update_index(plan.batch_id)
        return plan

    def save(self, plan: ReleasePlan) -> None:
        with self._io_lock:
            directory = self._batch_directory(plan.batch_id)
            directory.mkdir(parents=True, exist_ok=True)
            plan.updated_at = utc_now()
            self._atomic_json(directory / "plan.json", plan.to_dict())
            self._atomic_json(directory / "artifacts.json", self._document([asdict(item) for item in plan.artifacts]))
            self._atomic_json(directory / "preflight.json", self._document([asdict(item) for item in plan.preflight]))
            self._atomic_json(directory / "stages.json", self._document([asdict(item) for item in plan.stages]))

    def load(self, batch_id: str) -> ReleasePlan:
        with self._io_lock:
            directory = self._batch_directory(batch_id)
            try:
                raw, plan_migrated = self._migrate_plan_payload(
                    self._read_json(directory / "plan.json")
                )
                artifacts, artifacts_migrated = self._read_document(
                    directory / "artifacts.json"
                )
                preflight, preflight_migrated = self._read_document(
                    directory / "preflight.json"
                )
                stages, stages_migrated = self._read_document(
                    directory / "stages.json"
                )
                plan = ReleasePlan.from_dict(raw)
                plan.artifacts = [ReleaseArtifact.from_dict(item) for item in artifacts]
                plan.preflight = [PreflightCheck.from_dict(item) for item in preflight]
                plan.stages = [ReleaseStageRecord.from_dict(item) for item in stages]
                if any(
                    (
                        plan_migrated,
                        artifacts_migrated,
                        preflight_migrated,
                        stages_migrated,
                    )
                ):
                    self.save(plan)
                return plan
            except CorruptReleaseError:
                raise
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise CorruptReleaseError(f"cannot load release batch {batch_id}: {exc}") from exc

    def load_all(self, *, isolate_corrupt: bool = True) -> list[ReleasePlan]:
        plans: list[ReleasePlan] = []
        if not self.releases_root.exists():
            return plans
        for directory in sorted(self.releases_root.iterdir()):
            if not directory.is_dir() or directory.name.startswith("_"):
                continue
            try:
                plans.append(self.load(directory.name))
            except CorruptReleaseError:
                if isolate_corrupt:
                    self.isolate_corrupt(directory.name)
                else:
                    raise
        return plans

    def append_event(self, event: ReleaseEvent) -> None:
        with self._io_lock:
            directory = self._batch_directory(event.batch_id)
            if not directory.exists():
                raise ReleaseStoreError(f"release batch does not exist: {event.batch_id}")
            payload = asdict(event)
            payload["context"] = self._redact(payload["context"])
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            path = directory / "events.jsonl"
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())

    def read_events(self, batch_id: str) -> list[ReleaseEvent]:
        path = self._batch_directory(batch_id) / "events.jsonl"
        if not path.exists():
            return []
        events: list[ReleaseEvent] = []
        line_number = 0
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if line.strip():
                        events.append(ReleaseEvent.from_dict(json.loads(line)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CorruptReleaseError(f"invalid event log at line {line_number}: {exc}") from exc
        return events

    def recover_interrupted(self) -> list[ReleasePlan]:
        recovered: list[ReleasePlan] = []
        for plan in self.load_all():
            if plan.status is not ReleaseStatus.RUNNING:
                continue
            plan.transition_to(ReleaseStatus.INTERRUPTED)
            plan.recovery["interrupted_at"] = utc_now()
            plan.recovery["reason"] = "publisher_restarted_while_running"
            self.save(plan)
            event = ReleaseEvent(
                batch_id=plan.batch_id,
                event_type="release_interrupted",
                result="interrupted",
                trigger="recovery",
                context={"reason": plan.recovery["reason"]},
            )
            self.append_event(event)
            plan.event_ids.append(event.event_id)
            self.save(plan)
            recovered.append(plan)
        return recovered

    def archive(self, batch_id: str) -> Path:
        """Move a disposable batch out of the active history without deleting its audit trail."""
        source = self._batch_directory(batch_id)
        if not source.exists():
            raise ReleaseStoreError(f"release batch does not exist: {batch_id}")
        self.archive_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.archive_root / f"{batch_id}-{timestamp}"
        suffix = 1
        while target.exists():
            target = self.archive_root / f"{batch_id}-{timestamp}-{suffix}"
            suffix += 1
        shutil.move(str(source), str(target))
        self._remove_from_index(batch_id)
        return target

    def isolate_corrupt(self, batch_id: str) -> Path:
        source = self._batch_directory(batch_id)
        if not source.exists():
            raise ReleaseStoreError(f"release batch does not exist: {batch_id}")
        self.corrupt_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.corrupt_root / f"{batch_id}-{timestamp}"
        suffix = 1
        while target.exists():
            target = self.corrupt_root / f"{batch_id}-{timestamp}-{suffix}"
            suffix += 1
        shutil.move(str(source), str(target))
        return target

    def _batch_directory(self, batch_id: str) -> Path:
        if not _BATCH_ID_PATTERN.fullmatch(batch_id):
            raise ReleaseStoreError(f"invalid release batch id: {batch_id!r}")
        return self.releases_root / batch_id

    def _update_index(self, batch_id: str) -> None:
        ids: list[str] = []
        if self.index_path.exists():
            try:
                ids = list(self._read_json(self.index_path).get("batch_ids", []))
            except CorruptReleaseError:
                ids = []
        if batch_id not in ids:
            ids.append(batch_id)
        self._atomic_json(self.index_path, {"schema_version": SCHEMA_VERSION, "batch_ids": ids})

    def _remove_from_index(self, batch_id: str) -> None:
        if not self.index_path.exists():
            return
        try:
            ids = list(self._read_json(self.index_path).get("batch_ids", []))
        except CorruptReleaseError:
            return
        if batch_id in ids:
            self._atomic_json(
                self.index_path,
                {"schema_version": SCHEMA_VERSION, "batch_ids": [item for item in ids if item != batch_id]},
            )

    @staticmethod
    def _document(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "items": list(items)}

    def _read_document(self, path: Path) -> tuple[list[dict[str, Any]], bool]:
        payload = self._read_json(path)
        version = payload.get("schema_version", 0)
        items = payload.get("items")
        if not isinstance(items, list):
            raise CorruptReleaseError(f"invalid release document: {path}")
        if version == SCHEMA_VERSION:
            return items, False
        if version in {0, 1}:
            return items, True
        raise CorruptReleaseError(
            f"unsupported release document schema {version!r}: {path}"
        )

    @staticmethod
    def _migrate_plan_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        version = payload.get("schema_version", 0)
        if version == SCHEMA_VERSION:
            return payload, False
        if version not in {0, 1}:
            raise CorruptReleaseError(f"unsupported release schema: {version!r}")
        migrated = dict(payload)
        # Schema 2 formalizes batch-local collection and read-only remote
        # baselines.  They intentionally live in options so old plans remain
        # fully readable and so a new snapshot invalidates confirmation.
        migrated["schema_version"] = SCHEMA_VERSION
        migrated.setdefault("status", ReleaseStatus.DRAFT.value)
        migrated.setdefault("remote_targets", {})
        migrated.setdefault("notes", "")
        migrated.setdefault("options", {})
        migrated["options"].setdefault("collection", {})
        migrated["options"].setdefault("remote_baseline", {})
        migrated.setdefault("event_ids", [])
        migrated.setdefault("confirmation", {})
        migrated.setdefault("recovery", {})
        migrated.setdefault("input_fingerprint", None)
        return migrated, True

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CorruptReleaseError(f"cannot read JSON document {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise CorruptReleaseError(f"JSON document must contain an object: {path}")
        return payload

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(4):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    sleep(0.05 * (2**attempt))
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): "[REDACTED]" if any(marker in str(key).lower() for marker in _SENSITIVE_KEYS) else cls._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        if isinstance(value, tuple):
            return [cls._redact(item) for item in value]
        return value
