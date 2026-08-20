"""Tk workspace for the persistent DLC / patch upload queue."""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

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
            text="已加入的游戏会按顺序上传到 GitLink 和 GitHub。每个文件都会回读校验，catalog.json 始终最后发布。",
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
        self.upload_queue_refresh_button = ctk.CTkButton(
            actions, text="刷新", width=82, fg_color="transparent", border_width=1,
            border_color="#D8DEE6", text_color="#455A64", command=self._render_upload_queue,
        )
        self.upload_queue_refresh_button.grid(row=0, column=3, padx=(8, 0))

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

    def _enqueue_current_game_upload(self) -> None:
        """Turn the selected, fully built game into an ordinary queue item."""
        try:
            existing = self.content_upload_queue.active_for_game(self.profile.game_id)
            if existing is not None:
                raise UploadQueueError(
                    f"“{self.profile.display_name}”已在队列中（{self._queue_status_text(existing.status)}）。"
                )
            plan = self._create_current_game_content_batch()
        except Exception as error:
            messagebox.showerror("无法加入上传队列", str(error), parent=self)
            return
        display_name = self.profile.display_name
        game_id = self.profile.game_id
        self._show_queue_preview_loading(display_name)

        def worker() -> None:
            try:
                preview = self.release_service.preview_game_content_mirror(
                    plan.batch_id, self._release_center_providers(plan.batch_id)
                )
                self._post_ui(
                    lambda value=preview, name=display_name: self._confirm_enqueue_current_game(value, name)
                )
            except Exception as error:
                self._post_ui(
                    lambda value=error: self._handle_queue_preview_failure(value)
                )

        threading.Thread(target=worker, daemon=True, name=f"preview-content-{game_id}").start()

    def _handle_queue_preview_failure(self, error: Exception) -> None:
        self._refresh_content_release_summary()
        messagebox.showerror("无法读取云端资源", str(error), parent=self)

    def _show_queue_preview_loading(self, display_name: str) -> None:
        if hasattr(self, "content_release_scope_label"):
            self.content_release_scope_label.configure(text=f"正在读取“{display_name}”的云端资源差异…")

    def _confirm_enqueue_current_game(self, plan, display_name: str) -> None:
        preview = plan.options.get("remote_mirror_preview", {})
        extras = preview.get("extra_files", {}) if isinstance(preview, dict) else {}
        delete_lines = []
        if isinstance(extras, dict):
            for source, names in extras.items():
                if isinstance(names, list) and names:
                    delete_lines.append(f"• {source}：{', '.join(map(str, names))}")
        delete_detail = "\n".join(delete_lines) if delete_lines else "• 未发现远端多余文件。"
        if not messagebox.askyesno(
            "确认加入上传队列",
            f"将“{display_name}”加入上传队列。\n\n"
            "已完成本地与云端目录比对。上传时新增和变化文件会先回读校验，"
            "最后才发布 catalog.json。以下远端多余文件将在校验成功后删除：\n"
            f"{delete_detail}\n\n"
            "确认后可以继续整理其他游戏；队列会按加入顺序上传。",
            icon="warning",
            parent=self,
        ):
            self._refresh_content_release_summary()
            return
        try:
            confirmed = self.release_service.confirm_game_content_mirror_delete(plan.batch_id)
            self.content_upload_queue.enqueue(confirmed, display_name=display_name)
        except Exception as error:
            messagebox.showerror("无法加入上传队列", str(error), parent=self)
            return
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

    def _start_upload_queue(self) -> None:
        if self._queue_worker_running:
            return
        if not self._begin_background_mutation(
            "upload-queue", "资源上传队列正在执行"
        ):
            return
        self._queue_pause_requested = False
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
        self._render_upload_queue()
        self._poll_upload_queue_progress(item.item_id)

        def worker() -> None:
            try:
                plan = self.release_service.preflight(item.release_id)
                if plan.status is ReleaseStatus.PREFLIGHT_FAILED:
                    raise ValueError("本地发布文件已变化或不完整，请重新构建后再加入队列。")
                if plan.status is not ReleaseStatus.AWAITING_CONFIRMATION:
                    plan = self.release_service.confirm(plan.batch_id, actor="upload-queue")
                result = self.release_service.execute_game_content(
                    plan.batch_id, self._release_center_providers(plan.batch_id)
                )
                self._post_ui(lambda value=result, queue_id=item.item_id: self._upload_queue_item_finished(queue_id, value))
            except Exception as error:
                self._post_ui(lambda value=error, queue_id=item.item_id: self._upload_queue_item_failed(queue_id, value))

        threading.Thread(target=worker, daemon=False, name=f"content-upload-{item.game_id}").start()

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
            self.release_service.request_pause(item.release_id)
            self.upload_queue_pause_button.configure(state="disabled", text="正在暂停…")
        except Exception as error:
            messagebox.showerror("无法暂停上传", str(error), parent=self)

    def _upload_queue_item_finished(self, item_id: str, plan) -> None:
        self._queue_worker_running = False
        self._queue_current_item_id = None
        if plan.status is ReleaseStatus.PAUSED or self._queue_pause_requested:
            self.content_upload_queue.mark_paused(item_id)
        elif plan.status is ReleaseStatus.COMPLETED:
            self.content_upload_queue.mark_completed(item_id)
        else:
            self.content_upload_queue.mark_failed(item_id, "发布未完成，请查看发布记录。")
        self.upload_queue_pause_button.configure(text="暂停当前项")
        self._render_upload_queue()
        next_item = self.content_upload_queue.next_runnable()
        if not self._queue_pause_requested and next_item is not None:
            self.after(100, lambda value=next_item.item_id: self._start_upload_queue_item(value))
        else:
            self._end_background_mutation("upload-queue")

    def _upload_queue_item_failed(self, item_id: str, error: Exception) -> None:
        self._queue_worker_running = False
        self._queue_current_item_id = None
        text = str(error)
        if "发布文件" in text and ("变化" in text or "不完整" in text):
            self.content_upload_queue.mark_needs_rebuild(item_id, text)
        elif self._queue_pause_requested:
            self.content_upload_queue.mark_paused(item_id)
        else:
            self.content_upload_queue.mark_failed(item_id, text)
        self.upload_queue_pause_button.configure(text="暂停当前项")
        self._render_upload_queue()
        next_item = self.content_upload_queue.next_runnable()
        if not self._queue_pause_requested and next_item is not None:
            self.after(100, lambda value=next_item.item_id: self._start_upload_queue_item(value))
        else:
            self._end_background_mutation("upload-queue")
