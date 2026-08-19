"""Interfaces shared by release pipelines and remote providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .release_models import ReleaseArtifact, ReleasePlan, ReleaseStageRecord


@dataclass(slots=True)
class RemoteVerification:
    exists: bool
    size: int | None = None
    sha256: str | None = None
    remote_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class RemoteReleaseProvider(Protocol):
    """Boundary for a single release source; implementations must not depend on UI."""

    @property
    def source_id(self) -> str: ...

    def inspect(self, remote_key: str) -> RemoteVerification: ...

    def read_baseline(self) -> dict[str, Any]: ...

    def upload(self, artifact: ReleaseArtifact, local_path: Path) -> RemoteVerification: ...

    def delete(self, remote_key: str) -> RemoteVerification: ...

    def publish_index(self, plan: ReleasePlan, local_path: Path) -> RemoteVerification: ...


@dataclass(slots=True)
class StageExecutionResult:
    output_summary: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ReleasePipelineStage(Protocol):
    stage_id: str
    display_name: str
    order: int
    safe_checkpoint: bool

    def execute(self, plan: ReleasePlan) -> StageExecutionResult: ...


def stage_record(stage: ReleasePipelineStage) -> ReleaseStageRecord:
    return ReleaseStageRecord(stage_id=stage.stage_id, display_name=stage.display_name, order=stage.order)
