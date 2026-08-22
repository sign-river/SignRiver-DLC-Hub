from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from signriver_publisher.release_interfaces import RemoteVerification
from signriver_publisher.release_models import ReleaseStageRecord, ReleaseStatus
from signriver_publisher.release_service import ReleaseService, ReleaseServiceError


def write_program_package(path: Path, *, platform: str, version: str = "0.2.0") -> Path:
    manifest = {
        "schema_version": 1,
        "version": version,
        "target_platform": platform,
        "target_arch": "x64",
        "files": [],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("release-manifest.json", json.dumps(manifest))
        archive.writestr("payload.txt", platform)
    return path


class MemoryProvider:
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self.assets: dict[str, RemoteVerification] = {}

    def inspect(self, remote_key: str) -> RemoteVerification:
        return self.assets.get(remote_key, RemoteVerification(False))

    def upload(self, artifact, local_path: Path) -> RemoteVerification:
        result = RemoteVerification(True, local_path.stat().st_size, artifact.sha256, artifact.filename)
        self.assets[artifact.filename] = result
        return result

    def read_baseline(self) -> dict[str, object]:
        return {"release_exists": bool(self.assets), "assets": sorted(self.assets)}

    def publish_index(self, plan, local_path: Path) -> RemoteVerification:
        payload = json.loads(local_path.read_text(encoding="utf-8"))
        result = RemoteVerification(
            True, local_path.stat().st_size, remote_id=f"{self.source_id}-manifest",
            evidence={"manifest": payload},
        )
        self.assets[local_path.name] = result
        return result


def make_inbox(root: Path, version: str = "0.2.0") -> Path:
    root.mkdir()
    for platform in ("windows", "steamos", "macos"):
        write_program_package(
            root / f"SignRiver-DLC-Hub-full-v{version}-{platform}-x64.zip",
            platform=platform,
            version=version,
        )
    return root


def targets():
    return {
        "gitlink": {"owner": "owner", "repository": "repo"},
        "github": {"owner": "owner", "repository": "repo"},
    }


def test_release_service_drives_program_batch_end_to_end(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    inbox = make_inbox(tmp_path / "inbox")
    write_module_archive(inbox / "SignRiver-DLC-Hub-module-v0.2.0.zip")
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox,
        notes="完成发布中心重构。建议尽快更新。", remote_targets=targets(),
    )
    assert {item.role for item in plan.artifacts} == {"windows_full", "steamos_full", "macos_full", "module_archive"}

    plan = service.preflight(plan.batch_id)
    assert plan.status is ReleaseStatus.AWAITING_CONFIRMATION
    service.confirm(plan.batch_id, actor="test", skipped_acceptance_reason="自动化测试")
    providers = {source: MemoryProvider(source) for source in ("gitlink", "github")}
    module_providers = {source: MemoryProvider(source) for source in ("gitlink", "github")}
    plan = service.execute_program(plan.batch_id, providers, module_providers)

    assert plan.status is ReleaseStatus.COMPLETED
    assert service.progress_summary(plan) == {
        "batch_id": plan.batch_id,
        "kind": "program",
        "status": "completed",
        "target_label": "0.2.0",
        "current_stage": "",
        "inputs_ready": True,
        "indexes_switched": 2,
        "remote_verified": True,
    }



class ProgressProvider(MemoryProvider):
    def set_upload_progress_reporter(self, reporter) -> None:
        self.reporter = reporter


def test_upload_progress_is_persisted_without_credentials(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    plan = service.create_program_batch(
        version="0.2.0",
        inbox=make_inbox(tmp_path / "inbox"),
        notes="progress",
        remote_targets=targets(),
    )
    provider = ProgressProvider("github")

    service._bind_upload_progress(plan, ({"github": provider},))
    artifact = plan.artifacts[0]
    provider.reporter("github", artifact, 4, 8)

    persisted = service.get(plan.batch_id).options["upload_progress"]
    assert persisted["source"] == "github"
    assert persisted["filename"] == artifact.filename
    assert persisted["sent"] == 4
    assert persisted["total"] == 8
    assert isinstance(persisted["bytes_per_second"], float)
    assert "token" not in persisted
    assert "updated_at" in persisted

def test_replacing_artifact_invalidates_preflight_and_confirmation(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    inbox = make_inbox(tmp_path / "inbox")
    write_module_archive(inbox / "SignRiver-DLC-Hub-module-v0.2.0.zip")
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox, notes="说明。建议尽快更新。", remote_targets=targets(),
    )
    service.preflight(plan.batch_id)
    service.confirm(plan.batch_id, skipped_acceptance_reason="自动化测试")
    replacement = tmp_path / "replacement.zip"
    replacement.write_bytes(b"replacement")

    plan = service.replace_program_artifact(plan.batch_id, "windows_full", replacement)

    assert plan.status is ReleaseStatus.DRAFT
    assert not plan.preflight
    assert not plan.confirmation
    assert next(item for item in plan.artifacts if item.role == "windows_full").filename == "replacement.zip"


def test_changing_module_archive_invalidates_confirmed_program_batch(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    inbox = make_inbox(tmp_path / "inbox")
    module = write_module_archive(inbox / "SignRiver-DLC-Hub-module-v0.2.0.zip")
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox, notes="说明。建议尽快更新。", remote_targets=targets(),
    )
    service.preflight(plan.batch_id)
    service.confirm(plan.batch_id, skipped_acceptance_reason="自动化测试")
    module.write_bytes(b"changed")

    with pytest.raises(RuntimeError, match="frozen inputs changed"):
        service.execute_program(
            plan.batch_id,
            {source: MemoryProvider(source) for source in ("gitlink", "github")},
            {source: MemoryProvider(source) for source in ("gitlink", "github")},
        )


def test_program_manifest_urls_are_source_specific(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    plan = service.create_program_batch(
        version="0.2.0", inbox=make_inbox(tmp_path / "inbox"),
        notes="说明。建议尽快更新。", remote_targets={
            "gitlink": {"owner": "gitlink-owner", "repository": "assets"},
            "github": {"owner": "github-owner", "repository": "assets"},
        },
    )
    manifests = service.prepare_program_manifests(plan.batch_id)
    gitlink = json.loads(manifests["gitlink"].read_text(encoding="utf-8"))
    github = json.loads(manifests["github"].read_text(encoding="utf-8"))
    assert "gitlink-owner" in gitlink["releases"][0]["package_url"]
    assert "github-owner" in github["releases"][0]["package_url"]
    assert gitlink["releases"][0]["platform_packages"].keys() == github["releases"][0]["platform_packages"].keys()


def test_execute_program_rejects_non_program_batch_before_preparation(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    attachment = tmp_path / "asset.zip"
    attachment.write_bytes(b"asset")
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    plan = service.create_game_content_batch(
        game_id="game",
        release_tag="v1",
        attachments=[attachment],
        catalog=catalog,
        remote_targets=targets(),
    )

    with pytest.raises(RuntimeError, match="不是程序更新"):
        service.execute_program(plan.batch_id, {})
    assert not (
        tmp_path / "workspace" / "releases" / plan.batch_id / "prepared"
    ).exists()

def test_batch_creation_rejects_credentials_in_remote_target_summary(
    tmp_path: Path,
) -> None:
    service = ReleaseService(tmp_path / "workspace")

    with pytest.raises(ReleaseServiceError, match="非敏感摘要"):
        service.create_program_batch(
            version="0.2.0",
            inbox=make_inbox(tmp_path / "inbox"),
            notes="说明。建议尽快更新。",
            remote_targets={
                "gitlink": {"owner": "a", "repository": "b"},
                "github": {
                    "owner": "c",
                    "repository": "d",
                    "credentials": {"access_token": "must-not-persist"},
                },
            },
        )

    assert service.history() == []




def write_module_archive(path: Path, *, version: str = "0.2.0") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("module.json", json.dumps({"version": version, "entrypoint": "app_entry.py"}))
        archive.writestr("app_entry.py", "pass")
    return path


def test_program_batch_can_start_empty_and_refresh_collection(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    inbox = tmp_path / "inbox"
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox, notes="说明。建议尽快更新。", remote_targets=targets(),
    )
    assert not plan.artifacts
    assert set(plan.options["collection"]["platforms"].values()) == {"pending"}

    make_inbox(inbox)
    plan = service.refresh_program_collection(plan.batch_id)
    assert plan.status is ReleaseStatus.DRAFT
    assert {item.role for item in plan.artifacts} == {"windows_full", "steamos_full", "macos_full"}


def test_program_batch_collects_and_uploads_module_archives(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    inbox = make_inbox(tmp_path / "inbox")
    write_module_archive(inbox / "SignRiver-DLC-Hub-module-v0.2.0.zip")
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox, notes="说明。建议尽快更新。", remote_targets=targets(),
    )
    assert [item.role for item in plan.artifacts].count("module_archive") == 1
    service.preflight(plan.batch_id)
    service.confirm(plan.batch_id)
    update_providers = {source: MemoryProvider(source) for source in ("gitlink", "github")}
    with pytest.raises(ReleaseServiceError, match="modules Release"):
        service.execute_program(plan.batch_id, update_providers)
    module_providers = {source: MemoryProvider(source) for source in ("gitlink", "github")}
    plan = service.execute_program(plan.batch_id, update_providers, module_providers)
    assert plan.status is ReleaseStatus.COMPLETED
    assert all("SignRiver-DLC-Hub-module-v0.2.0.zip" in provider.assets for provider in module_providers.values())


def test_program_batch_collects_modules_from_separate_archive_directory(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    updates = make_inbox(tmp_path / "updates")
    modules = tmp_path / "modules"
    modules.mkdir()
    write_module_archive(modules / "SignRiver-DLC-Hub-module-v0.2.0.zip")

    plan = service.create_program_batch(
        version="0.2.0",
        inbox=updates,
        module_inbox=modules,
        notes="说明。建议尽快更新。",
        remote_targets=targets(),
    )

    assert plan.options["collection"]["inbox"] == str(updates.resolve())
    assert plan.options["collection"]["module_inbox"] == str(modules.resolve())
    assert [item.role for item in plan.artifacts].count("module_archive") == 1


def test_program_preflight_requires_current_module_archive(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    plan = service.create_program_batch(
        version="0.2.0",
        inbox=make_inbox(tmp_path / "updates"),
        module_inbox=tmp_path / "missing-modules",
        notes="说明。建议尽快更新。",
        remote_targets=targets(),
    )

    plan = service.preflight(plan.batch_id)
    check = next(item for item in plan.preflight if item.check_id == "program.module_archives")
    assert check.result.value == "fail"
    assert plan.status is ReleaseStatus.PREFLIGHT_FAILED



def test_game_content_batch_reuses_same_unexecuted_output(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    output_dir = tmp_path / "output" / "game"
    output_dir.mkdir(parents=True)
    attachment = output_dir / "content.zip"
    catalog = output_dir / "catalog.json"
    attachment.write_bytes(b"content")
    catalog.write_text("{}", encoding="utf-8")

    created = service.create_game_content_batch(
        game_id="game",
        release_tag="game-v1",
        attachments=[attachment],
        catalog=catalog,
        output_dir=output_dir,
        remote_targets=targets(),
    )

    reused = service.find_reusable_game_content_batch(
        game_id="game", release_tag="game-v1", output_dir=output_dir
    )

    assert created.options["collection"] == {
        "output_dir": str(output_dir.resolve()),
        "attachment_count": 1,
        "catalog": "catalog.json",
    }
    assert reused is not None
    assert reused.batch_id == created.batch_id
    assert (
        service.find_reusable_game_content_batch(
            game_id="game", release_tag="game-v1", output_dir=tmp_path / "other-output"
        )
        is None
    )


def test_game_content_batch_does_not_reuse_stale_failed_snapshot(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    output_dir = tmp_path / "output" / "game"
    output_dir.mkdir(parents=True)
    attachment = output_dir / "content.zip"
    catalog = output_dir / "catalog.json"
    attachment.write_bytes(b"old-content")
    catalog.write_text("{}", encoding="utf-8")
    created = service.create_game_content_batch(
        game_id="game",
        release_tag="game-v1",
        attachments=[attachment],
        catalog=catalog,
        output_dir=output_dir,
        remote_targets=targets(),
    )
    attachment.write_bytes(b"new-content")
    failed = service.preflight(created.batch_id)

    assert failed.status is ReleaseStatus.PREFLIGHT_FAILED
    assert (
        service.find_reusable_game_content_batch(
            game_id="game", release_tag="game-v1", output_dir=output_dir
        )
        is None
    )


def test_latest_game_content_reuse_cache_reads_completed_content_stage(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    attachment = tmp_path / "content.zip"
    catalog = tmp_path / "catalog.json"
    attachment.write_bytes(b"content")
    catalog.write_text("{}", encoding="utf-8")
    plan = service.create_game_content_batch(
        game_id="game",
        release_tag="game-v1",
        attachments=[attachment],
        catalog=catalog,
        remote_targets=targets(),
    )
    expected = {"gitlink": {"assets": {"content.zip": {"remote_id": "42"}}}}
    plan.status = ReleaseStatus.COMPLETED
    plan.stages = [
        ReleaseStageRecord(
            stage_id="content.upload_snapshot",
            display_name="上传完整附件快照",
            order=20,
            output_summary={"content_reuse_cache": expected},
        )
    ]
    service.store.save(plan)

    assert service.latest_game_content_reuse_cache(
        game_id="game", release_tag="game-v1"
    ) == expected


def test_capture_and_export_remote_baseline_is_read_only(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    plan = service.create_program_batch(
        version="0.2.0", inbox=tmp_path / "inbox", notes="说明。建议尽快更新。", remote_targets=targets(),
    )
    providers = {source: MemoryProvider(source) for source in ("gitlink", "github")}
    plan = service.capture_remote_baseline(plan.batch_id, providers)
    assert set(plan.options["remote_baseline"]["sources"]) == {"gitlink", "github"}
    assert not any(provider.assets for provider in providers.values())
    exported = service.export_remote_baseline(plan.batch_id, tmp_path / "baseline.json")
    assert json.loads(exported.read_text(encoding="utf-8"))["sources"]["github"]["release_exists"] is False


def test_capture_remote_baseline_reads_module_release_when_archives_exist(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "workspace")
    inbox = make_inbox(tmp_path / "updates")
    write_module_archive(inbox / "SignRiver-DLC-Hub-module-v0.2.0.zip")
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox, notes="说明。建议尽快更新。", remote_targets=targets()
    )
    providers = {source: MemoryProvider(source) for source in ("gitlink", "github")}
    module_providers = {source: MemoryProvider(source) for source in ("gitlink", "github")}

    plan = service.capture_remote_baseline(plan.batch_id, providers, module_providers)

    assert set(plan.options["remote_baseline"]["module_sources"]) == {"gitlink", "github"}
