"""Release pipelines for game content and Hub/announcement snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .release_interfaces import RemoteReleaseProvider, StageExecutionResult
from .release_models import ReleaseArtifact, ReleasePlan, ReleaseStatus
from .release_orchestrator import ReleaseStageError


REQUIRED_SOURCES = ("gitlink", "github")


def _validate_providers(providers: Mapping[str, RemoteReleaseProvider]) -> None:
    if set(providers) != set(REQUIRED_SOURCES):
        raise ValueError(
            "snapshot release requires exactly gitlink and github providers"
        )
    for source, provider in providers.items():
        if provider.source_id != source:
            raise ValueError(
                f"provider key/source mismatch: {source}/{provider.source_id}"
            )


def _verified(result, artifact: ReleaseArtifact) -> bool:
    return bool(
        result.exists
        and result.size == artifact.size
        and result.sha256 == artifact.sha256
    )


class UploadSnapshotAttachmentsStage:
    order = 20
    safe_checkpoint = True

    def __init__(
        self,
        *,
        stage_id: str,
        display_name: str,
        providers: Mapping[str, RemoteReleaseProvider],
        index_role: str,
        checkpoint=None,
    ) -> None:
        self.stage_id = stage_id
        self.display_name = display_name
        self.providers = dict(providers)
        self.index_role = index_role
        self.checkpoint = checkpoint

    def execute(self, plan: ReleasePlan) -> StageExecutionResult:
        attachments = [item for item in plan.artifacts if item.role != self.index_role]
        if not attachments:
            raise ReleaseStageError("发布快照没有附件", retryable=False)
        ready: dict[str, list[str]] = {}
        reused: dict[str, list[str]] = {}
        for source, provider in self.providers.items():
            ready[source], reused[source] = [], []
            for artifact in attachments:
                if self.checkpoint:
                    self.checkpoint(plan)
                result = provider.inspect(artifact.filename)
                if _verified(result, artifact):
                    reused[source].append(artifact.filename)
                else:
                    result = provider.upload(artifact, Path(artifact.local_path or ""))
                    if not _verified(result, artifact):
                        raise ReleaseStageError(f"{source} 附件回读失败：{artifact.filename}")
                ready[source].append(artifact.filename)
        return StageExecutionResult(
            {"ready": ready, "reused": reused},
            {"all_snapshot_attachments_ready": all(len(value) == len(attachments) for value in ready.values())},
        )


class PublishSnapshotIndexStage:
    order = 40
    safe_checkpoint = True

    def __init__(self, *, stage_id: str, display_name: str, providers: Mapping[str, RemoteReleaseProvider], index_role: str, upload_stage_id: str, checkpoint=None) -> None:
        self.stage_id = stage_id
        self.display_name = display_name
        self.providers = dict(providers)
        self.index_role = index_role
        self.upload_stage_id = upload_stage_id
        self.checkpoint = checkpoint

    def execute(self, plan: ReleasePlan) -> StageExecutionResult:
        gate = next((item for item in plan.stages if item.stage_id == self.upload_stage_id), None)
        if not gate or not gate.verification.get("all_snapshot_attachments_ready"):
            raise ReleaseStageError("完整快照门禁未满足，禁止切换主表", retryable=False)
        index = next((item for item in plan.artifacts if item.role == self.index_role), None)
        if index is None or not index.local_path:
            raise ReleaseStageError(f"缺少主表产物：{self.index_role}", retryable=False)
        switched: list[str] = []
        reused: list[str] = []
        for source, provider in self.providers.items():
            if self.checkpoint:
                self.checkpoint(plan)
            try:
                result = provider.inspect(index.filename)
                if _verified(result, index):
                    reused.append(source)
                else:
                    result = provider.publish_index(plan, Path(index.local_path))
            except Exception as exc:
                raise ReleaseStageError(
                    f"{source} 主表切换失败：{exc}",
                    status=ReleaseStatus.DEGRADED if switched else ReleaseStatus.FAILED,
                ) from exc
            if not _verified(result, index):
                raise ReleaseStageError(
                    f"{source} 主表回读失败",
                    status=ReleaseStatus.DEGRADED if switched else ReleaseStatus.FAILED,
                )
            switched.append(source)
        return StageExecutionResult(
            {"switched": switched, "reused": reused},
            {"all_indexes_verified": len(switched) == len(self.providers)},
        )


def _snapshot_stages(prefix: str, providers: Mapping[str, RemoteReleaseProvider], index_role: str, checkpoint=None):
    _validate_providers(providers)
    upload_id = f"{prefix}.upload_snapshot"
    return (
        UploadSnapshotAttachmentsStage(
            stage_id=upload_id,
            display_name="上传并回读完整附件快照",
            providers=providers,
            index_role=index_role,
            checkpoint=checkpoint,
        ),
        PublishSnapshotIndexStage(
            stage_id=f"{prefix}.publish_index",
            display_name="最后切换并回读主表",
            providers=providers,
            index_role=index_role,
            upload_stage_id=upload_id,
            checkpoint=checkpoint,
        ),
    )


def game_content_release_stages(providers: Mapping[str, RemoteReleaseProvider], *, checkpoint=None):
    return _snapshot_stages("content", providers, "catalog", checkpoint)


def hub_release_stages(providers: Mapping[str, RemoteReleaseProvider], *, checkpoint=None):
    return _snapshot_stages("hub", providers, "hub_index", checkpoint)
