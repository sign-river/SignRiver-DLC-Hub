from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from signriver_publisher.release_interfaces import RemoteVerification
from signriver_publisher.release_models import ReleaseStatus
from signriver_publisher.release_service import ReleaseService


class SnapshotProvider:
    def __init__(self, source_id: str, *, fail_index: bool = False, fail_upload: bool = False, lose_upload_response: bool = False) -> None:
        self.source_id = source_id
        self.fail_index = fail_index
        self.fail_upload = fail_upload
        self.lose_upload_response = lose_upload_response
        self.assets: dict[str, RemoteVerification] = {}
        self.calls: list[str] = []
        self.remote_names: set[str] = set()

    def inspect(self, key: str) -> RemoteVerification:
        raise AssertionError(f"发布前不应下载远端附件来检查复用：{key}")

    def upload(self, artifact, path: Path) -> RemoteVerification:
        self.calls.append(f"asset:{path.name}")
        if self.fail_upload:
            raise TimeoutError(f"{self.source_id} upload timeout")
        result = RemoteVerification(True, artifact.size, artifact.sha256, path.name)
        self.assets[path.name] = result
        self.remote_names.add(path.name)
        if self.lose_upload_response:
            raise TimeoutError(f"{self.source_id} response timeout")
        return result

    def read_baseline(self) -> dict[str, object]:
        return {
            "assets": [
                {
                    "name": name,
                    "remote_id": self.assets.get(
                        name, RemoteVerification(False, remote_id=f"{name}-id")
                    ).remote_id,
                }
                for name in sorted(self.remote_names)
            ]
        }

    def delete(self, key: str) -> RemoteVerification:
        self.remote_names.discard(key)
        self.assets.pop(key, None)
        return RemoteVerification(False)

    def publish_index(self, plan, path: Path) -> RemoteVerification:
        self.calls.append(f"index:{path.name}")
        if self.fail_index:
            raise RuntimeError("index failed")
        artifact = next(item for item in plan.artifacts if item.filename == path.name)
        result = RemoteVerification(True, artifact.size, artifact.sha256, path.name)
        self.assets[path.name] = result
        return result


def file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def confirmed(service: ReleaseService, batch_id: str) -> None:
    service.preflight(batch_id)
    service.confirm(batch_id, skipped_acceptance_reason="自动化测试")


def targets():
    return {"gitlink": {"repo": "a"}, "github": {"repo": "b"}}


