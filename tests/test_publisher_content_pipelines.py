from __future__ import annotations

from pathlib import Path

import pytest

from signriver_publisher.release_interfaces import RemoteVerification
from signriver_publisher.release_models import ReleaseStatus
from signriver_publisher.release_service import ReleaseService


class SnapshotProvider:
    def __init__(self, source_id: str, *, fail_index: bool = False) -> None:
        self.source_id = source_id
        self.fail_index = fail_index
        self.assets: dict[str, RemoteVerification] = {}
        self.calls: list[str] = []

    def inspect(self, key: str) -> RemoteVerification:
        return self.assets.get(key, RemoteVerification(False))

    def upload(self, artifact, path: Path) -> RemoteVerification:
        self.calls.append(f"asset:{path.name}")
        result = RemoteVerification(True, artifact.size, artifact.sha256, path.name)
        self.assets[path.name] = result
        return result

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


def test_matching_snapshot_attachment_is_reused(tmp_path: Path) -> None:
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

    assert f"asset:{artifact.filename}" not in providers["gitlink"].calls
    assert f"asset:{artifact.filename}" in providers["github"].calls


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
    assert providers["gitlink"].calls == gitlink_calls
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
