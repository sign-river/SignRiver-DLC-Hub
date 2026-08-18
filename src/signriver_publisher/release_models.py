"""Domain models for persistent, auditable publisher release batches."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReleaseKind(StrEnum):
    PROGRAM = "program"
    GAME_CONTENT = "game_content"
    HUB_ANNOUNCEMENT = "hub_announcement"


class ReleaseStatus(StrEnum):
    DRAFT = "draft"
    PREFLIGHT_FAILED = "preflight_failed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    DEGRADED = "degraded"
    FAILED = "failed"
    COMPLETED = "completed"


class CheckResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIPPED = "skipped"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSED = "paused"
    SKIPPED = "skipped"


_ALLOWED_TRANSITIONS: dict[ReleaseStatus, frozenset[ReleaseStatus]] = {
    ReleaseStatus.DRAFT: frozenset({ReleaseStatus.PREFLIGHT_FAILED, ReleaseStatus.AWAITING_CONFIRMATION}),
    ReleaseStatus.PREFLIGHT_FAILED: frozenset({ReleaseStatus.DRAFT, ReleaseStatus.AWAITING_CONFIRMATION}),
    ReleaseStatus.AWAITING_CONFIRMATION: frozenset({ReleaseStatus.DRAFT, ReleaseStatus.RUNNING}),
    ReleaseStatus.RUNNING: frozenset({
        ReleaseStatus.PAUSED,
        ReleaseStatus.INTERRUPTED,
        ReleaseStatus.DEGRADED,
        ReleaseStatus.FAILED,
        ReleaseStatus.COMPLETED,
    }),
    ReleaseStatus.PAUSED: frozenset({ReleaseStatus.DRAFT, ReleaseStatus.RUNNING, ReleaseStatus.FAILED}),
    ReleaseStatus.INTERRUPTED: frozenset({
        ReleaseStatus.DRAFT,
        ReleaseStatus.RUNNING,
        ReleaseStatus.DEGRADED,
        ReleaseStatus.FAILED,
    }),
    ReleaseStatus.DEGRADED: frozenset({ReleaseStatus.RUNNING, ReleaseStatus.FAILED, ReleaseStatus.COMPLETED}),
    ReleaseStatus.FAILED: frozenset({ReleaseStatus.DRAFT, ReleaseStatus.RUNNING}),
    ReleaseStatus.COMPLETED: frozenset(),
}


class InvalidReleaseTransition(ValueError):
    """Raised when a release status transition violates the state machine."""


def validate_transition(current: ReleaseStatus, target: ReleaseStatus) -> None:
    if target == current:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidReleaseTransition(f"illegal release transition: {current.value} -> {target.value}")


@dataclass(slots=True)
class ReleaseArtifact:
    role: str
    filename: str
    platform: str | None = None
    architecture: str | None = None
    version: str | None = None
    local_path: str | None = None
    workspace_path: str | None = None
    size: int | None = None
    modified_ns: int | None = None
    sha256: str | None = None
    remote_source: str | None = None
    remote_id: str | None = None
    verified: bool = False
    required: bool = True
    reusable: bool = False
    reuse_evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseArtifact:
        return cls(**data)

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "filename": self.filename,
            "local_path": self.local_path,
            "size": self.size,
            "modified_ns": self.modified_ns,
            "sha256": self.sha256,
        }


@dataclass(slots=True)
class PreflightCheck:
    check_id: str
    category: str
    result: CheckResult
    hard_gate: bool
    message: str
    remediation: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=utc_now)
    input_fingerprint: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreflightCheck:
        value = dict(data)
        value["result"] = CheckResult(value["result"])
        return cls(**value)


@dataclass(slots=True)
class ReleaseStageRecord:
    stage_id: str
    display_name: str
    order: int
    status: StageStatus = StageStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    attempts: int = 0
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    error_category: str | None = None
    retryable: bool = False
    safe_resume_stage: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseStageRecord:
        value = dict(data)
        value["status"] = StageStatus(value["status"])
        return cls(**value)


@dataclass(slots=True)
class ReleaseEvent:
    batch_id: str
    event_type: str
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: str = field(default_factory=utc_now)
    stage_id: str | None = None
    source: str | None = None
    artifact_role: str | None = None
    action: str | None = None
    result: str | None = None
    error_category: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    trigger: str = "system"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseEvent:
        return cls(**data)


@dataclass(slots=True)
class ReleasePlan:
    batch_id: str
    kind: ReleaseKind
    target: dict[str, Any]
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    status: ReleaseStatus = ReleaseStatus.DRAFT
    artifacts: list[ReleaseArtifact] = field(default_factory=list)
    remote_targets: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    preflight: list[PreflightCheck] = field(default_factory=list)
    stages: list[ReleaseStageRecord] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    confirmation: dict[str, Any] = field(default_factory=dict)
    recovery: dict[str, Any] = field(default_factory=dict)
    input_fingerprint: str | None = None
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(cls, kind: ReleaseKind, target: dict[str, Any], *, batch_id: str | None = None) -> ReleasePlan:
        return cls(batch_id=batch_id or uuid4().hex, kind=kind, target=dict(target))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleasePlan:
        value = dict(data)
        value["kind"] = ReleaseKind(value["kind"])
        value["status"] = ReleaseStatus(value["status"])
        value["artifacts"] = [ReleaseArtifact.from_dict(item) for item in value.get("artifacts", [])]
        value["preflight"] = [PreflightCheck.from_dict(item) for item in value.get("preflight", [])]
        value["stages"] = [ReleaseStageRecord.from_dict(item) for item in value.get("stages", [])]
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def transition_to(self, target: ReleaseStatus) -> None:
        validate_transition(self.status, target)
        self.status = target
        self.updated_at = utc_now()

    def invalidate_inputs(self, reason: str) -> None:
        if self.status is ReleaseStatus.COMPLETED:
            raise InvalidReleaseTransition("completed release inputs cannot be changed")
        self.status = ReleaseStatus.DRAFT
        self.preflight.clear()
        self.confirmation.clear()
        self.input_fingerprint = None
        self.recovery["input_invalidation_reason"] = reason
        self.recovery["input_invalidated_at"] = utc_now()
        self.updated_at = utc_now()

    def resolve_local_path(self, workspace_root: Path, artifact: ReleaseArtifact) -> Path | None:
        if artifact.local_path:
            return Path(artifact.local_path)
        if artifact.workspace_path:
            return workspace_root / artifact.workspace_path
        return None
