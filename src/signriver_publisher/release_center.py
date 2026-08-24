"""Tk presentation layer for the release-center workflow.

All release rules live in :mod:`release_service`; this module only translates
button actions into service calls and renders persisted batch state.
"""

from __future__ import annotations

from pathlib import Path
import json
from typing import Callable
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .release_models import CheckResult, ReleaseKind, ReleasePlan, ReleaseStatus
from .release_service import ReleaseService
from signriver_launcher.constants import LAUNCHER_VERSION


class ReleaseCenter(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        service: ReleaseService,
        remote_targets: Callable[[], dict[str, dict[str, str]]],
        execute_batch: Callable[[str, Callable[[ReleasePlan], None], Callable[[Exception], None]], bool],
        pause_batch: Callable[[str], None],
        default_inbox: Path | str | None = None,
        refresh_collection: Callable[[str], None] | None = None,
        capture_baseline: Callable[[str], None] | None = None,
        export_baseline: Callable[[str], None] | None = None,
        create_game_content_batch: Callable[[], ReleasePlan] | None = None,
        open_game_content_pipeline: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.service = service
        self.remote_targets = remote_targets
        self.execute_batch = execute_batch
        self.pause_batch = pause_batch
        self.default_inbox = Path(default_inbox) if default_inbox is not None else service.default_program_inbox()
        self.default_module_inbox = service.default_program_module_inbox()
        self.refresh_collection = refresh_collection
        self.capture_baseline = capture_baseline
        self.export_baseline = export_baseline
        self.create_game_content_batch_callback = create_game_content_batch
        self.open_game_content_pipeline_callback = open_game_content_pipeline
        self.current_batch_id: str | None = None
        self.viewed_history_batch_id: str | None = None
        # 发布在后台线程执行；界面定时从持久化批次读取阶段状态，确保操作人
        # 能看到当前步骤，并且仅在实际进入 RUNNING 后开放安全暂停。
        self._execution_in_progress = False
        self._execution_monitor_after_id: str | None = None
        self._pause_requested = False
        self._build()
        self.refresh_history()
        self._select_latest_record_as_current()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text="发布包与归档", font=("Microsoft YaHei UI", 24, "bold")).grid(
            row=0, column=0, padx=18, pady=(14, 4), sticky="w"
        )
        ctk.CTkLabel(
            self,
            text="选择发布包后完成核对与上传；程序会自动保留可恢复的发布记录。",
            text_color="#666666",
        ).grid(row=1, column=0, padx=18, pady=(0, 12), sticky="w")

        self.page_container = ctk.CTkFrame(self, fg_color="transparent")
        self.page_container.grid(row=2, column=0, padx=18, pady=(0, 14), sticky="nsew")
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._build_home_page()
        self._build_preparation_page()
        self._build_comparison_page()
        self._build_batches_page()
        self._build_preflight_page()
        self._build_execution_page()
        self.show_page("home")

    def _new_page(self, name: str) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.page_container, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self.pages[name] = page
        return page

    def _page_heading(
        self,
        page: ctk.CTkFrame,
        title: str,
        subtitle: str,
        *,
        back_page: str | None = "home",
    ) -> ctk.CTkFrame:
        heading = ctk.CTkFrame(page)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        title_column = 0
        if back_page is not None:
            heading.grid_columnconfigure(1, weight=1)
            ctk.CTkButton(
                heading,
                text="← 返回发布包与归档",
                width=156,
                height=40,
                font=("Microsoft YaHei UI", 14, "bold"),
                command=lambda: self.show_page(back_page),
            ).grid(row=0, column=0, rowspan=2, padx=10, pady=10, sticky="w")
            title_column = 1
        else:
            heading.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(heading, text=title, font=("Microsoft YaHei UI", 18, "bold")).grid(
            row=0, column=title_column, padx=(12, 10), pady=(9, 0), sticky="w"
        )
        ctk.CTkLabel(heading, text=subtitle, text_color="#666666").grid(
            row=1, column=title_column, padx=(12, 10), pady=(0, 9), sticky="w"
        )
        return heading

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.grid_remove()
        self.pages[name].grid()

    def _build_home_page(self) -> None:
        page = self._new_page("home")
        content = ctk.CTkFrame(page, fg_color="transparent")
        content.grid(row=0, column=0, sticky="ew", pady=(8, 0))
        content.grid_columnconfigure((0, 1), weight=1)

        primary = ctk.CTkFrame(
            content,
            fg_color="#EAF4FD",
            border_width=1,
            border_color="#B6DAFB",
        )
        primary.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        primary.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            primary,
            text="发布包与归档模块提交",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color="#1769C2",
        ).grid(row=0, column=0, padx=20, pady=(20, 3), sticky="w")
        ctk.CTkLabel(
            primary,
            text="查看发布包与归档模块提交，并与双端云端内容比较。上传只新增或替换同名文件，不会删除旧文件。",
            text_color="#40566E",
            wraplength=600,
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, padx=20, pady=(0, 16), sticky="w")
        ctk.CTkButton(
            primary,
            text="管理发布包与归档模块提交  →",
            command=self.start_new_program_release,
            width=170,
            height=42,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=2, column=0, padx=20, pady=(0, 20), sticky="w")

        history = ctk.CTkFrame(
            content,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#DDE5EE",
        )
        history.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        history.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            history,
            text="历史发布记录",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color="#334155",
        ).grid(row=0, column=0, padx=20, pady=(20, 3), sticky="w")
        ctk.CTkLabel(
            history,
            text="查看已提交发布的状态、远端核对结果和归档内容；历史记录不会影响下一次发布。",
            text_color="#687789",
            wraplength=520,
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, padx=20, pady=(0, 16), sticky="w")
        ctk.CTkButton(
            history,
            text="查看历史记录  →",
            command=lambda: self.show_page("batches"),
            width=170,
            height=42,
            fg_color="transparent",
            text_color="#1769C2",
            border_width=1,
            border_color="#A9D2F7",
            hover_color="#EAF4FD",
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=2, column=0, padx=20, pady=(0, 20), sticky="w")


    def _build_preparation_page(self) -> None:
        page = self._new_page("preparation")
        self._page_heading(
            page,
            "发布包与归档模块提交",
            "从提交目录读取三端更新包与模块归档并比较双端云端内容；同步只新增或替换同名文件，绝不删除远端旧文件。",
        )
        content = ctk.CTkFrame(page)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(content, text="程序版本").grid(row=0, column=0, padx=12, pady=(14, 8), sticky="w")
        self.version_entry = ctk.CTkEntry(content, width=160, placeholder_text="例如 0.2.0")
        self.version_entry.grid(row=0, column=1, padx=12, pady=(14, 8), sticky="w")
        self.version_entry.insert(0, LAUNCHER_VERSION)
        self.version_entry.bind("<FocusOut>", self._load_notes_for_version)
        ctk.CTkLabel(content, text="三端包收件目录").grid(row=1, column=0, padx=12, pady=8, sticky="w")
        self.inbox_entry = ctk.CTkEntry(content)
        self.inbox_entry.grid(row=1, column=1, padx=12, pady=8, sticky="ew")
        self.inbox_entry.insert(0, str(self.default_inbox))
        ctk.CTkButton(content, text="选择目录", width=92, command=self._choose_inbox).grid(row=1, column=2, padx=(0, 12), pady=8)
        ctk.CTkLabel(content, text="模块归档目录").grid(row=2, column=0, padx=12, pady=8, sticky="w")
        self.module_inbox_entry = ctk.CTkEntry(content)
        self.module_inbox_entry.grid(row=2, column=1, padx=12, pady=8, sticky="ew")
        self.module_inbox_entry.insert(0, str(self.default_module_inbox))
        ctk.CTkButton(content, text="选择目录", width=92, command=self._choose_module_inbox).grid(row=2, column=2, padx=(0, 12), pady=8)
        ctk.CTkLabel(content, text="更新说明", anchor="nw").grid(row=3, column=0, padx=12, pady=(12, 8), sticky="nw")
        self.notes_entry = ctk.CTkTextbox(content, height=150)
        self.notes_entry.grid(row=3, column=1, columnspan=2, padx=(12, 12), pady=(12, 8), sticky="ew")
        self.notes_entry.insert("1.0", self.service.load_update_notes_draft(self.version_entry.get().strip()))
        self.mandatory = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(content, text="强制更新", variable=self.mandatory).grid(row=4, column=1, padx=12, pady=10, sticky="w")
        ctk.CTkButton(content, text="保存版本草稿", command=self.save_notes_draft).grid(row=4, column=2, padx=12, pady=10, sticky="e")
        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.grid(row=5, column=1, columnspan=2, padx=12, pady=(2, 8), sticky="w")
        self.compare_button = ctk.CTkButton(
            actions,
            text="验证并查看差异",
            command=self.refresh_and_compare_local_files,
            height=42,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.compare_button.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="发布文件  →",
            command=self.publish_program_files,
            height=42,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(side="left")

    def _build_comparison_page(self) -> None:
        page = self._new_page("comparison")
        page.grid_rowconfigure(1, weight=0)
        page.grid_rowconfigure(2, weight=1)
        self._page_heading(
            page,
            "本地与云端差异",
            "核验后按两侧展示待同步文件与各云端的差异；仅展示远端旧文件，不会删除它们。",
            back_page=None,
        )
        toolbar = ctk.CTkFrame(page, fg_color="transparent")
        toolbar.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        ctk.CTkButton(toolbar, text="← 返回发布包与归档模块提交", command=lambda: self.show_page("preparation")).pack(side="left")
        self.comparison_summary = ctk.CTkLabel(toolbar, text="尚未验证云端文件。", text_color="#666666", anchor="w")
        self.comparison_summary.pack(side="left", padx=14)
        columns = ctk.CTkFrame(page, fg_color="transparent")
        columns.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")
        columns.grid_columnconfigure((0, 1), weight=1, uniform="comparison")
        columns.grid_rowconfigure(0, weight=1)
        local = ctk.CTkFrame(columns)
        remote = ctk.CTkFrame(columns)
        local.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        remote.grid(row=0, column=1, padx=(6, 0), sticky="nsew")
        for frame, title in ((local, "本地待同步文件"), (remote, "云端差异文件")):
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(1, weight=1)
            ctk.CTkLabel(frame, text=title, font=("Microsoft YaHei UI", 17, "bold"), text_color="#1976D2").grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")
        self.comparison_local_list = ctk.CTkScrollableFrame(local, fg_color="#FAFAFA")
        self.comparison_remote_list = ctk.CTkScrollableFrame(remote, fg_color="#FAFAFA")
        self.comparison_local_list.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.comparison_remote_list.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")

    def _build_batches_page(self) -> None:
        page = self._new_page("batches")
        self._page_heading(page, "发布记录", "选择记录后仅查看已保存的发布信息；不会切换当前发布或修改任何流程状态。")
        content = ctk.CTkFrame(page, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        # 历史侧栏必须是固定宽度；详情列独占余量，避免长看板文本在
        # 选择不同批次后反向挤压左列，造成界面比例抖动。
        content.grid_columnconfigure(0, weight=0, minsize=360)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)
        history_card = ctk.CTkFrame(content, width=360)
        history_card.grid(row=0, column=0, padx=(0, 7), sticky="nsew")
        history_card.grid_propagate(False)
        ctk.CTkLabel(history_card, text="发布记录", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", padx=10, pady=8)
        self.history = ctk.CTkScrollableFrame(history_card)
        self.history.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        detail = ctk.CTkFrame(content)
        detail.grid(row=0, column=1, padx=(7, 0), sticky="nsew")
        board_header = ctk.CTkFrame(detail, fg_color="transparent")
        board_header.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkLabel(
            board_header, text="发布详情", font=("Microsoft YaHei UI", 16, "bold")
        ).pack(side="left")
        self.board_content = ctk.CTkScrollableFrame(detail, fg_color="transparent")
        self.board_content.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        baseline_card = ctk.CTkFrame(self.board_content)
        baseline_card.pack(fill="x", padx=4, pady=(0, 8))
        baseline_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            baseline_card, text="远端核对记录", font=("Microsoft YaHei UI", 15, "bold")
        ).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
        self.baseline_status_label = ctk.CTkLabel(
            baseline_card,
            text="请在左侧选择一条发布记录查看已保存的远端核对信息。",
            justify="left",
            anchor="nw",
            wraplength=620,
            text_color="#666666",
        )
        self.baseline_status_label.grid(row=1, column=0, padx=12, pady=(3, 10), sticky="ew")
        self.status_label = ctk.CTkLabel(
            self.board_content,
            text="尚未选择发布记录",
            justify="left",
            anchor="nw",
            wraplength=640,
        )
        self.status_label.pack(fill="x", expand=True, padx=4, pady=(0, 4), anchor="nw")

    def _build_preflight_page(self) -> None:
        page = self._new_page("preflight")
        self._page_heading(page, "预检与确认", "先预检文件和发布条件；确认后会冻结本次输入。人工验收仅作为参考提醒。")
        content = ctk.CTkFrame(page)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        self.preflight_status_label = ctk.CTkLabel(content, text="请先创建或选择一条发布记录。", justify="left", anchor="nw", wraplength=900)
        self.preflight_status_label.grid(row=0, column=0, padx=14, pady=14, sticky="nsew")
        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="w")
        self.preflight_button = ctk.CTkButton(
            actions, text="运行预检", command=self.run_preflight, height=40,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.preflight_button.pack(side="left", padx=(0, 6))
        self.confirm_button = ctk.CTkButton(
            actions, text="确认冻结输入", command=self.confirm, height=40,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.confirm_button.pack(side="left", padx=6)

    def _build_execution_page(self) -> None:
        page = self._new_page("execution")
        self._page_heading(
            page,
            "发布文件",
            "进入后会自动预检；预检通过后请点击“开始发布”。预检错误会显示在下方，且不会上传文件。",
        )
        content = ctk.CTkFrame(page)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        progress = ctk.CTkFrame(content, fg_color="#F7FAFD", border_width=1, border_color="#D8E4F0")
        progress.grid(row=0, column=0, padx=14, pady=(14, 10), sticky="ew")
        progress.grid_columnconfigure(0, weight=1)
        self.execution_status_label = ctk.CTkLabel(
            progress,
            text="请先创建或选择一条发布记录。",
            justify="left",
            anchor="w",
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.execution_status_label.grid(row=0, column=0, padx=12, pady=(10, 3), sticky="ew")
        self.overall_progress_label = ctk.CTkLabel(
            progress, text="总体进度：等待开始", justify="left", anchor="w", text_color="#687789"
        )
        self.overall_progress_label.grid(row=1, column=0, padx=12, pady=(0, 3), sticky="ew")
        self.overall_progress_bar = ctk.CTkProgressBar(progress)
        self.overall_progress_bar.grid(row=2, column=0, padx=12, pady=(0, 9), sticky="ew")
        self.overall_progress_bar.set(0)

        upload_status = ctk.CTkFrame(progress, fg_color="#FFFFFF")
        upload_status.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        upload_status.grid_columnconfigure(0, weight=1)
        self.upload_progress_label = ctk.CTkLabel(
            upload_status,
            text="单文件进度：等待执行。",
            justify="left",
            anchor="w",
            font=("Microsoft YaHei UI", 13),
        )
        self.upload_progress_label.grid(row=0, column=0, padx=12, pady=(8, 3), sticky="ew")
        self.upload_progress_bar = ctk.CTkProgressBar(upload_status)
        self.upload_progress_bar.grid(row=1, column=0, padx=12, pady=(3, 9), sticky="ew")
        self.upload_progress_bar.set(0)

        log_frame = ctk.CTkFrame(content, fg_color="#F7F8FA", border_width=1, border_color="#DDE5EE")
        log_frame.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            log_frame, text="执行日志", font=("Microsoft YaHei UI", 15, "bold"), anchor="w"
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="ew")
        self.execution_log = ctk.CTkTextbox(
            log_frame,
            font=("Cascadia Mono", 12),
            wrap="word",
            fg_color="#FFFFFF",
            text_color="#243447",
        )
        self.execution_log.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.execution_log.configure(state="disabled")
        self._execution_log_text = ""
        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.grid(row=2, column=0, padx=14, pady=(0, 14), sticky="w")
        self.execute_button = ctk.CTkButton(
            actions, text="开始发布", command=self.start_program_publish, height=40,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.execute_button.pack(side="left", padx=(0, 6))
        self.pause_button = ctk.CTkButton(
            actions, text="安全暂停", command=self.pause, fg_color="#E09000", height=40,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.pause_button.pack(side="left", padx=6)

    def _load_notes_for_version(self, _event=None) -> None:
        version = self.version_entry.get().strip()
        if not version:
            return
        self.notes_entry.delete("1.0", "end")
        self.notes_entry.insert("1.0", self.service.load_update_notes_draft(version))

    def _notes(self) -> str:
        return self.notes_entry.get("1.0", "end").strip()

    def save_notes_draft(self) -> None:
        try:
            self.service.save_update_notes_draft(self.version_entry.get(), self._notes())
            messagebox.showinfo("已保存", "已保存该版本的更新说明草稿。", parent=self)
        except Exception as exc:
            messagebox.showerror("保存草稿失败", str(exc), parent=self)

    def _require_current_batch(self, action: str) -> bool:
        if self.current_batch_id:
            return True
        messagebox.showinfo("请先选择发布记录", f"请先创建或在左侧选择一条发布记录，再{action}。", parent=self)
        return False

    def start_new_program_release(self) -> None:
        """Leave historical inspection mode and prepare an editable program release.

        A completed record remains selectable for audit purposes, but must never
        silently become the target of refresh or replacement controls on the
        next release.  This explicit entry resets only form state, never the
        archived record itself.
        """
        self.current_batch_id = None
        self.version_entry.delete(0, "end")
        self.version_entry.insert(0, LAUNCHER_VERSION)
        self.inbox_entry.delete(0, "end")
        self.inbox_entry.insert(0, str(self.default_inbox))
        self.module_inbox_entry.delete(0, "end")
        self.module_inbox_entry.insert(0, str(self.default_module_inbox))
        self.notes_entry.delete("1.0", "end")
        self.notes_entry.insert(
            "1.0", self.service.load_update_notes_draft(LAUNCHER_VERSION)
        )
        self._render_empty_state("正在准备新的程序更新发布。填写版本和收件目录后继续。")
        self.show_page("preparation")

    def refresh_inbox(self) -> None:
        if self._require_current_batch("刷新收件目录") and self.refresh_collection:
            self.refresh_collection(self.current_batch_id)

    def read_baseline(self) -> None:
        if self._require_current_batch("读取远端基线") and self.capture_baseline:
            self.capture_baseline(self.current_batch_id)

    def save_baseline(self) -> None:
        if self._require_current_batch("导出远端基线") and self.export_baseline:
            self.export_baseline(self.current_batch_id)

    def _choose_inbox(self) -> None:
        current = Path(self.inbox_entry.get().strip()).expanduser()
        initialdir = current if current.is_dir() else self.default_inbox
        selected = filedialog.askdirectory(parent=self, initialdir=str(initialdir))
        if selected:
            self.inbox_entry.delete(0, "end")
            self.inbox_entry.insert(0, selected)

    def _choose_module_inbox(self) -> None:
        current = Path(self.module_inbox_entry.get().strip()).expanduser()
        initialdir = current if current.is_dir() else self.default_module_inbox
        selected = filedialog.askdirectory(parent=self, initialdir=str(initialdir))
        if selected:
            self.module_inbox_entry.delete(0, "end")
            self.module_inbox_entry.insert(0, selected)

    def _ensure_program_batch(self) -> tuple[ReleasePlan, bool]:
        """Create the internal record on demand; it is never a user-facing step."""
        version = self.version_entry.get().strip()
        state_path = self.service.workspace_root / "app" / "state.json"
        active_version = ""
        if state_path.is_file():
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            active_version = str(payload.get("active_version") or "").strip()
        if version != LAUNCHER_VERSION:
            raise ValueError(f"程序版本必须与启动器版本 {LAUNCHER_VERSION} 一致")
        if active_version and version != active_version:
            raise ValueError(
                f"程序版本必须与 app/state.json 的 active_version {active_version} 一致"
            )
        inbox = Path(self.inbox_entry.get()).expanduser()
        module_inbox = Path(self.module_inbox_entry.get()).expanduser()
        existing = self.service.find_reusable_program_batch(
            version=version, inbox=inbox, module_inbox=module_inbox
        )
        if existing is not None:
            return existing, True
        return (
            self.service.create_program_batch(
                version=version,
                inbox=inbox,
                module_inbox=module_inbox,
                notes=self._notes(),
                mandatory=self.mandatory.get(),
                remote_targets=self.remote_targets(),
            ),
            False,
        )

    def create_batch(self) -> None:
        try:
            plan, _reused = self._ensure_program_batch()
        except Exception as exc:
            messagebox.showerror("无法准备发布包与归档模块提交", str(exc), parent=self)
            return
        self.select(plan.batch_id, show_history=False)
        self.refresh_history()
        self.show_page("preflight")

    def publish_program_files(self) -> None:
        """Open the execution page and preflight only; publishing needs a second action."""
        try:
            plan, _reused = self._ensure_program_batch()
            self.select(plan.batch_id, show_history=False)
            self.refresh_history()
            self.show_page("execution")
            self.execution_status_label.configure(text="正在预检发布包与归档模块提交与发布条件…")
            plan = self.service.preflight(plan.batch_id)
            self._render(plan)
            if plan.status is ReleaseStatus.PREFLIGHT_FAILED:
                self.execution_status_label.configure(
                    text="预检未通过，未开始上传。\n\n" + self.execution_status_label.cget("text")
                )
                self.execute_button.configure(state="disabled", text="预检未通过")
                return
            if plan.status is ReleaseStatus.AWAITING_CONFIRMATION:
                self.execution_status_label.configure(
                    text="预检通过，尚未开始上传。请核对结果后点击“开始发布”。"
                )
                self.execute_button.configure(state="normal", text="开始发布")
                return
            self.execution_status_label.configure(
                text="当前发布记录尚未准备好开始上传，请根据下方状态处理后重试。"
            )
            self.execute_button.configure(state="disabled", text="暂不可发布")
        except Exception as exc:
            self.execution_status_label.configure(text=f"预检或发布准备失败，未开始上传。\n\n{exc}")
            self.execute_button.configure(state="disabled", text="预检失败")
            messagebox.showerror("无法提交发布包与归档模块", str(exc), parent=self)

    def start_program_publish(self) -> None:
        """Freeze a passed preflight and start the actual background upload."""
        if not self.current_batch_id:
            return
        try:
            plan = self.service.get(self.current_batch_id)
            if plan.status is ReleaseStatus.AWAITING_CONFIRMATION:
                plan = self.service.confirm(plan.batch_id)
                self._render(plan)
            elif plan.status not in {
                ReleaseStatus.PAUSED,
                ReleaseStatus.INTERRUPTED,
                ReleaseStatus.DEGRADED,
                ReleaseStatus.FAILED,
            }:
                self.execution_status_label.configure(
                    text="请先完成预检；预检通过后才能开始发布。"
                )
                return
            self.execute()
        except Exception as exc:
            self.execution_status_label.configure(text=f"无法开始发布，未上传文件。\n\n{exc}")
            messagebox.showerror("无法开始发布", str(exc), parent=self)

    def refresh_and_compare_local_files(self) -> None:
        try:
            plan, _reused = self._ensure_program_batch()
            self.select(plan.batch_id, show_history=False)
            self.show_page("comparison")
            self.comparison_summary.configure(text="正在读取发布包与归档模块提交，并依次核验 GitLink、GitHub 云端内容…")
            for frame in (self.comparison_local_list, self.comparison_remote_list):
                for child in frame.winfo_children():
                    child.destroy()
                ctk.CTkLabel(frame, text="比对进行中，请稍候…", text_color="#666666").pack(pady=24)
            if self.refresh_collection is None:
                raise RuntimeError("当前发布器未配置发布包与归档模块提交扫描器")
            self.refresh_collection(plan.batch_id)
            if self.capture_baseline is None:
                raise RuntimeError("当前发布器未配置远端文件比较器")
            self.capture_baseline(plan.batch_id)
        except Exception as exc:
            messagebox.showerror("发布包与归档模块提交比较失败", str(exc), parent=self)

    def open_game_content_pipeline(self) -> None:
        """Route content publishing through its game-scoped package page."""
        if self.open_game_content_pipeline_callback is not None:
            self.open_game_content_pipeline_callback()
            return
        # Compatibility fallback for callers that only provide the old callback.
        self.create_game_content_batch()

    def create_game_content_batch(self) -> None:
        """Create or reopen the current game's DLC/patch batch, then show its board."""
        if self.create_game_content_batch_callback is None:
            messagebox.showinfo(
                "暂不可创建资源发布",
                "请先在“资源管理”中选择游戏并完成本地构建。",
                parent=self,
            )
            return
        try:
            plan = self.create_game_content_batch_callback()
        except Exception as error:
            messagebox.showerror("创建 DLC / 补丁发布失败", str(error), parent=self)
            return
        self.select(plan.batch_id)
        self.refresh_history()
        self.show_page("batches")

    def archive_current_batch(self) -> None:
        if not self._require_current_batch("归档或移除草稿"):
            return
        try:
            plan = self.service.get(self.current_batch_id)
            target = plan.target.get("version") or plan.target.get("game_id") or "当前发布记录"
            if not messagebox.askyesno(
                "归档未执行发布",
                f"将把 {target} 的未执行发布从当前列表移除。\n"
                "不会删除审计记录；它会被移入本地归档，不能再用于发布或恢复。\n\n是否继续？",
                parent=self,
            ):
                return
            self.service.archive_unexecuted_batch(plan.batch_id)
        except Exception as exc:
            messagebox.showerror("无法归档发布记录", str(exc), parent=self)
            return
        self.current_batch_id = None
        self._render_empty_state("发布记录已归档。请创建新的发布，或在发布记录中选择其他记录。")
        self.refresh_history()

    def run_preflight(self) -> None:
        if not self.current_batch_id:
            return
        try:
            self._render(self.service.preflight(self.current_batch_id))
        except Exception as exc:
            messagebox.showerror("预检失败", str(exc), parent=self)

    def replace_artifact(self, role: str) -> None:
        if not self.current_batch_id:
            return
        try:
            plan = self.service.get(self.current_batch_id)
            if plan.kind is not ReleaseKind.PROGRAM:
                raise ValueError("只有程序更新发布支持单文件替换")
            selected = filedialog.askopenfilename(
                parent=self,
                title="选择替换程序包",
                filetypes=(("ZIP 更新包", "*.zip"), ("所有文件", "*.*")),
            )
            if not selected:
                return
            plan = self.service.replace_program_artifact(plan.batch_id, role, Path(selected))
        except Exception as exc:
            messagebox.showerror("替换程序包失败", str(exc), parent=self)
            return
        self._render(plan)
        self.refresh_history()

    def confirm(self) -> None:
        if not self.current_batch_id:
            return
        try:
            plan = self.service.get(self.current_batch_id)
            skip_reason = None
            if not messagebox.askyesno(
                "确认发布",
                self._confirmation_summary(plan),
                parent=self,
            ):
                return
            if getattr(plan, "kind", None) is ReleaseKind.GAME_CONTENT and not messagebox.askyesno(
                "确认镜像删除",
                "游戏内容发布会使远端附件与当前本地发布包完全一致。\n\n"
                "远端存在、但本地没有的附件将在上传完成后删除；删除失败会阻止 catalog 发布。\n\n"
                "是否确认此镜像删除操作？",
                icon="warning",
                parent=self,
            ):
                return
            if getattr(plan, "kind", None) is ReleaseKind.GAME_CONTENT:
                plan = self.service.confirm_game_content_mirror_delete(plan.batch_id)
            self._render(
                self.service.confirm(
                    plan.batch_id, skipped_acceptance_reason=skip_reason
                )
            )
        except Exception as exc:
            messagebox.showerror("无法确认", str(exc), parent=self)

    @staticmethod
    def _confirmation_summary(plan: ReleasePlan) -> str:
        target = plan.target.get("version") or plan.target.get("game_id") or plan.target.get("scope") or "-"
        artifacts = "\n".join(
            f"  • {item.role}: {item.filename} · {item.size} B · SHA-256 {item.sha256[:12]}…"
            for item in sorted(plan.artifacts, key=lambda item: (item.role, item.filename))
        ) or "  • 无"
        targets = ReleaseCenter._publication_target_text(plan.remote_targets, frozen=True)
        checks = "\n".join(
            f"  • {'通过' if item.result is CheckResult.PASS else '警告' if item.result is CheckResult.WARNING else '跳过' if item.result is CheckResult.SKIPPED else '失败'}：{item.message}"
            for item in plan.preflight
        ) or "  • 尚未运行预检"
        stages = " → ".join(
            stage.display_name for stage in sorted(plan.stages, key=lambda item: item.order)
        ) or "确认后由流水线生成并按安全顺序执行"
        notes = plan.notes or "（无）"
        return (
            f"类型：{plan.kind.value}\n目标版本 / 范围：{target}\n\n{targets}\n\n"
            f"产物\n{artifacts}\n\n更新说明 / 关键字段\n  {notes}\n\n"
            f"硬门禁、警告与跳过项\n{checks}\n\n阶段顺序\n  {stages}\n\n"
            "确认后将冻结当前输入；后续执行会向上述仓库上传附件并切换更新清单。是否继续？"
        )

    @staticmethod
    def _publication_target_text(
        remote_targets: dict[str, dict[str, str]], *, frozen: bool
    ) -> str:
        title = "本次实际发布目标（创建时已冻结）" if frozen else "下次创建发布将使用的发布目标"
        labels = {"gitlink": "GitLink", "github": "GitHub"}
        lines: list[str] = []
        for provider in ("gitlink", "github"):
            remote_target = remote_targets.get(provider, {})
            owner = str(remote_target.get("owner") or "").strip()
            repository = str(
                remote_target.get("repository") or remote_target.get("repo") or ""
            ).strip()
            repository_name = f"{owner}/{repository}" if owner and repository else "未完整配置"
            lines.append(f"  • {labels[provider]}：{repository_name}")
        for provider in sorted(set(remote_targets) - set(labels)):
            remote_target = remote_targets.get(provider, {})
            owner = str(remote_target.get("owner") or "").strip()
            repository = str(
                remote_target.get("repository") or remote_target.get("repo") or ""
            ).strip()
            repository_name = f"{owner}/{repository}" if owner and repository else "未完整配置"
            lines.append(f"  • {provider}：{repository_name}")
        return f"{title}\n" + "\n".join(lines)

    def execute(self) -> None:
        if not self.current_batch_id:
            return
        batch_id = self.current_batch_id
        self._pause_requested = False
        self.execute_button.configure(state="disabled", text="执行中…")
        # 后台线程尚未把批次切换为 RUNNING 前不能请求暂停；随后由进度轮询
        # 自动开放按钮，避免以前点击执行后暂停按钮始终灰掉的假入口。
        self.pause_button.configure(state="disabled", text="安全暂停（启动中）")
        self.execution_status_label.configure(
            text="\u6b63\u5728\u542f\u52a8\u53d1\u5e03\u4efb\u52a1\u2026\n\n\u51c6\u5907\u8bfb\u53d6\u9996\u4e2a\u5b89\u5168\u6267\u884c\u6b65\u9aa4\uff1b\u5f00\u59cb\u540e\u4f1a\u6301\u7eed\u663e\u793a\u5f53\u524d\u9636\u6bb5\u3002"
        )
        started = self.execute_batch(batch_id, self._execution_done, self._execution_failed)
        if not started:
            self.execute_button.configure(state="normal", text="执行 / 恢复")
            self.pause_button.configure(state="disabled", text="安全暂停")
            return
        self._execution_in_progress = True
        self._refresh_execution_progress(batch_id)

    def _refresh_execution_progress(self, batch_id: str) -> None:
        """Render persisted stage state while a background release is running."""
        if batch_id != self.current_batch_id or not self._execution_in_progress:
            return
        try:
            plan = self.service.get(batch_id)
        except Exception:
            # The worker completion path will surface the underlying failure.
            # Keep the monitor alive briefly so a transient file-replace race
            # cannot make the execution page look frozen.
            pass
        else:
            self._render(plan)
        if batch_id == self.current_batch_id and self._execution_in_progress:
            self._execution_monitor_after_id = self.after(
                450, lambda value=batch_id: self._refresh_execution_progress(value)
            )

    def _stop_execution_monitor(self) -> None:
        self._execution_in_progress = False
        after_id = self._execution_monitor_after_id
        self._execution_monitor_after_id = None
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass

    def pause(self) -> None:
        if not self.current_batch_id:
            return
        self.pause_button.configure(state="disabled", text="已请求安全暂停…")
        try:
            self.pause_batch(self.current_batch_id)
        except Exception:
            self._pause_requested = False
            self.pause_button.configure(state="normal", text="安全暂停")
            raise
        self._pause_requested = True
        self.execution_status_label.configure(
            text="\u5df2\u8bf7\u6c42\u5b89\u5168\u6682\u505c\u3002\n\n\u5f53\u524d\u6b65\u9aa4\u4f1a\u5728\u4e0b\u4e00\u4e2a\u5b89\u5168\u68c0\u67e5\u70b9\u7ed3\u675f\u540e\u6682\u505c\uff1b"
            "\u8bf7\u52ff\u5f3a\u5236\u5173\u95ed\u7a0b\u5e8f\u3002"
        )

    def _execution_done(self, plan: ReleasePlan) -> None:
        self._stop_execution_monitor()
        self._pause_requested = False
        self.execute_button.configure(state="normal", text="执行 / 恢复")
        self._render(plan)
        self.refresh_history()

    def _execution_failed(self, error: Exception) -> None:
        self._stop_execution_monitor()
        self._pause_requested = False
        self.execute_button.configure(state="normal", text="执行 / 恢复")
        if self.current_batch_id:
            try:
                self._render(self.service.get(self.current_batch_id))
            except Exception:
                pass
        messagebox.showerror("发布执行失败", str(error), parent=self)

    @staticmethod
    def _status_text(status: ReleaseStatus) -> str:
        return {
            ReleaseStatus.DRAFT: "待准备",
            ReleaseStatus.PREFLIGHT_FAILED: "预检未通过",
            ReleaseStatus.AWAITING_CONFIRMATION: "待冻结确认",
            ReleaseStatus.RUNNING: "正在发布",
            ReleaseStatus.PAUSED: "已安全暂停",
            ReleaseStatus.INTERRUPTED: "发布中断，可恢复",
            ReleaseStatus.DEGRADED: "部分完成，需要处理",
            ReleaseStatus.FAILED: "发布失败，需要处理",
            ReleaseStatus.COMPLETED: "发布完成",
        }[status]

    @staticmethod
    def _stage_status_text(status: str) -> str:
        return {
            "pending": "尚未开始",
            "running": "进行中",
            "succeeded": "已完成",
            "failed": "失败",
            "paused": "已暂停",
            "skipped": "已跳过",
        }.get(status, status)

    @staticmethod
    def _format_bytes(size: int) -> str:
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KiB"
        return f"{size / (1024 * 1024):.2f} MiB"

    def refresh_history(self) -> None:
        for child in self.history.winfo_children():
            child.destroy()
        # DLC / 补丁的内部发布记录由“上传队列”统一管理；这里仅保留
        # 程序更新与 Hub 公告，避免把底层执行记录再次暴露为另一套入口。
        plans = self._visible_history_plans()
        if not plans:
            ctk.CTkLabel(
                self.history, text="暂无历史发布记录。新的发布会在准备完成后自动出现在这里。",
                justify="left", wraplength=300,
            ).pack(fill="x", padx=8, pady=8)
            return
        for plan in plans:
            target = plan.target.get("version") or plan.target.get("game_id") or plan.target.get("scope") or "未命名"
            kind = {
                ReleaseKind.PROGRAM: "程序更新",
                ReleaseKind.GAME_CONTENT: "游戏内容",
                ReleaseKind.HUB_ANNOUNCEMENT: "中心公告",
            }[plan.kind]
            label = f"{target}｜{kind}｜{self._status_text(plan.status)}\n更新于 {plan.updated_at[:19].replace('T', ' ')}"
            ctk.CTkButton(
                self.history, text=label, anchor="w", height=66,
                command=lambda value=plan.batch_id: self.view_history_record(value),
            ).pack(fill="x", padx=3, pady=3)

    def _visible_history_plans(self) -> list[ReleasePlan]:
        return [
            plan
            for plan in self.service.history()
            if plan.kind is not ReleaseKind.GAME_CONTENT
        ]

    def _select_latest_record_as_current(self) -> None:
        """Initialize the editable workflow from the newest stored record once."""
        plans = self._visible_history_plans()
        if plans:
            self.select(plans[0].batch_id, show_history=False)

    def view_history_record(self, batch_id: str) -> None:
        """Show a historical record without changing the editable release context."""
        plan = self.service.get(batch_id)
        self.viewed_history_batch_id = batch_id
        target = (
            plan.target.get("version")
            or plan.target.get("game_id")
            or plan.target.get("scope")
            or "-"
        )
        artifacts = "\n".join(
            f"  • {item.filename}（{self._format_bytes(item.size)}，校验码 {item.sha256[:12]}…）"
            for item in sorted(plan.artifacts, key=lambda item: (item.role, item.filename))
        ) or "  • 未保存收件文件信息。"
        checks = "\n".join(
            f"  • {check.message}"
            for check in plan.preflight
        ) or "  • 未运行预检。"
        self.status_label.configure(
            text=(
                f"发布：{target}（{self._status_text(plan.status)}）\n"
                "此记录仅供查看，不会改变当前发布流程。\n\n"
                f"{self._publication_target_text(plan.remote_targets, frozen=True)}\n\n"
                f"收件文件\n{artifacts}\n\n"
                f"更新说明\n  {plan.notes or '（尚未填写）'}\n\n"
                f"预检结果\n{checks}\n\n"
                f"发布编号（仅用于支持与排障）：{plan.batch_id[:8]}"
            )
        )
        baseline = plan.options.get("remote_baseline")
        if isinstance(baseline, dict) and baseline:
            captured_at = str(baseline.get("captured_at") or "")[:19].replace("T", " ")
            sources = "、".join(sorted((baseline.get("sources") or {}).keys())) or "远端"
            baseline_text = f"已于 {captured_at} 读取 {sources} 的核对结果。"
        else:
            baseline_text = "此记录未保存远端核对结果。"
        self.baseline_status_label.configure(
            text=f"发布：{target}（{self._status_text(plan.status)}）\n{baseline_text}\n历史记录仅供查看。"
        )
        self.show_page("batches")

    def select(self, batch_id: str, *, show_history: bool = True) -> None:
        """Set the active release context for new or resumed publishing only."""
        self.current_batch_id = batch_id
        self.viewed_history_batch_id = None
        plan = self.service.get(batch_id)
        if plan.kind is ReleaseKind.PROGRAM:
            version = str(plan.target.get("version") or "")
            if version:
                self.version_entry.delete(0, "end")
                self.version_entry.insert(0, version)
            collection = plan.options.get("collection", {})
            inbox = collection.get("inbox") if isinstance(collection, dict) else None
            if inbox:
                self.inbox_entry.delete(0, "end")
                self.inbox_entry.insert(0, str(inbox))
            self.notes_entry.delete("1.0", "end")
            self.notes_entry.insert("1.0", plan.notes)
        self._render(plan)
        if show_history:
            self.show_page("batches")

    def _render_empty_state(self, message: str) -> None:
        self.status_label.configure(text=message)
        self.baseline_status_label.configure(text=message)
        self.preflight_status_label.configure(text=message)
        self.execution_status_label.configure(text=message)
        self.overall_progress_label.configure(text="总体进度：等待开始")
        self.overall_progress_bar.set(0)
        self._set_execution_log(message)

    @staticmethod
    def _format_upload_speed(value: object) -> str:
        try:
            speed = float(value)
        except (TypeError, ValueError):
            return "计算中…"
        return "计算中…" if speed <= 0 else f"{ReleaseCenter._format_bytes(int(speed))}/秒"

    def _render_upload_progress(self, plan: ReleasePlan) -> None:
        progress = plan.options.get("upload_progress")
        if not isinstance(progress, dict):
            self.upload_progress_bar.set(0)
            active_stage = next(
                (stage for stage in plan.stages if stage.status.value == "running"), None
            )
            if plan.status is ReleaseStatus.RUNNING and active_stage is not None:
                self.upload_progress_label.configure(
                    text=(
                        "单文件进度：正在准备远端传输并核验已有文件。\n"
                        "开始实际传输后，这里会显示文件名、字节进度和上传速度。"
                    )
                )
            else:
                self.upload_progress_label.configure(text="单文件进度：等待执行。")
            return
        source = str(progress.get("source") or "远端")
        source_label = {"github": "GitHub", "gitlink": "GitLink"}.get(source, source)
        filename = str(progress.get("filename") or "当前文件")
        try:
            sent = max(0, int(progress.get("sent") or 0))
            total = max(0, int(progress.get("total") or 0))
        except (TypeError, ValueError):
            sent, total = 0, 0
        ratio = min(1.0, sent / total) if total else 0.0
        self.upload_progress_bar.set(ratio)
        remote = plan.remote_targets.get(source, {})
        owner = str(remote.get("owner") or "").strip() if isinstance(remote, dict) else ""
        repository = str((remote.get("repository") or remote.get("repo") or "")).strip() if isinstance(remote, dict) else ""
        target = f" → {owner}/{repository}" if owner and repository else ""
        if total and sent >= total and plan.status is ReleaseStatus.RUNNING:
            detail = "上传已提交，正在远端回读校验…"
        else:
            detail = f"{ratio:.0%}｜{self._format_bytes(sent)} / {self._format_bytes(total)}｜{self._format_upload_speed(progress.get('bytes_per_second'))}"
        self.upload_progress_label.configure(
            text=f"单文件上传：{source_label}{target}\n{filename}\n{detail}"
        )

    def _set_execution_log(self, text: str) -> None:
        """Update the log only when its content changed, avoiding periodic redraw flicker."""
        if text == getattr(self, "_execution_log_text", ""):
            return
        self._execution_log_text = text
        self.execution_log.configure(state="normal")
        self.execution_log.delete("1.0", "end")
        self.execution_log.insert("1.0", text)
        self.execution_log.see("end")
        self.execution_log.configure(state="disabled")

    def _render_execution_log(self, plan: ReleasePlan) -> None:
        target = str(plan.target.get("version") or plan.target.get("game_id") or "-")
        lines = [
            f"[{plan.created_at[:19].replace('T', ' ')}] 已准备发布：{target}",
            "",
            "自动预检：",
        ]
        if plan.preflight:
            for check in plan.preflight:
                result = {
                    CheckResult.PASS: "通过",
                    CheckResult.FAIL: "失败",
                    CheckResult.WARNING: "提醒",
                    CheckResult.SKIPPED: "跳过",
                }[check.result]
                detail = f"；{check.remediation}" if check.remediation else ""
                lines.append(f"  [{result}] {check.message}{detail}")
        else:
            lines.append("  尚未完成预检。")

        lines.extend(("", "执行事件："))
        labels = {
            "release_created": "已创建本地发布记录",
            "preflight_completed": "自动预检完成",
            "release_confirmed": "预检通过，已冻结发布输入",
            "release_started": "开始执行发布",
            "stage_started": "开始步骤",
            "stage_succeeded": "步骤完成",
            "stage_failed": "步骤失败",
            "release_completed": "发布完成",
            "release_paused": "已安全暂停",
            "pause_requested": "已请求安全暂停",
        }
        stage_names = {stage.stage_id: stage.display_name for stage in plan.stages}
        try:
            events = self.service.events(plan.batch_id)
        except Exception:
            events = []
        for event in events:
            label = labels.get(event.event_type, event.event_type)
            stage = stage_names.get(event.stage_id or "")
            suffix = f"：{stage}" if stage else ""
            if event.event_type == "stage_failed":
                message = str(event.context.get("message") or "")
                suffix += f"（{message}）" if message else ""
            lines.append(f"  [{event.occurred_at[:19].replace('T', ' ')}] {label}{suffix}")
        if not events:
            lines.append("  等待发布器写入执行事件。")
        self._set_execution_log("\n".join(lines))

    def _render_local_remote_comparison(self, plan: ReleasePlan) -> None:
        if not hasattr(self, "comparison_local_list"):
            return
        baseline = plan.options.get("remote_baseline")
        sources = baseline.get("sources") if isinstance(baseline, dict) else None
        if not isinstance(sources, dict):
            self.comparison_summary.configure(text="尚未读取到云端目录，无法比较。")
            return
        artifacts = tuple(sorted(plan.artifacts, key=lambda item: item.filename.casefold()))
        update_artifacts = tuple(item for item in artifacts if item.role != "module_archive")
        module_artifacts = tuple(item for item in artifacts if item.role == "module_archive")
        local_changes: dict[str, set[str]] = {"新增": set(), "同名替换": set()}
        remote_lines: list[str] = []
        source_groups = (
            ("更新包", update_artifacts, sources),
            (
                "模块归档",
                module_artifacts,
                baseline.get("module_sources") if isinstance(baseline, dict) else {},
            ),
        )
        for group_label, group_artifacts, group_sources in source_groups:
            if not group_artifacts:
                continue
            if not isinstance(group_sources, dict):
                group_sources = {}
            for source in ("gitlink", "github"):
                payload = group_sources.get(source)
                raw_assets = payload.get("assets", []) if isinstance(payload, dict) else []
                remote_assets = {
                    str(item.get("name") or ""): item
                    for item in raw_assets
                    if isinstance(item, dict) and str(item.get("name") or "")
                }
                added: list[str] = []
                replaced: list[str] = []
                for artifact in group_artifacts:
                    remote = remote_assets.get(artifact.filename)
                    if remote is None:
                        added.append(artifact.filename)
                    elif (
                        int(remote.get("size") or -1) == artifact.size
                        and str(remote.get("sha256") or "") == artifact.sha256
                    ):
                        continue
                    else:
                        replaced.append(artifact.filename)
                local_changes["新增"].update(added)
                local_changes["同名替换"].update(replaced)
                source_name = {"gitlink": "GitLink", "github": "GitHub"}.get(source, source)
                remote_only = sorted(
                    set(remote_assets) - {item.filename for item in group_artifacts},
                    key=str.casefold,
                )
                remote_lines.append(
                    f"{group_label} · {source_name}：同名替换 {len(replaced)} 个，远端保留 {len(remote_only)} 个"
                )
                remote_lines.extend(f"  替换：{name}" for name in replaced)
                remote_lines.extend(f"  仅云端保留：{name}" for name in remote_only)
        for frame in (self.comparison_local_list, self.comparison_remote_list):
            for child in frame.winfo_children():
                child.destroy()
        local_lines = [f"新增：{name}" for name in sorted(local_changes["新增"], key=str.casefold)]
        local_lines += [f"同名替换：{name}" for name in sorted(local_changes["同名替换"], key=str.casefold)]
        if not local_lines:
            local_lines = ["所有发布包与归档模块提交文件均已与双端一致。"]
        for text in local_lines:
            ctk.CTkLabel(self.comparison_local_list, text=text, anchor="w").pack(fill="x", padx=8, pady=4)
        for text in remote_lines or ["双端均未返回可比较的差异文件。"]:
            ctk.CTkLabel(self.comparison_remote_list, text=text, anchor="w", justify="left").pack(fill="x", padx=8, pady=4)
        self.comparison_summary.configure(
            text=(
                f"本地已核验 {len(update_artifacts)} 个更新包、{len(module_artifacts)} 个模块归档；"
                "远端旧文件仅保留展示。"
            )
        )
        self.show_page("comparison")

    def _render(self, plan: ReleasePlan) -> None:
        role_labels = {
            "windows_full": "Windows 更新包",
            "steamos_full": "SteamOS 更新包",
            "macos_full": "macOS 更新包",
            "module_archive": "模块归档",
        }
        artifacts = "\n".join(
            f"  • {role_labels.get(item.role, item.role)}：{item.filename}（{self._format_bytes(item.size)}，校验码 {item.sha256[:12]}…）"
            for item in sorted(plan.artifacts, key=lambda item: (item.role, item.filename))
        ) or "  • 还未在收件目录中发现可用文件；请在“收件与准备”中放包后刷新。"
        checks = "\n".join(
            f"  • {'通过' if check.result is CheckResult.PASS else '失败' if check.result is CheckResult.FAIL else '提醒'}：{check.message}"
            + (f"（处理方法：{check.remediation}）" if check.remediation else "")
            for check in plan.preflight
        ) or "  • 尚未运行预检。"
        ordered_stages = sorted(plan.stages, key=lambda item: item.order)
        active_stage = next(
            (stage for stage in ordered_stages if stage.status.value == "running"), None
        )
        stages = "\n".join(
            f"  {'▶' if stage.status.value == 'running' else '✓' if stage.status.value == 'succeeded' else '!' if stage.status.value in {'failed', 'paused'} else '•'} "
            f"第{index}/{len(ordered_stages)}步 {stage.display_name}：{self._stage_status_text(stage.status.value)}"
            for index, stage in enumerate(ordered_stages, start=1)
        ) or "  • 尚未执行发布。"
        if active_stage is not None:
            active_index = ordered_stages.index(active_stage) + 1
            stages = (
                f"当前正在执行：第{active_index}/{len(ordered_stages)}步 {active_stage.display_name}\n\n"
                f"{stages}"
            )
        baseline = plan.options.get("remote_baseline")
        if isinstance(baseline, dict) and baseline:
            source_names = "、".join(sorted((baseline.get("sources") or {}).keys())) or "远端"
            baseline_text = (
                f"已于 {str(baseline.get('captured_at') or '')[:19].replace('T', ' ')} 读取 "
                f"{source_names}；仅供核对，不会阻断发布。"
            )
        else:
            baseline_text = "尚未读取；可按需点击“读取远端基线（只读）”，不会上传或修改远端。"
        next_action = {
            ReleaseStatus.DRAFT: "下一步：在“收件与准备”放好文件并刷新收件目录，再运行预检。",
            ReleaseStatus.PREFLIGHT_FAILED: "下一步：根据预检失败项修正文件或说明，再重新运行预检。",
            ReleaseStatus.AWAITING_CONFIRMATION: "下一步：核对文件与预检结果后，在“预检与确认”中冻结输入。",
            ReleaseStatus.RUNNING: "正在发布；如需停止，请使用“安全暂停”，不要强制结束程序。",
            ReleaseStatus.PAUSED: "已暂停；可在发布详情的执行面板从安全位置继续。",
            ReleaseStatus.INTERRUPTED: "上次发布被中断；核对信息后可在发布详情的执行面板继续。",
            ReleaseStatus.DEGRADED: "有部分步骤未完成；请在发布详情的执行面板查看进度并处理。",
            ReleaseStatus.FAILED: "发布失败；查看执行进度和错误后修复，再继续执行。",
            ReleaseStatus.COMPLETED: "本次发布已完成，仅保留为发布记录。",
        }[plan.status]
        target = plan.target.get("version") or plan.target.get("game_id") or plan.target.get("scope") or "-"
        publication_targets = self._publication_target_text(plan.remote_targets, frozen=True)
        overview = f"本次发布：{target}（{self._status_text(plan.status)}）\n{next_action}"
        board = (
            f"{overview}\n\n{publication_targets}\n\n收件文件\n{artifacts}\n\n"
            f"更新说明\n  {plan.notes or '（尚未填写）'}\n\n"
            f"预检结果\n{checks}\n\n"
            f"执行进度\n{stages}\n\n"
            f"发布编号（仅用于支持与排障）：{plan.batch_id[:8]}"
        )
        self.status_label.configure(text=board)
        self.baseline_status_label.configure(
            text=f"当前发布：{target}（{self._status_text(plan.status)}）\n{baseline_text}\n可随时重新读取；不会上传或修改远端。"
        )
        self.preflight_status_label.configure(
            text=f"当前发布：{target}（{self._status_text(plan.status)}）\n\n预检结果\n{checks}\n\n{next_action}"
        )
        completed_count = sum(
            stage.status.value in {"succeeded", "skipped"} for stage in ordered_stages
        )
        total_count = len(ordered_stages)
        self.execution_status_label.configure(
            text=(
                f"当前发布：{target}（{self._status_text(plan.status)}）"
                + (f"｜当前步骤：{active_stage.display_name}" if active_stage else "")
            )
        )
        if total_count:
            self.overall_progress_bar.set(completed_count / total_count)
            self.overall_progress_label.configure(
                text=f"总体进度：已完成 {completed_count}/{total_count} 个步骤"
            )
        else:
            self.overall_progress_bar.set(0)
            self.overall_progress_label.configure(text="总体进度：等待自动预检完成")
        self._render_execution_log(plan)
        self._render_upload_progress(plan)
        if plan.status is ReleaseStatus.RUNNING:
            if self._pause_requested:
                self.pause_button.configure(state="disabled", text="已请求安全暂停…")
            else:
                self.pause_button.configure(state="normal", text="安全暂停")
        else:
            self.pause_button.configure(state="disabled", text="安全暂停")
        editable = plan.status not in {ReleaseStatus.RUNNING, ReleaseStatus.COMPLETED}
        if hasattr(self, "compare_button"):
            self.compare_button.configure(state="normal" if editable else "disabled")