def test_game_catalog_is_uploaded_only_after_all_attachments_are_verified(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_game_content_batch(
        game_id="game", release_tag="game-v1",
        attachments=[file(tmp_path / "a.zip", b"a"), file(tmp_path / "b.zip", b"b")],
        catalog=file(tmp_path / "catalog.json", b"{}"), remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)
    providers = {name: SnapshotProvider(name) for name in ("gitlink", "github")}

    plan = service.execute_game_content(plan.batch_id, providers)

    assert plan.status is ReleaseStatus.COMPLETED
    for provider in providers.values():
        assert provider.calls[-1] == "index:catalog.json"
    activity = next(
        stage.output_summary["activity"]
        for stage in plan.stages
        if stage.stage_id == "content.upload_snapshot"
    )
    assert {(entry["source"], entry["filename"], entry["outcome"]) for entry in activity} == {
        ("gitlink", "a.zip", "uploaded"),
        ("gitlink", "b.zip", "uploaded"),
        ("github", "a.zip", "uploaded"),
        ("github", "b.zip", "uploaded"),
    }


def test_matching_snapshot_attachment_is_replaced_without_pre_download(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    attachment = file(tmp_path / "cartridge.json", b"snapshot")
    plan = service.create_hub_batch(
        attachments=[attachment], hub_index=file(tmp_path / "hub-catalog.json", b"index"),
        remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)
    providers = {name: SnapshotProvider(name) for name in ("gitlink", "github")}
    artifact = next(item for item in plan.artifacts if item.role == "hub_snapshot")
    providers["gitlink"].assets[artifact.filename] = RemoteVerification(True, artifact.size, artifact.sha256)

    service.execute_hub(plan.batch_id, providers)

    assert f"asset:{artifact.filename}" in providers["gitlink"].calls
    assert f"asset:{artifact.filename}" in providers["github"].calls


def test_game_content_reuses_matching_verified_cache_without_downloading(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    attachment = file(tmp_path / "dlc.zip", b"cached-content")
    catalog = file(tmp_path / "catalog.json", b"{}")
    digest = hashlib.sha256(attachment.read_bytes()).hexdigest()
    cache = {
        source: {
            "target": target,
            "assets": {
                "dlc.zip": {"sha256": digest, "size": attachment.stat().st_size, "remote_id": "dlc.zip-id"}
            },
        }
        for source, target in targets().items()
    }
    plan = service.create_game_content_batch(
        game_id="game",
        release_tag="game-v1",
        attachments=[attachment],
        catalog=catalog,
        remote_targets=targets(),
        reuse_cache=cache,
    )
    confirmed(service, plan.batch_id)
    providers = {name: SnapshotProvider(name) for name in ("gitlink", "github")}
    for provider in providers.values():
        provider.remote_names.add("dlc.zip")

    completed = service.execute_game_content(plan.batch_id, providers)

    assert completed.status is ReleaseStatus.COMPLETED
    assert all("asset:dlc.zip" not in provider.calls for provider in providers.values())
    assert all("index:catalog.json" in provider.calls for provider in providers.values())


def test_content_stage_recovers_an_upload_whose_response_was_lost(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_game_content_batch(
        game_id="game", release_tag="v1",
        attachments=[file(tmp_path / "asset.zip", b"asset")],
        catalog=file(tmp_path / "catalog.json", b"{}"), remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)
    providers = {
        "gitlink": SnapshotProvider("gitlink", lose_upload_response=True),
        "github": SnapshotProvider("github"),
    }

    completed = service.execute_game_content(plan.batch_id, providers)

    assert completed.status is ReleaseStatus.COMPLETED
    assert providers["gitlink"].calls.count("asset:asset.zip") == 1


def test_content_retry_only_reuploads_the_source_that_is_still_missing(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_game_content_batch(
        game_id="game", release_tag="v1",
        attachments=[file(tmp_path / "asset.zip", b"asset")],
        catalog=file(tmp_path / "catalog.json", b"{}"), remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)
    gitlink = SnapshotProvider("gitlink")
    github = SnapshotProvider("github", fail_upload=True)

    with pytest.raises(TimeoutError, match="github upload timeout"):
        service.execute_game_content(plan.batch_id, {"gitlink": gitlink, "github": github})

    github.fail_upload = False
    completed = service.execute_game_content(
        plan.batch_id, {"gitlink": gitlink, "github": github}
    )

    assert completed.status is ReleaseStatus.COMPLETED
    assert gitlink.calls.count("asset:asset.zip") == 1
    assert github.calls.count("asset:asset.zip") == 2


def test_non_dlc_content_is_replaced_even_when_a_cache_entry_matches(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    attachment = file(tmp_path / "patch.dll", b"new-patch")
    catalog = file(tmp_path / "catalog.json", b"{}")
    digest = hashlib.sha256(attachment.read_bytes()).hexdigest()
    cache = {
        source: {
            "target": target,
            "assets": {
                "patch.dll": {"sha256": digest, "size": attachment.stat().st_size, "remote_id": ""}
            },
        }
        for source, target in targets().items()
    }
    plan = service.create_game_content_batch(
        game_id="game",
        release_tag="game-v1",
        attachments=[attachment],
        catalog=catalog,
        remote_targets=targets(),
        reuse_cache=cache,
    )
    confirmed(service, plan.batch_id)
    providers = {name: SnapshotProvider(name) for name in ("gitlink", "github")}
    for provider in providers.values():
        provider.remote_names.add("patch.dll")

    service.execute_game_content(plan.batch_id, providers)

    assert all("asset:patch.dll" in provider.calls for provider in providers.values())


def test_hub_second_source_index_failure_becomes_degraded(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_hub_batch(
        attachments=[file(tmp_path / "announcement.json", b"announcement")],
        hub_index=file(tmp_path / "hub-catalog.json", b"index"), remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)
    providers = {
        "gitlink": SnapshotProvider("gitlink"),
        "github": SnapshotProvider("github", fail_index=True),
    }

    with pytest.raises(RuntimeError, match="主表切换失败"):
        service.execute_hub(plan.batch_id, providers)

    assert service.get(plan.batch_id).status is ReleaseStatus.DEGRADED
    assert providers["gitlink"].calls[-1] == "index:hub-catalog.json"


def test_hub_degraded_resume_only_switches_failed_index_source(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_hub_batch(
        attachments=[file(tmp_path / "announcement.json", b"announcement")],
        hub_index=file(tmp_path / "hub-catalog.json", b"index"),
        remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)
    providers = {
        "gitlink": SnapshotProvider("gitlink"),
        "github": SnapshotProvider("github", fail_index=True),
    }

    with pytest.raises(RuntimeError, match="主表切换失败"):
        service.execute_hub(plan.batch_id, providers)

    gitlink_calls = list(providers["gitlink"].calls)
    providers["github"].fail_index = False
    resumed = service.execute_hub(plan.batch_id, providers)

    assert resumed.status is ReleaseStatus.COMPLETED
    assert providers["gitlink"].calls == gitlink_calls + ["index:hub-catalog.json"]
    assert providers["github"].calls.count("index:hub-catalog.json") == 2


def test_content_batch_rejects_missing_required_inputs(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    catalog = file(tmp_path / "catalog.json", b"{}")
    with pytest.raises(RuntimeError, match="游戏 ID"):
        service.create_game_content_batch(
            game_id="", release_tag="v1", attachments=[catalog], catalog=catalog,
            remote_targets=targets(),
        )
    with pytest.raises(RuntimeError, match="至少需要一个 Hub"):
        service.create_hub_batch(attachments=[], hub_index=catalog, remote_targets=targets())


def test_content_preflight_rejects_wrong_sources_and_snapshot_shape(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_game_content_batch(
        game_id="game", release_tag="v1",
        attachments=[file(tmp_path / "asset.zip", b"asset")],
        catalog=file(tmp_path / "catalog.json", b"{}"),
        remote_targets={"gitlink": {"repo": "a"}, "mirror": {"repo": "b"}},
    )
    plan.artifacts = [item for item in plan.artifacts if item.role != "catalog"]
    service.store.save(plan)
    plan = service.preflight(plan.batch_id)
    failed = {item.check_id for item in plan.preflight if item.result.value == "fail"}
    assert {"remote.dual_source", "content.snapshot_structure"} <= failed
    assert plan.status is ReleaseStatus.PREFLIGHT_FAILED


@pytest.mark.parametrize(
    "providers",
    [
        {},
        {"gitlink": SnapshotProvider("gitlink")},
    ],
)
def test_snapshot_pipeline_rejects_missing_dual_source_providers(
    tmp_path: Path, providers: dict[str, SnapshotProvider]
) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_hub_batch(
        attachments=[file(tmp_path / "announcement.json", b"announcement")],
        hub_index=file(tmp_path / "hub-catalog.json", b"index"),
        remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)

    with pytest.raises(ValueError, match="exactly gitlink and github"):
        service.execute_hub(plan.batch_id, providers)


def test_snapshot_pipeline_rejects_provider_key_source_mismatch(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_game_content_batch(
        game_id="game",
        release_tag="v1",
        attachments=[file(tmp_path / "asset.zip", b"asset")],
        catalog=file(tmp_path / "catalog.json", b"{}"),
        remote_targets=targets(),
    )
    confirmed(service, plan.batch_id)
    providers = {
        "gitlink": SnapshotProvider("github"),
        "github": SnapshotProvider("github"),
    }

    with pytest.raises(ValueError, match="provider key/source mismatch"):
        service.execute_game_content(plan.batch_id, providers)


def test_mirror_execution_rejects_a_remote_change_after_confirmation(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_game_content_batch(
        game_id="game",
        release_tag="v1",
        attachments=[file(tmp_path / "asset.zip", b"asset")],
        catalog=file(tmp_path / "catalog.json", b"{}"),
        remote_targets=targets(),
    )
    providers = {name: SnapshotProvider(name) for name in ("gitlink", "github")}
    providers["gitlink"].remote_names.add("old.zip")
    plan = service.preview_game_content_mirror(plan.batch_id, providers)
    plan.options["mirror_delete_confirmed"] = True
    service.store.save(plan)
    confirmed(service, plan.batch_id)

    providers["gitlink"].remote_names.add("changed-after-preview.zip")

    with pytest.raises(RuntimeError, match="远端目录已发生变化"):
        service.execute_game_content(plan.batch_id, providers)


def test_compatibility_publish_never_deletes_remote_only_files(tmp_path: Path) -> None:
    service = ReleaseService(tmp_path / "ws")
    plan = service.create_game_content_batch(
        game_id="game",
        release_tag="v1",
        attachments=[file(tmp_path / "asset.zip", b"asset")],
        catalog=file(tmp_path / "catalog.json", b"{}"),
        remote_targets=targets(),
        preserve_remote_only_files=True,
    )
    providers = {name: SnapshotProvider(name) for name in ("gitlink", "github")}
    for provider in providers.values():
        provider.remote_names.add("old-client-asset.zip")
    plan = service.preview_game_content_mirror(plan.batch_id, providers)
    # Defend against old or manually edited queue records that still claim deletion.
    plan.options["mirror_delete_confirmed"] = True
    service.store.save(plan)
    confirmed(service, plan.batch_id)

    completed = service.execute_game_content(plan.batch_id, providers)

    assert completed.status is ReleaseStatus.COMPLETED
    assert all("old-client-asset.zip" in provider.remote_names for provider in providers.values())
    stage = next(item for item in completed.stages if item.stage_id == "content.upload_snapshot")
    assert stage.output_summary["deleted"] == {"gitlink": [], "github": []}
    assert stage.output_summary["preserved_remote_only_files"] is True
