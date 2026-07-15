from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from .gitlink import GitLinkAttachmentClient, GitLinkCli, GitLinkError, GitLinkRepository
from .models import GameProfile, PublishAsset
from .remote import RemoteAsset, RemoteRelease, RemoteResourceManager
from .settings import PublisherSettings
from .workspace import PublisherWorkspace, WorkspaceError

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
BRAND = "#3A7EBF"
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
        "single_directory": "每次导入一个 DLC 目录",
        "children_if_root": "选择 DLC 根目录时批量拆分",
    },
}


class PublisherApplication(ctk.CTk):
    def __init__(self, workspace: PublisherWorkspace, *, settings: PublisherSettings | None = None) -> None:
        super().__init__()
        self.workspace = workspace
        self.settings = settings or PublisherSettings()
        self.profile = workspace.initialize()
        self.gitlink = GitLinkCli()
        self.repository = GitLinkRepository(self.settings.owner, self.settings.repository)
        self._remote_operation_active = False
        self.title("SignRiver 发布管理器")
        self.geometry("1240x800")
        self.minsize(980, 660)
        self.configure(fg_color=PAGE)
        ctk.set_appearance_mode("light")
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color=BRAND, corner_radius=0, height=116)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="SignRiver 发布管理器", font=("Microsoft YaHei UI", 28, "bold"), text_color="white").grid(row=0, column=0, padx=(28, 20), pady=(22, 4), sticky="w")
        ctk.CTkLabel(header, text="服务端制卡机 · 每张游戏卡带独立构建与发布", font=("Microsoft YaHei UI", 14), text_color="#EAF4FF").grid(row=1, column=0, padx=30, pady=(0, 20), sticky="w")
        self.game_menu = ctk.CTkOptionMenu(header, command=self._select_game, width=220, fg_color=LIGHT_BLUE, button_color=BLUE)
        self.game_menu.grid(row=0, column=2, rowspan=2, padx=28)

        self.tabs = ctk.CTkTabview(self, fg_color=PAGE, segmented_button_selected_color=BLUE, segmented_button_selected_hover_color=BRAND)
        self.tabs.grid(row=1, column=0, padx=22, pady=18, sticky="nsew")
        self.sources_tab = self.tabs.add("资源管理")
        self.build_tab = self.tabs.add("构建与发布")
        self.remote_tab = self.tabs.add("远程资源")
        self.games_tab = self.tabs.add("卡带配置")
        self._build_sources_tab()
        self._build_publish_tab()
        self._build_remote_tab()
        self._build_games_tab()

    def _card(self, parent, row: int, title: str) -> ctk.CTkFrame:
        parent.grid_columnconfigure(0, weight=1)
        frame = ctk.CTkFrame(parent, fg_color=CARD, border_width=1, border_color="#D8DEE6", corner_radius=14)
        frame.grid(row=row, column=0, padx=8, pady=8, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=title, font=("Microsoft YaHei UI", 20, "bold"), text_color=BLUE).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")
        return frame

    def _build_sources_tab(self) -> None:
        self.sources_tab.grid_rowconfigure(0, weight=1)
        self.sources_tab.grid_columnconfigure((0, 1), weight=1)
        self.dlc_card = ctk.CTkFrame(self.sources_tab, fg_color=CARD, border_width=1, border_color="#D8DEE6", corner_radius=14)
        self.dlc_card.grid(row=0, column=0, padx=(8, 5), pady=8, sticky="nsew")
        self.patch_card = ctk.CTkFrame(self.sources_tab, fg_color=CARD, border_width=1, border_color="#D8DEE6", corner_radius=14)
        self.patch_card.grid(row=0, column=1, padx=(5, 8), pady=8, sticky="nsew")
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
        self.dlc_list = ctk.CTkScrollableFrame(self.dlc_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0")
        self.dlc_list.grid(row=2, column=0, padx=16, pady=(6, 16), sticky="nsew")
        self.patch_list = ctk.CTkScrollableFrame(self.patch_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0")
        self.patch_list.grid(row=2, column=0, padx=16, pady=(6, 16), sticky="nsew")

    def _resource_header(self, card, title, import_command, open_command, clear_command):
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=0, column=0, padx=16, pady=(14, 2), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text=title, font=("Microsoft YaHei UI", 20, "bold"), text_color=BLUE).grid(row=0, column=0, padx=4, sticky="w")
        import_button = ctk.CTkButton(bar, text="导入", width=72, fg_color=BLUE, command=import_command)
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
        ctk.CTkButton(bar, text="打开目录", width=88, fg_color=LIGHT_BLUE, command=open_command).grid(row=0, column=3, padx=4)
        ctk.CTkLabel(card, text="可直接把资源放入对应目录，再点击刷新", text_color=MUTED).grid(row=1, column=0, padx=20, pady=(0, 4), sticky="w")
        return import_button, clear_button

    def _build_publish_tab(self) -> None:
        self.build_tab.grid_rowconfigure(1, weight=1)
        build_card = self._card(self.build_tab, 0, "本地构建")
        actions = ctk.CTkFrame(build_card, fg_color="transparent")
        actions.grid(row=1, column=0, padx=18, pady=(2, 16), sticky="ew")
        self.build_button = ctk.CTkButton(actions, text="生成全部发布文件", width=180, fg_color=BLUE, command=self.build_all)
        self.build_button.pack(side="left", padx=4)
        self.steam_button = ctk.CTkButton(actions, text="刷新 Steam 数据", width=150, fg_color=LIGHT_BLUE, command=self.refresh_steam_data)
        self.steam_button.pack(side="left", padx=4)
        ctk.CTkButton(actions, text="打开输出目录", width=150, fg_color=LIGHT_BLUE, command=self.open_output_folder).pack(side="left", padx=4)
        self.build_summary = ctk.CTkLabel(actions, text="尚未构建", text_color=MUTED)
        self.build_summary.pack(side="left", padx=18)

        remote = self._card(self.build_tab, 1, "GitLink 新仓库")
        remote.grid_rowconfigure(3, weight=1)
        settings = ctk.CTkFrame(remote, fg_color="transparent")
        settings.grid(row=1, column=0, padx=20, sticky="ew")
        settings.grid_columnconfigure((1, 3), weight=1)
        ctk.CTkLabel(settings, text="所有者").grid(row=0, column=0, padx=(0, 8))
        self.owner_entry = ctk.CTkEntry(settings, border_color="#BDBDBD")
        self.owner_entry.insert(0, self.repository.owner)
        self.owner_entry.grid(row=0, column=1, padx=(0, 18), sticky="ew")
        ctk.CTkLabel(settings, text="新仓库").grid(row=0, column=2, padx=(0, 8))
        self.repo_entry = ctk.CTkEntry(settings, border_color="#BDBDBD")
        self.repo_entry.insert(0, self.repository.name)
        self.repo_entry.grid(row=0, column=3, padx=(0, 10), sticky="ew")
        buttons = ctk.CTkFrame(remote, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=18, pady=12, sticky="ew")
        self.check_gitlink_button = ctk.CTkButton(buttons, text="检查登录与仓库", width=160, fg_color=LIGHT_BLUE, command=self.check_gitlink)
        self.check_gitlink_button.pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="创建新仓库", width=140, fg_color=LIGHT_BLUE, command=self.create_repository).pack(side="left", padx=4)
        self.publish_button = ctk.CTkButton(buttons, text="发布到 Release", width=160, fg_color=BLUE, command=self.publish_release)
        self.publish_button.pack(side="left", padx=4)
        self.token_entry = ctk.CTkEntry(buttons, width=230, show="●", placeholder_text="GitLink 私有令牌", border_color="#BDBDBD")
        self.token_entry.pack(side="right", padx=4)
        if self.settings.token:
            self.token_entry.insert(0, self.settings.token)
        self.log = ctk.CTkTextbox(remote, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0", text_color=TEXT)
        self.log.grid(row=3, column=0, padx=20, pady=(0, 18), sticky="nsew")
        self._log("令牌从本地私密配置或输入框读取，不会输出到日志。")

    def _build_remote_tab(self) -> None:
        self.remote_tab.grid_rowconfigure(1, weight=1)
        self.remote_tab.grid_columnconfigure((0, 1), weight=1)
        toolbar = ctk.CTkFrame(self.remote_tab, fg_color=CARD, border_width=1, border_color="#D8DEE6", corner_radius=14)
        toolbar.grid(row=0, column=0, columnspan=2, padx=8, pady=(8, 4), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)
        self.remote_status = ctk.CTkLabel(toolbar, text="选择当前游戏后刷新远程 Release", text_color=MUTED, anchor="w")
        self.remote_status.grid(row=0, column=0, padx=18, pady=14, sticky="ew")
        self.remote_refresh_button = ctk.CTkButton(toolbar, text="刷新远程", width=110, fg_color=LIGHT_BLUE, command=self.refresh_remote_resources)
        self.remote_refresh_button.grid(row=0, column=1, padx=4, pady=10)
        ctk.CTkButton(toolbar, text="选择文件上传", width=130, fg_color=BLUE, command=self.choose_remote_upload).grid(row=0, column=2, padx=(4, 14), pady=10)

        local_card = ctk.CTkFrame(self.remote_tab, fg_color=CARD, border_width=1, border_color="#D8DEE6", corner_radius=14)
        local_card.grid(row=1, column=0, padx=(8, 5), pady=(4, 8), sticky="nsew")
        remote_card = ctk.CTkFrame(self.remote_tab, fg_color=CARD, border_width=1, border_color="#D8DEE6", corner_radius=14)
        remote_card.grid(row=1, column=1, padx=(5, 8), pady=(4, 8), sticky="nsew")
        for card in (local_card, remote_card):
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(local_card, text="本地发布文件", font=("Microsoft YaHei UI", 19, "bold"), text_color=BLUE).grid(row=0, column=0, padx=18, pady=(14, 6), sticky="w")
        ctk.CTkLabel(remote_card, text="GitLink Release 附件", font=("Microsoft YaHei UI", 19, "bold"), text_color=BLUE).grid(row=0, column=0, padx=18, pady=(14, 6), sticky="w")
        self.local_output_list = ctk.CTkScrollableFrame(local_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0")
        self.local_output_list.grid(row=1, column=0, padx=14, pady=(4, 14), sticky="nsew")
        self.remote_asset_list = ctk.CTkScrollableFrame(remote_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0")
        self.remote_asset_list.grid(row=1, column=0, padx=14, pady=(4, 14), sticky="nsew")

    def _build_games_tab(self) -> None:
        card = self._card(self.games_tab, 0, "游戏卡带配置")
        form = ctk.CTkFrame(card, fg_color="transparent")
        form.grid(row=1, column=0, padx=20, pady=(0, 16), sticky="ew")
        form.grid_columnconfigure(1, weight=1)
        labels = (
            ("游戏 ID", "game_id"),
            ("显示名称", "display_name"),
            ("Steam App ID", "steam_app_id"),
            ("Release 标签", "release_tag"),
            ("AppInfo 文件", "appinfo_name"),
            ("补丁 DLL", "patch_unlocker_name"),
            ("原版备份 DLL", "patch_original_backup_name"),
            ("DLC 安装目录", "dlc_relative_dir"),
            ("补丁安装目录", "patch_relative_dir"),
            ("压缩包目录结构", "dlc_archive_root_mode"),
            ("导入编号方式", "dlc_import_naming_mode"),
            ("批量导入方式", "dlc_import_layout_mode"),
        )
        self.profile_entries: dict[str, object] = {}
        for row, (label, key) in enumerate(labels):
            ctk.CTkLabel(form, text=label, width=110, anchor="w").grid(row=row, column=0, pady=6, sticky="w")
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
        ctk.CTkButton(form, text="保存当前卡带", fg_color=BLUE, command=self.save_profile).grid(row=len(labels), column=1, pady=10, sticky="e")
        ctk.CTkButton(form, text="新增游戏卡带", fg_color=LIGHT_BLUE, command=self.add_game).grid(row=len(labels), column=0, pady=10, sticky="w")

    def refresh(self) -> None:
        games = self.workspace.list_games()
        labels = [f"{item.display_name} ({item.game_id})" for item in games]
        self.game_menu.configure(values=labels)
        selected = f"{self.profile.display_name} ({self.profile.game_id})"
        self.game_menu.set(selected)
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
            entry.insert(0, getattr(self.profile, key))
            if key == "appinfo_name":
                entry.configure(state="disabled")
        if hasattr(self, "local_output_list"):
            self._fill_local_outputs()
            self._show_remote_message("点击“刷新远程”读取当前游戏的 Release")

    def _fill_resources(self, parent, resources: tuple[Path, ...], kind: str) -> None:
        for child in parent.winfo_children():
            child.destroy()
        if not resources:
            ctk.CTkLabel(parent, text="暂无资源", text_color=MUTED).pack(pady=24)
            return
        for path in resources:
            row = ctk.CTkFrame(parent, fg_color=CARD, border_width=1, border_color="#E0E0E0", corner_radius=8)
            row.pack(fill="x", padx=4, pady=4)
            ctk.CTkLabel(row, text=path.name, anchor="w", text_color=TEXT).pack(side="left", fill="x", expand=True, padx=12, pady=10)
            ctk.CTkButton(row, text="删除", width=64, fg_color="transparent", border_width=1, border_color=RED, text_color=RED, hover_color="#FFEBEE", command=lambda k=kind, n=path.name: self.remove_resource(k, n)).pack(side="right", padx=8, pady=6)

    def _select_game(self, label: str) -> None:
        game_id = label.rsplit("(", 1)[-1].rstrip(")")
        self.profile = next(item for item in self.workspace.list_games() if item.game_id == game_id)
        self.refresh()

    def _fill_local_outputs(self) -> None:
        for child in self.local_output_list.winfo_children():
            child.destroy()
        target = self.workspace.output_dir / self.profile.game_id
        files = tuple(sorted(path for path in target.iterdir() if path.is_file())) if target.is_dir() else ()
        if not files:
            ctk.CTkLabel(self.local_output_list, text="尚未生成本地发布文件", text_color=MUTED).pack(pady=24)
            return
        for path in files:
            row = ctk.CTkFrame(self.local_output_list, fg_color=CARD, border_width=1, border_color="#E0E0E0", corner_radius=8)
            row.pack(fill="x", padx=4, pady=4)
            ctk.CTkLabel(row, text=path.name, anchor="w", text_color=TEXT).pack(side="left", fill="x", expand=True, padx=10, pady=9)
            ctk.CTkButton(row, text="上传", width=64, fg_color=BLUE, command=lambda value=path: self.upload_remote_file(value)).pack(side="right", padx=7, pady=6)

    def _show_remote_message(self, message: str) -> None:
        for child in self.remote_asset_list.winfo_children():
            child.destroy()
        ctk.CTkLabel(self.remote_asset_list, text=message, text_color=MUTED).pack(pady=24)

    def _fill_remote_assets(self, assets: tuple[RemoteAsset, ...]) -> None:
        for child in self.remote_asset_list.winfo_children():
            child.destroy()
        if not assets:
            ctk.CTkLabel(self.remote_asset_list, text="当前 Release 暂无附件", text_color=MUTED).pack(pady=24)
            return
        for asset in sorted(assets, key=lambda item: item.name.casefold()):
            row = ctk.CTkFrame(self.remote_asset_list, fg_color=CARD, border_width=1, border_color="#E0E0E0", corner_radius=8)
            row.pack(fill="x", padx=4, pady=4)
            text = asset.name + (f"  ·  {asset.display_size}" if asset.display_size else "")
            ctk.CTkLabel(row, text=text, anchor="w", text_color=TEXT).pack(side="left", fill="x", expand=True, padx=10, pady=9)
            ctk.CTkButton(row, text="删除", width=64, fg_color="transparent", border_width=1, border_color=RED, text_color=RED, hover_color="#FFEBEE", command=lambda value=asset: self.delete_remote_resource(value)).pack(side="right", padx=7, pady=6)

    def import_dlc(self) -> None:
        path = filedialog.askdirectory(title="选择 DLC 文件夹")
        if not path:
            return
        source = Path(path)
        profile = self.profile
        collection = self.workspace.is_dlc_collection(profile, source)
        interrupted = (
            self.workspace.interrupted_collection_import(profile, source)
            if collection else ()
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
        wrapped = self.workspace.wrapped_collection_import(profile, source) if collection else None
        if wrapped is not None:
            confirmed = messagebox.askyesno(
                "修正旧版误导入",
                f"检测到之前把整个 DLC 根目录导入成了 {wrapped.name}。\n\n"
                "是否直接把现有副本中的一级子目录拆分并分别编号？\n"
                "这是同一磁盘内的快速移动，不会重新复制，也不会删除原始 DLC 目录。",
            )
            if not confirmed:
                return
        self.dlc_import_button.configure(state="disabled", text="准备中…")
        self.dlc_clear_button.configure(state="disabled")
        self.game_menu.configure(state="disabled")

        def progress(index: int, total: int, name: str) -> None:
            self.after(
                0,
                lambda: self.dlc_import_button.configure(
                    text=f"{index}/{total} {name[:10]}"
                ),
            )

        def work() -> None:
            try:
                if reset_interrupted:
                    self.after(
                        0,
                        lambda: self.dlc_import_button.configure(text="清理上次失败记录…"),
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
                self.after(0, lambda: self._import_dlc_done(profile, result))
            except (WorkspaceError, OSError) as error:
                message = str(error)
                self.after(0, lambda: self._import_dlc_failed(message))

        threading.Thread(target=work, daemon=True).start()

    def _import_dlc_done(self, profile: GameProfile, imported: tuple[Path, ...]) -> None:
        self.dlc_import_button.configure(state="normal", text="导入")
        self.dlc_clear_button.configure(state="normal")
        self.game_menu.configure(state="normal")
        if self.profile.game_id == profile.game_id:
            self.refresh()
        messagebox.showinfo("导入完成", f"已导入 {len(imported)} 个 DLC 文件夹")

    def _import_dlc_failed(self, message: str) -> None:
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
            self._run_action(lambda: self.workspace.import_patch(self.profile, Path(path)), "补丁已导入")

    def remove_resource(self, kind: str, name: str) -> None:
        if not messagebox.askyesno("确认删除", f"从发布工作区删除 {name}？\n此操作不会删除 GitLink 上已经发布的附件。"):
            return
        self._run_action(lambda: self.workspace.remove_source(self.profile, kind, name), "资源已删除")

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
        import_button = self.dlc_import_button if kind == "dlc" else self.patch_import_button
        clear_button = self.dlc_clear_button if kind == "dlc" else self.patch_clear_button
        import_button.configure(state="disabled")
        clear_button.configure(state="disabled", text="正在清空…")
        self.game_menu.configure(state="disabled")
        profile = self.profile

        def work() -> None:
            try:
                count = self.workspace.clear_sources(profile, kind)
                self.after(
                    0,
                    lambda: self._clear_local_resources_done(
                        profile, label, count, import_button, clear_button
                    ),
                )
            except (WorkspaceError, OSError) as error:
                message = str(error)
                self.after(
                    0,
                    lambda: self._clear_local_resources_failed(
                        message, import_button, clear_button
                    ),
                )

        threading.Thread(target=work, daemon=True).start()

    def _clear_local_resources_done(
        self, profile: GameProfile, label: str, count: int, import_button, clear_button
    ) -> None:
        import_button.configure(state="normal")
        clear_button.configure(state="normal", text="清空全部")
        self.game_menu.configure(state="normal")
        if self.profile.game_id == profile.game_id:
            self.refresh()
        messagebox.showinfo("清理完成", f"已删除 {count} 项本地{label}")

    def _clear_local_resources_failed(self, message: str, import_button, clear_button) -> None:
        import_button.configure(state="normal")
        clear_button.configure(state="normal", text="清空全部")
        self.game_menu.configure(state="normal")
        messagebox.showerror("清理失败", message)

    def save_profile(self) -> None:
        try:
            values = {key: entry.get().strip() for key, entry in self.profile_entries.items()}
            for key, labels in PROFILE_OPTION_LABELS.items():
                displayed = values[key]
                values[key] = next(
                    (stored for stored, label in labels.items() if label == displayed),
                    displayed,
                )
            values["appinfo_name"] = f"{values['game_id']}_appinfo.json"
            profile = GameProfile(**values)
            if profile.game_id != self.profile.game_id:
                raise WorkspaceError("已创建游戏的 ID 不允许直接修改；请新增游戏")
            self.workspace.save_game(profile)
            self.profile = profile
            self.refresh()
            messagebox.showinfo("保存成功", "游戏卡带配置已保存")
        except (WorkspaceError, OSError) as error:
            messagebox.showerror("保存失败", str(error))

    def add_game(self) -> None:
        game_id = simpledialog.askstring("新增游戏卡带", "输入游戏 ID（如 crusader_kings_3）：", parent=self)
        if not game_id:
            return
        display = simpledialog.askstring("新增游戏卡带", "输入显示名称：", parent=self) or game_id
        steam_app_id = simpledialog.askstring("新增游戏卡带", "输入 Steam App ID：", parent=self) or ""
        normalized_id = game_id.strip().lower()
        profile = GameProfile.create(normalized_id, display.strip(), steam_app_id.strip())
        try:
            if any(item.game_id == profile.game_id for item in self.workspace.list_games()):
                raise WorkspaceError("该游戏已经存在")
            self.workspace.save_game(profile)
            self.profile = profile
            self.refresh()
        except (WorkspaceError, OSError) as error:
            messagebox.showerror("新增失败", str(error))

    def build_all(self) -> None:
        self.build_button.configure(state="disabled", text="正在构建…")
        def work() -> None:
            try:
                records = self.workspace.build(self.profile)
                files = self.workspace.publish_files(self.profile)
                size = sum(path.stat().st_size for path in files)
                self.after(0, lambda: self._build_done(len(records), len(files), size))
            except (WorkspaceError, OSError) as error:
                message = str(error)
                self.after(0, lambda value=message: self._build_failed(value))
        threading.Thread(target=work, daemon=True).start()

    def _build_done(self, resources: int, files: int, size: int) -> None:
        self.build_button.configure(state="normal", text="生成全部发布文件")
        self.build_summary.configure(text=f"{resources} 个资源 · {files} 个文件 · {size / 1024 / 1024:.1f} MiB")
        self._log(f"本地构建完成：{self.profile.game_id}，共 {files} 个发布文件。")
        self._fill_local_outputs()

    def _build_failed(self, message: str) -> None:
        self.build_button.configure(state="normal", text="生成全部发布文件")
        messagebox.showerror("构建失败", message)

    def refresh_steam_data(self) -> None:
        self.steam_button.configure(state="disabled", text="正在查询…")
        profile = self.profile
        def work() -> None:
            try:
                appinfo = self.workspace.refresh_appinfo(profile)
                self.after(0, lambda: self._steam_refresh_done(appinfo.name, len(appinfo.dlcs)))
            except (WorkspaceError, OSError) as error:
                message = str(error)
                self.after(0, lambda value=message: self._steam_refresh_failed(value))
        threading.Thread(target=work, daemon=True).start()

    def _steam_refresh_done(self, name: str, count: int) -> None:
        self.steam_button.configure(state="normal", text="刷新 Steam 数据")
        self._log(f"Steam 数据已更新：{name}，{count} 个 DLC。")
        messagebox.showinfo("更新完成", f"已生成 Steam AppInfo，共 {count} 个 DLC。")

    def _steam_refresh_failed(self, message: str) -> None:
        self.steam_button.configure(state="normal", text="刷新 Steam 数据")
        messagebox.showerror("Steam 数据更新失败", message)

    def refresh_remote_resources(self) -> None:
        if not self._begin_remote_operation("正在读取远程资源…"):
            return
        try:
            manager, profile = self._remote_manager()
        except GitLinkError as error:
            self._remote_failed(str(error))
            return
        def work() -> None:
            try:
                release = manager.get_release(profile.release_tag)
                self.after(0, lambda: self._remote_loaded(profile, release))
            except (GitLinkError, OSError) as error:
                message = str(error)
                self.after(0, lambda value=message: self._remote_failed(value))
        threading.Thread(target=work, daemon=True).start()

    def choose_remote_upload(self) -> None:
        initial = self.workspace.output_dir / self.profile.game_id
        path = filedialog.askopenfilename(title="选择要上传到当前 Release 的文件", initialdir=initial if initial.is_dir() else None)
        if path:
            self.upload_remote_file(Path(path))

    def upload_remote_file(self, path: Path) -> None:
        if not messagebox.askyesno("确认上传", f"上传 {path.name} 到 {self.profile.display_name} 的 {self.profile.release_tag} Release？\n\n存在同名附件时将安全替换。"):
            return
        if not self._begin_remote_operation(f"正在上传 {path.name}…"):
            return
        try:
            manager, profile = self._remote_manager()
        except GitLinkError as error:
            self._remote_failed(str(error))
            return
        def work() -> None:
            try:
                result = manager.upload_file(profile, path)
                release = manager.get_release(profile.release_tag)
                self.after(0, lambda: self._remote_mutation_done(profile, result.action, result.asset.name, result.warnings, release))
            except (GitLinkError, OSError) as error:
                message = str(error)
                self.after(0, lambda value=message: self._remote_failed(value))
        threading.Thread(target=work, daemon=True).start()

    def delete_remote_resource(self, asset: RemoteAsset) -> None:
        if not messagebox.askyesno("确认删除远程资源", f"从 {self.profile.release_tag} Release 永久删除：\n{asset.name}\n\n此操作无法撤销，是否继续？"):
            return
        if not self._begin_remote_operation(f"正在删除 {asset.name}…"):
            return
        try:
            manager, profile = self._remote_manager()
        except GitLinkError as error:
            self._remote_failed(str(error))
            return
        def work() -> None:
            try:
                result = manager.delete_asset(profile, asset.asset_id)
                release = manager.get_release(profile.release_tag)
                self.after(0, lambda: self._remote_mutation_done(profile, result.action, result.asset.name, result.warnings, release))
            except (GitLinkError, OSError) as error:
                message = str(error)
                self.after(0, lambda value=message: self._remote_failed(value))
        threading.Thread(target=work, daemon=True).start()

    def _remote_manager(self) -> tuple[RemoteResourceManager, GameProfile]:
        repository = self._repository()
        token = self.token_entry.get().strip() or None
        return RemoteResourceManager(GitLinkAttachmentClient(token), repository), self.profile

    def _begin_remote_operation(self, message: str) -> bool:
        if self._remote_operation_active:
            messagebox.showinfo("远程操作进行中", "请等待当前远程操作完成")
            return False
        self._remote_operation_active = True
        self.remote_refresh_button.configure(state="disabled")
        self.remote_status.configure(text=message)
        return True

    def _remote_loaded(self, profile: GameProfile, release: RemoteRelease | None) -> None:
        self._remote_operation_active = False
        self.remote_refresh_button.configure(state="normal")
        if profile.game_id != self.profile.game_id:
            return
        if release is None:
            self.remote_status.configure(text=f"{profile.release_tag} · Release 尚未创建")
            self._fill_remote_assets(())
            return
        self.remote_status.configure(text=f"{release.tag} · {len(release.assets)} 个远程附件")
        self._fill_remote_assets(release.assets)

    def _remote_mutation_done(self, profile: GameProfile, action: str, name: str, warnings: tuple[str, ...], release: RemoteRelease | None) -> None:
        self._remote_operation_active = False
        self.remote_refresh_button.configure(state="normal")
        self._log(f"远程资源{action}完成：{name}")
        if profile.game_id == self.profile.game_id:
            if release is None:
                self.remote_status.configure(text=f"{profile.release_tag} · Release 尚未创建")
                self._fill_remote_assets(())
            else:
                self.remote_status.configure(text=f"{release.tag} · {len(release.assets)} 个远程附件")
                self._fill_remote_assets(release.assets)
        if warnings:
            messagebox.showwarning("操作完成但有警告", "\n".join(warnings))
        else:
            messagebox.showinfo("远程操作完成", f"已{action}：{name}")

    def _remote_failed(self, message: str) -> None:
        self._remote_operation_active = False
        self.remote_refresh_button.configure(state="normal")
        self.remote_status.configure(text="远程操作失败")
        self._log(f"远程操作失败：{message}")
        messagebox.showerror("远程操作失败", message)

    def check_gitlink(self) -> None:
        try:
            manager, profile = self._remote_manager()
        except GitLinkError as error:
            messagebox.showerror("GitLink 检查失败", str(error))
            return
        self.check_gitlink_button.configure(state="disabled", text="正在检查…")
        repo = manager.repository

        def work() -> None:
            try:
                release = manager.get_release(profile.release_tag)
                self.after(0, lambda: self._gitlink_check_done(repo, profile, release))
            except (GitLinkError, OSError) as error:
                message = str(error)
                self.after(0, lambda value=message: self._gitlink_check_failed(value))

        threading.Thread(target=work, daemon=True).start()

    def _gitlink_check_done(self, repo: GitLinkRepository, profile: GameProfile, release: RemoteRelease | None) -> None:
        self.check_gitlink_button.configure(state="normal", text="检查登录与仓库")
        repository_url = f"https://www.gitlink.org.cn/{repo.owner}/{repo.name}"
        if release is None:
            detail = f"仓库可以访问；当前游戏的 {profile.release_tag} Release 尚未创建。首次上传时会自动创建。"
        else:
            detail = f"仓库可以访问；{release.tag} Release 当前有 {len(release.assets)} 个附件。"
        self._log(f"GitLink API 检查成功：{repository_url}；{detail}")
        messagebox.showinfo("GitLink 检查完成", detail)

    def _gitlink_check_failed(self, message: str) -> None:
        self.check_gitlink_button.configure(state="normal", text="检查登录与仓库")
        self._log(f"GitLink API 检查失败：{message}")
        if "404" in message or "不存在" in message or "已被删除" in message:
            guidance = "当前配置的仓库不存在。请先在 GitLink 网页创建仓库，或者安装 gitlink-cli 后使用“创建新仓库”。"
        else:
            guidance = "请检查私有令牌、仓库所有者、仓库名称和网络连接。该检查不需要安装 gitlink-cli。"
        messagebox.showerror("GitLink 检查失败", f"{message}\n\n{guidance}")

    def create_repository(self) -> None:
        try:
            repo = self._repository()
        except GitLinkError as error:
            messagebox.showerror("创建失败", str(error))
            return
        if not messagebox.askyesno("创建新仓库", f"确认创建公开资源仓库 {repo.owner}/{repo.name}？"):
            return
        try:
            self.gitlink.create_repository(repo, "SignRiver DLC Hub public release assets")
            self._log(f"新仓库创建完成：https://www.gitlink.org.cn/{repo.owner}/{repo.name}")
        except GitLinkError as error:
            messagebox.showerror("创建失败", str(error))

    def publish_release(self) -> None:
        try:
            assets = self.workspace.publish_assets(self.profile)
            repo = self._repository()
            previous_state = self.workspace.load_publish_state(self.profile, repo.owner, repo.name)
        except WorkspaceError as error:
            messagebox.showerror("无法发布", str(error))
            return
        except GitLinkError as error:
            messagebox.showerror("无法发布", str(error))
            return
        if not messagebox.askyesno("确认增量发布", f"同步 {len(assets)} 个文件到\n{repo.owner}/{repo.name} · {self.profile.release_tag}\n\n未变化文件将复用远程附件；AppInfo 每次强制更新。是否继续？"):
            return
        token = self.token_entry.get().strip() or None
        self.publish_button.configure(state="disabled", text="正在发布…")
        self._log(f"开始增量发布 {self.profile.display_name}：共 {len(assets)} 个文件。")
        profile = self.profile
        threading.Thread(target=self._publish_worker, args=(repo, profile, assets, previous_state, token), daemon=True).start()

    def _publish_worker(self, repo: GitLinkRepository, profile: GameProfile, assets: tuple[PublishAsset, ...], previous_state: dict[str, object], token: str | None) -> None:
        try:
            client = GitLinkAttachmentClient(token)
            manager = RemoteResourceManager(client, repo)

            def progress(index: int, total: int, name: str, stage: str) -> None:
                self.after(0, lambda i=index, count=total, value=name, action=stage: self._log(f"[{i}/{count}] {action} {value}"))

            result = manager.sync_release(
                profile,
                assets,
                previous_state,
                force_upload=frozenset({profile.appinfo_name}),
                progress=progress,
            )
            warnings = result.warnings
            try:
                self.workspace.save_publish_state(profile, result.state)
            except OSError as error:
                warnings = (*warnings, f"Release 已更新，但本地发布状态保存失败；下次可能重新上传：{error}")
            self.after(0, lambda value=result, notes=warnings: self._publish_done(repo, profile, value.action, value.uploaded, value.reused, value.removed, notes))
        except (GitLinkError, OSError) as error:
            message = str(error)
            self.after(0, lambda value=message: self._publish_failed(value))

    def _publish_done(self, repo: GitLinkRepository, profile: GameProfile, action: str, uploaded: int, reused: int, removed: int, warnings: tuple[str, ...]) -> None:
        self.publish_button.configure(state="normal", text="发布到 Release")
        if not self.settings.token:
            self.token_entry.delete(0, "end")
        summary = f"Release {action}完成：上传 {uploaded}，复用 {reused}，清理旧附件 {removed}。"
        self._log(summary)
        if warnings:
            messagebox.showwarning("发布完成但有警告", f"{summary}\n\n" + "\n".join(warnings))
        else:
            messagebox.showinfo("发布完成", f"资源已发布到 {repo.owner}/{repo.name} 的 {profile.release_tag} Release。\n\n{summary}")

    def _publish_failed(self, message: str) -> None:
        self.publish_button.configure(state="normal", text="发布到 Release")
        self._log(f"发布失败：{message}")
        messagebox.showerror("发布失败", message)

    def _repository(self) -> GitLinkRepository:
        owner = self.owner_entry.get().strip()
        name = self.repo_entry.get().strip()
        if not owner or not name:
            raise GitLinkError("请填写 GitLink 所有者和仓库名")
        return GitLinkRepository(owner, name)

    @staticmethod
    def _display_api_result(value: dict[str, object]) -> str:
        data = value.get("data")
        if isinstance(data, dict):
            for key in ("login", "username", "name"):
                if data.get(key):
                    return str(data[key])
        return "已认证用户"

    def _run_action(self, command, success: str) -> None:
        try:
            command()
            self.refresh()
            messagebox.showinfo("完成", success)
        except (WorkspaceError, OSError) as error:
            messagebox.showerror("操作失败", str(error))

    def _log(self, message: str) -> None:
        if not hasattr(self, "log"):
            return
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_dlc_folder(self) -> None:
        self._open(self.workspace.game_dir(self.profile.game_id) / "dlc")

    def open_patch_folder(self) -> None:
        self._open(self.workspace.game_dir(self.profile.game_id) / "patches")

    def open_output_folder(self) -> None:
        path = self.workspace.output_dir / self.profile.game_id
        path.mkdir(parents=True, exist_ok=True)
        self._open(path)

    @staticmethod
    def _open(path: Path) -> None:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
