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
        self.refresh_collection = refresh_collection
        self.capture_baseline = capture_baseline
        self.export_baseline = export_baseline
        self.create_game_content_batch_callback = create_game_content_batch
        self.open_game_content_pipeline_callback = open_game_content_pipeline
        self.current_batch_id: str | None = None
        # 发布在后台线程执行；界面定时从持久化批次读取阶段状态，确保操作人
        # 能看到当前步骤，并且仅在实际进入 RUNNING 后开放安全暂停。
        self._execution_in_progress = False
        self._execution_monitor_after_id: str | None = None
        self._pause_requested = False
        self._build()
        self.refresh_history()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text="发布工作台", font=("Microsoft YaHei UI", 24, "bold")).grid(
            row=0, column=0, padx=18, pady=(14, 4), sticky="w"
        )
        ctk.CTkLabel(
            self,
            text="按批次顺序完成准备、核对、确认与执行；详细页面会覆盖当前内容，并可随时返回工作台。",
            text_color="#666666",
        ).grid(row=1, column=0, padx=18, pady=(0, 12), sticky="w")

        self.page_container = ctk.CTkFrame(self, fg_color="transparent")
        self.page_container.grid(row=2, column=0, padx=18, pady=(0, 14), sticky="nsew")
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._build_home_page()
        self._build_preparation_page()
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

    def _page_heading(self, page: ctk.CTkFrame, title: str, subtitle: str) -> ctk.CTkFrame:
        heading = ctk.CTkFrame(page)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        heading.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            heading,
            text="← 返回发布工作台",
            width=156,
            height=40,
            font=("Microsoft YaHei UI", 14, "bold"),
            command=lambda: self.show_page("home"),
        ).grid(row=0, column=0, rowspan=2, padx=10, pady=10, sticky="w")
        ctk.CTkLabel(heading, text=title, font=("Microsoft YaHei UI", 18, "bold")).grid(
            row=0, column=1, padx=(0, 10), pady=(9, 0), sticky="w"
        )
        ctk.CTkLabel(heading, text=subtitle, text_color="#666666").grid(
            row=1, column=1, padx=(0, 10), pady=(0, 9), sticky="w"
        )
        return heading

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.grid_remove()
        self.pages[name].grid()

    def _build_home_page(self) -> None:
        page = self._new_page("home")
        overview = ctk.CTkFrame(page)
        overview.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        overview.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(overview, text="当前发布任务", font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, padx=16, pady=(14, 2), sticky="w"
        )
        self.home_summary_label = ctk.CTkLabel(
            overview,
            text="尚未打开批次。程序更新、DLC 与补丁都从这里创建同一套可追踪、可暂停、可恢复的发布批次。",
            justify="left",
            anchor="w",
            wraplength=820,
        )
        self.home_summary_label.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        self.home_target_label = ctk.CTkLabel(
            overview,
            text=self._publication_target_text(self.remote_targets(), frozen=False),
            justify="left",
            anchor="w",
            wraplength=820,
            text_color="#9A5B00",
        )
        self.home_target_label.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="ew")
        actions = ctk.CTkFrame(overview, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, padx=14, pady=12, sticky="e")
        ctk.CTkButton(
            actions,
            text="程序更新发布",
            command=lambda: self.show_page("preparation"),
            width=156,
            height=48,
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(side="left", padx=4)
        self.content_batch_button = ctk.CTkButton(
            actions,
            text="DLC / 补丁发布",
            command=self.open_game_content_pipeline,
            width=156,
            height=48,
            font=("Microsoft YaHei UI", 15, "bold"),
        )
        self.content_batch_button.pack(side="left", padx=4)
        ctk.CTkButton(
            actions,
            text="打开批次看板",
            command=lambda: self.show_page("batches"),
            width=142,
            height=48,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(side="left", padx=4)

        workflow = ctk.CTkFrame(page)
        workflow.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(
            workflow,
            text="同一批次的操作顺序",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=5, padx=16, pady=(12, 5), sticky="w")
        stages = (
            ("① 准备", "程序包或内容构建", "preparation"),
            ("② 核对", "批次看板内远端核对（可选）", "batches"),
            ("③ 确认", "预检并冻结输入", "preflight"),
            ("④ 执行", "发布、暂停或恢复", "execution"),
            ("⑤ 回读", "查看批次记录", "batches"),
        )
        for column, (title, hint, destination) in enumerate(stages):
            workflow.grid_columnconfigure(column, weight=1, uniform="release_workflow")
            ctk.CTkButton(
                workflow,
                text=f"{title}\n{hint}",
                height=64,
                font=("Microsoft YaHei UI", 14, "bold"),
                fg_color="#EAF3FC" if destination != "execution" else "#1976D2",
                text_color="#1D4F80" if destination != "execution" else "white",
                hover_color="#D7E9F9" if destination != "execution" else "#145A9E",
                command=lambda value=destination: self.show_page(value),
            ).grid(row=1, column=column, padx=5, pady=(0, 7), sticky="ew")
        ctk.CTkLabel(
            workflow,
            text="人工验收在“核对与验收”中按需执行，只作参考，不会成为发布门禁。",
            text_color="#666666",
            anchor="w",
        ).grid(row=2, column=0, columnspan=5, padx=16, pady=(0, 12), sticky="ew")


    def _build_preparation_page(self) -> None:
        page = self._new_page("preparation")
        self._page_heading(page, "收件与准备", "填写发布输入；默认收件目录已指向放包位置，仍可手动调整。")
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
        ctk.CTkLabel(content, text="更新说明", anchor="nw").grid(row=2, column=0, padx=12, pady=(12, 8), sticky="nw")
        self.notes_entry = ctk.CTkTextbox(content, height=150)
        self.notes_entry.grid(row=2, column=1, columnspan=2, padx=(12, 12), pady=(12, 8), sticky="ew")
        self.notes_entry.insert("1.0", self.service.load_update_notes_draft(self.version_entry.get().strip()))
        self.mandatory = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(content, text="强制更新", variable=self.mandatory).grid(row=3, column=1, padx=12, pady=10, sticky="w")
        ctk.CTkButton(content, text="保存版本草稿", command=self.save_notes_draft).grid(row=3, column=2, padx=12, pady=10, sticky="e")
        tools = ctk.CTkFrame(content, fg_color="transparent")
        tools.grid(row=4, column=0, columnspan=3, padx=12, pady=(4, 12), sticky="ew")
        ctk.CTkLabel(tools, text="已有批次的文件操作：").pack(side="left", padx=(0, 8))
        self.refresh_button = ctk.CTkButton(tools, text="刷新收件目录", command=self.refresh_inbox)
        self.refresh_button.pack(side="left", padx=4)
        self.replace_buttons = []
        for role, label in (("windows_full", "替换 Windows 包"), ("steamos_full", "替换 SteamOS 包"), ("macos_full", "替换 macOS 包")):
            button = ctk.CTkButton(tools, text=label, width=126, command=lambda value=role: self.replace_artifact(value))
            button.pack(side="left", padx=4)
            self.replace_buttons.append(button)

    def _build_batches_page(self) -> None:
        page = self._new_page("batches")
        self._page_heading(page, "批次历史与看板", "左侧选择批次；右侧在同一看板内完成远端核对、查看状态与管理草稿。")
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
        ctk.CTkLabel(history_card, text="批次列表", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", padx=10, pady=8)
        self.history = ctk.CTkScrollableFrame(history_card)
        self.history.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        detail = ctk.CTkFrame(content)
        detail.grid(row=0, column=1, padx=(7, 0), sticky="nsew")
        board_header = ctk.CTkFrame(detail, fg_color="transparent")
        board_header.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkLabel(
            board_header, text="批次看板", font=("Microsoft YaHei UI", 16, "bold")
        ).pack(side="left")
        # 批次管理必须固定在看板顶部；长更新说明只能在下方滚动，不能把
        # “归档 / 移除草稿”挤到页面底部而让操作员误以为没有管理入口。
        self.archive_button = ctk.CTkButton(
            board_header,
            text="归档 / 移除当前草稿",
            command=self.archive_current_batch,
            fg_color="#6B7280",
            height=40,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.archive_button.pack(side="right")
        self.board_content = ctk.CTkScrollableFrame(detail, fg_color="transparent")
        self.board_content.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 远端核对不再单独跳转页面：选中批次后直接在当前看板读取、查看并导出。
        baseline_card = ctk.CTkFrame(self.board_content)
        baseline_card.pack(fill="x", padx=4, pady=(0, 8))
        baseline_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            baseline_card, text="远端核对（只读）", font=("Microsoft YaHei UI", 15, "bold")
        ).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
        self.baseline_status_label = ctk.CTkLabel(
            baseline_card,
            text="请先在左侧选择一个批次。",
            justify="left",
            anchor="nw",
            wraplength=620,
            text_color="#666666",
        )
        self.baseline_status_label.grid(row=1, column=0, padx=12, pady=(3, 10), sticky="ew")
        baseline_actions = ctk.CTkFrame(baseline_card, fg_color="transparent")
        baseline_actions.grid(row=0, column=1, rowspan=2, padx=12, pady=10, sticky="e")
        self.baseline_button = ctk.CTkButton(
            baseline_actions,
            text="读取远端基线（只读）",
            command=self.read_baseline,
            height=40,
            state="disabled",
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.baseline_button.pack(side="left", padx=(0, 6))
        self.export_baseline_button = ctk.CTkButton(
            baseline_actions,
            text="导出基线 JSON",
            command=self.save_baseline,
            height=40,
            state="disabled",
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.export_baseline_button.pack(side="left")
        self.status_label = ctk.CTkLabel(
            self.board_content,
            text="尚未选择批次",
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
        self.preflight_status_label = ctk.CTkLabel(content, text="请先创建或选择一个批次。", justify="left", anchor="nw", wraplength=900)
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
        self._page_heading(page, "执行", "确认后在这里执行、观察进度；正在发布时可请求安全暂停。")
        content = ctk.CTkFrame(page)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        self.execution_status_label = ctk.CTkLabel(content, text="请先创建或选择一个批次。", justify="left", anchor="nw", wraplength=900)
        self.execution_status_label.grid(row=0, column=0, padx=14, pady=(14, 8), sticky="nsew")
        upload_status = ctk.CTkFrame(content)
        upload_status.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="ew")
        upload_status.grid_columnconfigure(0, weight=1)
        self.upload_progress_label = ctk.CTkLabel(
            upload_status,
            text="当前文件上传状态：等待执行。",
            justify="left",
            anchor="w",
            font=("Microsoft YaHei UI", 13),
        )
        self.upload_progress_label.grid(row=0, column=0, padx=12, pady=(8, 3), sticky="ew")
        self.upload_progress_bar = ctk.CTkProgressBar(upload_status)
        self.upload_progress_bar.grid(row=1, column=0, padx=12, pady=(3, 9), sticky="ew")
        self.upload_progress_bar.set(0)
        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.grid(row=2, column=0, padx=14, pady=(0, 14), sticky="w")
        self.execute_button = ctk.CTkButton(
            actions, text="执行 / 恢复", command=self.execute, height=40,
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
        messagebox.showinfo("请先选择批次", f"请先创建或在左侧选择一个批次，再{action}。", parent=self)
        return False

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

    def create_batch(self) -> None:
        try:
            version = self.version_entry.get().strip()
            state_path = self.service.workspace_root / "app" / "state.json"
            active_version = ""
            if state_path.is_file():
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                active_version = str(payload.get("active_version") or "").strip()
            if version != LAUNCHER_VERSION:
                raise ValueError(f"程序版本必须与启动器版本 {LAUNCHER_VERSION} 一致")
            if active_version and version != active_version:
                raise ValueError(f"程序版本必须与 app/state.json 的 active_version {active_version} 一致")
            inbox = Path(self.inbox_entry.get()).expanduser()
            existing = self.service.find_reusable_program_batch(version=version, inbox=inbox)
            if existing is not None:
                self.select(existing.batch_id)
                self.refresh_history()
                messagebox.showinfo(
                    "已打开现有批次",
                    "已找到同一版本和收件目录的未执行批次，已直接打开，避免重复创建。\n"
                    "如需重新开始，请先使用“归档 / 移除草稿”处理该批次。",
                    parent=self,
                )
                return
            plan = self.service.create_program_batch(
                version=version, inbox=inbox,
                notes=self._notes(), mandatory=self.mandatory.get(),
                remote_targets=self.remote_targets(),
            )
        except Exception as exc:
            messagebox.showerror("创建发布批次失败", str(exc), parent=self)
            return
        self.select(plan.batch_id)
        self.refresh_history()

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
                "暂不可创建内容批次",
                "请先在“内容准备”中选择游戏并完成构建。",
                parent=self,
            )
            return
        try:
            plan = self.create_game_content_batch_callback()
        except Exception as error:
            messagebox.showerror("创建 DLC / 补丁批次失败", str(error), parent=self)
            return
        self.select(plan.batch_id)
        self.refresh_history()
        self.show_page("batches")

    def archive_current_batch(self) -> None:
        if not self._require_current_batch("归档或移除草稿"):
            return
        try:
            plan = self.service.get(self.current_batch_id)
            target = plan.target.get("version") or plan.target.get("game_id") or "该批次"
            if not messagebox.askyesno(
                "归档未执行批次",
                f"将把 {target} 的未执行批次从当前列表移除。\n"
                "不会删除审计记录；它会被移入本地归档，不能再用于发布或恢复。\n\n是否继续？",
                parent=self,
            ):
                return
            self.service.archive_unexecuted_batch(plan.batch_id)
        except Exception as exc:
            messagebox.showerror("无法归档批次", str(exc), parent=self)
            return
        self.current_batch_id = None
        self._render_empty_state("批次已归档。请创建新的批次，或在批次历史中选择其他记录。")
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
                raise ValueError("只有程序更新批次支持单文件替换")
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
                "确认发布批次",
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
        title = "本批次实际发布目标（创建时已冻结）" if frozen else "下次创建批次将使用的发布目标"
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
        messagebox.showerror("发布批次执行失败", str(error), parent=self)

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
        plans = self.service.history()
        if not plans:
            ctk.CTkLabel(
                self.history, text="暂无发布批次。填写版本和收件目录后，点击“创建 / 打开本次批次”。",
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
                command=lambda value=plan.batch_id: self.select(value),
            ).pack(fill="x", padx=3, pady=3)

    def select(self, batch_id: str) -> None:
        self.current_batch_id = batch_id
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
        self.show_page("batches")

    def _render_empty_state(self, message: str) -> None:
        self.status_label.configure(text=message)
        self.baseline_status_label.configure(text=message)
        self.baseline_button.configure(state="disabled")
        self.export_baseline_button.configure(state="disabled")
        self.preflight_status_label.configure(text=message)
        self.execution_status_label.configure(text=message)
        self.home_summary_label.configure(text=message)
        self.home_target_label.configure(
            text=self._publication_target_text(self.remote_targets(), frozen=False)
        )

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
            self.upload_progress_label.configure(text="当前文件上传状态：等待上传任务开始。")
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
            text=f"当前文件上传：{source_label}{target}\n{filename}\n{detail}"
        )

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
            ReleaseStatus.PAUSED: "已暂停；可在发布工作台的执行面板从安全位置继续。",
            ReleaseStatus.INTERRUPTED: "上次发布被中断；核对信息后可在发布工作台的执行面板继续。",
            ReleaseStatus.DEGRADED: "有部分步骤未完成；请在发布工作台的执行面板查看进度并处理。",
            ReleaseStatus.FAILED: "发布失败；查看执行进度和错误后修复，再继续执行。",
            ReleaseStatus.COMPLETED: "本批次已完成，仅保留为发布记录。",
        }[plan.status]
        target = plan.target.get("version") or plan.target.get("game_id") or plan.target.get("scope") or "-"
        publication_targets = self._publication_target_text(plan.remote_targets, frozen=True)
        overview = f"本次发布：{target}（{self._status_text(plan.status)}）\n{next_action}"
        board = (
            f"{overview}\n\n{publication_targets}\n\n收件文件\n{artifacts}\n\n"
            f"更新说明\n  {plan.notes or '（尚未填写）'}\n\n"
            f"预检结果\n{checks}\n\n"
            f"执行进度\n{stages}\n\n"
            f"批次编号（仅用于支持与排障）：{plan.batch_id[:8]}"
        )
        self.status_label.configure(text=board)
        self.home_summary_label.configure(
            text=f"当前批次：{target}｜{self._status_text(plan.status)}。{next_action}"
        )
        self.home_target_label.configure(text=publication_targets)
        self.baseline_status_label.configure(
            text=f"当前批次：{target}（{self._status_text(plan.status)}）\n{baseline_text}\n可随时重新读取；不会上传或修改远端。"
        )
        self.baseline_button.configure(state="normal", text="读取远端基线（只读）")
        self.export_baseline_button.configure(
            state="normal" if isinstance(baseline, dict) and baseline else "disabled"
        )
        self.preflight_status_label.configure(
            text=f"当前批次：{target}（{self._status_text(plan.status)}）\n\n预检结果\n{checks}\n\n{next_action}"
        )
        self.execution_status_label.configure(
            text=f"当前批次：{target}（{self._status_text(plan.status)}）\n\n执行进度\n{stages}\n\n{next_action}"
        )
        self._render_upload_progress(plan)
        if plan.status is ReleaseStatus.RUNNING:
            if self._pause_requested:
                self.pause_button.configure(state="disabled", text="已请求安全暂停…")
            else:
                self.pause_button.configure(state="normal", text="安全暂停")
        else:
            self.pause_button.configure(state="disabled", text="安全暂停")
        archive_state = "normal" if plan.status in {
            ReleaseStatus.DRAFT, ReleaseStatus.PREFLIGHT_FAILED, ReleaseStatus.AWAITING_CONFIRMATION,
        } else "disabled"
        self.archive_button.configure(state=archive_state)
        replace_state = (
            "normal"
            if plan.kind is ReleaseKind.PROGRAM and plan.status is not ReleaseStatus.COMPLETED
            else "disabled"
        )
        for button in self.replace_buttons:
            button.configure(state=replace_state)
