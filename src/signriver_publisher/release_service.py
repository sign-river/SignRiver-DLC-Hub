"""Application service for persistent publisher release batches.

This module is deliberately UI-free.  It is the only entry point the release
center needs for collecting inputs, preflight, confirmation, execution and
recovery.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .artifact_collector import ArtifactCollector, fingerprint_artifact
from .program_release_pipeline import program_release_stages
from .content_release_pipeline import game_content_release_stages, hub_release_stages
from .release_interfaces import RemoteReleaseProvider
from .release_models import ReleaseEvent, ReleaseKind, ReleasePlan, ReleaseStatus, utc_now
from .release_orchestrator import ReleaseOrchestrator
from .release_store import ReleaseStore
from .updates import UPDATE_MANIFEST_ASSET, release_asset_url

_PROGRAM_ROLES = {
    "windows_full": ("windows", "windows-x64"),
    "steamos_full": ("steamos", "steamos-x64"),
    "macos_full": ("macos", "macos-x64"),
}
_SENSITIVE_TARGET_KEY_PARTS = (
    "token",
    "password",
    "passwd",
    "secret",
    "cookie",
    "authorization",
    "credential",
    "private_key",
    "access_key",
    "session_key",
)


class ReleaseServiceError(RuntimeError):
    """Raised when a release-center command cannot be applied safely."""


def _copy_remote_target_summaries(
    remote_targets: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    def reject_sensitive_keys(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key)
                if any(
                    part in key_text.casefold()
                    for part in _SENSITIVE_TARGET_KEY_PARTS
                ):
                    raise ReleaseServiceError(
                        f"远端目标只能保存非敏感摘要，禁止字段：{path}{key_text}"
                    )
                reject_sensitive_keys(item, f"{path}{key_text}.")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                reject_sensitive_keys(item, f"{path}{index}.")

    copied = {name: dict(value) for name, value in remote_targets.items()}
    reject_sensitive_keys(copied, "remote_targets.")
    return copied


class ReleaseService:
    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.store = ReleaseStore(self.workspace_root)
        self.collector = ArtifactCollector()
        self.orchestrator = ReleaseOrchestrator(self.store)
        self._upload_progress_lock = threading.Lock()
        self._upload_progress_samples: dict[tuple[str, str, str], tuple[int, float, float]] = {}
        self._upload_progress_last_saved: dict[tuple[str, str, str], float] = {}

    def recover_interrupted(self) -> list[ReleasePlan]:
        return self.store.recover_interrupted()

    def history(self) -> list[ReleasePlan]:
        return sorted(self.store.load_all(), key=lambda plan: plan.updated_at, reverse=True)

    def get(self, batch_id: str) -> ReleasePlan:
        return self.store.load(batch_id)

    def find_reusable_program_batch(self, *, version: str, inbox: Path | str) -> ReleasePlan | None:
        """Return the newest local program batch that has not produced remote side effects."""
        normalized_inbox = str(Path(inbox).resolve())
        reusable_statuses = {
            ReleaseStatus.DRAFT,
            ReleaseStatus.PREFLIGHT_FAILED,
            ReleaseStatus.AWAITING_CONFIRMATION,
        }
        for plan in self.history():
            if plan.kind is not ReleaseKind.PROGRAM or plan.status not in reusable_statuses:
                continue
            collection = plan.options.get("collection", {})
            existing_inbox = collection.get("inbox") if isinstance(collection, dict) else None
            if (
                str(plan.target.get("version") or "") == version
                and existing_inbox
                and str(Path(existing_inbox).resolve()) == normalized_inbox
            ):
                return plan
        return None

    def archive_unexecuted_batch(self, batch_id: str) -> Path:
        plan = self.get(batch_id)
        removable_statuses = {
            ReleaseStatus.DRAFT,
            ReleaseStatus.PREFLIGHT_FAILED,
            ReleaseStatus.AWAITING_CONFIRMATION,
        }
        if plan.status not in removable_statuses:
            raise ReleaseServiceError("只能归档尚未执行的草稿、预检失败或待确认批次；已有执行记录的批次会保留用于审计与恢复。")
        self._record_event(plan, "release_archived", {"reason": "user_removed_unexecuted_batch"})
        return self.store.archive(batch_id)

    def create_program_batch(
        self,
        *,
        version: str,
        inbox: Path | str | None = None,
        notes: str = "",
        mandatory: bool = True,
        min_launcher_version: str = "0.1.2",
        remote_targets: Mapping[str, Mapping[str, object]],
    ) -> ReleasePlan:
        version = version.strip()
        if not version:
            raise ReleaseServiceError("目标版本不能为空")
        collection_root = Path(inbox) if inbox is not None else self.default_program_inbox()
        plan = ReleasePlan.create(ReleaseKind.PROGRAM, {"version": version, "channel": "stable"})
        plan.artifacts = (
            self.collector.collect_program_packages(collection_root, version=version)
            + self.collector.collect_program_module_artifacts(collection_root, version=version)
        )
        plan.notes = notes.strip()
        plan.options = {
            "mandatory": bool(mandatory),
            "min_launcher_version": min_launcher_version.strip() or "0.1.2",
            "collection": {
                "inbox": str(collection_root.resolve()),
                "platforms": {role: "received" if any(item.role == role for item in plan.artifacts) else "pending" for role in _PROGRAM_ROLES},
                "modules": {
                    "count": sum(item.role == "module_archive" for item in plan.artifacts),
                    "files": [item.filename for item in plan.artifacts if item.role == "module_archive"],
                },
            },
            "remote_baseline": {},
        }
        plan.remote_targets = _copy_remote_target_summaries(remote_targets)
        return self.store.create(plan)


    def default_program_inbox(self) -> Path:
        """Default three-platform inbox; callers may always override it."""
        return self.workspace_root / "output" / "updates"

    def load_update_notes_draft(self, version: str) -> str:
        try:
            payload = json.loads((self.workspace_root / "update-notes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return ""
        value = payload.get(version) if isinstance(payload, dict) else None
        return value.strip() if isinstance(value, str) else ""

    def save_update_notes_draft(self, version: str, notes: str) -> None:
        version = version.strip()
        text = notes.strip()
        if not version:
            raise ReleaseServiceError("版本号不能为空")
        if not text:
            raise ReleaseServiceError("更新说明不能为空")
        path = self.workspace_root / "update-notes.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError, TypeError) as exc:
            raise ReleaseServiceError(f"无法读取更新说明草稿：{exc}") from exc
        if not isinstance(payload, dict):
            raise ReleaseServiceError("更新说明草稿必须是 JSON 对象")
        payload[version] = text
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def refresh_program_collection(self, batch_id: str, inbox: Path | str | None = None) -> ReleasePlan:
        plan = self.get(batch_id)
        if plan.kind is not ReleaseKind.PROGRAM:
            raise ReleaseServiceError("当前批次不是程序更新")
        if plan.status is ReleaseStatus.RUNNING or plan.status is ReleaseStatus.COMPLETED:
            raise ReleaseServiceError("运行中或已完成批次不能重新收件")
        root = Path(inbox) if inbox is not None else Path(str(plan.options.get("collection", {}).get("inbox") or self.default_program_inbox()))
        version = str(plan.target.get("version") or "")
        plan.artifacts = (
            self.collector.collect_program_packages(root, version=version)
            + self.collector.collect_program_module_artifacts(root, version=version)
        )
        plan.options["collection"] = {
            "inbox": str(root.resolve()),
            "platforms": {role: "received" if any(item.role == role for item in plan.artifacts) else "pending" for role in _PROGRAM_ROLES},
            "modules": {
                "count": sum(item.role == "module_archive" for item in plan.artifacts),
                "files": [item.filename for item in plan.artifacts if item.role == "module_archive"],
            },
            "refreshed_at": utc_now(),
        }
        plan.invalidate_inputs("program inbox refreshed")
        self.store.save(plan)
        self._record_event(plan, "program_collection_refreshed", {"artifact_count": len(plan.artifacts)})
        return plan

    def capture_remote_baseline(
        self, batch_id: str, providers: Mapping[str, RemoteReleaseProvider]
    ) -> ReleasePlan:
        """Persist a sanitized read-only snapshot; this never uploads or locks UI writes."""
        plan = self.get(batch_id)
        expected = set(plan.remote_targets)
        if set(providers) != expected:
            raise ReleaseServiceError("远端基线 provider 必须与批次双源目标完全一致")
        sources: dict[str, object] = {}
        for source, provider in providers.items():
            reader = getattr(provider, "read_baseline", None)
            if not callable(reader):
                raise ReleaseServiceError(f"{source} provider 不支持只读远端基线")
            sources[source] = reader()
        plan.options["remote_baseline"] = {"captured_at": utc_now(), "sources": sources}
        plan.invalidate_inputs("remote baseline refreshed")
        self.store.save(plan)
        self._record_event(plan, "remote_baseline_captured", {"sources": sorted(sources)})
        return plan

    def export_remote_baseline(self, batch_id: str, destination: Path | str) -> Path:
        plan = self.get(batch_id)
        baseline = plan.options.get("remote_baseline")
        if not isinstance(baseline, dict) or not baseline:
            raise ReleaseServiceError("当前批次尚未读取远端基线")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target

    def _record_event(self, plan: ReleasePlan, event_type: str, context: dict[str, object]) -> None:
        event = ReleaseEvent(batch_id=plan.batch_id, event_type=event_type, context=context)
        self.store.append_event(event)
        plan.event_ids.append(event.event_id)
        self.store.save(plan)

    def find_reusable_game_content_batch(
        self, *, game_id: str, release_tag: str, output_dir: Path | str
    ) -> ReleasePlan | None:
        """Return the newest unexecuted batch for the same built game output."""
        normalized_output = str(Path(output_dir).resolve())
        reusable_statuses = {
            ReleaseStatus.DRAFT,
            ReleaseStatus.PREFLIGHT_FAILED,
            ReleaseStatus.AWAITING_CONFIRMATION,
        }
        for plan in self.history():
            if plan.kind is not ReleaseKind.GAME_CONTENT or plan.status not in reusable_statuses:
                continue
            collection = plan.options.get("collection", {})
            existing_output = collection.get("output_dir") if isinstance(collection, dict) else None
            if (
                str(plan.target.get("game_id") or "") == game_id
                and str(plan.target.get("release_tag") or "") == release_tag
                and existing_output
                and str(Path(existing_output).resolve()) == normalized_output
            ):
                return plan
        return None

    def create_game_content_batch(
        self,
        *,
        game_id: str,
        release_tag: str,
        attachments: list[Path],
        catalog: Path,
        remote_targets: Mapping[str, Mapping[str, object]],
        output_dir: Path | str | None = None,
    ) -> ReleasePlan:
        game_id = game_id.strip()
        release_tag = release_tag.strip()
        if not game_id:
            raise ReleaseServiceError("游戏 ID 不能为空")
        if not release_tag:
            raise ReleaseServiceError("内容 Release 标签不能为空")
        if not attachments:
            raise ReleaseServiceError("至少需要一个内容附件")
        plan = ReleasePlan.create(
            ReleaseKind.GAME_CONTENT,
            {"game_id": game_id, "release_tag": release_tag},
        )
        plan.artifacts = [
            fingerprint_artifact(path, role="content_attachment")
            for path in attachments
        ] + [fingerprint_artifact(catalog, role="catalog")]
        collection_root = Path(output_dir) if output_dir is not None else catalog.parent
        plan.options = {
            "collection": {
                "output_dir": str(collection_root.resolve()),
                "attachment_count": len(attachments),
                "catalog": catalog.name,
            },
            "remote_baseline": {},
        }
        plan.remote_targets = _copy_remote_target_summaries(remote_targets)
        return self.store.create(plan)

    def create_hub_batch(
        self,
        *,
        attachments: list[Path],
        hub_index: Path,
        remote_targets: Mapping[str, Mapping[str, object]],
    ) -> ReleasePlan:
        if not attachments:
            raise ReleaseServiceError("至少需要一个 Hub 快照或公告附件")
        plan = ReleasePlan.create(ReleaseKind.HUB_ANNOUNCEMENT, {"scope": "hub"})
        plan.artifacts = [
            fingerprint_artifact(path, role="hub_snapshot")
            for path in attachments
        ] + [fingerprint_artifact(hub_index, role="hub_index")]
        plan.remote_targets = _copy_remote_target_summaries(remote_targets)
        return self.store.create(plan)

    def replace_program_artifact(self, batch_id: str, role: str, path: Path | str) -> ReleasePlan:
        if role not in _PROGRAM_ROLES:
            raise ReleaseServiceError(f"未知程序包角色：{role}")
        plan = self.get(batch_id)
        if plan.kind is not ReleaseKind.PROGRAM:
            raise ReleaseServiceError("当前批次不是程序更新")
        platform, _platform_key = _PROGRAM_ROLES[role]
        replacement = fingerprint_artifact(
            Path(path), role=role, platform=platform, architecture="x64",
            version=str(plan.target.get("version") or ""),
        )
        plan.artifacts = [item for item in plan.artifacts if item.role != role]
        plan.artifacts.append(replacement)
        collection = dict(plan.options.get("collection") or {})
        platforms = dict(collection.get("platforms") or {})
        platforms[role] = "received"
        collection["platforms"] = platforms
        collection["refreshed_at"] = utc_now()
        plan.options["collection"] = collection
        plan.invalidate_inputs(f"artifact replaced: {role}")
        self.store.save(plan)
        return plan

    def preflight(self, batch_id: str) -> ReleasePlan:
        return self.orchestrator.run_preflight(self.get(batch_id))

    def confirm(
        self,
        batch_id: str,
        *,
        actor: str = "publisher-ui",
        skipped_acceptance_reason: str | None = None,
    ) -> ReleasePlan:
        plan = self.get(batch_id)
        self.orchestrator.confirm(
            plan,
            actor=actor,
            skipped_acceptance_reason=skipped_acceptance_reason,
        )
        return plan

    def prepare_program_manifests(self, batch_id: str) -> dict[str, Path]:
        plan = self.get(batch_id)
        if plan.kind is not ReleaseKind.PROGRAM:
            raise ReleaseServiceError("当前批次不是程序更新")
        artifacts = {item.role: item for item in plan.artifacts}
        missing = set(_PROGRAM_ROLES) - artifacts.keys()
        if missing:
            raise ReleaseServiceError(f"缺少程序包：{', '.join(sorted(missing))}")
        root = self.workspace_root / "releases" / plan.batch_id / "prepared"
        manifests: dict[str, Path] = {}
        for source in ("gitlink", "github"):
            target = plan.remote_targets.get(source) or {}
            owner = str(target.get("owner") or "").strip()
            repository = str(target.get("repository") or target.get("repo") or "").strip()
            if not owner or not repository:
                raise ReleaseServiceError(f"{source} 目标缺少 owner/repository")
            platform_packages = {}
            for role, (_platform, platform_key) in _PROGRAM_ROLES.items():
                artifact = artifacts[role]
                platform_packages[platform_key] = {
                    "package_url": release_asset_url(source, owner, repository, artifact.filename),
                    "sha256": artifact.sha256,
                    "size": artifact.size,
                }
            windows = artifacts["windows_full"]
            release = {
                "version": str(plan.target.get("version") or ""),
                "kind": "full",
                "min_launcher_version": str(plan.options.get("min_launcher_version") or "0.1.2"),
                "package_url": platform_packages["windows-x64"]["package_url"],
                "sha256": windows.sha256,
                "size": windows.size,
                "mandatory": bool(plan.options.get("mandatory", True)),
                "notes": plan.notes,
                "installer_version": 1,
                "platform_packages": platform_packages,
            }
            payload = {
                "schema_version": 1,
                "channel": str(plan.target.get("channel") or "stable"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "releases": [release],
            }
            path = root / source / UPDATE_MANIFEST_ASSET
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
            manifests[source] = path
        return manifests

    def _bind_upload_progress(
        self, plan: ReleasePlan, provider_sets: tuple[Mapping[str, RemoteReleaseProvider], ...]
    ) -> None:
        """Persist a throttled, credential-free sample from the active provider."""

        def report(source: str, artifact, sent: int, total: int) -> None:
            now = time.monotonic()
            sent_value = max(0, int(sent))
            total_value = max(0, int(total))
            key = (plan.batch_id, source, artifact.filename)
            with self._upload_progress_lock:
                previous = self._upload_progress_samples.get(key)
                speed = 0.0
                if previous is not None:
                    previous_sent, previous_at, previous_speed = previous
                    elapsed = now - previous_at
                    if sent_value >= previous_sent and elapsed > 0:
                        instant = (sent_value - previous_sent) / elapsed
                        speed = instant if previous_speed <= 0 else (previous_speed * 0.65 + instant * 0.35)
                self._upload_progress_samples[key] = (sent_value, now, speed)
                last_saved = self._upload_progress_last_saved.get(key, 0.0)
                if sent_value != total_value and now - last_saved < 0.20:
                    return
                self._upload_progress_last_saved[key] = now
                plan.options["upload_progress"] = {
                    "source": source,
                    "filename": artifact.filename,
                    "sent": sent_value,
                    "total": total_value,
                    "bytes_per_second": round(speed, 1),
                    "updated_at": utc_now(),
                }
                self.store.save(plan)

        seen: set[int] = set()
        for providers in provider_sets:
            for provider in providers.values():
                provider_id = id(provider)
                if provider_id in seen:
                    continue
                seen.add(provider_id)
                setter = getattr(provider, "set_upload_progress_reporter", None)
                if callable(setter):
                    setter(report)

    def execute_program(
        self,
        batch_id: str,
        providers: Mapping[str, RemoteReleaseProvider],
        module_providers: Mapping[str, RemoteReleaseProvider] | None = None,
    ) -> ReleasePlan:
        plan = self.get(batch_id)
        if plan.kind is not ReleaseKind.PROGRAM:
            raise ReleaseServiceError("当前批次不是程序更新")
        manifests = self.prepare_program_manifests(batch_id)
        module_artifacts = [item for item in plan.artifacts if item.role == "module_archive"]
        if module_artifacts and module_providers is None:
            raise ReleaseServiceError("批次包含模块归档，但未提供 modules Release 的双源 provider")
        self._bind_upload_progress(
            plan,
            (dict(providers),) + ((dict(module_providers),) if module_providers is not None else ()),
        )
        stages = program_release_stages(
            dict(providers), manifests,
            module_providers=(dict(module_providers) if module_providers is not None else None),
            checkpoint=self.orchestrator.checkpoint,
        )
        return self.orchestrator.execute(plan, stages)

    def execute_game_content(
        self, batch_id: str, providers: Mapping[str, RemoteReleaseProvider]
    ) -> ReleasePlan:
        plan = self.get(batch_id)
        if plan.kind is not ReleaseKind.GAME_CONTENT:
            raise ReleaseServiceError("当前批次不是游戏内容发布")
        self._bind_upload_progress(plan, (providers,))
        return self.orchestrator.execute(
            plan,
            game_content_release_stages(
                providers, checkpoint=self.orchestrator.checkpoint
            ),
        )

    def execute_hub(
        self, batch_id: str, providers: Mapping[str, RemoteReleaseProvider]
    ) -> ReleasePlan:
        plan = self.get(batch_id)
        if plan.kind is not ReleaseKind.HUB_ANNOUNCEMENT:
            raise ReleaseServiceError("当前批次不是 Hub/公告发布")
        self._bind_upload_progress(plan, (providers,))
        return self.orchestrator.execute(
            plan,
            hub_release_stages(providers, checkpoint=self.orchestrator.checkpoint),
        )
    def request_pause(self, batch_id: str) -> ReleasePlan:
        plan = self.get(batch_id)
        self.orchestrator.request_pause(plan)
        return plan

    @staticmethod
    def progress_summary(plan: ReleasePlan) -> dict[str, object]:
        program_upload = next(
            (stage for stage in plan.stages if stage.stage_id == "program.upload_packages"), None
        )
        program_manifests = [
            stage for stage in plan.stages
            if stage.stage_id.startswith("program.publish_manifest.")
        ]
        program_verify = next(
            (stage for stage in plan.stages if stage.stage_id == "program.verify_manifests"), None
        )
        snapshot_upload = next(
            (stage for stage in plan.stages if stage.stage_id.endswith(".upload_snapshot")), None
        )
        snapshot_index = next(
            (stage for stage in plan.stages if stage.stage_id.endswith(".publish_index")), None
        )
        if plan.kind is ReleaseKind.PROGRAM:
            inputs_ready = bool(
                program_upload and program_upload.verification.get("all_packages_ready")
            )
            indexes_switched = sum(
                stage.status.value == "succeeded" for stage in program_manifests
            )
            remote_verified = bool(
                program_verify and program_verify.verification.get("all_manifests_verified")
            )
            target_label = str(plan.target.get("version") or "-")
        else:
            inputs_ready = bool(
                snapshot_upload
                and snapshot_upload.verification.get("all_snapshot_attachments_ready")
            )
            switched = (snapshot_index.output_summary.get("switched", []) if snapshot_index else [])
            indexes_switched = len(switched)
            remote_verified = bool(
                snapshot_index and snapshot_index.verification.get("all_indexes_verified")
            )
            target_label = str(
                plan.target.get("game_id") or plan.target.get("scope") or "-"
            )
        return {
            "batch_id": plan.batch_id,
            "kind": plan.kind.value,
            "status": plan.status.value,
            "target_label": target_label,
            "current_stage": next(
                (stage.display_name for stage in plan.stages if stage.status.value in {"running", "failed", "paused"}),
                "",
            ),
            "inputs_ready": inputs_ready,
            "indexes_switched": indexes_switched,
            "remote_verified": remote_verified,
        }
