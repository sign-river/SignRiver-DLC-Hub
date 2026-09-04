"""Release pipelines for game content and Hub/announcement snapshots."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Mapping

from .release_interfaces import RemoteReleaseProvider, RemoteVerification, StageExecutionResult
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


def _trusted_remote_record(result, artifact: ReleaseArtifact) -> bool:
    return bool(
        result.exists
        and result.size == artifact.size
        and result.remote_id
    )


def _is_immutable_dlc(artifact: ReleaseArtifact) -> bool:
    name = artifact.filename.casefold()
    return name.startswith("dlc") and (name.endswith(".zip") or ".zip.part" in name)


def _content_reuse_assets(plan: ReleasePlan, source: str) -> dict[str, object]:
    """Return local fingerprints paired with a trusted remote attachment ID."""
    cache = plan.options.get("content_reuse_cache")
    if not isinstance(cache, dict):
        return {}
    source_cache = cache.get(source)
    if not isinstance(source_cache, dict):
        return {}
    if source_cache.get("target") != plan.remote_targets.get(source):
        return {}
    assets = source_cache.get("assets")
    return assets if isinstance(assets, dict) else {}


def _cache_content_asset(
    cache: dict[str, object], plan: ReleasePlan, source: str, artifact: ReleaseArtifact, result
) -> None:
    source_cache = cache.setdefault(
        source, {"target": dict(plan.remote_targets.get(source, {})), "assets": {}}
    )
    if not isinstance(source_cache, dict):
        return
    source_cache["target"] = dict(plan.remote_targets.get(source, {}))
    assets = source_cache.setdefault("assets", {})
    if isinstance(assets, dict):
        assets[artifact.filename] = {
            "sha256": artifact.sha256,
            "size": artifact.size,
            "remote_id": result.remote_id or "",
        }


def _stage_progress(plan: ReleasePlan, stage_id: str) -> dict[str, object]:
    record = next((item for item in plan.stages if item.stage_id == stage_id), None)
    if record is None:
        return {}
    if not isinstance(record.output_summary, dict):
        record.output_summary = {}
    return record.output_summary


def _record_upload_activity(
    progress: dict[str, object],
    *,
    source: str,
    artifact: ReleaseArtifact,
    outcome: str,
    remote_id: object = None,
) -> None:
    """Persist one user-visible attachment result at its safe checkpoint.

    The queue UI consumes these records while a game is still uploading, rather
    than waiting for the whole snapshot stage to finish.
    """
    activities = progress.setdefault("activity", [])
    if not isinstance(activities, list):
        activities = []
        progress["activity"] = activities
    event_id = f"{source}:{artifact.filename}:{outcome}:{remote_id or ''}"
    if any(isinstance(item, dict) and item.get("id") == event_id for item in activities):
        return
    activities.append(
        {
            "id": event_id,
            "source": source,
            "filename": artifact.filename,
            "size": artifact.size,
            "sha256": artifact.sha256 or "",
            "outcome": outcome,
        }
    )
    del activities[:-1000]


def _trusted_record_matches(
    record: object, remote: object, artifact: ReleaseArtifact
) -> bool:
    return bool(
        isinstance(record, dict)
        and record.get("size") == artifact.size
        and record.get("remote_id")
        and isinstance(remote, dict)
        and remote.get("remote_id")
        and str(record["remote_id"]) == str(remote["remote_id"])
    )


def _remote_upload_recovered(
    provider: RemoteReleaseProvider, artifact: ReleaseArtifact
):
    """Confirm an upload whose server response was lost, without downloading it."""
    baseline = provider.read_baseline()
    remote = next(
        (
            item
            for item in baseline.get("assets", [])
            if isinstance(item, dict) and item.get("name") == artifact.filename
        ),
        None,
    )
    if not isinstance(remote, dict) or not remote.get("remote_id"):
        return None
    remote_size = remote.get("size")
    if remote_size is not None and remote_size != artifact.size:
        return None
    return RemoteVerification(
        True, size=artifact.size, remote_id=str(remote["remote_id"])
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
        desired_names = {artifact.filename for artifact in attachments}
        desired_names.add(next(item.filename for item in plan.artifacts if item.role == self.index_role))
        preserve_remote_only_files = bool(plan.options.get("preserve_remote_only_files"))
        delete_confirmed = bool(plan.options.get("mirror_delete_confirmed")) and not preserve_remote_only_files
        ready: dict[str, list[str]] = {}
        reused: dict[str, list[str]] = {}
        recovered: dict[str, list[str]] = {}
        continued: dict[str, list[str]] = {}
        deleted: dict[str, list[str]] = {}
        pending_deletes: dict[str, list[str]] = {}
        index = next(
            (item for item in plan.artifacts if item.role == self.index_role), None
        )
        if index is None or not index.local_path:
            raise ReleaseStageError(f"缺少主表产物：{self.index_role}", retryable=False)
        reuse_enabled = isinstance(plan.options.get("content_reuse_cache"), dict)
        next_reuse_cache = deepcopy(plan.options.get("content_reuse_cache", {})) if reuse_enabled else {}
        progress = _stage_progress(plan, self.stage_id)
        prior_switched = progress.get("switched", [])
        switched: list[str] = [
            str(source) for source in prior_switched
            if str(source) in self.providers
        ] if isinstance(prior_switched, list) else []
        prior_trusted = progress.get("trusted", {})
        trusted = deepcopy(prior_trusted) if isinstance(prior_trusted, dict) else {}
        for source, provider in self.providers.items():
            ready[source], reused[source], recovered[source], continued[source], deleted[source], pending_deletes[source] = [], [], [], [], [], []
            read_baseline = getattr(provider, "read_baseline", None)
            if not callable(read_baseline):
                raise ReleaseStageError(f"{source} 不支持读取远端资源目录", retryable=False)
            baseline = read_baseline()
            remote_assets = {
                str(item.get("name") or ""): item
                for item in baseline.get("assets", [])
                if isinstance(item, dict) and str(item.get("name") or "")
            }
            cached_assets = _content_reuse_assets(plan, source) if reuse_enabled else {}
            source_trusted = trusted.setdefault(source, {})
            if not isinstance(source_trusted, dict):
                source_trusted = {}
                trusted[source] = source_trusted
            for artifact in attachments:
                if self.checkpoint:
                    self.checkpoint(plan)
                cached = cached_assets.get(artifact.filename)
                remote = remote_assets.get(artifact.filename)
                cache_matches = isinstance(cached, dict) and (
                    cached.get("sha256") == artifact.sha256
                    and cached.get("size") == artifact.size
                )
                remote_id_matches = (
                    isinstance(cached, dict)
                    and bool(cached.get("remote_id"))
                    and isinstance(remote, dict)
                    and bool(remote.get("remote_id"))
                    and str(cached["remote_id"]) == str(remote["remote_id"])
                )
                if (
                    _is_immutable_dlc(artifact)
                    and remote is not None
                    and cache_matches
                    and remote_id_matches
                ):
                    ready[source].append(artifact.filename)
                    reused[source].append(artifact.filename)
                    _record_upload_activity(
                        progress, source=source, artifact=artifact, outcome="reused",
                        remote_id=cached.get("remote_id") if isinstance(cached, dict) else None,
                    )
                    if self.checkpoint:
                        self.checkpoint(plan)
                    continue
                previous = source_trusted.get(artifact.filename)
                if _trusted_record_matches(previous, remote, artifact):
                    ready[source].append(artifact.filename)
                    continued[source].append(artifact.filename)
                    if reuse_enabled:
                        _cache_content_asset(
                            next_reuse_cache,
                            plan,
                            source,
                            artifact,
                            RemoteVerification(
                                True,
                                size=artifact.size,
                                remote_id=str(previous["remote_id"]),
                            ),
                        )
                    _record_upload_activity(
                        progress, source=source, artifact=artifact, outcome="continued",
                        remote_id=previous.get("remote_id") if isinstance(previous, dict) else None,
                    )
                    if self.checkpoint:
                        self.checkpoint(plan)
                    continue
                try:
                    result = provider.upload(artifact, Path(artifact.local_path or ""))
                except Exception:
                    result = _remote_upload_recovered(provider, artifact)
                    if result is None:
                        raise
                    recovered[source].append(artifact.filename)
                if not _trusted_remote_record(result, artifact):
                    raise ReleaseStageError(
                        f"{source} 附件上传后未取得可信的附件 ID 或大小：{artifact.filename}"
                    )
                ready[source].append(artifact.filename)
                source_trusted[artifact.filename] = {
                    "remote_id": result.remote_id,
                    "size": artifact.size,
                }
                if reuse_enabled:
                    _cache_content_asset(next_reuse_cache, plan, source, artifact, result)
                _record_upload_activity(
                    progress,
                    source=source,
                    artifact=artifact,
                    outcome="recovered" if artifact.filename in recovered[source] else "uploaded",
                    remote_id=result.remote_id,
                )
                progress.update(
                    {
                        "ready": ready,
                        "reused": reused,
                        "recovered": recovered,
                        "continued": continued,
                        "trusted": trusted,
                        "content_reuse_cache": next_reuse_cache,
                    }
                )
                if self.checkpoint:
                    self.checkpoint(plan)
            # Legacy direct publishing only replaces the declared attachments.
            # The queue-driven mirror workflow explicitly asks the operator to
            # confirm remote deletion first; only that path requires a remote
            # directory snapshot.  Keeping the capability opt-in also lets
            # minimal providers upload safely without pretending to support
            # destructive mirror synchronisation.
            if delete_confirmed:
                remote_names = {
                    str(item.get("name") or "")
                    for item in baseline.get("assets", [])
                    if isinstance(item, dict)
                }
                extras = sorted(name for name in remote_names - desired_names if name)
                preview = plan.options.get("remote_mirror_preview")
                expected_extras: object | None = None
                if isinstance(preview, dict):
                    previewed_sources = preview.get("extra_files")
                    if isinstance(previewed_sources, dict):
                        expected_extras = previewed_sources.get(source)
                if expected_extras is not None:
                    expected = sorted(str(name) for name in expected_extras)
                    if extras != expected:
                        raise ReleaseStageError(
                            f"{source} 远端目录已发生变化，请重新读取差异并确认删除清单。",
                            retryable=False,
                        )
                for remote_name in extras:
                    if self.checkpoint:
                        self.checkpoint(plan)
                    if provider.delete(remote_name).exists:
                        raise ReleaseStageError(f"{source} 附件删除后仍存在：{remote_name}")
                    deleted[source].append(remote_name)

            # Complete one provider's snapshot before touching the next one.
            # This prevents a later source failure from leaving an earlier
            # source with replaced attachments but its old catalog/index.
            if source in switched:
                continue
            if self.checkpoint:
                self.checkpoint(plan)
            try:
                result = provider.publish_index(plan, Path(index.local_path))
            except Exception as exc:
                raise ReleaseStageError(
                    f"{source} 主表切换失败：{exc}",
                    status=ReleaseStatus.DEGRADED if switched else ReleaseStatus.FAILED,
                ) from exc
            if not _trusted_remote_record(result, index):
                raise ReleaseStageError(
                    f"{source} 主表上传后未取得可信的附件 ID 或大小",
                    status=ReleaseStatus.DEGRADED if switched else ReleaseStatus.FAILED,
                )
            switched.append(source)
            progress["switched"] = list(switched)
            if self.checkpoint:
                self.checkpoint(plan)
        if any(pending_deletes.values()):
            details = "；".join(
                f"{source}: {', '.join(names)}"
                for source, names in pending_deletes.items() if names
            )
            raise ReleaseStageError(
                f"检测到远端多余附件，需二次确认镜像删除：{details}", retryable=False
            )
        return StageExecutionResult(
            {
                "ready": ready,
                "reused": reused,
                "recovered": recovered,
                "continued": continued,
                "deleted": deleted,
                "preserved_remote_only_files": preserve_remote_only_files,
                "content_reuse_cache": next_reuse_cache,
                "trusted": trusted,
                "activity": progress.get("activity", []),
                "switched": switched,
            },
            {
                "all_snapshot_attachments_ready": all(
                    len(value) == len(attachments) for value in ready.values()
                ),
                "all_indexes_verified": len(switched) == len(self.providers),
            },
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
        if gate and gate.verification.get("all_indexes_verified"):
            return StageExecutionResult(
                {"switched": list(gate.output_summary.get("switched", []))},
                {"all_indexes_verified": True},
            )
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
                result = provider.publish_index(plan, Path(index.local_path))
            except Exception as exc:
                raise ReleaseStageError(
                    f"{source} 主表切换失败：{exc}",
                    status=ReleaseStatus.DEGRADED if switched else ReleaseStatus.FAILED,
                ) from exc
            if not _trusted_remote_record(result, index):
                raise ReleaseStageError(
                    f"{source} 主表上传后未取得可信的附件 ID 或大小",
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
            display_name="上传完整附件快照并记录远端 ID",
            providers=providers,
            index_role=index_role,
            checkpoint=checkpoint,
        ),
        PublishSnapshotIndexStage(
            stage_id=f"{prefix}.publish_index",
            display_name="最后切换主表并记录远端 ID",
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
