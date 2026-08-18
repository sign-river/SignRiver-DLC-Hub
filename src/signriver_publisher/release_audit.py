"""Acceptance snapshots, release diagnostics and audited maintenance commands."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .release_models import ReleaseEvent, ReleasePlan, ReleaseStatus, utc_now
from .release_store import ReleaseStore

_SENSITIVE_KEY_PARTS = (
    "token", "password", "passwd", "secret", "cookie", "authorization",
    "credential", "private_key", "access_key", "session_key",
)


def _redact_sensitive(value: Any) -> Any:
    """Return a JSON-safe copy with credential-shaped fields removed."""
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
                else _redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class MaintenanceApproval:
    operation_id: str
    batch_id: str
    action: str
    impact_summary: str
    confirmation_text: str
    created_at: str


class ReleaseAuditService:
    """Adds immutable evidence without coupling acceptance or maintenance to Tk."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.store = ReleaseStore(workspace_root)
        self._pending: dict[str, MaintenanceApproval] = {}
        self._authorized: dict[str, MaintenanceApproval] = {}

    def attach_acceptance_snapshot(self, batch_id: str, snapshot: dict[str, Any]) -> ReleasePlan:
        plan = self.store.load(batch_id)
        if plan.status in {ReleaseStatus.RUNNING, ReleaseStatus.COMPLETED}:
            raise ValueError("运行中或已完成批次不能替换验收快照")
        normalized = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
        payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
        plan.options["acceptance_snapshot"] = {
            "captured_at": utc_now(),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "result": normalized,
        }
        plan.invalidate_inputs("acceptance snapshot changed")
        self.store.save(plan)
        self._event(plan, "acceptance_snapshot_attached", context={"sha256": plan.options["acceptance_snapshot"]["sha256"]}, trigger="user")
        return plan

    def prepare_maintenance(self, batch_id: str, *, action: str, impact_summary: str) -> MaintenanceApproval:
        plan = self.store.load(batch_id)
        operation_id = uuid4().hex
        approval = MaintenanceApproval(
            operation_id=operation_id,
            batch_id=batch_id,
            action=action,
            impact_summary=impact_summary,
            confirmation_text=f"确认执行 {action}：{impact_summary}",
            created_at=utc_now(),
        )
        self._pending[operation_id] = approval
        self._event(plan, "maintenance_prepared", action=action, context={"operation_id": operation_id, "impact_summary": impact_summary}, trigger="user")
        return approval

    def execute_maintenance(
        self,
        approval: MaintenanceApproval,
        *,
        confirmation_text: str,
        operation: Callable[[], Any],
    ) -> Any:
        self.authorize_maintenance(approval, confirmation_text=confirmation_text)
        try:
            result = operation()
        except Exception as exc:
            self.fail_maintenance(approval, str(exc))
            raise
        self.complete_maintenance(approval)
        return result

    def authorize_maintenance(
        self, approval: MaintenanceApproval, *, confirmation_text: str
    ) -> MaintenanceApproval:
        """Consume a typed confirmation without claiming the operation completed."""
        pending = self._pending.pop(approval.operation_id, None)
        if pending != approval or confirmation_text != approval.confirmation_text:
            raise ValueError("高级维护二次确认无效或已过期")
        self._authorized[approval.operation_id] = approval
        plan = self.store.load(approval.batch_id)
        self._event(
            plan,
            "maintenance_authorized",
            action=approval.action,
            context={
                "operation_id": approval.operation_id,
                "impact_summary": approval.impact_summary,
            },
            trigger="user",
        )
        return approval

    def complete_maintenance(
        self, approval: MaintenanceApproval, *, context: dict[str, Any] | None = None
    ) -> None:
        self._consume_authorized(approval)
        plan = self.store.load(approval.batch_id)
        details = {
            "operation_id": approval.operation_id,
            "impact_summary": approval.impact_summary,
        }
        if context:
            details.update(context)
        self._event(
            plan,
            "maintenance_completed",
            action=approval.action,
            result="completed",
            context=details,
            trigger="user",
        )

    def fail_maintenance(self, approval: MaintenanceApproval, message: str) -> None:
        self._consume_authorized(approval)
        plan = self.store.load(approval.batch_id)
        self._event(
            plan,
            "maintenance_failed",
            action=approval.action,
            result="failed",
            context={"operation_id": approval.operation_id, "message": message},
            trigger="user",
        )

    def _consume_authorized(self, approval: MaintenanceApproval) -> None:
        authorized = self._authorized.pop(approval.operation_id, None)
        if authorized != approval:
            raise ValueError("高级维护授权无效、未确认或已结束")

    def diagnose(self, batch_id: str) -> dict[str, Any]:
        plan = self.store.load(batch_id)
        failed = [stage for stage in plan.stages if stage.status.value == "failed"]
        return {
            "batch_id": batch_id,
            "status": plan.status.value,
            "safe_resume_stage": plan.recovery.get("safe_resume_stage"),
            "failed_stages": [
                {"stage_id": stage.stage_id, "category": stage.error_category, "retryable": stage.retryable}
                for stage in failed
            ],
            "preflight_failures": [check.message for check in plan.preflight if check.result.value == "fail"],
            "event_count": len(self.store.read_events(batch_id)),
        }

    def export_audit(self, batch_id: str, destination: Path | str) -> Path:
        plan = self.store.load(batch_id)
        payload = _redact_sensitive({
            "schema_version": 1,
            "exported_at": utc_now(),
            "plan": plan.to_dict(),
            "events": [asdict(event) for event in self.store.read_events(batch_id)],
            "diagnosis": self.diagnose(batch_id),
        })
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def _event(self, plan: ReleasePlan, event_type: str, *, action: str | None = None, result: str | None = None, context: dict[str, Any] | None = None, trigger: str = "system") -> None:
        event = ReleaseEvent(batch_id=plan.batch_id, event_type=event_type, action=action, result=result, context=context or {}, trigger=trigger)
        self.store.append_event(event)
        plan.event_ids.append(event.event_id)
        self.store.save(plan)
