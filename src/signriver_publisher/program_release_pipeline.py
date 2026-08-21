"""Program update pipeline with immutable package gates and per-source manifests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .release_interfaces import (
    RemoteReleaseProvider,
    RemoteVerification,
    StageExecutionResult,
)
from .release_models import ReleaseArtifact, ReleasePlan, ReleaseStatus, StageStatus
from .release_orchestrator import ReleasePauseRequested, ReleaseStageError
from .updates import UPDATE_MANIFEST_ASSET

PACKAGE_ROLES = ("windows_full", "steamos_full", "macos_full")
MODULE_ROLE = "module_archive"
REQUIRED_SOURCES = ("gitlink", "github")
_ROLE_TO_PLATFORM_KEY = {
    "windows_full": "windows-x64",
    "steamos_full": "steamos-x64",
    "macos_full": "macos-x64",
}


def _validate_providers(providers: dict[str, RemoteReleaseProvider]) -> None:
    if set(providers) != set(REQUIRED_SOURCES):
        raise ValueError(
            "program release requires exactly gitlink and github providers"
        )
    for source, provider in providers.items():
        if provider.source_id != source:
            raise ValueError(
                f"provider key/source mismatch: {source}/{provider.source_id}"
            )


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseStageError(
            f"invalid update manifest {path}: {exc}", retryable=False
        ) from exc
    if not isinstance(payload, dict):
        raise ReleaseStageError(
            "update manifest root must be an object", retryable=False
        )
    return payload


def _validate_manifest_payload(payload: dict[str, Any], plan: ReleasePlan) -> None:
    version = str(plan.target.get("version") or "")
    releases = payload.get("releases")
    if payload.get("schema_version") != 1 or not isinstance(releases, list):
        raise ReleaseStageError("update manifest schema is invalid", retryable=False)
    release = next(
        (
            item
            for item in releases
            if isinstance(item, dict) and item.get("version") == version
        ),
        None,
    )
    if release is None:
        raise ReleaseStageError(
            f"update manifest does not contain version {version}", retryable=False
        )
    if release.get("notes") != plan.notes:
        raise ReleaseStageError(
            "update manifest notes do not match the release batch", retryable=False
        )
    if bool(release.get("mandatory")) != bool(plan.options.get("mandatory", False)):
        raise ReleaseStageError(
            "update manifest mandatory flag does not match the release batch",
            retryable=False,
        )
    packages = release.get("platform_packages")
    if not isinstance(packages, dict) or set(packages) != set(
        _ROLE_TO_PLATFORM_KEY.values()
    ):
        raise ReleaseStageError(
            "update manifest must contain all three platform packages", retryable=False
        )
    artifacts = {item.role: item for item in plan.artifacts}
    for role, platform_key in _ROLE_TO_PLATFORM_KEY.items():
        artifact = artifacts.get(role)
        item = packages.get(platform_key)
        if artifact is None or not isinstance(item, dict):
            raise ReleaseStageError(
                f"missing manifest package entry: {platform_key}", retryable=False
            )
        if item.get("size") != artifact.size or item.get("sha256") != artifact.sha256:
            raise ReleaseStageError(
                f"manifest package fingerprint mismatch: {platform_key}",
                retryable=False,
            )
        if not str(item.get("package_url") or "").strip():
            raise ReleaseStageError(
                f"manifest package URL is missing: {platform_key}", retryable=False
            )


def _trusted_remote_record(result: RemoteVerification, artifact: ReleaseArtifact) -> bool:
    return bool(
        result.exists
        and result.remote_id
        and result.size == artifact.size
    )


class UploadProgramPackagesStage:
    stage_id = "program.upload_packages"
    display_name = "上传双源程序包并记录远端 ID"
    order = 20
    safe_checkpoint = True

    def __init__(
        self,
        providers: dict[str, RemoteReleaseProvider],
        *,
        checkpoint: Callable[[ReleasePlan], None] | None = None,
    ) -> None:
        _validate_providers(providers)
        self.providers = providers
        self.checkpoint = checkpoint

    def execute(self, plan: ReleasePlan) -> StageExecutionResult:
        artifacts = {item.role: item for item in plan.artifacts}
        missing = [role for role in PACKAGE_ROLES if role not in artifacts]
        if missing:
            raise ReleaseStageError(
                f"missing required program artifacts: {', '.join(missing)}",
                retryable=False,
            )
        ready: dict[str, dict[str, Any]] = {}
        for role in PACKAGE_ROLES:
            artifact = artifacts[role]
            if not artifact.local_path:
                raise ReleaseStageError(
                    f"artifact has no local path: {role}", retryable=False
                )
            path = Path(artifact.local_path)
            for source in REQUIRED_SOURCES:
                if self.checkpoint:
                    self.checkpoint(plan)
                provider = self.providers[source]
                key = f"{source}:{role}"
                # 同名程序包的发布语义就是替换。此前先完整下载远端大包来
                # 判断能否复用，会让界面长时间停在“等待上传”且没有字节进度。
                # 现在直接上传并记录远端附件 ID 与大小，不再下载大包回读。
                result = provider.upload(artifact, path)
                if not _trusted_remote_record(result, artifact):
                    raise ReleaseStageError(
                        f"remote package verification failed: {key}"
                    )
                ready[key] = {
                    "remote_id": result.remote_id,
                    "size": result.size,
                    "sha256": artifact.sha256,
                    "reused": False,
                }
        expected_count = len(PACKAGE_ROLES) * len(REQUIRED_SOURCES)
        return StageExecutionResult(
            {"ready": sorted(ready), "details": ready},
            {
                "all_packages_ready": len(ready) == expected_count,
                "verified_count": len(ready),
            },
        )


class UploadProgramModulesStage:
    stage_id = "program.upload_modules"
    display_name = "上传双源模块归档并记录远端 ID"
    order = 25
    safe_checkpoint = True

    def __init__(
        self,
        providers: dict[str, RemoteReleaseProvider],
        *,
        checkpoint: Callable[[ReleasePlan], None] | None = None,
    ) -> None:
        _validate_providers(providers)
        self.providers = providers
        self.checkpoint = checkpoint

    def execute(self, plan: ReleasePlan) -> StageExecutionResult:
        artifacts = [item for item in plan.artifacts if item.role == MODULE_ROLE]
        if not artifacts:
            return StageExecutionResult(
                {"ready": [], "skipped": True},
                {"all_modules_ready": True, "skipped": True, "verified_count": 0},
            )
        ready: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            if not artifact.local_path:
                raise ReleaseStageError(f"module artifact has no local path: {artifact.filename}", retryable=False)
            path = Path(artifact.local_path)
            for source in REQUIRED_SOURCES:
                if self.checkpoint:
                    self.checkpoint(plan)
                # 模块归档与程序包采用相同策略：同名文件直接替换并记录附件 ID。
                result = self.providers[source].upload(artifact, path)
                if not _trusted_remote_record(result, artifact):
                    raise ReleaseStageError(f"remote module verification failed: {source}:{artifact.filename}")
                ready[f"{source}:{artifact.filename}"] = {
                    "remote_id": result.remote_id, "size": result.size,
                    "sha256": artifact.sha256, "reused": False,
                }
        return StageExecutionResult(
            {"ready": sorted(ready), "details": ready},
            {"all_modules_ready": len(ready) == len(artifacts) * len(REQUIRED_SOURCES), "verified_count": len(ready)},
        )


class PublishProgramManifestStage:
    safe_checkpoint = True

    def __init__(
        self,
        source: str,
        provider: RemoteReleaseProvider,
        manifest: Path,
        *,
        order: int,
        checkpoint: Callable[[ReleasePlan], None] | None = None,
    ) -> None:
        if source not in REQUIRED_SOURCES or provider.source_id != source:
            raise ValueError(f"invalid program manifest provider: {source}")
        self.source = source
        self.provider = provider
        self.manifest = Path(manifest)
        self.order = order
        self.stage_id = f"program.publish_manifest.{source}"
        self.display_name = f"切换 {source} 更新清单"
        self.checkpoint = checkpoint

    def execute(self, plan: ReleasePlan) -> StageExecutionResult:
        upload = next(
            (
                item
                for item in plan.stages
                if item.stage_id == "program.upload_packages"
            ),
            None,
        )
        if (
            upload is None
            or upload.status is not StageStatus.SUCCEEDED
            or not upload.verification.get("all_packages_ready")
        ):
            raise ReleaseStageError(
                "dual-source package gate is not satisfied", retryable=False
            )
        if any(item.role == MODULE_ROLE for item in plan.artifacts):
            modules = next(
                (
                    item
                    for item in plan.stages
                    if item.stage_id == "program.upload_modules"
                ),
                None,
            )
            if (
                modules is None
                or modules.status is not StageStatus.SUCCEEDED
                or not modules.verification.get("all_modules_ready")
            ):
                raise ReleaseStageError(
                    "dual-source module gate is not satisfied", retryable=False
                )
        expected = _load_manifest(self.manifest)
        _validate_manifest_payload(expected, plan)
        if self.checkpoint:
            self.checkpoint(plan)
        try:
            result = self.provider.publish_index(plan, self.manifest)
        except ReleasePauseRequested:
            raise
        except Exception as exc:
            prior_switched = any(
                item.stage_id.startswith("program.publish_manifest.")
                and item.stage_id != self.stage_id
                and item.status is StageStatus.SUCCEEDED
                for item in plan.stages
            )
            raise ReleaseStageError(
                f"{self.source} manifest publish failed: {exc}",
                status=ReleaseStatus.DEGRADED
                if prior_switched
                else ReleaseStatus.FAILED,
            ) from exc
        artifact = ReleaseArtifact(
            role="program_manifest",
            filename=self.manifest.name,
            size=self.manifest.stat().st_size,
        )
        if not _trusted_remote_record(result, artifact):
            prior_switched = any(
                item.stage_id.startswith("program.publish_manifest.")
                and item.stage_id != self.stage_id
                and item.status is StageStatus.SUCCEEDED
                for item in plan.stages
            )
            raise ReleaseStageError(
                f"{self.source} manifest attachment record is incomplete",
                status=ReleaseStatus.DEGRADED
                if prior_switched
                else ReleaseStatus.FAILED,
            )
        return StageExecutionResult(
            {
                "source": self.source,
                "manifest": self.manifest.name,
                "remote_id": result.remote_id,
                "size": result.size,
            },
            {"manifest_verified": True, "remote_id": result.remote_id},
        )


class VerifyProgramManifestsStage:
    stage_id = "program.verify_manifests"
    display_name = "核对双源更新清单附件记录"
    order = 50
    safe_checkpoint = True

    def __init__(
        self, providers: dict[str, RemoteReleaseProvider], manifests: dict[str, Path]
    ) -> None:
        _validate_providers(providers)
        if set(manifests) != set(REQUIRED_SOURCES):
            raise ValueError("program release requires one manifest per source")
        self.providers = providers
        self.manifests = {key: Path(value) for key, value in manifests.items()}

    def execute(self, plan: ReleasePlan) -> StageExecutionResult:
        verified: list[str] = []
        for source in REQUIRED_SOURCES:
            expected = _load_manifest(self.manifests[source])
            _validate_manifest_payload(expected, plan)
            result = self.providers[source].inspect(UPDATE_MANIFEST_ASSET)
            publish_stage = next(
                (
                    item
                    for item in plan.stages
                    if item.stage_id == f"program.publish_manifest.{source}"
                ),
                None,
            )
            published_id = (
                publish_stage.output_summary.get("remote_id")
                if publish_stage is not None
                else None
            )
            if (
                not result.exists
                or not result.remote_id
                or str(result.remote_id) != str(published_id)
            ):
                raise ReleaseStageError(
                    f"{source} final manifest attachment record changed",
                    status=ReleaseStatus.DEGRADED,
                )
            verified.append(source)
        return StageExecutionResult(
            {"verified": verified},
            {"all_manifests_verified": len(verified) == len(REQUIRED_SOURCES)},
        )


def program_release_stages(
    providers: dict[str, RemoteReleaseProvider],
    manifests: dict[str, Path],
    *,
    module_providers: dict[str, RemoteReleaseProvider] | None = None,
    checkpoint: Callable[[ReleasePlan], None] | None = None,
) -> tuple[object, ...]:
    """Build the canonical, safely resumable program release stage sequence."""
    _validate_providers(providers)
    if module_providers is None:
        module_providers = providers
    else:
        _validate_providers(module_providers)
    return (
        UploadProgramPackagesStage(providers, checkpoint=checkpoint),
        UploadProgramModulesStage(module_providers, checkpoint=checkpoint),
        PublishProgramManifestStage(
            "gitlink",
            providers["gitlink"],
            manifests["gitlink"],
            order=30,
            checkpoint=checkpoint,
        ),
        PublishProgramManifestStage(
            "github",
            providers["github"],
            manifests["github"],
            order=40,
            checkpoint=checkpoint,
        ),
        VerifyProgramManifestsStage(providers, manifests),
    )
