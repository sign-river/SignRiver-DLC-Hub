"""Tk workspace for the persistent DLC / patch upload queue."""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from .models import GameProfile
from .release_models import ReleaseStatus
from .upload_queue import UploadQueueError, UploadQueueStatus

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
MUTED = "#757575"
RED = "#E53935"


def _display_bytes(value: float) -> str:
    amount = max(0.0, float(value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} TB"


class UploadQueueUiMixin:
    """Resource queue UI; all networking remains in the existing release service."""

    def _build_upload_queue_tab(self) -> None:
        self.upload_queue_tab.grid_columnconfigure(0, weight=1)
        self.upload_queue_tab.grid_rowconfigure(1, weight=1)
        header = self._card(self.upload_queue_tab, 0, "资源上传队列")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            header,
            text="← 返回资源入口",
            width=142,
            height=34,
            fg_color="transparent",
            text_color=BLUE,
            border_width=1,
            border_color="#90CAF9",
            hover_color="#EAF4FD",
            command=lambda: self.content_tabs.set("DLC / 补丁发布"),
        ).grid(row=0, column=1, padx=20, pady=(14, 8), sticky="e")
        ctk.CTkLabel(
            header,
            text="加入队列不访问网络；每项轮到上传时才读取双端差异并确认云端删除。上传成功后以远端附件 ID 和大小建立可信记录，catalog.json 始终最后发布。",
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=2, column=0, padx=20, pady=(0, 16), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        self.upload_queue_summary = ctk.CTkLabel(
            actions, text="队列正在读取…", text_color=MUTED, anchor="w"
        )
        self.upload_queue_summary.grid(row=0, column=0, sticky="w")
        self.upload_queue_start_button = ctk.CTkButton(
            actions, text="开始队列", width=110, fg_color=BLUE,
            command=self._start_upload_queue,
        )
        self.upload_queue_start_button.grid(row=0, column=1, padx=(10, 0))
        self.upload_queue_pause_button = ctk.CTkButton(
            actions, text="暂停当前项", width=110, fg_color="transparent", border_width=1,
            border_color="#90CAF9", text_color=BLUE, state="disabled",
            command=self._pause_upload_queue,
        )
        self.upload_queue_pause_button.grid(row=0, column=2, padx=(8, 0))
        self.upload_queue_clear_button = ctk.CTkButton(
            actions, text="一键清空队列", width=126, fg_color="transparent", border_width=1,
            border_color="#FF8A80", text_color=RED, hover_color="#FFEBEE",
            command=self._clear_upload_queue,
        )
        self.upload_queue_clear_button.grid(row=0, column=3, padx=(8, 0))
        self.upload_queue_refresh_button = ctk.CTkButton(
            actions, text="刷新", width=82, fg_color="transparent", border_width=1,
            border_color="#D8DEE6", text_color="#455A64", command=self._render_upload_queue,
        )
        self.upload_queue_refresh_button.grid(row=0, column=4, padx=(8, 0))

        self.upload_queue_list = ctk.CTkScrollableFrame(
            self.upload_queue_tab, fg_color="#F7F9FC", corner_radius=12,
            border_width=1, border_color="#D8DEE6",
        )
        self.upload_queue_list.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self._queue_current_item_id: str | None = None
        self._queue_worker_running = False
        self._queue_pause_requested = False
        self._upload_queue_progress_widgets: dict[str, tuple[ctk.CTkLabel, ctk.CTkProgressBar]] = {}
        self._render_upload_queue()

    def _enqueue_current_game_upload(self, *, profile: GameProfile | None = None) -> None:
        """Queue a built game immediately; remote preflight is deferred to execution."""
        profile = profile or self.profile
        self._log(f"用户操作：准备将“{profile.display_name}”加入上传队列。")
        try:
            plan = self._create_game_content_batch_for_profile(profile)
        except Exception as error:
            messagebox.showerror("无法加入上传队列", str(error), parent=self)
            return
        try:
            self._enqueue_game_content_plan(plan, profile.display_name)
        except Exception as error:
            messagebox.showerror("无法加入上传队列", str(error), parent=self)
            return
        self._log(
            f"用户操作：已将“{profile.display_name}”加入上传队列；"
            "远端差异会在实际上传前读取。"
        )
        self._render_upload_queue()
        self.content_tabs.set("上传队列")

    def _enqueue_game_content_plan(self, plan, display_name: str) -> None:
        """Persist a local build in FIFO without performing any network operation."""
        game_id = str(plan.target.get("game_id") or "")
        previous = next(
            (
                item
                for item in self.content_upload_queue.list_items()
                if item.game_id == game_id
            ),
            None,
        )
        self.content_upload_queue.enqueue(plan, display_name=display_name)
        if previous is None:
            self._log(f"后台队列：新增“{display_name}”上传项。")
        elif previous.status is UploadQueueStatus.RUNNING:
            self._log(
                f"后台队列：检测到“{display_name}”正在上传；"
                "保留新提交，当前安全步骤结束后将上传最新提交。"
            )
        else:
            self._log(
                f"后台队列：覆盖“{display_name}”原有{previous.status}上传项，"
                "已舍弃旧提交，仅保留最新提交。"
            )

    def _handle_queue_preview_failure(self, error: Exception) -> None:
        self._refresh_content_release_summary()
        messagebox.showerror("无法读取云端资源", str(error), parent=self)

    def _show_queue_preview_loading(self, display_name: str) -> None:
        if hasattr(self, "content_release_scope_label"):
            self.content_release_scope_label.configure(text=f"正在读取“{display_name}”的云端资源差异…")

    def _confirm_enqueue_current_game(self, plan, display_name: str) -> None:
        preview = plan.options.get("remote_mirror_preview", {})
        extras = preview.get("extra_files", {}) if isinstance(preview, dict) else {}
        preserve_remote_only_files = bool(plan.options.get("preserve_remote_only_files"))
        delete_lines = []
        if isinstance(extras, dict):
            for source, names in extras.items():
                if isinstance(names, list) and names:
                    delete_lines.append(f"• {source}：{', '.join(map(str, names))}")
        delete_detail = "\n".join(delete_lines) if delete_lines else "• 未发现远端多余文件。"
        remote_only_message = (
            "兼容发布已开启，以下云端仅有文件会保留，不会删除：\n"
            if preserve_remote_only_files
            else "以下远端多余文件将在校验成功后删除：\n"
        )
        if not messagebox.askyesno(
            "确认加入上传队列",
            f"将“{display_name}”加入上传队列。\n\n"
            "已完成本地与云端目录比对。上传时新增和变化文件会记录远端附件 ID 与大小，"
            f"最后才发布 catalog.json。{remote_only_message}"
            f"{delete_detail}\n\n"
            "确认后可以继续整理其他游戏；队列会按加入顺序上传。",
            icon="warning",
            parent=self,
        ):
            self._log(f"用户操作：取消将“{display_name}”加入上传队列。")
            self._refresh_content_release_summary()
            return
        try:
            confirmed = (
                plan
                if preserve_remote_only_files
                else self.release_service.confirm_game_content_mirror_delete(plan.batch_id)
            )
            game_id = str(confirmed.target.get("game_id") or "")
            previous = next(
                (
                    item
                    for item in self.content_upload_queue.list_items()
                    if item.game_id == game_id
                ),
                None,
            )
            self.content_upload_queue.enqueue(confirmed, display_name=display_name)
        except Exception as error:
            messagebox.showerror("无法加入上传队列", str(error), parent=self)
            return
        compatibility_note = "（兼容发布：保留云端仅有文件）" if preserve_remote_only_files else ""
        self._log(f"用户操作：已将“{display_name}”加入上传队列。{compatibility_note}")
        if previous is None:
            self._log(f"后台队列：新增“{display_name}”上传项。")
        elif previous.status is UploadQueueStatus.RUNNING:
            self._log(
                f"后台队列：检测到“{display_name}”正在上传；"
                "保留新提交，当前安全步骤结束后将上传最新提交。"
            )
        else:
            self._log(
                f"后台队列：覆盖“{display_name}”原有{previous.status}上传项，"
                "已舍弃旧提交，仅保留最新提交。"
            )
        self._refresh_content_release_summary()
        self._render_upload_queue()
        self.content_tabs.set("上传队列")

    def _render_upload_queue(self) -> None:
        if not hasattr(self, "upload_queue_list"):
            return
        for child in self.upload_queue_list.winfo_children():
            child.destroy()
        self._upload_queue_progress_widgets.clear()
        items = self.content_upload_queue.list_items()
        active = next((item for item in items if item.status is UploadQueueStatus.RUNNING), None)
        pending = sum(item.status is UploadQueueStatus.QUEUED for item in items)
        completed = sum(item.status is UploadQueueStatus.COMPLETED for item in items)
        self.upload_queue_summary.configure(
            text=f"队列：{len(items)} 项 · 等待 {pending} 项 · 已完成 {completed} 项"
        )
        self.upload_queue_start_button.configure(
            state="disabled" if active is not None or pending == 0 else "normal"
        )
        self.upload_queue_pause_button.configure(
            state="normal" if active is not None else "disabled"
        )
        if not items:
            ctk.CTkLabel(
                self.upload_queue_list,
                text="暂无上传项。请在“DLC / 补丁发布”完成资源构建后加入队列。",
                text_color=MUTED,
            ).grid(row=0, column=0, padx=20, pady=28, sticky="w")
            return
        self.upload_queue_list.grid_columnconfigure(0, weight=1)
        for row, item in enumerate(items):
            self._render_upload_queue_item(row, item, active is not None)

    def _render_upload_queue_item(self, row: int, item, has_active: bool) -> None:
        selected = item.item_id == self._queue_current_item_id
        card = ctk.CTkFrame(
            self.upload_queue_list,
            fg_color="#EAF4FF" if selected else "#FFFFFF",
            border_width=1,
            border_color="#90CAF9" if selected else "#D8DEE6",
            corner_radius=10,
        )
        card.grid(row=row, column=0, padx=10, pady=(10 if row == 0 else 4, 4), sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=f"#{row + 1}", width=36, text_color=BLUE).grid(
            row=0, column=0, rowspan=2, padx=(14, 6), pady=12
        )
        ctk.CTkLabel(
            card, text=item.display_name, font=("Microsoft YaHei UI", 15, "bold"), anchor="w"
        ).grid(row=0, column=1, padx=(0, 12), pady=(12, 1), sticky="ew")
        state_color = {
            UploadQueueStatus.COMPLETED: "#2E7D32",
            UploadQueueStatus.FAILED: RED,
            UploadQueueStatus.NEEDS_REBUILD: "#E65100",
            UploadQueueStatus.RUNNING: BLUE,
            UploadQueueStatus.PAUSED: "#9A6700",
            UploadQueueStatus.CANCELLED: MUTED,
        }.get(item.status, "#455A64")
        ctk.CTkLabel(
            card, text=self._queue_status_text(item.status), text_color=state_color
        ).grid(row=0, column=2, padx=(6, 14), pady=(12, 1), sticky="e")
        detail_label = ctk.CTkLabel(
            card, text=self._queue_item_detail(item), text_color=MUTED, anchor="w"
        )
        detail_label.grid(
            row=1, column=1, columnspan=2, padx=(0, 12), pady=(1, 8), sticky="ew"
        )
        progress = ctk.CTkProgressBar(card, height=8, progress_color=BLUE)
        total = max(1, item.total_bytes * (2 if item.status is UploadQueueStatus.RUNNING else 1))
        progress.set(1 if item.status is UploadQueueStatus.COMPLETED else min(1, item.completed_bytes / total))
        progress.grid(row=2, column=0, columnspan=3, padx=14, pady=(0, 10), sticky="ew")
        self._upload_queue_progress_widgets[item.item_id] = (detail_label, progress)
        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=0, column=3, rowspan=3, padx=(8, 14), pady=10)
        can_move = item.status is not UploadQueueStatus.RUNNING
        ctk.CTkButton(
            controls, text="↑", width=34, fg_color="transparent", border_width=1,
            border_color="#D8DEE6", text_color="#455A64",
            state="normal" if can_move and row else "disabled",
            command=lambda value=item.item_id: self._move_upload_queue_item(value, -1),
        ).grid(row=0, column=0, padx=2)
        ctk.CTkButton(
            controls, text="↓", width=34, fg_color="transparent", border_width=1,
            border_color="#D8DEE6", text_color="#455A64",
            state="normal" if can_move and row < len(self.content_upload_queue.list_items()) - 1 else "disabled",
            command=lambda value=item.item_id: self._move_upload_queue_item(value, 1),
        ).grid(row=0, column=1, padx=2)
        ctk.CTkButton(
            controls, text="删除", width=56, fg_color="transparent", border_width=1,
            border_color=RED, text_color=RED, hover_color="#FFEBEE",
            state="normal" if can_move else "disabled",
            command=lambda value=item.item_id: self._remove_upload_queue_item(value),
        ).grid(row=0, column=2, padx=(8, 0))
        if item.status in {UploadQueueStatus.PAUSED, UploadQueueStatus.FAILED}:
            ctk.CTkButton(
                controls, text="继续" if item.status is UploadQueueStatus.PAUSED else "重试",
                width=56, fg_color=LIGHT_BLUE,
                state="normal" if not has_active else "disabled",
                command=lambda value=item.item_id: self._resume_upload_queue_item(value),
            ).grid(row=0, column=3, padx=(8, 0))

    @staticmethod
    def _queue_status_text(status: UploadQueueStatus) -> str:
        return {
            UploadQueueStatus.QUEUED: "等待上传",
            UploadQueueStatus.RUNNING: "正在上传",
            UploadQueueStatus.PAUSED: "已暂停",
            UploadQueueStatus.FAILED: "上传失败",
            UploadQueueStatus.COMPLETED: "已完成",
            UploadQueueStatus.CANCELLED: "已取消",
            UploadQueueStatus.NEEDS_REBUILD: "需要重新构建",
        }[status]

    @staticmethod
    def _queue_item_detail(item) -> str:
        detail = f"{item.artifact_count} 个文件 · {_display_bytes(item.total_bytes)}"
        if item.status is UploadQueueStatus.RUNNING:
            total = max(1, item.total_bytes * 2)
            detail += f" · {item.current_source or '准备中'} {item.current_filename or ''}".rstrip()
            detail += f" · {_display_bytes(item.completed_bytes)} / {_display_bytes(total)}"
            if item.bytes_per_second > 0:
                detail += f" · {_display_bytes(item.bytes_per_second)}/s"
            if item.error:
                detail += f" · {item.error}"
        elif item.error:
            detail += f" · {item.error}"
        return detail

    def _move_upload_queue_item(self, item_id: str, offset: int) -> None:
        try:
            self.content_upload_queue.move(item_id, offset)
        except UploadQueueError as error:
            messagebox.showwarning("无法调整顺序", str(error), parent=self)
        self._render_upload_queue()

    def _remove_upload_queue_item(self, item_id: str) -> None:
        try:
            item = self.content_upload_queue.get(item_id)
            if not messagebox.askyesno(
                "移除上传项", f"确定从队列移除“{item.display_name}”吗？\n不会删除本地发布文件。", parent=self
            ):
                return
            self.content_upload_queue.remove(item_id)
        except UploadQueueError as error:
            messagebox.showwarning("无法移除上传项", str(error), parent=self)
        self._render_upload_queue()

    def _clear_upload_queue(self) -> None:
        """Remove every pending queue record after a deliberate confirmation."""
        items = self.content_upload_queue.list_items()
        if not items:
            messagebox.showinfo("上传队列为空", "当前没有可清空的上传项。", parent=self)
            return
        if not messagebox.askyesno(
            "清空上传队列",
            f"确定清空当前 {len(items)} 个上传项吗？\n不会删除已构建的本地发布文件。",
            icon="warning",
            parent=self,
        ):
            return
        try:
            removed = self.content_upload_queue.clear()
        except UploadQueueError as error:
            messagebox.showwarning("无法清空上传队列", str(error), parent=self)
            return
        self._log(f"用户操作：已清空上传队列，共移除 {len(removed)} 项。")
        self._render_upload_queue()

    def _start_upload_queue(self) -> None:
        if self._queue_worker_running:
            return
        if not self._begin_background_mutation(
            "upload-queue", "资源上传队列正在执行"
        ):
            return
        self._queue_pause_requested = False
        self._log("用户操作：开始上传队列。")
        item = self.content_upload_queue.next_runnable()
        if item is None:
            self._end_background_mutation("upload-queue")
            self._render_upload_queue()
            return
        self._start_upload_queue_item(item.item_id)

    def _start_upload_queue_item(self, item_id: str) -> None:
        if self._queue_worker_running:
            return
        try:
            item = self.content_upload_queue.mark_running(item_id)
            self._queue_current_item_id = item.item_id
        except UploadQueueError as error:
            messagebox.showwarning("无法开始上传", str(error), parent=self)
            return
        self._queue_worker_running = True
        self._last_logged_transfer = None
        self._log(f"后台任务：开始上传“{item.display_name}”。")
        self._render_upload_queue()
        self._poll_upload_queue_progress(item.item_id)

        def worker() -> None:
            release_id = item.release_id
            try:
                if not release_id:
                    self._log_background(
                        f"后台任务：正在校验“{item.display_name}”的本地发布文件。"
                    )
                    profile = next(
                        (
                            value
                            for value in self.workspace.list_games()
                            if value.game_id == item.game_id
                        ),
                        None,
                    )
                    if profile is None:
                        raise ValueError("找不到上传项对应的游戏配置。")
                    plan = self._create_game_content_batch_for_profile(profile)
                    self.content_upload_queue.enqueue(plan, display_name=item.display_name)
                    release_id = plan.batch_id
                self._log_background(
                    f"后台任务：正在读取“{item.display_name}”的双端云端差异。"
                )
                plan = self.release_service.preview_game_content_mirror(
                    release_id, self._release_center_providers(release_id)
                )
                plan = self.release_service.preflight(release_id)
                if plan.status is ReleaseStatus.PREFLIGHT_FAILED:
                    raise ValueError("本地发布文件已变化或不完整，请重新构建后再加入队列。")
                self._post_ui(
                    lambda value=plan, queue_id=item.item_id: self._confirm_upload_queue_remote_preview(
                        queue_id, value
                    )
                )
            except Exception as error:
                self._post_ui(
                    lambda value=error, queue_id=item.item_id, release_id=release_id: self._upload_queue_item_failed(
                        queue_id, value, release_id
                    )
                )

        threading.Thread(target=worker, daemon=False, name=f"content-upload-{item.game_id}").start()

    def _confirm_upload_queue_remote_preview(self, item_id: str, plan) -> None:
        """Ask for strict-mirror deletion only when this FIFO item reaches upload."""
        if item_id != self._queue_current_item_id:
            return
        self._log_upload_queue_preflight_details(plan)
        preserve_remote_only_files = bool(plan.options.get("preserve_remote_only_files"))
        extras = plan.options.get("remote_mirror_preview", {})
        extra_files = extras.get("extra_files", {}) if isinstance(extras, dict) else {}
        lines = [
            f"• {source}：{', '.join(map(str, names))}"
            for source, names in extra_files.items()
            if isinstance(names, list) and names
        ] if isinstance(extra_files, dict) else []
        if not preserve_remote_only_files:
            detail = "\n".join(lines) if lines else "• 未发现远端多余文件。"
            if not messagebox.askyesno(
                "确认本项云端变更",
                f"“{self.content_upload_queue.get(item_id).display_name}”已轮到上传。\n\n"
                "以下远端仅有文件将在新文件上传并记录双端附件 ID 后删除：\n"
                f"{detail}\n\n确认后开始上传；取消则保留本项等待稍后继续。",
                icon="warning",
                parent=self,
            ):
                self.content_upload_queue.mark_paused(item_id)
                self._queue_worker_running = False
                self._queue_current_item_id = None
                self._log("用户操作：取消当前上传项的云端变更确认，项目已暂停。")
                self._render_upload_queue()
                self._end_background_mutation("upload-queue")
                return
            plan = self.release_service.confirm_game_content_mirror_delete(plan.batch_id)
        if plan.status is ReleaseStatus.AWAITING_CONFIRMATION:
            plan = self.release_service.confirm(plan.batch_id, actor="upload-queue")
        self._log(f"后台任务：远端预检完成，开始上传“{self.content_upload_queue.get(item_id).display_name}”。")
        self._start_upload_queue_execution(item_id, plan.batch_id)

    def _log_upload_queue_preflight_details(self, plan) -> None:
        """Render the complete local snapshot and remote-only diff into the audit log."""
        self._log(f"本地发布快照：共 {len(plan.artifacts)} 个文件。")
        for artifact in plan.artifacts:
            self._log(
                f"本地文件：{artifact.filename} · {_display_bytes(artifact.size)} · "
                f"SHA-256 {artifact.sha256 or '未记录'}"
            )
        preview = plan.options.get("remote_mirror_preview", {})
        extra_files = preview.get("extra_files", {}) if isinstance(preview, dict) else {}
        preserve = bool(plan.options.get("preserve_remote_only_files"))
        action = "保留" if preserve else "将在附件校验成功后删除"
        if not isinstance(extra_files, dict):
            self._log("云端差异：未取得可展示的差异清单。")
            return
        for source in ("gitlink", "github"):
            names = extra_files.get(source, [])
            if not isinstance(names, list) or not names:
                self._log(f"{source} 云端差异：没有云端仅有文件。")
                continue
            self._log(
                f"{source} 云端仅有 {len(names)} 个文件，{action}："
                + "、".join(map(str, names))
            )

    def _log_upload_queue_verification_details(self, plan, upload_stage) -> None:
        """Log every attachment's trusted/reused outcome after a successful upload."""
        summary = upload_stage.output_summary if upload_stage is not None else {}
        ready = summary.get("ready", {}) if isinstance(summary, dict) else {}
        reused = summary.get("reused", {}) if isinstance(summary, dict) else {}
        recovered = summary.get("recovered", {}) if isinstance(summary, dict) else {}
        continued = summary.get("continued", {}) if isinstance(summary, dict) else {}
        deleted = summary.get("deleted", {}) if isinstance(summary, dict) else {}
        artifacts = {artifact.filename: artifact for artifact in plan.artifacts}
        for source in ("gitlink", "github"):
            source_ready = ready.get(source, []) if isinstance(ready, dict) else []
            source_reused = reused.get(source, []) if isinstance(reused, dict) else []
            source_recovered = recovered.get(source, []) if isinstance(recovered, dict) else []
            source_continued = continued.get(source, []) if isinstance(continued, dict) else []
            reused_names = set(source_reused) if isinstance(source_reused, list) else set()
            recovered_names = set(source_recovered) if isinstance(source_recovered, list) else set()
            continued_names = set(source_continued) if isinstance(source_continued, list) else set()
            if isinstance(source_ready, list):
                for name in source_ready:
                    artifact = artifacts.get(str(name))
                    if artifact is None:
                        continue
                    if name in reused_names:
                        result = "复用可信云端附件记录"
                    elif name in recovered_names:
                        result = "上传响应丢失，已从远端附件记录恢复"
                    elif name in continued_names:
                        result = "沿用本批此前已成功的上传端"
                    else:
                        result = "上传成功，已记录远端附件 ID 与大小"
                    self._log(
                        f"{source} 校验结果：{name} · {result} · "
                        f"{_display_bytes(artifact.size)} · SHA-256 {artifact.sha256 or '未记录'}"
                    )
            source_deleted = deleted.get(source, []) if isinstance(deleted, dict) else []
            if isinstance(source_deleted, list):
                for name in source_deleted:
                    self._log(f"{source} 云端差异处理：已删除远端仅有文件 {name}。")
        index_stage = next(
            (stage for stage in plan.stages if stage.stage_id == "game_content.publish_index"),
            None,
        )
        catalog = next((item for item in plan.artifacts if item.filename == "catalog.json"), None)
        if index_stage is not None and catalog is not None:
            switched = index_stage.output_summary.get("switched", [])
            self._log(
                f"catalog.json 发布成功，已记录远端附件 ID 与大小：{', '.join(map(str, switched))} · "
                f"{_display_bytes(catalog.size)} · SHA-256 {catalog.sha256 or '未记录'}"
            )

    def _start_upload_queue_execution(self, item_id: str, batch_id: str) -> None:
        def worker() -> None:
            try:
                result = self.release_service.execute_game_content(
                    batch_id, self._release_center_providers(batch_id)
                )
                self._post_ui(
                    lambda value=result, queue_id=item_id: self._upload_queue_item_finished(
                        queue_id, value
                    )
                )
            except Exception as error:
                self._post_ui(
                    lambda value=error, queue_id=item_id, release_id=batch_id:
                    self._upload_queue_item_failed(queue_id, value, release_id)
                )

        threading.Thread(
            target=worker, daemon=False, name=f"execute-content-{batch_id[:8]}"
        ).start()

    def _resume_upload_queue_item(self, item_id: str) -> None:
        """Explicitly resume a paused/failed item before later queued games."""
        if self._queue_worker_running:
            return
        if not self._begin_background_mutation(
            "upload-queue", "资源上传队列正在执行"
        ):
            return
        self._queue_pause_requested = False
        self._start_upload_queue_item(item_id)

    def _poll_upload_queue_progress(self, item_id: str) -> None:
        if item_id != self._queue_current_item_id or not self._queue_worker_running:
            return
        try:
            item = self.content_upload_queue.get(item_id)
            plan = self.release_service.get(item.release_id)
            sample = plan.options.get("upload_progress")
            if isinstance(sample, dict):
                self._update_content_transfer_progress(sample)
                sent = int(sample.get("sent") or 0)
                total = int(sample.get("total") or 0)
                completed_key = (
                    str(sample.get("operation") or "上传"),
                    str(sample.get("source") or ""),
                    str(sample.get("filename") or ""),
                )
                if total > 0 and sent >= total and completed_key != getattr(self, "_last_logged_transfer", None):
                    self._last_logged_transfer = completed_key
                    self._log(
                        f"文件传输完成：{completed_key[0]} · {completed_key[1]} · {completed_key[2]} · "
                        f"{_display_bytes(total)}"
                    )
            item = self.content_upload_queue.sync_progress(item_id, plan)
            widgets = self._upload_queue_progress_widgets.get(item_id)
            if widgets is not None:
                detail_label, progress = widgets
                total = max(1, item.total_bytes * 2)
                detail_label.configure(text=self._queue_item_detail(item))
                progress.set(min(1, item.completed_bytes / total))
        except Exception:
            pass
        self.after(350, lambda value=item_id: self._poll_upload_queue_progress(value))

    def _pause_upload_queue(self) -> None:
        item_id = self._queue_current_item_id
        if item_id is None:
            return
        try:
            item = self.content_upload_queue.get(item_id)
            self._queue_pause_requested = True
            self._log(f"用户操作：请求安全暂停“{item.display_name}”的上传。")
            self.release_service.request_pause(item.release_id)
            self.upload_queue_pause_button.configure(state="disabled", text="正在暂停…")
        except Exception as error:
            messagebox.showerror("无法暂停上传", str(error), parent=self)

    def _upload_queue_item_finished(self, item_id: str, plan) -> None:
        self._queue_worker_running = False
        self._queue_current_item_id = None
        latest = self.content_upload_queue.get(item_id)
        if latest.release_id != plan.batch_id:
            self.content_upload_queue.requeue_latest(item_id)
            self._log(f"后台任务：旧提交上传结束；“{latest.display_name}”已保留最新提交并重新排队。")
        elif plan.status is ReleaseStatus.PAUSED or self._queue_pause_requested:
            self.content_upload_queue.mark_paused(item_id)
        elif plan.status is ReleaseStatus.COMPLETED:
            self.content_upload_queue.mark_completed(item_id)
            upload_stage = next(
                (
                    stage
                    for stage in plan.stages
                    if stage.stage_id == "game_content.upload_snapshot"
                ),
                None,
            )
            reused = (
                upload_stage.output_summary.get("reused", {})
                if upload_stage is not None
                else {}
            )
            reuse_cache = (
                upload_stage.output_summary.get("content_reuse_cache")
                if upload_stage is not None
                else None
            )
            profile = next(
                (
                    value
                    for value in self.workspace.list_games()
                    if value.game_id == latest.game_id
                ),
                None,
            )
            if profile is not None and isinstance(reuse_cache, dict):
                self.workspace.save_content_reuse_cache(profile, reuse_cache)
            self._log_upload_queue_verification_details(plan, upload_stage)
            reused_count = sum(
                len(value) for value in reused.values() if isinstance(value, list)
            )
            if reused_count:
                self._log(
                    f"后台任务：已按云端构建缓存复用 {reused_count} 个附件，未重复上传。"
                )
            self._log(f"后台任务：已完成“{latest.display_name}”的上传。")
        else:
            self.content_upload_queue.mark_failed(item_id, "发布未完成，请查看发布记录。")
        self.upload_queue_pause_button.configure(text="暂停当前项")
        self._render_upload_queue()
        next_item = self.content_upload_queue.next_runnable()
        if not self._queue_pause_requested and next_item is not None:
            self.after(100, lambda value=next_item.item_id: self._start_upload_queue_item(value))
        else:
            self._end_background_mutation("upload-queue")

    def _upload_queue_item_failed(
        self, item_id: str, error: Exception, running_release_id: str
    ) -> None:
        self._queue_worker_running = False
        self._queue_current_item_id = None
        text = str(error)
        latest = self.content_upload_queue.get(item_id)
        if latest.release_id != running_release_id:
            self.content_upload_queue.requeue_latest(item_id)
            self._log(f"后台任务：旧上传失败；“{latest.display_name}”的最新提交已重新排队。")
        elif self._queue_pause_requested:
            self.content_upload_queue.mark_paused(item_id)
        elif "发布文件" in text and ("变化" in text or "不完整" in text):
            self.content_upload_queue.mark_needs_rebuild(item_id, text)
        else:
            self.content_upload_queue.mark_failed(item_id, text)
            self._log(f"后台任务：上传失败：{text}")
        self.upload_queue_pause_button.configure(text="暂停当前项")
        self._render_upload_queue()
        next_item = self.content_upload_queue.next_runnable()
        if not self._queue_pause_requested and next_item is not None:
            self.after(100, lambda value=next_item.item_id: self._start_upload_queue_item(value))
        else:
            self._end_background_mutation("upload-queue")
