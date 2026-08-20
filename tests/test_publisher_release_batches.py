from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from signriver_publisher.artifact_collector import (
    ArtifactCollector,
    fingerprint_artifact,
)
from signriver_publisher.release_models import (
    CheckResult,
    InvalidReleaseTransition,
    PreflightCheck,
    ReleaseArtifact,
    ReleaseKind,
    ReleasePlan,
    ReleaseStatus,
)
from signriver_publisher.release_preflight import ReleasePreflightService
from signriver_publisher.release_service import ReleaseService
from signriver_publisher.release_store import CorruptReleaseError, ReleaseStore


def _write_program_package(
    path: Path,
    *,
    platform: str,
    version: str = "0.2.0",
    architecture: str = "x64",
) -> Path:
    manifest = {
        "schema_version": 1,
        "version": version,
        "target_platform": platform,
        "target_arch": architecture,
        "files": [],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("release-manifest.json", json.dumps(manifest))
        archive.writestr("payload.txt", platform)
    module_archive = path.parent / f"SignRiver-DLC-Hub-module-v{version}.zip"
    with zipfile.ZipFile(module_archive, "w") as archive:
        archive.writestr(
            "module.json",
            json.dumps({"version": version, "entrypoint": "app_entry.py"}),
        )
        archive.writestr("app_entry.py", "pass")
    return path


def _collect_program_artifacts(directory: Path, *, version: str) -> list[ReleaseArtifact]:
    collector = ArtifactCollector()
    return (
        collector.collect_program_packages(directory, version=version)
        + collector.collect_program_module_artifacts(directory, version=version)
    )


def test_release_plan_round_trip_and_centralized_transition() -> None:
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="batch-1"
    )
    plan.artifacts.append(ReleaseArtifact(role="windows_full", filename="windows.zip"))
    plan.preflight.append(PreflightCheck("check", "test", CheckResult.PASS, True, "ok"))

    restored = ReleasePlan.from_dict(plan.to_dict())

    assert restored == plan
    plan.transition_to(ReleaseStatus.AWAITING_CONFIRMATION)
    with pytest.raises(InvalidReleaseTransition):
        plan.transition_to(ReleaseStatus.COMPLETED)


def test_store_creates_atomic_documents_and_append_only_redacted_events(
    tmp_path: Path,
) -> None:
    store = ReleaseStore(tmp_path)
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="batch-1"
    )
    store.create(plan)

    from signriver_publisher.release_models import ReleaseEvent

    store.append_event(
        ReleaseEvent(
            batch_id=plan.batch_id,
            event_type="upload",
            context={"token": "secret", "safe": "value"},
        )
    )
    restored = store.load(plan.batch_id)
    events = store.read_events(plan.batch_id)

    assert restored.batch_id == plan.batch_id
    assert restored.event_ids
    assert [event.event_type for event in events] == ["release_created", "upload"]
    assert events[-1].context == {"safe": "value", "token": "[REDACTED]"}
    assert not list((tmp_path / "releases" / plan.batch_id).glob("*.tmp"))


def test_store_marks_running_batches_interrupted_after_restart(tmp_path: Path) -> None:
    store = ReleaseStore(tmp_path)
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="batch-1"
    )
    store.create(plan)
    plan.transition_to(ReleaseStatus.AWAITING_CONFIRMATION)
    plan.transition_to(ReleaseStatus.RUNNING)
    store.save(plan)

    recovered = store.recover_interrupted()

    assert [item.batch_id for item in recovered] == [plan.batch_id]
    restored = store.load(plan.batch_id)
    assert restored.status is ReleaseStatus.INTERRUPTED
    assert restored.recovery["reason"] == "publisher_restarted_while_running"
    assert store.read_events(plan.batch_id)[-1].event_type == "release_interrupted"


def test_load_all_isolates_a_corrupt_batch_without_hiding_valid_batches(
    tmp_path: Path,
) -> None:
    store = ReleaseStore(tmp_path)
    store.create(
        ReleasePlan.create(ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="valid")
    )
    corrupt = tmp_path / "releases" / "broken"
    corrupt.mkdir()
    (corrupt / "plan.json").write_text("{not-json", encoding="utf-8")

    plans = store.load_all()

    assert [plan.batch_id for plan in plans] == ["valid"]
    assert not corrupt.exists()
    assert len(list((tmp_path / "releases" / "_corrupt").iterdir())) == 1


