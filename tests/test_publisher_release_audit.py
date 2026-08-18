from __future__ import annotations

import json
from pathlib import Path

import pytest

from signriver_publisher.release_audit import ReleaseAuditService
from signriver_publisher.release_models import ReleaseKind, ReleasePlan
from signriver_publisher.release_store import ReleaseStore


def batch(root: Path) -> ReleasePlan:
    store = ReleaseStore(root)
    return store.create(ReleasePlan.create(ReleaseKind.GAME_CONTENT, {"game_id": "test"}))


def test_acceptance_snapshot_is_fingerprinted_and_persisted(tmp_path: Path) -> None:
    plan = batch(tmp_path)
    audit = ReleaseAuditService(tmp_path)

    updated = audit.attach_acceptance_snapshot(plan.batch_id, {"passed": 4, "failed": 0})

    snapshot = updated.options["acceptance_snapshot"]
    assert len(snapshot["sha256"]) == 64
    assert audit.store.load(plan.batch_id).options["acceptance_snapshot"]["result"]["passed"] == 4


def test_maintenance_requires_exact_one_time_confirmation_and_audits(tmp_path: Path) -> None:
    plan = batch(tmp_path)
    audit = ReleaseAuditService(tmp_path)
    approval = audit.prepare_maintenance(
        plan.batch_id, action="删除远端附件", impact_summary="删除 old.zip，客户端将无法下载"
    )
    calls: list[str] = []

    with pytest.raises(ValueError, match="二次确认"):
        audit.execute_maintenance(approval, confirmation_text="不匹配", operation=lambda: calls.append("bad"))
    assert not calls

    approval = audit.prepare_maintenance(
        plan.batch_id, action="删除远端附件", impact_summary="删除 old.zip，客户端将无法下载"
    )
    audit.execute_maintenance(
        approval, confirmation_text=approval.confirmation_text,
        operation=lambda: calls.append("deleted"),
    )
    assert calls == ["deleted"]
    assert audit.store.read_events(plan.batch_id)[-1].event_type == "maintenance_completed"



def test_async_maintenance_records_completion_only_after_real_result(tmp_path: Path) -> None:
    plan = batch(tmp_path)
    audit = ReleaseAuditService(tmp_path)
    approval = audit.prepare_maintenance(
        plan.batch_id, action="单源发布", impact_summary="切换远端清单"
    )

    audit.authorize_maintenance(
        approval, confirmation_text=approval.confirmation_text
    )
    event_types = [event.event_type for event in audit.store.read_events(plan.batch_id)]
    assert event_types[-1] == "maintenance_authorized"
    assert "maintenance_completed" not in event_types

    audit.complete_maintenance(approval, context={"target": "gitlink"})
    events = audit.store.read_events(plan.batch_id)
    assert events[-1].event_type == "maintenance_completed"
    assert events[-1].context["target"] == "gitlink"


def test_async_maintenance_records_failure_and_cannot_finish_twice(tmp_path: Path) -> None:
    plan = batch(tmp_path)
    audit = ReleaseAuditService(tmp_path)
    approval = audit.prepare_maintenance(
        plan.batch_id, action="删除附件", impact_summary="永久删除 old.zip"
    )
    audit.authorize_maintenance(
        approval, confirmation_text=approval.confirmation_text
    )

    audit.fail_maintenance(approval, "remote rejected")
    event = audit.store.read_events(plan.batch_id)[-1]
    assert event.event_type == "maintenance_failed"
    assert event.context["message"] == "remote rejected"
    with pytest.raises(ValueError, match="已结束"):
        audit.complete_maintenance(approval)

def test_diagnosis_and_audit_export(tmp_path: Path) -> None:
    plan = batch(tmp_path)
    audit = ReleaseAuditService(tmp_path)
    destination = tmp_path / "exports" / "audit.json"

    exported = audit.export_audit(plan.batch_id, destination)
    payload = json.loads(exported.read_text(encoding="utf-8"))

    assert payload["plan"]["batch_id"] == plan.batch_id
    assert payload["diagnosis"]["event_count"] >= 1
    assert payload["events"]


def test_audit_export_recursively_redacts_credentials(tmp_path: Path) -> None:
    plan = batch(tmp_path)
    plan.remote_targets = {
        "github": {
            "token": "top-secret",
            "nested": {"Authorization": "Bearer hidden", "owner": "safe"},
        }
    }
    ReleaseStore(tmp_path).save(plan)
    audit = ReleaseAuditService(tmp_path)

    payload = json.loads(
        audit.export_audit(plan.batch_id, tmp_path / "audit.json").read_text(encoding="utf-8")
    )

    target = payload["plan"]["remote_targets"]["github"]
    assert target["token"] == "[REDACTED]"
    assert target["nested"]["Authorization"] == "[REDACTED]"
    assert target["nested"]["owner"] == "safe"
    assert "top-secret" not in json.dumps(payload, ensure_ascii=False)
