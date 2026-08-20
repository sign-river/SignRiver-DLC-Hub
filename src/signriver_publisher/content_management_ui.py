from __future__ import annotations

import threading
from pathlib import Path
from queue import Empty
from tkinter import TclError, filedialog, messagebox

import customtkinter as ctk

from .models import GameProfile
from .workspace import WorkspaceError

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
PAGE = "#F5F7FA"
CARD = "#FFFFFF"
TEXT = "#212121"
MUTED = "#757575"
RED = "#E53935"

PROFILE_OPTION_LABELS = {
    "dlc_archive_root_mode": {
        "source": "保留管理目录名",
        "strip_id_prefix": "去掉管理编号，恢复游戏原目录名",
    },
    "dlc_import_naming_mode": {
        "manual_prefixed": "沿用自带编号或手动编号",
        "auto_prefix": "自动分配管理编号",
    },
    "dlc_import_layout_mode": {
        "grouped_leaf_paths": "跨分支按同名 DLC 目录合并",
        "single_directory": "每次导入一个 DLC 目录",
        "children_if_root": "选择 DLC 根目录时批量拆分",
    },
    "package_inspector": {
        "grouped_directory": "多路径聚合目录包",
        "directory": "通用目录包",
        "stellaris_zip": "Stellaris ZIP 描述包",
    },
}