def test_collector_discovers_three_native_program_packages(tmp_path: Path) -> None:
    for platform in ("windows", "steamos", "macos"):
        _write_program_package(
            tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip",
            platform=platform,
        )
    (tmp_path / "SignRiver-DLC-Hub-full-v0.1.7-windows-x64.zip").write_bytes(b"old")

    artifacts = ArtifactCollector().collect_program_packages(tmp_path, version="0.2.0")

    assert {item.role for item in artifacts} == {
        "windows_full",
        "steamos_full",
        "macos_full",
    }
    assert all(item.sha256 and item.size and item.modified_ns for item in artifacts)


def test_preflight_invalidates_changed_fingerprint(tmp_path: Path) -> None:
    package = tmp_path / "SignRiver-DLC-Hub-full-v0.2.0-windows-x64.zip"
    package.write_bytes(b"first")
    artifact = fingerprint_artifact(
        package,
        role="windows_full",
        platform="windows",
        architecture="x64",
        version="0.2.0",
    )
    plan = ReleasePlan.create(ReleaseKind.PROGRAM, {"version": "0.2.0"})
    plan.artifacts = [artifact]
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "测试更新。建议尽快更新。"
    service = ReleasePreflightService()

    checks = service.run(plan)
    assert plan.status is ReleaseStatus.PREFLIGHT_FAILED
    assert any(
        check.check_id == "program.platform_packages"
        and check.result is CheckResult.FAIL
        for check in checks
    )

    package.write_bytes(b"second-content")
    os.utime(package, None)
    checks = service.run(plan)
    changed = next(
        check for check in checks if check.check_id == "artifacts.fingerprints"
    )
    assert changed.result is CheckResult.FAIL


def test_preflight_rejects_program_package_that_is_not_a_zip(tmp_path: Path) -> None:
    for platform in ("windows", "steamos", "macos"):
        path = tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip"
        if platform == "windows":
            path.write_bytes(b"not-a-zip")
        else:
            _write_program_package(path, platform=platform)
    plan = ReleasePlan.create(ReleaseKind.PROGRAM, {"version": "0.2.0"})
    plan.artifacts = _collect_program_artifacts(tmp_path, version="0.2.0")
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "说明。建议尽快更新。"

    checks = ReleasePreflightService().run(plan)

    structure = next(check for check in checks if check.check_id == "program.package_structure")
    assert structure.result is CheckResult.FAIL
    assert structure.hard_gate is True
    assert "windows_full" in structure.evidence["errors"]
    assert plan.status is ReleaseStatus.PREFLIGHT_FAILED


def test_preflight_rejects_non_object_program_manifest(tmp_path: Path) -> None:
    for platform in ("windows", "steamos", "macos"):
        path = tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip"
        if platform == "windows":
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("release-manifest.json", "[]")
        else:
            _write_program_package(path, platform=platform)
    plan = ReleasePlan.create(ReleaseKind.PROGRAM, {"version": "0.2.0"})
    plan.artifacts = _collect_program_artifacts(tmp_path, version="0.2.0")
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "说明。建议尽快更新。"

    checks = ReleasePreflightService().run(plan)

    structure = next(check for check in checks if check.check_id == "program.package_structure")
    assert structure.result is CheckResult.FAIL
    assert "windows_full" in structure.evidence["errors"]
    assert plan.status is ReleaseStatus.PREFLIGHT_FAILED


def test_preflight_rejects_embedded_program_platform_mismatch(tmp_path: Path) -> None:
    for platform in ("windows", "steamos", "macos"):
        embedded_platform = "macos" if platform == "windows" else platform
        _write_program_package(
            tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip",
            platform=embedded_platform,
        )
    plan = ReleasePlan.create(ReleaseKind.PROGRAM, {"version": "0.2.0"})
    plan.artifacts = _collect_program_artifacts(tmp_path, version="0.2.0")
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "说明。建议尽快更新。"

    checks = ReleasePreflightService().run(plan)

    structure = next(check for check in checks if check.check_id == "program.package_structure")
    assert structure.result is CheckResult.FAIL
    assert structure.hard_gate is True
    assert "windows_full" in structure.evidence["errors"]
    assert plan.status is ReleaseStatus.PREFLIGHT_FAILED


