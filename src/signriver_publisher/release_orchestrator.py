"""Headless orchestration primitives for release stages."""

from __future__ import annotations

from collections.abc import Iterable
from threading import Lock
from typing import Any

from .release_interfaces import ReleasePipelineStage, stage_record
from .release_models import (
    CheckResult,
    ReleaseEvent,
    ReleasePlan,
    ReleaseStatus,
    StageStatus,
    utc_now,
)
from .release_preflight import ReleasePreflightService
from .release_store import ReleaseStore


class ReleaseOrchestrationError(RuntimeError):
    """Raised when an orchestration command is unsafe for the current batch."""


class ReleaseStageError(RuntimeError):
    """A classified stage failure with an explicit batch outcome."""

    def __init__(
        self,
        message: str,
        *,
        status: ReleaseStatus = ReleaseStatus.FAILED,
        retryable: bool = True,
    ) -> None:
        if status not in {ReleaseStatus.FAILED, ReleaseStatus.DEGRADED}:
            raise ValueError("stage errors may only produce failed or degraded")
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ReleasePauseRequested(RuntimeError):
    """Raised at a declared safe checkpoint when a release should pause."""


class ReleaseOrchestrator:
    def __init__(
        self, store: ReleaseStore, preflight: ReleasePreflightService | None = None
    ) -> None:
        self.store = store
        self.preflight = preflight or ReleasePreflightService()
        self._pause_requests: set[str] = set()
        self._pause_lock = Lock()

    def run_preflight(self, plan: ReleasePlan) -> ReleasePlan:
        self.preflight.run(plan)
        self._event(plan, "preflight_completed", result=plan.status.value)
        self.store.save(plan)
        return plan

    def confirm(
        self,
        plan: ReleasePlan,
        *,
        actor: str,
        skipped_acceptance_reason: str | None = None,
    ) -> None:
        if (
            plan.status is not ReleaseStatus.AWAITING_CONFIRMATION
            or not self.preflight.is_current(plan)
        ):
            raise ReleaseOrchestrationError(
                "release must have a current successful preflight before confirmation"
            )
        if any(
            check.hard_gate and check.result is CheckResult.FAIL
            for check in plan.preflight
        ):
            raise ReleaseOrchestrationError("hard-gate failures cannot be confirmed")
        acceptance = next(
            (check for check in plan.preflight if check.check_id == "human.acceptance"),
            None,
        )
        # Acceptance is a persisted review reference. It must never turn into a
        # hidden confirmation gate: operational preflight hard gates remain the
        # sole blockers for remote writes. Keep the legacy parameter only for
        # backward-compatible callers and audit it if one is voluntarily given.
        skip_reason = (skipped_acceptance_reason or "").strip()
        acceptance_result = (
            acceptance.result.value if acceptance is not None else "missing"
        )
        acceptance_snapshot_attached = isinstance(
            plan.options.get("acceptance_snapshot"), dict
        )
        acceptance_context = {
            "acceptance_result": acceptance_result,
            "acceptance_snapshot_attached": acceptance_snapshot_attached,
            "acceptance_reference_only": True,
        }
        plan.confirmation = {
            "actor": actor,
            "confirmed_at": utc_now(),
            "input_fingerprint": plan.input_fingerprint,
            **acceptance_context,
        }
        if skip_reason:
            plan.confirmation["skipped_acceptance_reason"] = skip_reason
        self._event(
            plan,
            "release_confirmed",
            trigger="user",
            context={"actor": actor, **acceptance_context, "acceptance_skipped": bool(skip_reason)},
        )
        self.store.save(plan)

    def request_pause(self, plan: ReleasePlan, *, actor: str = "user") -> None:
        if plan.status is not ReleaseStatus.RUNNING:
            raise ReleaseOrchestrationError("only a running release can be paused")
        with self._pause_lock:
            self._pause_requests.add(plan.batch_id)
        self._event(plan, "pause_requested", trigger=actor)
        self.store.save(plan)

    def pause_requested(self, plan: ReleasePlan) -> bool:
        with self._pause_lock:
            return plan.batch_id in self._pause_requests

    def checkpoint(self, plan: ReleasePlan) -> None:
        """Raise only between idempotent remote operations."""
        if self.pause_requested(plan):
            raise ReleasePauseRequested("release paused at a safe checkpoint")
        # Stages may append a completed remote operation to their record before
        # calling this checkpoint. Persist that small recovery point so a
        # network failure only needs to retry the source/file that is missing.
        self.store.save(plan)

    def execute(
        self, plan: ReleasePlan, stages: Iterable[ReleasePipelineStage]
    ) -> ReleasePlan:
        if plan.status not in {
            ReleaseStatus.AWAITING_CONFIRMATION,
            ReleaseStatus.PAUSED,
            ReleaseStatus.INTERRUPTED,
            ReleaseStatus.DEGRADED,
            ReleaseStatus.FAILED,
        }:
            raise ReleaseOrchestrationError(
                f"release cannot run from {plan.status.value}"
            )
        if (
            not plan.confirmation
            or plan.confirmation.get("input_fingerprint") != plan.input_fingerprint
        ):
            raise ReleaseOrchestrationError("release confirmation is absent or stale")
        if not self.preflight.is_current(plan):
            plan.invalidate_inputs("frozen inputs changed before execution")
            self._event(plan, "release_inputs_invalidated", result="draft")
            self.store.save(plan)
            raise ReleaseOrchestrationError(
                "frozen inputs changed; preflight and confirmation were invalidated"
            )

        ordered = sorted(stages, key=lambda item: item.order)
        records = {record.stage_id: record for record in plan.stages}
        for stage in ordered:
            records.setdefault(stage.stage_id, stage_record(stage))
        plan.stages = sorted(records.values(), key=lambda item: item.order)
        plan.transition_to(ReleaseStatus.RUNNING)
        self._event(plan, "release_started", result="running")
        self.store.save(plan)

        try:
            for stage in ordered:
                record = records[stage.stage_id]
                if record.status in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}:
                    continue
                if self.pause_requested(plan):
                    plan.transition_to(ReleaseStatus.PAUSED)
                    plan.recovery["safe_resume_stage"] = stage.stage_id
                    self._event(
                        plan,
                        "release_paused",
                        stage_id=stage.stage_id,
                        result="paused",
                    )
                    self.store.save(plan)
                    return plan
                record.status = StageStatus.RUNNING
                record.started_at = utc_now()
                record.finished_at = None
                record.attempts += 1
                record.error_category = None
                self._event(plan, "stage_started", stage_id=stage.stage_id)
                self.store.save(plan)
                try:
                    result = stage.execute(plan)
                except ReleasePauseRequested:
                    record.status = StageStatus.PAUSED
                    record.finished_at = utc_now()
                    record.retryable = True
                    record.safe_resume_stage = stage.stage_id
                    plan.transition_to(ReleaseStatus.PAUSED)
                    plan.recovery["safe_resume_stage"] = stage.stage_id
                    self._event(
                        plan, "release_paused", stage_id=stage.stage_id, result="paused"
                    )
                    self.store.save(plan)
                    return plan
                except Exception as exc:
                    record.status = StageStatus.FAILED
                    record.finished_at = utc_now()
                    record.error_category = type(exc).__name__
                    record.retryable = bool(
                        exc.retryable
                        if isinstance(exc, ReleaseStageError)
                        else stage.safe_checkpoint
                    )
                    target = (
                        exc.status
                        if isinstance(exc, ReleaseStageError)
                        else ReleaseStatus.FAILED
                    )
                    plan.transition_to(target)
                    self._event(
                        plan,
                        "stage_failed",
                        stage_id=stage.stage_id,
                        result=target.value,
                        error_category=record.error_category,
                        context={"message": str(exc)},
                    )
                    self.store.save(plan)
                    raise
                record.status = StageStatus.SUCCEEDED
                record.finished_at = utc_now()
                record.output_summary = dict(result.output_summary)
                record.verification = dict(result.verification)
                self._event(
                    plan, "stage_succeeded", stage_id=stage.stage_id, result="succeeded"
                )
                self.store.save(plan)

            plan.transition_to(ReleaseStatus.COMPLETED)
            plan.recovery.pop("safe_resume_stage", None)
            self._event(plan, "release_completed", result="completed")
            self.store.save(plan)
            return plan
        finally:
            with self._pause_lock:
                self._pause_requests.discard(plan.batch_id)

    def _event(
        self,
        plan: ReleasePlan,
        event_type: str,
        *,
        stage_id: str | None = None,
        result: str | None = None,
        error_category: str | None = None,
        context: dict[str, Any] | None = None,
        trigger: str = "system",
    ) -> None:
        event = ReleaseEvent(
            batch_id=plan.batch_id,
            event_type=event_type,
            stage_id=stage_id,
            result=result,
            error_category=error_category,
            context=context or {},
            trigger=trigger,
        )
        self.store.append_event(event)
        plan.event_ids.append(event.event_id)
