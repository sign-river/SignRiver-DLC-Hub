from __future__ import annotations

import json
from tkinter import filedialog, messagebox, simpledialog

from .release_audit import MaintenanceApproval


class ReleaseActionsUiMixin:
    """Batch creation, acceptance binding, diagnostics, and maintenance audit UI."""

    def _select_release_batch_for_action(self):
        batch_id = getattr(self.release_center, "current_batch_id", None)
        if not batch_id:
            messagebox.showinfo("请选择发布批次", "请先在发布中心选择一个批次。", parent=self)
            return None
        return self.release_service.get(batch_id)

    def _open_release_batch(self, batch_id: str) -> None:
        self.release_center.refresh_history()
        self.release_center.select(batch_id)
        self.tabs.set("发布包与归档")

    def create_game_content_release_batch(self) -> None:
        """Open the DLC/patch package page before creating a frozen release batch."""
        self._open_game_content_release_pipeline()

    def attach_acceptance_to_release_batch(self) -> None:
        plan = self._select_release_batch_for_action()
        if plan is None:
            return
        session = self._acceptance_session
        if session is None:
            messagebox.showinfo("暂无验收结果", "请先开始验收并记录结果。", parent=self)
            return
        try:
            updated = self.release_audit.attach_acceptance_snapshot(
                plan.batch_id, session.to_dict()
            )
        except Exception as error:
            messagebox.showerror("附加验收失败", str(error), parent=self)
            return
        self.release_center._render(updated)
        messagebox.showinfo(
            "已附加验收", "验收快照已写入批次；请重新运行预检并确认。", parent=self
        )

    def _confirm_maintenance_authorization(
        self, action: str, impact_summary: str
    ) -> MaintenanceApproval | None:
        batch_id = getattr(self.release_center, "current_batch_id", None)
        if not batch_id:
            messagebox.showerror(
                "缺少关联批次",
                "高级维护操作必须写入批次审计。请先在“发布中心”选择或创建关联批次。",
                parent=self,
            )
            return None
        if self._active_maintenance_approval is not None:
            messagebox.showinfo("维护操作进行中", "请等待当前高级维护操作结束。", parent=self)
            return None
        approval = self.release_audit.prepare_maintenance(
            batch_id, action=action, impact_summary=impact_summary
        )
        entered = simpledialog.askstring(
            "高级维护二次确认",
            f"请输入以下完整文本以继续：\n\n{approval.confirmation_text}",
            parent=self,
        )
        if entered is None:
            return None
        try:
            return self.release_audit.authorize_maintenance(
                approval, confirmation_text=entered
            )
        except ValueError as error:
            messagebox.showerror("二次确认失败", str(error), parent=self)
            return None

    def _activate_maintenance(self, approval: MaintenanceApproval) -> None:
        self._active_maintenance_approval = approval

    def _complete_active_maintenance(self, **context: object) -> None:
        approval = self._active_maintenance_approval
        if approval is None:
            return
        self._active_maintenance_approval = None
        self.release_audit.complete_maintenance(approval, context=context or None)

    def _fail_active_maintenance(self, message: str) -> None:
        approval = self._active_maintenance_approval
        if approval is None:
            return
        self._active_maintenance_approval = None
        self.release_audit.fail_maintenance(approval, message)

    def diagnose_release_batch(self) -> None:
        plan = self._select_release_batch_for_action()
        if plan is None:
            return
        diagnosis = self.release_audit.diagnose(plan.batch_id)
        messagebox.showinfo(
            "批次诊断",
            json.dumps(diagnosis, ensure_ascii=False, indent=2),
            parent=self,
        )

    def export_release_audit(self) -> None:
        plan = self._select_release_batch_for_action()
        if plan is None:
            return
        destination = filedialog.asksaveasfilename(
            title="导出脱敏审计记录",
            defaultextension=".json",
            initialfile=f"release-audit-{plan.batch_id[:8]}.json",
            filetypes=(("JSON", "*.json"),),
            parent=self,
        )
        if not destination:
            return
        try:
            path = self.release_audit.export_audit(plan.batch_id, destination)
        except Exception as error:
            messagebox.showerror("导出审计失败", str(error), parent=self)
            return
        messagebox.showinfo("审计已导出", str(path), parent=self)