def test_store_rejects_corrupt_schema(tmp_path: Path) -> None:
    store = ReleaseStore(tmp_path)
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="batch-1"
    )
    store.create(plan)
    path = tmp_path / "releases" / "batch-1" / "plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorruptReleaseError):
        store.load("batch-1")


class _SuccessfulStage:
    stage_id = "upload_packages"
    display_name = "上传程序包"
    order = 10
    safe_checkpoint = True

    def execute(self, plan: ReleasePlan):
        from signriver_publisher.release_interfaces import StageExecutionResult

        return StageExecutionResult(
            output_summary={"count": len(plan.artifacts)}, verification={"ok": True}
        )


def test_orchestrator_requires_current_confirmation_and_completes(
    tmp_path: Path,
) -> None:
    from signriver_publisher.release_orchestrator import ReleaseOrchestrator

    packages = []
    for platform in ("windows", "steamos", "macos"):
        path = tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip"
        packages.append(_write_program_package(path, platform=platform))
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="batch-1"
    )
    plan.artifacts = _collect_program_artifacts(tmp_path, version="0.2.0")
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "测试更新。建议尽快更新。"
    store = ReleaseStore(tmp_path / "workspace")
    store.create(plan)
    orchestrator = ReleaseOrchestrator(store)

    orchestrator.run_preflight(plan)
    assert plan.status is ReleaseStatus.AWAITING_CONFIRMATION
    orchestrator.confirm(plan, actor="tester", skipped_acceptance_reason="自动化测试")
    orchestrator.execute(plan, [_SuccessfulStage()])

    restored = store.load(plan.batch_id)
    assert restored.status is ReleaseStatus.COMPLETED
    assert restored.stages[0].status.value == "succeeded"
    assert restored.stages[0].verification == {"ok": True}


def test_orchestrator_rejects_file_changed_after_confirmation(tmp_path: Path) -> None:
    from signriver_publisher.release_orchestrator import (
        ReleaseOrchestrationError,
        ReleaseOrchestrator,
    )

    for platform in ("windows", "steamos", "macos"):
        _write_program_package(
            tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip",
            platform=platform,
        )
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="batch-1"
    )
    plan.artifacts = _collect_program_artifacts(tmp_path, version="0.2.0")
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "测试更新。建议尽快更新。"
    store = ReleaseStore(tmp_path / "workspace")
    store.create(plan)
    orchestrator = ReleaseOrchestrator(store)
    orchestrator.run_preflight(plan)
    orchestrator.confirm(plan, actor="tester", skipped_acceptance_reason="自动化测试")
    Path(plan.artifacts[0].local_path).write_bytes(b"changed-after-confirmation")

    with pytest.raises(ReleaseOrchestrationError):
        orchestrator.execute(plan, [_SuccessfulStage()])

    assert plan.status is ReleaseStatus.DRAFT
    assert not plan.confirmation
    assert not plan.preflight


class _FakeProvider:
    def __init__(
        self,
        source_id: str,
        *,
        fail_upload: bool = False,
        fail_manifest: bool = False,
        timeout_upload: bool = False,
    ) -> None:
        self.source_id = source_id
        self.fail_upload = fail_upload
        self.fail_manifest = fail_manifest
        self.timeout_upload = timeout_upload
        self.assets = {}
        self.upload_calls = 0
        self.manifest_calls = 0

    def inspect(self, remote_key):
        from signriver_publisher.release_interfaces import RemoteVerification

        return self.assets.get(remote_key, RemoteVerification(False))

    def upload(self, artifact, local_path):
        from signriver_publisher.release_interfaces import RemoteVerification

        self.upload_calls += 1
        if self.timeout_upload:
            raise TimeoutError("simulated timeout")
        result = RemoteVerification(
            not self.fail_upload, artifact.size, artifact.sha256
        )
        if not self.fail_upload:
            self.assets[artifact.filename] = result
        return result

    def publish_index(self, plan, local_path):
        import hashlib

        from signriver_publisher.release_interfaces import RemoteVerification

        self.manifest_calls += 1
        if self.fail_manifest:
            raise TimeoutError("simulated manifest timeout")
        payload = Path(local_path).read_bytes()
        result = RemoteVerification(
            True,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            evidence={"manifest": json.loads(payload)},
        )
        self.assets[Path(local_path).name] = result
        return result


