from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .acceptance import (
    FAILED,
    PASSED,
    SKIPPED,
    AcceptanceCase,
    AcceptanceError,
    AcceptanceFingerprint,
    AcceptancePaths,
    AcceptanceSession,
    INTERFERENCE_FILE_SAMPLE_NAMES,
    PreparationPreview,
)

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
CARD = "#FFFFFF"
TEXT = "#212121"
MUTED = "#757575"
RED = "#E53935"


class AcceptanceUiMixin:
    """Acceptance-center widgets and workflow controls."""

    def _build_acceptance_tab(self) -> None:
        self.acceptance_tab.grid_columnconfigure(0, weight=1)
        self.acceptance_tab.grid_rowconfigure(1, weight=1)

        summary = ctk.CTkFrame(
            self.acceptance_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        summary.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        summary.grid_columnconfigure(0, weight=1)
        title_bar = ctk.CTkFrame(summary, fg_color="transparent")
        title_bar.grid(row=0, column=0, padx=18, pady=(14, 6), sticky="ew")
        title_bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            title_bar,
            text="发布验收",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, sticky="w")
        self.acceptance_summary = ctk.CTkLabel(
            title_bar, text="正在读取当前构建…", text_color=MUTED, anchor="e"
        )
        self.acceptance_summary.grid(row=0, column=1, padx=12, sticky="e")
        self.acceptance_refresh_button = ctk.CTkButton(
            title_bar,
            text="刷新指纹",
            width=110,
            fg_color=LIGHT_BLUE,
            command=self.refresh_acceptance,
        )
        self.acceptance_refresh_button.grid(row=0, column=2, padx=4)
        self.acceptance_new_button = ctk.CTkButton(
            title_bar,
            text="开始新一轮",
            width=110,
            fg_color=BLUE,
            command=self.new_acceptance_session,
        )
        self.acceptance_new_button.grid(row=0, column=3, padx=(4, 0))
        ctk.CTkButton(
            title_bar, text="附加到发布批次", width=130, fg_color=LIGHT_BLUE,
            command=self.attach_acceptance_to_release_batch,
        ).grid(row=0, column=4, padx=(8, 0))

        path_area = ctk.CTkFrame(summary, fg_color="transparent")
        self.acceptance_path_area = path_area
        path_area.grid(row=1, column=0, padx=18, pady=(2, 14), sticky="ew")
        path_area.grid_columnconfigure(1, weight=1)
        path_area.grid_columnconfigure(
            (2, 3, 4, 5), weight=0, minsize=112, uniform="acceptance_paths"
        )
        ctk.CTkLabel(path_area, text="待测客户端", width=80, anchor="w").grid(
            row=0, column=0, padx=(0, 8), pady=4, sticky="w"
        )
        self.acceptance_client_label = ctk.CTkLabel(
            path_area, text="尚未选择", text_color=MUTED, anchor="w"
        )
        self.acceptance_client_label.grid(row=0, column=1, pady=4, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="选择 EXE",
            fg_color=LIGHT_BLUE,
            command=self.choose_acceptance_client,
        ).grid(row=0, column=2, padx=4, pady=3, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="启动客户端",
            fg_color=BLUE,
            command=self.launch_acceptance_client,
        ).grid(row=0, column=3, padx=4, pady=3, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="收集日志",
            fg_color=LIGHT_BLUE,
            command=self.collect_acceptance_log,
        ).grid(row=0, column=4, padx=4, pady=3, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="打开证据",
            fg_color=LIGHT_BLUE,
            command=self.open_acceptance_evidence,
        ).grid(row=0, column=5, padx=4, pady=3, sticky="ew")

        ctk.CTkLabel(path_area, text="实际游戏目录", width=80, anchor="w").grid(
            row=1, column=0, padx=(0, 8), pady=4, sticky="w"
        )
        self.acceptance_game_label = ctk.CTkLabel(
            path_area, text="尚未选择", text_color=MUTED, anchor="w"
        )
        self.acceptance_game_label.grid(row=1, column=1, pady=4, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="选择目录",
            fg_color=LIGHT_BLUE,
            command=self.choose_acceptance_game,
        ).grid(row=1, column=2, padx=4, pady=3, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="游戏根目录",
            fg_color=LIGHT_BLUE,
            command=self.open_acceptance_game,
        ).grid(row=1, column=3, padx=4, pady=3, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="打开 DLC",
            fg_color=LIGHT_BLUE,
            command=self.open_acceptance_dlc,
        ).grid(row=1, column=4, padx=4, pady=3, sticky="ew")
        ctk.CTkButton(
            path_area,
            text="打开补丁",
            fg_color=LIGHT_BLUE,
            command=self.open_acceptance_patch,
        ).grid(row=1, column=5, padx=4, pady=3, sticky="ew")

        ctk.CTkLabel(path_area, text="补丁测试", width=80, anchor="w").grid(
            row=2, column=0, padx=(0, 8), pady=(4, 0), sticky="w"
        )
        ctk.CTkLabel(
            path_area,
            text="在当前卡带的补丁目录创建干扰文件样例，供客户端清理流程验收",
            text_color=MUTED,
            anchor="w",
        ).grid(row=2, column=1, pady=(4, 0), sticky="ew")
        ctk.CTkButton(
            path_area,
            text="添加干扰文件",
            fg_color=LIGHT_BLUE,
            command=self.create_acceptance_interference_files,
        ).grid(row=2, column=2, padx=4, pady=(4, 0), sticky="ew")

        body = ctk.CTkFrame(
            self.acceptance_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        body.grid(row=1, column=0, padx=8, pady=(4, 8), sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.acceptance_case_list = ctk.CTkScrollableFrame(
            body,
            width=330,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
        )
        self.acceptance_case_list.grid(
            row=0, column=0, padx=(14, 7), pady=14, sticky="nsew"
        )
        detail = ctk.CTkFrame(body, fg_color="transparent")
        detail.grid(row=0, column=1, padx=(7, 14), pady=14, sticky="nsew")
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_rowconfigure(2, weight=1)
        self.acceptance_case_title = ctk.CTkLabel(
            detail,
            text="选择一个验收项目",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color=BLUE,
            anchor="w",
        )
        self.acceptance_case_title.grid(row=0, column=0, sticky="ew")
        self.acceptance_case_meta = ctk.CTkLabel(
            detail, text="", text_color=MUTED, anchor="w"
        )
        self.acceptance_case_meta.grid(row=1, column=0, pady=(2, 6), sticky="ew")
        self.acceptance_instructions = ctk.CTkTextbox(
            detail,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
            text_color=TEXT,
            wrap="word",
        )
        self.acceptance_instructions.grid(row=2, column=0, sticky="nsew")
        self.acceptance_instructions.configure(state="disabled")

        environment = ctk.CTkFrame(detail, fg_color="#F7FAFD", corner_radius=10)
        self.acceptance_environment = environment
        environment.grid(row=3, column=0, pady=(8, 0), sticky="ew")
        environment.grid_columnconfigure(0, weight=1)
        self.acceptance_environment_status = ctk.CTkLabel(
            environment,
            text="补丁测试环境：尚未记录基线",
            text_color=MUTED,
            anchor="w",
        )
        self.acceptance_environment_status.grid(
            row=0, column=0, padx=10, pady=(8, 4), sticky="ew"
        )
        env_actions = ctk.CTkFrame(environment, fg_color="transparent")
        env_actions.grid(row=1, column=0, padx=6, pady=(0, 4), sticky="ew")
        env_actions.grid_columnconfigure((0, 1, 2), weight=1, uniform="acceptance_env")
        self.acceptance_inspect_button = ctk.CTkButton(
            env_actions,
            text="检查并记录",
            fg_color=LIGHT_BLUE,
            command=self.inspect_acceptance_environment,
        )
        self.acceptance_inspect_button.grid(
            row=0, column=0, padx=4, pady=4, sticky="ew"
        )
        self.acceptance_baseline_button = ctk.CTkButton(
            env_actions,
            text="记录补丁基线",
            fg_color=LIGHT_BLUE,
            command=self.capture_acceptance_baseline,
        )
        self.acceptance_baseline_button.grid(
            row=0, column=1, padx=4, pady=4, sticky="ew"
        )
        self.acceptance_restore_button = ctk.CTkButton(
            env_actions,
            text="恢复测试环境",
            fg_color="transparent",
            border_width=1,
            border_color=RED,
            text_color=RED,
            hover_color="#FFEBEE",
            state="disabled",
            command=self.restore_acceptance_environment,
        )
        self.acceptance_restore_button.grid(
            row=0, column=2, padx=4, pady=4, sticky="ew"
        )
        ctk.CTkLabel(
            environment,
            text=(
                "补丁失败场景：点「构建该环境」即可造出对应坏补丁状态；"
                "测完后务必点「恢复测试环境」。"
            ),
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=620,
        ).grid(row=2, column=0, padx=12, pady=(2, 2), sticky="ew")
        self.acceptance_scenario_list = ctk.CTkScrollableFrame(
            environment,
            height=168,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
        )
        self.acceptance_scenario_list.grid(
            row=3, column=0, padx=10, pady=(2, 10), sticky="ew"
        )
        self._acceptance_scenario_buttons: dict[str, ctk.CTkButton] = {}
        self._render_acceptance_scenario_list()
        # Kept for compatibility with older preparation helpers that still
        # reference the variant menu; the scenario list is the primary UX.
        self.acceptance_variant_menu = ctk.CTkOptionMenu(
            environment,
            values=["当前项目没有自动准备方案"],
            fg_color=LIGHT_BLUE,
            button_color=BLUE,
            state="disabled",
        )
        self.acceptance_preview_button = ctk.CTkButton(
            environment, text="预览环境准备", state="disabled"
        )
        self.acceptance_apply_button = ctk.CTkButton(
            environment, text="执行环境准备", state="disabled"
        )
        environment.grid_remove()

        ctk.CTkLabel(detail, text="结果备注（可选）", text_color=MUTED).grid(
            row=4, column=0, pady=(8, 2), sticky="w"
        )
        self.acceptance_note = ctk.CTkTextbox(
            detail,
            height=62,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#BDBDBD",
            text_color=TEXT,
            wrap="word",
        )
        self.acceptance_note.grid(row=5, column=0, sticky="ew")
        result_bar = ctk.CTkFrame(detail, fg_color="transparent")
        result_bar.grid(row=6, column=0, pady=(8, 0), sticky="ew")
        result_bar.grid_columnconfigure(
            (0, 1, 2, 3), weight=1, uniform="acceptance_results"
        )
        ctk.CTkButton(
            result_bar,
            text="标记通过",
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            command=lambda: self.mark_acceptance_result(PASSED),
        ).grid(row=0, column=0, padx=4, sticky="ew")
        ctk.CTkButton(
            result_bar,
            text="标记失败",
            fg_color=RED,
            hover_color="#C62828",
            command=lambda: self.mark_acceptance_result(FAILED),
        ).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(
            result_bar,
            text="暂时跳过",
            fg_color=MUTED,
            command=lambda: self.mark_acceptance_result(SKIPPED),
        ).grid(row=0, column=2, padx=4, sticky="ew")
        ctk.CTkButton(
            result_bar,
            text="清除结果",
            fg_color="transparent",
            border_width=1,
            border_color="#BDBDBD",
            text_color=MUTED,
            hover_color="#EEEEEE",
            command=self.clear_acceptance_result,
        ).grid(row=0, column=3, padx=4, sticky="ew")

    def refresh_acceptance(self) -> None:
        self._acceptance_generation += 1
        generation = self._acceptance_generation
        profile = self.profile
        paths = self.acceptance.configured_paths(profile)
        cases = self.acceptance.cases_for(profile)
        self._acceptance_paths = paths
        self._acceptance_cases = cases
        self.acceptance_refresh_button.configure(state="disabled", text="正在读取…")
        self.acceptance_summary.configure(text="正在计算客户端与资源指纹…")
        self.acceptance_client_label.configure(
            text=self._acceptance_display_path(paths.client_path),
            text_color=TEXT if paths.client_path and paths.client_path.is_file() else MUTED,
        )
        self.acceptance_game_label.configure(
            text=self._acceptance_display_path(paths.game_path),
            text_color=TEXT if paths.game_path and paths.game_path.is_dir() else MUTED,
        )

        def work() -> None:
            try:
                fingerprint = self.acceptance.fingerprint(profile, paths.client_path)
                session = self.acceptance.ensure_session(profile, fingerprint)
                self._post_ui(
                    lambda: self._acceptance_loaded(
                        generation, profile.game_id, paths, cases, fingerprint, session
                    )
                )
            except (AcceptanceError, OSError, ValueError) as error:
                self._post_ui(
                    lambda value=str(error): self._acceptance_load_failed(
                        generation, profile.game_id, value
                    )
                )

        threading.Thread(target=work, daemon=True).start()

    def _acceptance_loaded(
        self,
        generation: int,
        game_id: str,
        paths: AcceptancePaths,
        cases: tuple[AcceptanceCase, ...],
        fingerprint: AcceptanceFingerprint,
        session: AcceptanceSession,
    ) -> None:
        if generation != self._acceptance_generation or game_id != self.profile.game_id:
            return
        self.acceptance_refresh_button.configure(state="normal", text="刷新指纹")
        self._acceptance_paths = paths
        self._acceptance_cases = cases
        self._acceptance_fingerprint = fingerprint
        self._acceptance_session = session
        self._fill_acceptance_cases()
        self._render_acceptance_case()

    def _acceptance_load_failed(
        self, generation: int, game_id: str, message: str
    ) -> None:
        if generation != self._acceptance_generation or game_id != self.profile.game_id:
            return
        self.acceptance_refresh_button.configure(state="normal", text="刷新指纹")
        self._acceptance_fingerprint = None
        self._acceptance_session = None
        self.acceptance_summary.configure(text=f"验收信息读取失败：{message}", text_color=RED)

    def _fill_acceptance_cases(self) -> None:
        for child in self.acceptance_case_list.winfo_children():
            child.destroy()
        self._acceptance_case_buttons: dict[str, ctk.CTkButton] = {}
        session = self._acceptance_session
        fingerprint = self._acceptance_fingerprint
        stale = bool(
            session and fingerprint and session.fingerprint.value != fingerprint.value
        )
        valid_ids = {case.case_id for case in self._acceptance_cases}
        if self._acceptance_case_id not in valid_ids:
            self._acceptance_case_id = (
                self._acceptance_cases[0].case_id if self._acceptance_cases else ""
            )
        current_category = ""
        for case in self._acceptance_cases:
            if case.category != current_category:
                current_category = case.category
                ctk.CTkLabel(
                    self.acceptance_case_list,
                    text=current_category,
                    font=("Microsoft YaHei UI", 14, "bold"),
                    text_color=BLUE,
                    anchor="w",
                ).pack(fill="x", padx=7, pady=(10, 3))
            result = session.results.get(case.case_id) if session else None
            status = result.status if result else "pending"
            status_text, status_color = self._acceptance_status_style(status, stale)
            selected = case.case_id == self._acceptance_case_id
            row = ctk.CTkButton(
                self.acceptance_case_list,
                text=f"{case.title}    {status_text}",
                height=38,
                anchor="w",
                fg_color="#E3F2FD" if selected else CARD,
                hover_color="#E3F2FD",
                border_width=1,
                border_color=BLUE if selected else "#E0E0E0",
                text_color=status_color if status != "pending" or stale else TEXT,
                command=lambda value=case.case_id: self.select_acceptance_case(value),
            )
            row.pack(fill="x", padx=4, pady=3)
            self._acceptance_case_buttons[case.case_id] = row
        self._schedule_scrollable_reset(self.acceptance_case_list)
        counts = {PASSED: 0, FAILED: 0, SKIPPED: 0}
        if session:
            for case in self._acceptance_cases:
                result = session.results.get(case.case_id)
                if result and result.status in counts:
                    counts[result.status] += 1
        total = len(self._acceptance_cases)
        completed = sum(counts.values())
        if fingerprint is None or session is None:
            summary = "尚未建立验收轮次"
        elif stale:
            summary = (
                f"结果已过期 · 当前 {fingerprint.short} · "
                f"原轮次 {session.fingerprint.short} · 请开始新一轮"
            )
        else:
            summary = (
                f"构建 {fingerprint.short} · {completed}/{total} · "
                f"通过 {counts[PASSED]} · 失败 {counts[FAILED]} · 跳过 {counts[SKIPPED]}"
            )
        self.acceptance_summary.configure(
            text=summary, text_color=RED if stale or counts[FAILED] else MUTED
        )

    def _acceptance_status_style(status: str, stale: bool) -> tuple[str, str]:
        if stale and status != "pending":
            return "已过期", MUTED
        return {
            PASSED: ("已通过", "#2E7D32"),
            FAILED: ("失败", RED),
            SKIPPED: ("已跳过", MUTED),
        }.get(status, ("未测试", TEXT))

    def _render_acceptance_scenario_list(self) -> None:
        for child in self.acceptance_scenario_list.winfo_children():
            child.destroy()
        self._acceptance_scenario_buttons = {}
        for scenario in self.acceptance.patch_failure_scenarios():
            row = ctk.CTkFrame(
                self.acceptance_scenario_list,
                fg_color=CARD,
                border_width=1,
                border_color="#E0E0E0",
                corner_radius=8,
            )
            row.pack(fill="x", padx=4, pady=4)
            row.grid_columnconfigure(0, weight=1)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.grid(row=0, column=0, padx=10, pady=8, sticky="ew")
            ctk.CTkLabel(
                text,
                text=scenario.title,
                font=("Microsoft YaHei UI", 14, "bold"),
                text_color=TEXT,
                anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                text,
                text=f"{scenario.description}  预期：{scenario.expected_client}",
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=760,
            ).pack(anchor="w", pady=(2, 0))
            if scenario.auto_buildable:
                button = ctk.CTkButton(
                    row,
                    text="构建该环境",
                    width=110,
                    fg_color=BLUE,
                    command=lambda scenario_id=scenario.scenario_id: (
                        self.build_acceptance_failure_environment(scenario_id)
                    ),
                )
            else:
                button = ctk.CTkButton(
                    row,
                    text="需人工操作",
                    width=110,
                    fg_color=LIGHT_BLUE,
                    state="disabled",
                )
            button.grid(row=0, column=1, padx=10, pady=8)
            self._acceptance_scenario_buttons[scenario.scenario_id] = button

    def select_acceptance_case(self, case_id: str) -> None:
        if case_id == self._acceptance_case_id:
            return
        if case_id not in {case.case_id for case in self._acceptance_cases}:
            return
        self._acceptance_case_id = case_id
        for item_id, button in self._acceptance_case_buttons.items():
            selected = item_id == case_id
            button.configure(
                fg_color="#E3F2FD" if selected else CARD,
                border_color=BLUE if selected else "#E0E0E0",
            )
        self._render_acceptance_case()

    def _render_acceptance_case(self) -> None:
        case = next(
            (
                item
                for item in self._acceptance_cases
                if item.case_id == self._acceptance_case_id
            ),
            None,
        )
        if case is None:
            return
        session = self._acceptance_session
        result = session.results.get(case.case_id) if session else None
        self.acceptance_case_title.configure(text=case.title)
        self.acceptance_case_meta.configure(
            text=f"{case.category} · {case.case_id} · {case.download_level}"
        )
        self.acceptance_instructions.configure(state="normal")
        self.acceptance_instructions.delete("1.0", "end")
        self.acceptance_instructions.insert("1.0", case.instructions())
        self.acceptance_instructions.configure(state="disabled")
        self.acceptance_note.delete("1.0", "end")
        if result and result.note:
            self.acceptance_note.insert("1.0", result.note)
        if case.case_id == "patch.test-environment":
            self.acceptance_environment.grid()
        else:
            self.acceptance_environment.grid_remove()
        self._update_acceptance_environment_controls()

    def _update_acceptance_environment_controls(self) -> None:
        session = self._acceptance_session
        active = self.acceptance.active_preparation(self.profile)
        variants = self.acceptance.preparation_variants(self._acceptance_case_id)
        self._acceptance_variant_by_label = {
            variant.label: variant.variant_id for variant in variants
        }
        if variants:
            labels = list(self._acceptance_variant_by_label)
            selected = self.acceptance_variant_menu.get()
            self.acceptance_variant_menu.configure(values=labels)
            self.acceptance_variant_menu.set(
                selected if selected in self._acceptance_variant_by_label else labels[0]
            )
        else:
            self.acceptance_variant_menu.configure(
                values=["当前项目没有自动准备方案"]
            )
            self.acceptance_variant_menu.set("当前项目没有自动准备方案")
        if active is not None:
            label = str(active.get("variant_label", "未知方案"))
            self.acceptance_environment_status.configure(
                text=f"存在未恢复的测试环境：{label}（测完请恢复）",
                text_color=RED,
            )
            self.acceptance_baseline_button.configure(state="disabled")
            self.acceptance_restore_button.configure(state="normal")
            self._set_acceptance_scenario_buttons(enabled=False)
            return
        baseline = (
            self.acceptance.current_baseline(self.profile, session)
            if session is not None
            else None
        )
        if baseline is None:
            self.acceptance_environment_status.configure(
                text="补丁测试环境：尚未记录当前轮次基线（可先点场景里的构建，将提示记录基线）",
                text_color=MUTED,
            )
        else:
            self.acceptance_environment_status.configure(
                text=f"补丁基线已记录：{baseline.get('created_at', '')}",
                text_color="#2E7D32",
            )
        self.acceptance_baseline_button.configure(
            state="normal" if session and self._acceptance_fingerprint else "disabled"
        )
        self.acceptance_restore_button.configure(state="disabled")
        ready = bool(
            baseline is not None
            and self._acceptance_fingerprint is not None
            and session is not None
            and self._acceptance_paths.game_path is not None
        )
        self._set_acceptance_scenario_buttons(enabled=ready or (
            session is not None and self._acceptance_fingerprint is not None
        ))

    def _set_acceptance_scenario_buttons(self, *, enabled: bool) -> None:
        for scenario in self.acceptance.patch_failure_scenarios():
            button = self._acceptance_scenario_buttons.get(scenario.scenario_id)
            if button is None:
                continue
            if not scenario.auto_buildable:
                button.configure(state="disabled", text="需人工操作")
                continue
            button.configure(
                state="normal" if enabled else "disabled",
                text="构建该环境",
            )

    def build_acceptance_failure_environment(self, scenario_id: str) -> None:
        try:
            scenario = self.acceptance.patch_failure_scenario(scenario_id)
        except AcceptanceError as error:
            messagebox.showerror("无法构建测试环境", str(error))
            return
        if not scenario.auto_buildable:
            messagebox.showinfo(
                "需要人工操作",
                f"{scenario.title}\n\n{scenario.description}\n\n"
                f"预期：{scenario.expected_client}",
            )
            return
        if self.acceptance.active_preparation(self.profile) is not None:
            messagebox.showwarning(
                "请先恢复环境",
                "当前已有未恢复的测试环境。请先点击“恢复测试环境”，再构建新的场景。",
            )
            return
        fingerprint = self._acceptance_fingerprint
        session = self._acceptance_session
        if fingerprint is None or session is None:
            messagebox.showinfo("验收尚未就绪", "请先等待或刷新当前构建指纹")
            return
        if self._acceptance_paths.game_path is None:
            messagebox.showinfo("缺少游戏目录", "请先选择实际游戏目录")
            return
        baseline = self.acceptance.current_baseline(self.profile, session)
        if baseline is None:
            if not messagebox.askyesno(
                "需要先记录基线",
                "构建失败场景前需要先记录补丁基线（仅备份 DLL/INI，不改游戏文件）。\n\n"
                "是否现在记录基线并继续构建该场景？",
            ):
                return
            try:
                self.acceptance.capture_patch_baseline(
                    self.profile,
                    self._acceptance_paths,
                    session,
                    fingerprint,
                    overwrite=False,
                )
            except (AcceptanceError, OSError) as error:
                messagebox.showerror("记录补丁基线失败", str(error))
                return
        self.select_acceptance_case(scenario.case_id)
        try:
            preview = self.acceptance.preview_preparation(
                self.profile,
                self._acceptance_paths,
                session,
                fingerprint,
                scenario.case_id,
                scenario.variant_id,
            )
        except (AcceptanceError, OSError) as error:
            messagebox.showerror("无法构建测试环境", str(error))
            return
        if not messagebox.askyesno(
            f"构建：{scenario.title}",
            f"{scenario.description}\n\n"
            f"预期客户端表现：{scenario.expected_client}\n\n"
            + "\n".join(f"· {action}" for action in preview.actions)
            + "\n\n执行前请关闭游戏和客户端。测完后务必恢复环境。是否继续？",
        ):
            return
        try:
            self.acceptance.apply_preparation(
                self.profile,
                self._acceptance_paths,
                session,
                fingerprint,
                scenario.case_id,
                scenario.variant_id,
            )
            self._update_acceptance_environment_controls()
            messagebox.showwarning(
                "测试环境已构建",
                f"「{scenario.title}」已生效。\n\n"
                "现在可以启动客户端验证对应行为。\n"
                "测完后请点击“恢复测试环境”。",
            )
        except (AcceptanceError, OSError) as error:
            self._update_acceptance_environment_controls()
            messagebox.showerror("构建测试环境失败", str(error))

    def _selected_preparation_variant(self) -> str:
        return self._acceptance_variant_by_label.get(
            self.acceptance_variant_menu.get(), ""
        )

    def capture_acceptance_baseline(self) -> None:
        fingerprint = self._acceptance_fingerprint
        session = self._acceptance_session
        if fingerprint is None or session is None:
            messagebox.showinfo("验收尚未就绪", "请先等待或刷新当前构建指纹")
            return
        existing = self.acceptance.current_baseline(self.profile, session)
        overwrite = False
        if existing is not None:
            overwrite = messagebox.askyesno(
                "重新记录补丁基线",
                "当前轮次已经记录过补丁基线。\n\n"
                "只有确认游戏已经恢复到正确状态时才能覆盖，是否继续？",
            )
            if not overwrite:
                return
        elif not messagebox.askyesno(
            "记录补丁基线",
            "将只复制补丁目录中的两个 DLL 和 cream_api.ini 到验收备份。\n\n"
            "不会修改游戏文件，也不会备份或扫描全部 DLC。是否继续？",
        ):
            return
        try:
            output = self.acceptance.capture_patch_baseline(
                self.profile,
                self._acceptance_paths,
                session,
                fingerprint,
                overwrite=overwrite,
            )
            self._update_acceptance_environment_controls()
            messagebox.showinfo("基线已记录", f"补丁测试基线已保存：\n{output}")
        except (AcceptanceError, OSError) as error:
            messagebox.showerror("记录补丁基线失败", str(error))

    def preview_acceptance_preparation(self) -> None:
        try:
            preview = self._acceptance_preparation_preview()
            messagebox.showinfo(
                "环境准备预览",
                f"方案：{preview.variant.label}\n\n"
                f"{preview.variant.description}\n\n"
                + "\n".join(f"· {action}" for action in preview.actions)
                + "\n\n此时尚未修改游戏文件。",
            )
        except (AcceptanceError, OSError) as error:
            messagebox.showerror("无法预览环境准备", str(error))

    def apply_acceptance_preparation(self) -> None:
        try:
            preview = self._acceptance_preparation_preview()
        except (AcceptanceError, OSError) as error:
            messagebox.showerror("无法准备测试环境", str(error))
            return
        if not messagebox.askyesno(
            "执行环境准备",
            f"方案：{preview.variant.label}\n\n"
            + "\n".join(f"· {action}" for action in preview.actions)
            + "\n\n执行前请关闭游戏和客户端。程序会保留基线用于恢复，是否继续？",
        ):
            return
        try:
            assert self._acceptance_session is not None
            assert self._acceptance_fingerprint is not None
            self.acceptance.apply_preparation(
                self.profile,
                self._acceptance_paths,
                self._acceptance_session,
                self._acceptance_fingerprint,
                self._acceptance_case_id,
                preview.variant.variant_id,
            )
            self._update_acceptance_environment_controls()
            messagebox.showwarning(
                "测试环境已准备",
                "测试环境已经生效。现在可以启动客户端执行对应测试。\n\n"
                "测试完成后务必点击“恢复测试环境”。",
            )
        except (AcceptanceError, OSError) as error:
            self._update_acceptance_environment_controls()
            messagebox.showerror("准备测试环境失败", str(error))

    def _acceptance_preparation_preview(self) -> PreparationPreview:
        fingerprint = self._acceptance_fingerprint
        session = self._acceptance_session
        variant_id = self._selected_preparation_variant()
        if fingerprint is None or session is None:
            raise AcceptanceError("请先等待或刷新当前构建指纹")
        if not variant_id:
            raise AcceptanceError("当前验收项目没有可自动准备的安全环境方案")
        return self.acceptance.preview_preparation(
            self.profile,
            self._acceptance_paths,
            session,
            fingerprint,
            self._acceptance_case_id,
            variant_id,
        )

    def restore_acceptance_environment(self) -> None:
        active = self.acceptance.active_preparation(self.profile)
        if active is None:
            messagebox.showinfo("无需恢复", "当前游戏没有未恢复的测试环境")
            return
        if not messagebox.askyesno(
            "恢复测试环境",
            f"将按照测试前基线恢复补丁文件。\n\n"
            f"当前方案：{active.get('variant_label', '未知方案')}\n"
            "恢复前请关闭游戏和客户端，是否继续？",
        ):
            return
        try:
            count = self.acceptance.restore_prepared_environment(self.profile)
            self._update_acceptance_environment_controls()
            messagebox.showinfo("测试环境已恢复", f"已按基线恢复 {count} 个补丁目标。")
        except (AcceptanceError, OSError) as error:
            self._update_acceptance_environment_controls()
            messagebox.showerror(
                "恢复测试环境失败",
                f"{error}\n\n测试环境仍标记为未恢复，请不要启动游戏。",
            )

    def new_acceptance_session(self) -> None:
        if self.acceptance.active_preparation(self.profile) is not None:
            messagebox.showwarning(
                "请先恢复测试环境", "当前游戏仍有未恢复的测试环境，不能开始新一轮。"
            )
            return
        fingerprint = self._acceptance_fingerprint
        if fingerprint is None:
            messagebox.showinfo("验收尚未就绪", "请先等待或刷新当前构建指纹")
            return
        session = self._acceptance_session
        if session and session.results and not messagebox.askyesno(
            "开始新一轮验收",
            "当前轮次已有测试记录。旧记录会归档保留，新一轮将从未测试开始，是否继续？",
        ):
            return
        try:
            self._acceptance_session = self.acceptance.new_session(
                self.profile, fingerprint
            )
            self._fill_acceptance_cases()
            self._render_acceptance_case()
        except OSError as error:
            messagebox.showerror("无法开始验收", str(error))

    def mark_acceptance_result(self, status: str) -> None:
        fingerprint = self._acceptance_fingerprint
        if not self._acceptance_case_id or fingerprint is None:
            messagebox.showinfo("验收尚未就绪", "请先等待或刷新当前构建指纹")
            return
        note = self.acceptance_note.get("1.0", "end").strip()
        try:
            self._acceptance_session = self.acceptance.record_result(
                self.profile,
                self._acceptance_case_id,
                status,
                fingerprint,
                note=note,
            )
            self._fill_acceptance_cases()
            self._render_acceptance_case()
        except (AcceptanceError, OSError) as error:
            messagebox.showerror("记录验收结果失败", str(error))

    def clear_acceptance_result(self) -> None:
        if not self._acceptance_case_id:
            return
        try:
            self._acceptance_session = self.acceptance.clear_result(
                self.profile, self._acceptance_case_id
            )
            self._fill_acceptance_cases()
            self._render_acceptance_case()
        except OSError as error:
            messagebox.showerror("清除验收结果失败", str(error))

    def choose_acceptance_client(self) -> None:
        current = self._acceptance_paths.client_path
        path = filedialog.askopenfilename(
            title="选择要人工验收的客户端 EXE",
            initialdir=current.parent if current and current.parent.is_dir() else None,
            filetypes=(("Windows 程序", "*.exe"), ("所有文件", "*.*")),
        )
        if not path:
            return
        selected = Path(path)
        try:
            self._acceptance_paths = self.acceptance.save_paths(
                self.profile, client_path=selected, keep_client=False
            )
            self.refresh_acceptance()
        except OSError as error:
            messagebox.showerror("保存客户端路径失败", str(error))

    def choose_acceptance_game(self) -> None:
        if self.acceptance.active_preparation(self.profile) is not None:
            messagebox.showwarning(
                "请先恢复测试环境", "当前游戏仍有未恢复的测试环境，不能更换游戏目录。"
            )
            return
        current = self._acceptance_paths.game_path
        path = filedialog.askdirectory(
            title=f"选择 {self.profile.display_name} 的实际游戏目录",
            initialdir=current if current and current.is_dir() else None,
        )
        if not path:
            return
        try:
            self._acceptance_paths = self.acceptance.save_paths(
                self.profile, game_path=Path(path), keep_game=False
            )
            self.refresh_acceptance()
        except OSError as error:
            messagebox.showerror("保存游戏路径失败", str(error))

    def launch_acceptance_client(self) -> None:
        path = self._acceptance_paths.client_path
        if path is None or not path.is_file():
            messagebox.showinfo("未选择客户端", "请先选择要测试的客户端 EXE")
            return
        try:
            root = path.parent.parent if path.parent.name.casefold() == "bin" else path.parent
            subprocess.Popen([str(path)], cwd=root)
        except OSError as error:
            messagebox.showerror("启动客户端失败", str(error))

    def open_acceptance_dlc(self) -> None:
        game_root = self._acceptance_paths.game_path
        if game_root is None or not game_root.is_dir():
            messagebox.showinfo("未选择游戏目录", "请先选择当前游戏的实际安装目录")
            return
        path = game_root / self.profile.dlc_relative_dir
        if not path.is_dir():
            messagebox.showwarning("DLC 目录不存在", f"当前卡带配置的目录不存在：\n{path}")
            return
        self._open(path)

    def open_acceptance_game(self) -> None:
        game_root = self._acceptance_paths.game_path
        if game_root is None or not game_root.is_dir():
            messagebox.showinfo("未选择游戏目录", "请先选择当前游戏的实际安装目录")
            return
        self._open(game_root)

    def open_acceptance_patch(self) -> None:
        game_root = self._acceptance_paths.game_path
        if game_root is None or not game_root.is_dir():
            messagebox.showinfo("未选择游戏目录", "请先选择当前游戏的实际安装目录")
            return
        try:
            path = self.acceptance.patch_directory(
                self.profile, game_root, require_exists=True
            )
        except AcceptanceError as error:
            messagebox.showwarning("补丁目录不存在", str(error))
            return
        self._open(path)

    def create_acceptance_interference_files(self) -> None:
        game_root = self._acceptance_paths.game_path
        if game_root is None or not game_root.is_dir():
            messagebox.showinfo("未选择游戏目录", "请先选择当前游戏的实际安装目录")
            return
        count = len(INTERFERENCE_FILE_SAMPLE_NAMES)
        try:
            patch_dir = self.acceptance.patch_directory(
                self.profile, game_root, require_exists=True
            )
        except AcceptanceError as error:
            messagebox.showwarning("补丁目录不存在", str(error))
            return
        if not messagebox.askyesno(
            "添加干扰文件样例",
            f"将在以下补丁目录创建 {count} 个空文件，用于验收客户端的清理流程：\n"
            f"{patch_dir}\n\n"
            "同名文件绝不会被覆盖；如发现同名文件，操作会取消。是否继续？",
        ):
            return
        try:
            created = self.acceptance.create_interference_file_samples(
                self.profile, game_root
            )
        except AcceptanceError as error:
            messagebox.showerror("添加干扰文件失败", str(error))
            return
        messagebox.showinfo(
            "干扰文件样例已添加",
            f"已在当前补丁目录创建 {len(created)} 个干扰文件样例。\n\n"
            "现在可在客户端执行一键解锁或一键修复，验收清理流程。",
        )

    def inspect_acceptance_environment(self) -> None:
        fingerprint = self._acceptance_fingerprint
        if fingerprint is None:
            messagebox.showinfo("验收尚未就绪", "请先等待或刷新当前构建指纹")
            return
        try:
            session = self._acceptance_session or self.acceptance.ensure_session(
                self.profile, fingerprint
            )
            output, report = self.acceptance.inspect_environment(
                self.profile, self._acceptance_paths, session
            )
            patch_files = report.get("patch_files", {})
            patch_ready = sum(
                1
                for value in patch_files.values()
                if isinstance(value, dict) and value.get("exists")
            ) if isinstance(patch_files, dict) else 0
            messagebox.showinfo(
                "环境状态已记录",
                f"DLC 文件夹：{report['dlc_folder_count']} 个\n"
                f"补丁相关文件：{patch_ready}/3 个存在\n\n"
                f"只进行了读取，没有修改游戏文件。\n记录：{output}",
            )
        except (AcceptanceError, OSError) as error:
            messagebox.showerror("检查环境失败", str(error))

    def collect_acceptance_log(self) -> None:
        fingerprint = self._acceptance_fingerprint
        if fingerprint is None:
            messagebox.showinfo("验收尚未就绪", "请先等待或刷新当前构建指纹")
            return
        try:
            session = self._acceptance_session or self.acceptance.ensure_session(
                self.profile, fingerprint
            )
            output = self.acceptance.collect_client_log(
                self.profile, self._acceptance_paths, session
            )
            messagebox.showinfo("日志已收集", f"客户端日志已复制到：\n{output}")
        except (AcceptanceError, OSError) as error:
            messagebox.showerror("收集日志失败", str(error))

    def open_acceptance_evidence(self) -> None:
        session = self._acceptance_session
        if session is None:
            messagebox.showinfo("验收尚未就绪", "当前还没有验收轮次")
            return
        try:
            self._open(self.acceptance.evidence_dir(self.profile, session))
        except OSError as error:
            messagebox.showerror("打开证据目录失败", str(error))

    def _acceptance_display_path(self, path: Path | None, limit: int = 92) -> str:
        if path is None:
            return "尚未选择"
        text = str(path)
        return text if len(text) <= limit else "…" + text[-(limit - 1):]