class ContentManagementUiMixin:
    """Local content import, game profiles, builds, and Steam metadata controls."""

    def _build_sources_tab(self) -> None:
        self.sources_tab.grid_rowconfigure(1, weight=1)
        self.sources_tab.grid_columnconfigure((0, 1), weight=1)
        navigation = ctk.CTkFrame(self.sources_tab, fg_color="transparent")
        navigation.grid(row=0, column=0, columnspan=2, padx=8, pady=(2, 0), sticky="ew")
        ctk.CTkButton(
            navigation,
            text="← 返回资源入口",
            width=142,
            height=34,
            fg_color="transparent",
            text_color=BLUE,
            border_width=1,
            border_color="#90CAF9",
            hover_color="#EAF4FD",
            command=lambda: self.content_tabs.set("DLC / 补丁发布"),
        ).pack(side="left")
        self.dlc_card = ctk.CTkFrame(
            self.sources_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        self.dlc_card.grid(row=1, column=0, padx=(8, 5), pady=8, sticky="nsew")
        self.patch_card = ctk.CTkFrame(
            self.sources_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        self.patch_card.grid(row=1, column=1, padx=(5, 8), pady=8, sticky="nsew")
        for card in (self.dlc_card, self.patch_card):
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(2, weight=1)
        self.dlc_import_button, self.dlc_clear_button = self._resource_header(
            self.dlc_card,
            "DLC 文件夹",
            self.import_dlc,
            self.open_dlc_folder,
            lambda: self.clear_local_resources("dlc"),
        )
        self.patch_import_button, self.patch_clear_button = self._resource_header(
            self.patch_card,
            "补丁资源",
            self.import_patch,
            self.open_patch_folder,
            lambda: self.clear_local_resources("patches"),
        )
        self.dlc_list = ctk.CTkScrollableFrame(
            self.dlc_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0"
        )
        self.dlc_list.grid(row=2, column=0, padx=16, pady=(6, 16), sticky="nsew")
        self.patch_list = ctk.CTkScrollableFrame(
            self.patch_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0"
        )
        self.patch_list.grid(row=2, column=0, padx=16, pady=(6, 16), sticky="nsew")

    def _resource_header(
        self, card, title, import_command, open_command, clear_command
    ):
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=0, column=0, padx=16, pady=(14, 2), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bar, text=title, font=("Microsoft YaHei UI", 20, "bold"), text_color=BLUE
        ).grid(row=0, column=0, padx=4, sticky="w")
        import_button = ctk.CTkButton(
            bar, text="导入", width=72, fg_color=BLUE, command=import_command
        )
        import_button.grid(row=0, column=1, padx=4)
        clear_button = ctk.CTkButton(
            bar,
            text="清空全部",
            width=88,
            fg_color="transparent",
            border_width=1,
            border_color=RED,
            text_color=RED,
            hover_color="#FFEBEE",
            command=clear_command,
        )
        clear_button.grid(row=0, column=2, padx=4)
        ctk.CTkButton(
            bar, text="打开目录", width=88, fg_color=LIGHT_BLUE, command=open_command
        ).grid(row=0, column=3, padx=4)
        ctk.CTkLabel(
            card, text="可直接把资源放入对应目录，再点击刷新", text_color=MUTED
        ).grid(row=1, column=0, padx=20, pady=(0, 4), sticky="w")
        return import_button, clear_button

    def _build_content_release_tab(self) -> None:
        """Build the only game selector used for DLC/patch release work."""
        self.content_release_tab.grid_rowconfigure(0, weight=1)
        self.content_release_tab.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(
            self.content_release_tab, fg_color=PAGE, corner_radius=0
        )
        scroll.grid(row=0, column=0, sticky="nsew")

        scope = self._card(scroll, 0, "DLC / 补丁发布包")
        scope.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(scope, text="当前发布游戏", width=110, anchor="w").grid(
            row=1, column=0, padx=(20, 10), pady=(0, 8), sticky="w"
        )
        self.game_menu = ctk.CTkOptionMenu(
            scope,
            command=self._select_game,
            width=280,
            fg_color=LIGHT_BLUE,
            button_color=BLUE,
        )
        self.game_menu.grid(row=1, column=1, padx=(0, 20), pady=(0, 8), sticky="ew")
        self.content_release_scope_label = ctk.CTkLabel(
            scope,
            text="准备完成后可直接加入上传队列；后台会按顺序同步双端资源，发布记录由程序自动维护。",
            text_color=MUTED,
            justify="left",
            anchor="w",
            wraplength=760,
        )
        self.content_release_scope_label.grid(
            row=2, column=0, columnspan=2, padx=20, pady=(0, 12), sticky="ew"
        )

        actions = ctk.CTkFrame(scope, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 18), sticky="ew")
        actions.grid_columnconfigure((0, 1, 2, 3), weight=1)
        ctk.CTkButton(
            actions,
            text="查看本游戏本地资源",
            fg_color="transparent",
            border_width=1,
            border_color="#90CAF9",
            text_color=BLUE,
            command=self._open_selected_game_sources,
            height=44,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.content_enqueue_button = ctk.CTkButton(
            actions,
            text="加入上传队列",
            fg_color=BLUE,
            command=self._build_and_enqueue_current_game_upload,
            height=44,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.content_enqueue_button.grid(row=0, column=1, padx=6, sticky="ew")
        ctk.CTkButton(
            actions,
            text="查看上传队列",
            fg_color="transparent",
            border_width=1,
            border_color="#90CAF9",
            text_color=BLUE,
            command=lambda: self.content_tabs.set("上传队列"),
            height=44,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=0, column=2, padx=6, sticky="ew")
        ctk.CTkButton(
            actions,
            text="远端资源维护",
            fg_color="transparent",
            border_width=1,
            border_color="#90CAF9",
            text_color=BLUE,
            command=lambda: self.content_tabs.set("远端维护"),
            height=44,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=0, column=3, padx=(6, 0), sticky="ew")

        output = self._card(scroll, 1, "发布包状态")
        self.content_release_output_label = ctk.CTkLabel(
            output,
            text="正在读取当前游戏的发布包状态…",
            text_color=MUTED,
            justify="left",
            anchor="w",
            wraplength=760,
        )
        self.content_release_output_label.grid(
            row=1, column=0, padx=20, pady=(0, 18), sticky="ew"
        )

    def _open_game_content_release_pipeline(self) -> None:
        """Enter the DLC/patch package page with the active profile in view."""
        self.tabs.set("资源管理")
        self.content_tabs.set("DLC / 补丁发布")
        self._refresh_content_release_summary()

    def _open_selected_game_sources(self) -> None:
        self.tabs.set("资源管理")
        self.content_tabs.set("本地资源")

    def _create_or_open_game_content_release_batch(self) -> None:
        try:
            plan = self._create_current_game_content_batch()
        except Exception as error:
            messagebox.showerror("准备上传任务失败", str(error), parent=self)
            return
        self._open_release_batch(plan.batch_id)

    def _refresh_content_release_summary(self) -> None:
        if not hasattr(self, "content_release_output_label"):
            return
        output_dir = self.workspace.output_dir / self.profile.game_id
        files = (
            tuple(sorted(path for path in output_dir.iterdir() if path.is_file()))
            if output_dir.is_dir()
            else ()
        )
        catalog = next((path for path in files if path.name == "catalog.json"), None)
        if catalog is None:
            text = (
                f"当前游戏：{self.profile.display_name}（{self.profile.game_id}）\n"
                "尚未准备可发布的 catalog.json。请先在“本地资源”准备 DLC / 补丁，"
                "然后点击“加入上传队列”，程序会自动构建发布文件。"
            )
        else:
            attachments = [path for path in files if path != catalog]
            total_size = sum(path.stat().st_size for path in files)
            text = (
                f"当前游戏：{self.profile.display_name}（{self.profile.game_id}）\n"
                f"已找到 {len(attachments)} 个附件和 catalog.json，共 {total_size / 1024 / 1024:.1f} MiB。"
            )
        self.content_release_output_label.configure(text=text)

    def _build_games_tab(self) -> None:
        self.games_tab.grid_rowconfigure(0, weight=1)
        self.games_tab.grid_columnconfigure(0, weight=1)
        self.games_scroll = ctk.CTkScrollableFrame(
            self.games_tab,
            fg_color=PAGE,
            corner_radius=0,
        )
        self.games_scroll.grid(row=0, column=0, sticky="nsew")
        card = self._card(self.games_scroll, 0, "游戏卡带配置")
        form = ctk.CTkFrame(card, fg_color="transparent")
        form.grid(row=1, column=0, padx=20, pady=(0, 16), sticky="ew")
        form.grid_columnconfigure(1, weight=1)
        labels = (
            ("游戏 ID", "game_id"),
            ("显示名称", "display_name"),
            ("Steam App ID", "steam_app_id"),
            ("Release 标签", "release_tag"),
            ("AppInfo 文件", "appinfo_name"),
            ("可执行文件", "executable_relative_path"),
            ("补丁 DLL", "patch_unlocker_name"),
            ("DLC 安装目录", "dlc_relative_dir"),
            ("补丁安装目录", "patch_relative_dir"),
            ("包校验方式", "package_inspector"),
            ("压缩包目录结构", "dlc_archive_root_mode"),
            ("导入编号方式", "dlc_import_naming_mode"),
            ("批量导入方式", "dlc_import_layout_mode"),
            ("聚合扫描目录", "dlc_group_search_roots"),
        )
        self.profile_entries: dict[str, object] = {}
        for row, (label, key) in enumerate(labels):
            ctk.CTkLabel(form, text=label, width=110, anchor="w").grid(
                row=row, column=0, pady=6, sticky="w"
            )
            if key in PROFILE_OPTION_LABELS:
                values = list(PROFILE_OPTION_LABELS[key].values())
                entry = ctk.CTkOptionMenu(
                    form,
                    values=values,
                    fg_color=LIGHT_BLUE,
                    button_color=BLUE,
                )
            else:
                entry = ctk.CTkEntry(form, border_color="#BDBDBD")
            entry.grid(row=row, column=1, pady=6, sticky="ew")
            if key == "appinfo_name":
                entry.configure(state="disabled")
            self.profile_entries[key] = entry
        ctk.CTkButton(
            form, text="保存当前卡带", fg_color=BLUE, command=self.save_profile
        ).grid(row=len(labels), column=1, pady=10, sticky="e")
        ctk.CTkButton(
            form, text="新增游戏卡带", fg_color=LIGHT_BLUE, command=self.add_game
        ).grid(row=len(labels), column=0, pady=10, sticky="w")

    def refresh(self) -> None:
        games = self.workspace.list_games()
        self._game_label_ids = {item.display_name: item.game_id for item in games}
        labels = [item.display_name for item in games]
        self.game_menu.configure(values=labels or ["尚未配置游戏"])
        self.game_menu.set(self.profile.display_name)
        self._refresh_content_release_summary()
        dlcs, patches = self.workspace.scan_sources(self.profile)
        self._fill_resources(self.dlc_list, dlcs, "dlc")
        self._fill_resources(self.patch_list, patches, "patches")
        for key, entry in self.profile_entries.items():
            if key in PROFILE_OPTION_LABELS:
                value = getattr(self.profile, key)
                entry.set(PROFILE_OPTION_LABELS[key].get(value, value))
                continue
            if key == "appinfo_name":
                entry.configure(state="normal")
            entry.delete(0, "end")
            value = getattr(self.profile, key)
            if key == "dlc_group_search_roots":
                value = "; ".join(value)
            entry.insert(0, value)
            if key == "appinfo_name":
                entry.configure(state="disabled")
        if hasattr(self, "local_output_list"):
            self._fill_local_outputs()
            self._show_remote_message("点击“刷新远程”读取当前游戏的 Release")
        if hasattr(self, "acceptance_case_list"):
            try:
                self.after_idle(self.refresh_acceptance)
            except TclError:
                pass
        self._update_freshness_summary()
        if hasattr(self, "cartridge_list"):
            self.refresh_cartridge_management()

    def _fill_resources(self, parent, resources: tuple[Path, ...], kind: str) -> None:
        for child in parent.winfo_children():
            child.destroy()
        if not resources:
            ctk.CTkLabel(parent, text="暂无资源", text_color=MUTED).pack(pady=24)
            self._schedule_scrollable_reset(parent)
            return
        for path in resources:
            row = ctk.CTkFrame(
                parent,
                fg_color=CARD,
                border_width=1,
                border_color="#E0E0E0",
                corner_radius=8,
            )
            row.pack(fill="x", padx=4, pady=4)
            ctk.CTkLabel(row, text=path.name, anchor="w", text_color=TEXT).pack(
                side="left", fill="x", expand=True, padx=12, pady=10
            )
            ctk.CTkButton(
                row,
                text="删除",
                width=64,
                fg_color="transparent",
                border_width=1,
                border_color=RED,
                text_color=RED,
                hover_color="#FFEBEE",
                command=lambda k=kind, n=path.name: self.remove_resource(k, n),
            ).pack(side="right", padx=8, pady=6)
        self._schedule_scrollable_reset(parent)

    def _select_game(self, label: str) -> None:
        game_id = getattr(self, "_game_label_ids", {}).get(label)
        if not game_id:
            # Backward-compatible fallback for older "Name (game_id)" labels.
            game_id = label.rsplit("(", 1)[-1].rstrip(")")
        self.profile = next(
            item for item in self.workspace.list_games() if item.game_id == game_id
        )
        self.refresh()

    def _fill_local_outputs(self) -> None:
        for child in self.local_output_list.winfo_children():
            child.destroy()
        target = self.workspace.output_dir / self.profile.game_id
        files = (
            tuple(sorted(path for path in target.iterdir() if path.is_file()))
            if target.is_dir()
            else ()
        )
        if not files:
            ctk.CTkLabel(
                self.local_output_list, text="尚未生成本地发布文件", text_color=MUTED
            ).pack(pady=24)
            self._schedule_scrollable_reset(self.local_output_list)
            return
        for path in files:
            row = ctk.CTkFrame(
                self.local_output_list,
                fg_color=CARD,
                border_width=1,
                border_color="#E0E0E0",
                corner_radius=8,
            )
            row.pack(fill="x", padx=4, pady=4)
            ctk.CTkLabel(row, text=path.name, anchor="w", text_color=TEXT).pack(
                side="left", fill="x", expand=True, padx=10, pady=9
            )
            ctk.CTkLabel(
                row,
                text="将用于当前游戏资源发布",
                text_color=MUTED,
            ).pack(side="right", padx=10, pady=9)
        self._schedule_scrollable_reset(self.local_output_list)

    def import_dlc(self) -> None:
        path = filedialog.askdirectory(title="选择 DLC 文件夹")
        if not path:
            return
        source = Path(path)
        profile = self.profile
        collection = self.workspace.is_dlc_collection(profile, source)
        interrupted = (
            self.workspace.interrupted_collection_import(profile, source)
            if collection
            else ()
        )
        reset_interrupted = False
        if interrupted:
            confirmed = messagebox.askyesno(
                "重置上次失败的导入",
                f"检测到上次导入中断后留下的 {len(interrupted)} 个错误编号目录。\n\n"
                "是否清理这些工作区副本和残留临时文件，并从 1 重新编号？\n"
                "不会删除游戏的原始 DLC 目录。",
            )
            if not confirmed:
                return
            reset_interrupted = True
        wrapped = (
            self.workspace.wrapped_collection_import(profile, source)
            if collection
            else None
        )
        if wrapped is not None:
            confirmed = messagebox.askyesno(
                "修正旧版误导入",
                f"检测到之前把整个 DLC 根目录导入成了 {wrapped.name}。\n\n"
                "是否直接把现有副本中的一级子目录拆分并分别编号？\n"
                "这是同一磁盘内的快速移动，不会重新复制，也不会删除原始 DLC 目录。",
            )
            if not confirmed:
                return
        if not self._begin_background_mutation(
            "dlc-import", "正在导入 DLC 资源"
        ):
            return
        self.dlc_import_button.configure(state="disabled", text="准备中…")
        self.dlc_clear_button.configure(state="disabled")
        self.game_menu.configure(state="disabled")

        def progress(index: int, total: int, name: str) -> None:
            self._post_ui(
                lambda: self.dlc_import_button.configure(
                    text=f"{index}/{total} {name[:10]}"
                )
            )

        def work() -> None:
            try:
                if reset_interrupted:
                    self._post_ui(
                        lambda: self.dlc_import_button.configure(
                            text="清理上次失败记录…"
                        )
                    )
                    self.workspace.reset_interrupted_collection_import(profile, source)
                if wrapped is not None:
                    result = self.workspace.split_wrapped_collection_import(
                        profile, source, progress=progress
                    )
                elif collection:
                    result = self.workspace.import_dlc_collection(
                        profile, source, progress=progress
                    )
                else:
                    result = (self.workspace.import_dlc(profile, source),)
                self._post_ui(lambda: self._import_dlc_done(profile, result))
            except Exception as error:
                message = str(error)
                self._post_ui(lambda: self._import_dlc_failed(message))

        threading.Thread(target=work, daemon=True).start()

    def _import_dlc_done(
        self, profile: GameProfile, imported: tuple[Path, ...]
    ) -> None:
        self._end_background_mutation("dlc-import")
        self.dlc_import_button.configure(state="normal", text="导入")
        self.dlc_clear_button.configure(state="normal")
        self.game_menu.configure(state="normal")
        if self.profile.game_id == profile.game_id:
            self.refresh()
        messagebox.showinfo("导入完成", f"已导入 {len(imported)} 个 DLC 文件夹")

    def _import_dlc_failed(self, message: str) -> None:
        self._end_background_mutation("dlc-import")
        self.dlc_import_button.configure(state="normal", text="导入")
        self.dlc_clear_button.configure(state="normal")
        self.game_menu.configure(state="normal")
        if not self.winfo_exists():
            return
        messagebox.showerror("导入失败", message)

    def import_patch(self) -> None:
        path = filedialog.askopenfilename(title="选择补丁文件")
        if not path:
            path = filedialog.askdirectory(title="或选择补丁文件夹")
        if path:
            self._run_action(
                lambda: self.workspace.import_patch(self.profile, Path(path)),
                "补丁已导入",
            )

    def remove_resource(self, kind: str, name: str) -> None:
        if not messagebox.askyesno(
            "确认删除",
            f"从发布工作区删除 {name}？\n此操作不会删除 GitLink 上已经发布的附件。",
        ):
            return
        self._run_action(
            lambda: self.workspace.remove_source(self.profile, kind, name), "资源已删除"
        )

    def clear_local_resources(self, kind: str) -> None:
        dlcs, patches = self.workspace.scan_sources(self.profile)
        resources = dlcs if kind == "dlc" else patches
        if not resources:
            messagebox.showinfo("无需清理", "当前区域没有本地资源")
            return
        label = "DLC 文件夹" if kind == "dlc" else "补丁资源"
        if not messagebox.askyesno(
            f"清空全部{label}",
            f"将从当前“{self.profile.display_name}”卡带的本地工作区删除 "
            f"{len(resources)} 项{label}。\n\n"
            "不会删除游戏原文件，也不会删除 GitLink Release。此操作无法撤销，是否继续？",
        ):
            return
        import_button = (
            self.dlc_import_button if kind == "dlc" else self.patch_import_button
        )
        clear_button = (
            self.dlc_clear_button if kind == "dlc" else self.patch_clear_button
        )
        operation_key = f"clear-local-{kind}"
        if not self._begin_background_mutation(
            operation_key, f"正在清空本地{label}"
        ):
            return
        import_button.configure(state="disabled")
        clear_button.configure(state="disabled", text="正在清空…")
        self.game_menu.configure(state="disabled")
        profile = self.profile

        def work() -> None:
            try:
                count = self.workspace.clear_sources(profile, kind)
                self._post_ui(
                    lambda: self._clear_local_resources_done(
                        profile,
                        label,
                        count,
                        import_button,
                        clear_button,
                        operation_key,
                    )
                )
            except Exception as error:
                message = str(error)
                self._post_ui(
                    lambda: self._clear_local_resources_failed(
                        message, import_button, clear_button, operation_key
                    )
                )

        threading.Thread(target=work, daemon=True).start()

    def _clear_local_resources_done(
        self,
        profile: GameProfile,
        label: str,
        count: int,
        import_button,
        clear_button,
        operation_key: str,
    ) -> None:
        self._end_background_mutation(operation_key)
        import_button.configure(state="normal")
        clear_button.configure(state="normal", text="清空全部")
        self.game_menu.configure(state="normal")
        if self.profile.game_id == profile.game_id:
            self.refresh()
        messagebox.showinfo("清理完成", f"已删除 {count} 项本地{label}")

    def _clear_local_resources_failed(
        self, message: str, import_button, clear_button, operation_key: str
    ) -> None:
        self._end_background_mutation(operation_key)
        import_button.configure(state="normal")
        clear_button.configure(state="normal", text="清空全部")
        self.game_menu.configure(state="normal")
        messagebox.showerror("清理失败", message)

    def save_profile(self) -> None:
        if not self._begin_background_mutation(
            "profile-save", "正在保存游戏卡带配置"
        ):
            return
        try:
            values = {
                key: entry.get().strip() for key, entry in self.profile_entries.items()
            }
            for key, labels in PROFILE_OPTION_LABELS.items():
                displayed = values[key]
                values[key] = next(
                    (stored for stored, label in labels.items() if label == displayed),
                    displayed,
                )
            values["appinfo_name"] = f"{values['game_id']}_appinfo.json"
            values["dlc_group_search_roots"] = [
                item.strip()
                for item in values.get("dlc_group_search_roots", "").split(";")
                if item.strip()
            ]
            merged = {**self.profile.to_dict(), **values}
            profile = GameProfile.from_dict(merged)
            if profile.game_id != self.profile.game_id:
                raise WorkspaceError("已创建游戏的 ID 不允许直接修改；请新增游戏")
            self.workspace.save_game(profile)
            self.profile = profile
            self.refresh()
            messagebox.showinfo("保存成功", "游戏卡带配置已保存")
        except (WorkspaceError, OSError) as error:
            messagebox.showerror("保存失败", str(error))
        finally:
            self._end_background_mutation("profile-save")

    def add_game(self) -> None:
        details = self._prompt_new_game_details()
        if details is None:
            return
        game_id, display, steam_app_id = details
        if not self._begin_background_mutation(
            "game-add", "正在新增游戏卡带"
        ):
            return
        try:
            normalized_id = game_id.strip().lower()
            profile = GameProfile.create(
                normalized_id, display.strip(), steam_app_id.strip()
            )
            if any(
                item.game_id == profile.game_id for item in self.workspace.list_games()
            ):
                raise WorkspaceError("该游戏已经存在")
            self.workspace.save_game(profile)
            self.profile = profile
            self.refresh()
        except (WorkspaceError, OSError) as error:
            messagebox.showerror("新增失败", str(error))
        finally:
            self._end_background_mutation("game-add")

    def _prompt_new_game_details(self) -> tuple[str, str, str] | None:
        """Collect a new game profile in a publisher-styled modal dialog."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("新增游戏")
        # This compact form intentionally fits without a scrollbar.  Keep enough
        # room for the action row at high display-scaling factors as well.
        dialog.geometry("520x440")
        dialog.resizable(False, False)
        dialog.configure(fg_color=PAGE)
        dialog.transient(self)

        surface = ctk.CTkFrame(
            dialog,
            fg_color=CARD,
            corner_radius=14,
            border_width=1,
            border_color="#D8DEE6",
        )
        surface.pack(fill="both", expand=True, padx=18, pady=18)
        surface.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            surface,
            text="新增游戏",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, padx=22, pady=(20, 4), sticky="w")
        ctk.CTkLabel(
            surface,
            text="填写基础信息后，将创建一份可继续编辑的游戏配置。",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).grid(row=1, column=0, padx=22, pady=(0, 16), sticky="w")

        form = ctk.CTkFrame(surface, fg_color="transparent")
        form.grid(row=2, column=0, padx=22, sticky="ew")
        form.grid_columnconfigure(0, weight=1)

        def add_field(row: int, title: str, hint: str) -> ctk.CTkEntry:
            ctk.CTkLabel(
                form,
                text=title,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=TEXT,
            ).grid(row=row, column=0, pady=(0, 4), sticky="w")
            entry = ctk.CTkEntry(
                form,
                height=34,
                placeholder_text=hint,
                border_color="#B8C5D3",
            )
            entry.grid(row=row + 1, column=0, pady=(0, 10), sticky="ew")
            return entry

        game_id_entry = add_field(0, "游戏 ID", "例如 crusader_kings_3")
        display_entry = add_field(2, "显示名称（可选）", "留空时使用游戏 ID")
        steam_app_id_entry = add_field(4, "Steam App ID（可选）", "例如 1158310")
        validation = ctk.CTkLabel(
            surface,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=RED,
        )
        validation.grid(row=3, column=0, padx=22, pady=(1, 0), sticky="w")

        result: dict[str, tuple[str, str, str] | None] = {"value": None}

        def close() -> None:
            try:
                dialog.grab_release()
            except TclError:
                pass
            if dialog.winfo_exists():
                dialog.destroy()

        def confirm() -> None:
            game_id = game_id_entry.get().strip()
            if not game_id:
                validation.configure(text="请先输入游戏 ID。")
                game_id_entry.focus_set()
                return
            result["value"] = (
                game_id,
                display_entry.get().strip() or game_id,
                steam_app_id_entry.get().strip(),
            )
            close()

        actions = ctk.CTkFrame(surface, fg_color="transparent")
        actions.grid(row=4, column=0, padx=22, pady=(12, 20), sticky="e")
        ctk.CTkButton(
            actions,
            text="取消",
            width=88,
            height=34,
            fg_color="transparent",
            text_color=TEXT,
            border_width=1,
            border_color="#B8C5D3",
            hover_color="#EEF2F6",
            command=close,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="新增游戏",
            width=108,
            height=34,
            fg_color=BLUE,
            hover_color="#1565C0",
            command=confirm,
        ).pack(side="left")

        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Return>", lambda _event: confirm())
        dialog.bind("<Escape>", lambda _event: close())
        dialog.grab_set()

        def center_on_publisher() -> None:
            try:
                parent = self.winfo_toplevel()
                parent.update_idletasks()
                dialog.update_idletasks()
                x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_width()) // 2
                y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_height()) // 2
                dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
            except TclError:
                pass

        def focus_game_id() -> None:
            try:
                if dialog.winfo_exists() and game_id_entry.winfo_exists():
                    game_id_entry.focus_set()
            except TclError:
                pass

        dialog.after(0, center_on_publisher)
        dialog.after(20, focus_game_id)
        self.wait_window(dialog)
        return result["value"]

    def _build_and_enqueue_current_game_upload(self) -> None:
        """Build the selected game first, then enter the normal queue flow."""
        try:
            existing = self.content_upload_queue.active_for_game(self.profile.game_id)
            if existing is not None:
                raise WorkspaceError(
                    f"“{self.profile.display_name}”已在上传队列中，请先处理现有上传项。"
                )
        except WorkspaceError as error:
            messagebox.showinfo("无法加入上传队列", str(error), parent=self)
            return
        self._enqueue_after_build_game_id = self.profile.game_id
        if not self.build_all():
            self._enqueue_after_build_game_id = None

    def build_all(self) -> bool:
        if not self._begin_background_mutation(
            "build", "正在构建发布文件"
        ):
            return False
        self.build_button.configure(state="disabled", text="正在构建…")
        if hasattr(self, "content_enqueue_button"):
            self.content_enqueue_button.configure(state="disabled", text="正在构建…")
        self.steam_button.configure(state="disabled")
        self.publish_button.configure(state="disabled")
        self.adopt_remote_button.configure(state="disabled")
        self.game_menu.configure(state="disabled")
        self._build_operation_active = True
        profile = self.profile
        workers = self.workspace.compression_worker_count()
        self._log(
            f"开始构建 {profile.display_name}：ZIP 压缩等级保持不变，"
            f"最多并行处理 {workers} 个 DLC。"
        )

        def progress(
            stage: str, index: int, total: int, name: str, detail: str
        ) -> None:
            self._build_progress_events.put((stage, index, total, name, detail))

        self.after(50, self._poll_build_progress)

        def work() -> None:
            try:
                records = self.workspace.build(profile, progress=progress)
                files = self.workspace.publish_files(profile)
                size = sum(path.stat().st_size for path in files)
                self._post_ui(
                    lambda: self._build_done(
                        profile.game_id, len(records), len(files), size
                    )
                )
            except Exception as error:
                message = str(error)
                self._post_ui(lambda value=message: self._build_failed(value))

        threading.Thread(target=work, daemon=True).start()
        return True

    def _poll_build_progress(self) -> None:
        while True:
            try:
                event = self._build_progress_events.get_nowait()
            except Empty:
                break
            self._build_progress(*event)
        if self._build_operation_active:
            self.after(80, self._poll_build_progress)

    def _build_progress(
        self, stage: str, index: int, total: int, name: str, detail: str
    ) -> None:
        self.build_button.configure(text=f"正在构建 · {stage}")
        if hasattr(self, "content_enqueue_button"):
            self.content_enqueue_button.configure(text=f"正在构建 · {stage}")
        position = f"[{index}/{total}] " if index > 0 and total > 0 else ""
        subject = f" {name}" if name else ""
        suffix = f" · {detail}" if detail else ""
        self._log(f"{position}{stage}{subject}{suffix}")

    def _build_done(self, game_id: str, resources: int, files: int, size: int) -> None:
        self._build_operation_active = False
        self._end_background_mutation("build")
        self._poll_build_progress()
        self.build_button.configure(state="normal", text="生成全部发布文件")
        if hasattr(self, "content_enqueue_button"):
            self.content_enqueue_button.configure(state="normal", text="加入上传队列")
        self.steam_button.configure(state="normal")
        self.publish_button.configure(state="normal")
        self.adopt_remote_button.configure(state="normal")
        self.game_menu.configure(state="normal")
        self.build_summary.configure(
            text=(
                f"{resources} 个资源 · {files} 个文件（含 catalog.json） · "
                f"{size / 1024 / 1024:.1f} MiB"
            )
        )
        self._log(
            "已生成静态目录 catalog.json；发布到 Release 时会作为最后一个附件上传。"
        )
        self._log(f"本地构建完成：{game_id}，共 {files} 个发布文件。")
        self._fill_local_outputs()
        self._update_freshness_summary()
        self._refresh_content_release_summary()
        self.refresh_acceptance()
        if getattr(self, "_enqueue_after_build_game_id", None) == game_id:
            self._enqueue_after_build_game_id = None
            self._enqueue_current_game_upload()

    def _build_failed(self, message: str) -> None:
        self._build_operation_active = False
        self._end_background_mutation("build")
        self._poll_build_progress()
        self.build_button.configure(state="normal", text="生成全部发布文件")
        if hasattr(self, "content_enqueue_button"):
            self.content_enqueue_button.configure(state="normal", text="加入上传队列")
        self._enqueue_after_build_game_id = None
        self.steam_button.configure(state="normal")
        self.publish_button.configure(state="normal")
        self.adopt_remote_button.configure(state="normal")
        self.game_menu.configure(state="normal")
        self._log(f"本地构建失败：{message}")
        messagebox.showerror("构建失败", message)

    def refresh_steam_data(self) -> None:
        if not self._begin_background_mutation(
            "steam-refresh", "正在刷新 Steam 数据"
        ):
            return
        self.steam_button.configure(state="disabled", text="正在查询…")
        profile = self.profile

        def work() -> None:
            try:
                appinfo = self.workspace.refresh_appinfo(profile)
                self._post_ui(
                    lambda: self._steam_refresh_done(appinfo.name, len(appinfo.dlcs))
                )
            except Exception as error:
                message = str(error)
                self._post_ui(lambda value=message: self._steam_refresh_failed(value))

        threading.Thread(target=work, daemon=True).start()

    def _steam_refresh_done(self, name: str, count: int) -> None:
        self._end_background_mutation("steam-refresh")
        self.steam_button.configure(state="normal", text="刷新 Steam 数据")
        self._log(f"Steam 数据已更新：{name}，{count} 个 DLC。")
        messagebox.showinfo("更新完成", f"已生成 Steam AppInfo，共 {count} 个 DLC。")

    def _steam_refresh_failed(self, message: str) -> None:
        self._end_background_mutation("steam-refresh")
        self.steam_button.configure(state="normal", text="刷新 Steam 数据")
        messagebox.showerror("Steam 数据更新失败", message)

    def open_dlc_folder(self) -> None:
        self._open(self.workspace.game_dir(self.profile.game_id) / "dlc")

    def open_patch_folder(self) -> None:
        self._open(self.workspace.game_dir(self.profile.game_id) / "patches")