def _program_plan(tmp_path: Path, *, batch_id: str = "program"):
    for platform in ("windows", "steamos", "macos"):
        _write_program_package(
            tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip",
            platform=platform,
        )
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id=batch_id
    )
    plan.artifacts = _collect_program_artifacts(tmp_path, version="0.2.0")
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "说明。建议尽快更新。"
    plan.options = {"mandatory": False}
    return plan


def _program_manifests(tmp_path: Path, plan: ReleasePlan) -> dict[str, Path]:
    platform_keys = {
        "windows_full": "windows-x64",
        "steamos_full": "steamos-x64",
        "macos_full": "macos-x64",
    }
    artifacts = {item.role: item for item in plan.artifacts}
    manifests = {}
    for source in ("gitlink", "github"):
        payload = {
            "schema_version": 1,
            "channel": "stable",
            "generated_at": "2026-08-17T00:00:00Z",
            "releases": [
                {
                    "version": "0.2.0",
                    "kind": "full",
                    "min_launcher_version": "0.1.2",
                    "package_url": f"https://example.invalid/{source}/windows.zip",
                    "sha256": artifacts["windows_full"].sha256,
                    "size": artifacts["windows_full"].size,
                    "mandatory": False,
                    "notes": plan.notes,
                    "installer_version": 1,
                    "platform_packages": {
                        platform_key: {
                            "package_url": f"https://example.invalid/{source}/{artifact.filename}",
                            "sha256": artifact.sha256,
                            "size": artifact.size,
                        }
                        for role, platform_key in platform_keys.items()
                        for artifact in (artifacts[role],)
                    },
                }
            ],
        }
        path = tmp_path / source / "update-manifest.json"
        path.parent.mkdir()
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        manifests[source] = path
    return manifests


def _confirmed_program(tmp_path: Path, *, batch_id: str = "program"):
    from signriver_publisher.release_orchestrator import ReleaseOrchestrator

    plan = _program_plan(tmp_path, batch_id=batch_id)
    manifests = _program_manifests(tmp_path, plan)
    store = ReleaseStore(tmp_path / "ws")
    store.create(plan)
    orchestrator = ReleaseOrchestrator(store)
    orchestrator.run_preflight(plan)
    orchestrator.confirm(plan, actor="tester", skipped_acceptance_reason="自动化测试")
    return plan, manifests, store, orchestrator


def test_program_pipeline_never_switches_manifest_before_both_sources_ready(
    tmp_path: Path,
) -> None:
    from signriver_publisher.program_release_pipeline import program_release_stages

    plan, manifests, _store, orchestrator = _confirmed_program(tmp_path)
    good = _FakeProvider("gitlink")
    bad = _FakeProvider("github", fail_upload=True)

    with pytest.raises(Exception, match="verification failed"):
        orchestrator.execute(
            plan,
            program_release_stages(
                {"gitlink": good, "github": bad},
                manifests,
                checkpoint=orchestrator.checkpoint,
            ),
        )

    assert plan.status is ReleaseStatus.FAILED
    assert good.manifest_calls == bad.manifest_calls == 0


def test_program_pipeline_reuploads_remote_packages_with_matching_hash(
    tmp_path: Path,
) -> None:
    from signriver_publisher.program_release_pipeline import program_release_stages
    from signriver_publisher.release_interfaces import RemoteVerification

    plan, manifests, _store, orchestrator = _confirmed_program(tmp_path)
    providers = {source: _FakeProvider(source) for source in ("gitlink", "github")}
    for provider in providers.values():
        for artifact in plan.artifacts:
            provider.assets[artifact.filename] = RemoteVerification(
                True, artifact.size, artifact.sha256
            )

    orchestrator.execute(
        plan,
        program_release_stages(
            providers, manifests, checkpoint=orchestrator.checkpoint
        ),
    )

    assert plan.status is ReleaseStatus.COMPLETED
    assert all(provider.upload_calls == 4 for provider in providers.values())
    upload = next(
        item for item in plan.stages if item.stage_id == "program.upload_packages"
    )
    assert not any(item["reused"] for item in upload.output_summary["details"].values())


def test_program_pipeline_timeout_fails_before_manifest_switch(tmp_path: Path) -> None:
    from signriver_publisher.program_release_pipeline import program_release_stages

    plan, manifests, _store, orchestrator = _confirmed_program(tmp_path)
    providers = {
        "gitlink": _FakeProvider("gitlink"),
        "github": _FakeProvider("github", timeout_upload=True),
    }

    with pytest.raises(TimeoutError):
        orchestrator.execute(plan, program_release_stages(providers, manifests))

    assert plan.status is ReleaseStatus.FAILED
    assert all(provider.manifest_calls == 0 for provider in providers.values())


def test_partial_manifest_failure_is_degraded_and_resume_only_fills_failed_source(
    tmp_path: Path,
) -> None:
    from signriver_publisher.program_release_pipeline import program_release_stages

    plan, manifests, _store, orchestrator = _confirmed_program(tmp_path)
    gitlink = _FakeProvider("gitlink")
    github = _FakeProvider("github", fail_manifest=True)
    providers = {"gitlink": gitlink, "github": github}
    stages = program_release_stages(providers, manifests)

    with pytest.raises(Exception, match="github manifest publish failed"):
        orchestrator.execute(plan, stages)

    assert plan.status is ReleaseStatus.DEGRADED
    assert gitlink.manifest_calls == 1
    initial_upload_calls = (gitlink.upload_calls, github.upload_calls)
    github.fail_manifest = False
    orchestrator.execute(plan, stages)

    assert plan.status is ReleaseStatus.COMPLETED
    assert gitlink.manifest_calls == 1
    assert github.manifest_calls == 2
    assert (gitlink.upload_calls, github.upload_calls) == initial_upload_calls


def test_running_batch_recovers_and_retries_only_interrupted_stage(
    tmp_path: Path,
) -> None:
    from signriver_publisher.release_interfaces import StageExecutionResult
    from signriver_publisher.release_orchestrator import ReleaseOrchestrator

    plan, _manifests, store, orchestrator = _confirmed_program(tmp_path)

    class CrashStage:
        stage_id = "crash"
        display_name = "crash"
        order = 1
        safe_checkpoint = True

        def execute(self, plan):
            raise KeyboardInterrupt("simulated process death")

    with pytest.raises(KeyboardInterrupt):
        orchestrator.execute(plan, [CrashStage()])
    recovered = store.recover_interrupted()
    assert recovered[0].status is ReleaseStatus.INTERRUPTED

    class ResumeStage(CrashStage):
        def execute(self, plan):
            return StageExecutionResult({"resumed": True}, {"ok": True})

    restored = store.load(plan.batch_id)
    ReleaseOrchestrator(store).execute(restored, [ResumeStage()])
    assert restored.status is ReleaseStatus.COMPLETED
    assert restored.stages[0].attempts == 2


def test_pause_request_is_applied_at_next_safe_checkpoint(tmp_path: Path) -> None:
    from signriver_publisher.release_interfaces import StageExecutionResult

    plan, _manifests, _store, orchestrator = _confirmed_program(tmp_path)

    class RequestPauseStage:
        stage_id = "request-pause"
        display_name = "request pause"
        order = 1
        safe_checkpoint = True

        def execute(self, current):
            orchestrator.request_pause(current)
            return StageExecutionResult()

    class MustNotRunStage(RequestPauseStage):
        stage_id = "must-not-run"
        order = 2

        def execute(self, current):
            raise AssertionError("stage ran after pause request")

    result = orchestrator.execute(plan, [RequestPauseStage(), MustNotRunStage()])

    assert result.status is ReleaseStatus.PAUSED
    assert result.stages[0].status.value == "succeeded"
    assert result.stages[1].status.value == "pending"


def test_manual_acceptance_is_reference_only_and_is_audited(tmp_path: Path) -> None:
    from signriver_publisher.release_orchestrator import ReleaseOrchestrator

    for platform in ("windows", "steamos", "macos"):
        _write_program_package(
            tmp_path / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip",
            platform=platform,
        )
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="acceptance-gate"
    )
    plan.artifacts = _collect_program_artifacts(tmp_path, version="0.2.0")
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    plan.notes = "说明。建议尽快更新。"
    store = ReleaseStore(tmp_path / "workspace")
    store.create(plan)
    orchestrator = ReleaseOrchestrator(store)

    orchestrator.run_preflight(plan)
    acceptance = next(
        check for check in plan.preflight if check.check_id == "human.acceptance"
    )
    assert acceptance.result is CheckResult.WARNING
    orchestrator.confirm(plan, actor="tester")

    assert plan.confirmation["acceptance_result"] == "warning"
    assert plan.confirmation["acceptance_snapshot_attached"] is False
    assert plan.confirmation["acceptance_reference_only"] is True
    event = store.read_events(plan.batch_id)[-1]
    assert event.context["acceptance_reference_only"] is True
    assert event.context["acceptance_skipped"] is False


def test_complete_acceptance_snapshot_passes_without_skip_reason(tmp_path: Path) -> None:
    plan = ReleasePlan.create(
        ReleaseKind.GAME_CONTENT, {"game_id": "game", "release_tag": "v1"}, batch_id="accepted"
    )
    plan.options["acceptance_snapshot"] = {
        "result": {
            "version": 1,
            "results": {
                "launch": {"status": "passed"},
                "update": {"status": "passed"},
            },
        }
    }
    plan.remote_targets = {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}
    attachment = tmp_path / "asset.zip"
    attachment.write_bytes(b"asset")
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    plan.artifacts = [
        fingerprint_artifact(attachment, role="content_attachment"),
        fingerprint_artifact(catalog, role="catalog"),
    ]
    store = ReleaseStore(tmp_path / "workspace")
    store.create(plan)
    from signriver_publisher.release_orchestrator import ReleaseOrchestrator

    orchestrator = ReleaseOrchestrator(store)
    orchestrator.run_preflight(plan)
    acceptance = next(
        check for check in plan.preflight if check.check_id == "human.acceptance"
    )
    assert acceptance.result is CheckResult.PASS
    orchestrator.confirm(plan, actor="tester")
    assert "skipped_acceptance_reason" not in plan.confirmation
    assert plan.confirmation["acceptance_result"] == "pass"
    assert plan.confirmation["acceptance_snapshot_attached"] is True
    assert plan.confirmation["acceptance_reference_only"] is True



def test_store_migrates_legacy_schema_zero_documents_in_place(tmp_path: Path) -> None:
    store = ReleaseStore(tmp_path)
    plan = ReleasePlan.create(
        ReleaseKind.PROGRAM, {"version": "0.2.0"}, batch_id="legacy"
    )
    store.create(plan)
    directory = tmp_path / "releases" / "legacy"
    for name in ("plan.json", "artifacts.json", "preflight.json", "stages.json"):
        path = directory / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("schema_version", None)
        path.write_text(json.dumps(payload), encoding="utf-8")

    restored = store.load("legacy")

    assert restored.schema_version == 2
    assert restored.options["collection"] == {}
    assert restored.options["remote_baseline"] == {}
    for name in ("plan.json", "artifacts.json", "preflight.json", "stages.json"):
        payload = json.loads((directory / name).read_text(encoding="utf-8"))
        assert payload["schema_version"] == 2


def test_service_reuses_same_unexecuted_program_batch_and_archives_it(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox, notes="说明。建议尽快更新。",
        remote_targets={"gitlink": {"repo": "a"}, "github": {"repo": "b"}},
    )

    reusable = service.find_reusable_program_batch(version="0.2.0", inbox=inbox)
    archived = service.archive_unexecuted_batch(plan.batch_id)

    assert reusable is not None and reusable.batch_id == plan.batch_id
    assert archived.parent.name == "_archived"
    assert service.history() == []
    assert (archived / "events.jsonl").is_file()


def test_service_refuses_to_archive_batch_with_execution_history(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_program_batch(
        version="0.2.0", inbox=tmp_path / "inbox", notes="说明。建议尽快更新。",
        remote_targets={"gitlink": {"repo": "a"}, "github": {"repo": "b"}},
    )
    plan.transition_to(ReleaseStatus.AWAITING_CONFIRMATION)
    plan.transition_to(ReleaseStatus.RUNNING)
    service.store.save(plan)

    with pytest.raises(Exception, match="只能归档尚未执行"):
        service.archive_unexecuted_batch(plan.batch_id)
