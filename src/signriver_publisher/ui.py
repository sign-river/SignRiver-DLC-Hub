from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import TclError, filedialog, messagebox, simpledialog

import customtkinter as ctk

from .announcements import AnnouncementDraft, AnnouncementValidationError
from .acceptance import (
    FAILED,
    PASSED,
    SKIPPED,
    AcceptanceCase,
    AcceptanceError,
    AcceptanceFingerprint,
    AcceptanceManager,
    AcceptancePaths,
    AcceptanceSession,
    PreparationPreview,
)
from .github import (
    GitHubPublisherError,
    GitHubReleaseClient,
    GitHubRepository,
    GitHubUploadPaused,
)
from .gitlink import (
    GitLinkAttachmentClient,
    GitLinkCli,
    GitLinkError,
    GitLinkRepository,
    UploadControl,
    UploadPaused,
)
from .models import GameProfile, PublishAsset
from .remote import RemoteAsset, RemoteBulkDeleteResult, RemoteRelease, RemoteResourceManager
from .settings import PublisherSettings, PublisherSettingsError
from .updates import (
    MODULE_ARCHIVE_RELEASE_TAG,
    UPDATE_MANIFEST_ASSET,
    UPDATE_RELEASE_TAG,
    UpdateReleaseDraft,
    inspect_module_archive,
    inspect_update_package,
    release_asset_url,
    write_update_manifest,
)
from .workspace import PublisherWorkspace, WorkspaceError

LOGGER = logging.getLogger(__name__)

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


class PublisherApplication(ctk.CTk):
    def __init__(
        self,
        workspace: PublisherWorkspace,
        *,
        settings: PublisherSettings | None = None,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.settings = settings or PublisherSettings()
        self.settings_path = settings_path
        self.profile = workspace.initialize()
        self.acceptance = AcceptanceManager(workspace)
        self._acceptance_generation = 0
        self._acceptance_fingerprint: AcceptanceFingerprint | None = None
        self._acceptance_session: AcceptanceSession | None = None
        self._acceptance_paths = AcceptancePaths(None, None)
        self._acceptance_cases: tuple[AcceptanceCase, ...] = ()
        self._acceptance_case_id = ""
        self._acceptance_case_buttons: dict[str, ctk.CTkButton] = {}
        self._acceptance_variant_by_label: dict[str, str] = {}
        self.gitlink = GitLinkCli()
        self.repository = GitLinkRepository(
            self.settings.owner, self.settings.repository
        )
        self._remote_operation_active = False
        self._build_operation_active = False
        self._build_progress_events = SimpleQueue()
        # Tk must only be touched by the main thread.  Background build,
        # network, and fingerprint workers post plain callbacks here; one
        # main-loop pump applies them in bounded batches.
        self._ui_events = SimpleQueue()
        self._ui_pump_running = True
        self._pending_upload_progress: tuple[int, int, str, int, int] | None = None
        self._pending_upload_progress_lock = threading.Lock()
        # Main-thread owned registry for background operations that mutate the
        # workspace or a remote Release.  Keeping the window/event pump alive
        # until these finish prevents daemon workers from being terminated in
        # the middle of a ZIP, state-file write, or attachment upload.
        self._background_mutations: dict[str, str] = {}
        self._upload_control: UploadControl | None = None
        self._github_publish_resume_context = None
        self._publish_resume_context: (
            tuple[GitLinkRepository, GameProfile, tuple[PublishAsset, ...], str | None]
            | None
        ) = None
        self._active_publish_scope = "game"
        self._upload_control = UploadControl()
        self._upload_sample: tuple[str, int, float] | None = None
        self._upload_speed = 0.0
        self._publish_advanced_visible = False
        self._current_remote_release: RemoteRelease | None = None
        self.title("SignRiver 发布管理器")
        self.geometry("1240x800")
        self.minsize(980, 660)
        self.configure(fg_color=PAGE)
        ctk.set_appearance_mode("light")
        self._build_ui()
        self._sync_publish_target_controls()
        self.protocol("WM_DELETE_WINDOW", self._close_publisher)
        self.after(40, self._drain_ui_events)
        self.refresh()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color=BRAND, corner_radius=0, height=116)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="SignRiver 发布管理器",
            font=("Microsoft YaHei UI", 28, "bold"),
            text_color="white",
        ).grid(row=0, column=0, padx=(28, 20), pady=(22, 4), sticky="w")
        ctk.CTkLabel(
            header,
            text="服务端制卡机 · 每张游戏卡带独立构建与发布",
            font=("Microsoft YaHei UI", 14),
            text_color="#EAF4FF",
        ).grid(row=1, column=0, padx=30, pady=(0, 20), sticky="w")
        self.game_menu = ctk.CTkOptionMenu(
            header,
            command=self._select_game,
            width=220,
            fg_color=LIGHT_BLUE,
            button_color=BLUE,
        )
        self.game_menu.grid(row=0, column=2, rowspan=2, padx=28)

        self.tabs = ctk.CTkTabview(
            self,
            fg_color=PAGE,
            segmented_button_selected_color=BLUE,
            segmented_button_selected_hover_color=BRAND,
        )
        self.tabs.grid(row=1, column=0, padx=22, pady=18, sticky="nsew")
        self.sources_tab = self.tabs.add("资源管理")
        self.build_tab = self.tabs.add("构建与发布")
        self.remote_tab = self.tabs.add("远程资源")
        self.games_tab = self.tabs.add("卡带配置")
        self.acceptance_tab = self.tabs.add("发布验收")
        self.cartridges_tab = self.tabs.add("卡带管理")
        self._build_sources_tab()
        self._build_publish_tab()
        self._build_remote_tab()
        self._build_cartridge_management_tab()
        self._build_acceptance_tab()
        self._build_games_tab()

    def _post_ui(self, callback) -> None:
        """Transfer work to Tk's owning thread without calling Tk directly."""
        if self._ui_pump_running:
            self._ui_events.put(callback)

    def _begin_background_mutation(
        self, key: str, label: str, *, resume: bool = False
    ) -> bool:
        """Acquire the publisher's single-writer reservation on the Tk thread.

        The publisher has several independent tabs, but their write operations
        share the same workspace and Release.  Serializing them here prevents a
        build from racing a source edit and prevents two Release updates from
        replacing each other's attachment list.  A paused publish retains its
        reservation and may reacquire only that same key when it resumes.
        """
        registered = set(self._background_mutations)
        if resume and registered == {key}:
            return True
        active = self._active_background_mutations()
        if active:
            detail = "\n".join(f"• {value}" for value in active)
            messagebox.showinfo(
                "操作正在进行",
                f"请等待当前操作完成后再试：\n{detail}",
            )
            return False
        self._background_mutations[key] = label
        return True

    def _end_background_mutation(self, key: str) -> None:
        """Mark a registered background write operation as terminal."""
        self._background_mutations.pop(key, None)

    def _active_background_mutations(self) -> tuple[str, ...]:
        """Return stable, de-duplicated descriptions for close protection."""
        active = dict(self._background_mutations)
        # Retain defensive fallbacks for operations started by older call
        # paths or a future path that sets the established state flags first.
        if self._build_operation_active:
            active.setdefault("build", "正在构建发布文件")
        if self._remote_operation_active:
            active.setdefault("remote", "正在处理 GitLink 远程资源")
        if self._upload_control is not None:
            active.setdefault("publish", "正在上传 Release")
        return tuple(dict.fromkeys(active.values()))

    def _queue_upload_progress(
        self, index: int, total: int, name: str, sent: int, size: int
    ) -> None:
        """Keep only the newest high-frequency upload progress sample."""
        if not self._ui_pump_running:
            return
        with self._pending_upload_progress_lock:
            if not self._ui_pump_running:
                return
            self._pending_upload_progress = (index, total, name, sent, size)

    def _drain_ui_events(self) -> None:
        if not self._ui_pump_running:
            return
        for _ in range(250):
            try:
                callback = self._ui_events.get_nowait()
            except Empty:
                break
            try:
                callback()
            except Exception:
                # One stale callback must not stop delivery of later build or
                # upload events.  This also covers a window destroyed between
                # posting and delivery.
                LOGGER.exception("Unable to apply publisher UI event")
        with self._pending_upload_progress_lock:
            progress = self._pending_upload_progress
            self._pending_upload_progress = None
        if progress is not None:
            self._show_upload_progress(*progress)
        if self._ui_pump_running:
            try:
                self.after(40, self._drain_ui_events)
            except TclError:
                self._ui_pump_running = False

    def _card(self, parent, row: int, title: str) -> ctk.CTkFrame:
        parent.grid_columnconfigure(0, weight=1)
        frame = ctk.CTkFrame(
            parent,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        frame.grid(row=row, column=0, padx=8, pady=8, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame, text=title, font=("Microsoft YaHei UI", 20, "bold"), text_color=BLUE
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")
        return frame

    def _build_sources_tab(self) -> None:
        self.sources_tab.grid_rowconfigure(0, weight=1)
        self.sources_tab.grid_columnconfigure((0, 1), weight=1)
        self.dlc_card = ctk.CTkFrame(
            self.sources_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        self.dlc_card.grid(row=0, column=0, padx=(8, 5), pady=8, sticky="nsew")
        self.patch_card = ctk.CTkFrame(
            self.sources_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
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

    def _build_publish_tab(self) -> None:
        self.build_tab.grid_rowconfigure(1, weight=1)
        build_card = self._card(self.build_tab, 0, "本地构建")
        actions = ctk.CTkFrame(build_card, fg_color="transparent")
        actions.grid(row=1, column=0, padx=18, pady=(2, 16), sticky="ew")
        self.build_button = ctk.CTkButton(
            actions,
            text="生成全部发布文件",
            width=180,
            fg_color=BLUE,
            command=self.build_all,
        )
        self.build_button.pack(side="left", padx=4)
        self.steam_button = ctk.CTkButton(
            actions,
            text="刷新 Steam 数据",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.refresh_steam_data,
        )
        self.steam_button.pack(side="left", padx=4)
        ctk.CTkButton(
            actions,
            text="打开输出目录",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.open_output_folder,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            actions,
            text="打开卡带管理",
            width=180,
            fg_color=LIGHT_BLUE,
            command=lambda: self.tabs.set("卡带管理"),
        ).pack(side="left", padx=4)
        self.build_summary = ctk.CTkLabel(actions, text="尚未构建", text_color=MUTED)
        self.build_summary.pack(side="left", padx=18)
        self.freshness_summary = ctk.CTkLabel(
            build_card,
            text="资源提交时间：切换卡带或构建后自动读取本地包修改时间",
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=980,
        )
        self.freshness_summary.grid(row=2, column=0, padx=22, pady=(0, 14), sticky="ew")

        remote = self._card(self.build_tab, 1, "发布控制台")
        remote.grid_rowconfigure(6, weight=1)
        settings = ctk.CTkFrame(remote, fg_color="transparent")
        settings.grid(row=1, column=0, padx=20, sticky="ew")
        settings.grid_columnconfigure((1, 3, 5), weight=1)
        ctk.CTkLabel(settings, text="发布目标").grid(row=0, column=0, padx=(0, 8))
        self.publish_target_menu = ctk.CTkOptionMenu(
            settings,
            values=["GitLink", "GitHub"],
            fg_color=LIGHT_BLUE,
            button_color=BLUE,
            command=self._on_publish_target_changed,
        )
        self.publish_target_menu.set(
            "GitHub" if self.settings.publish_target == "github" else "GitLink"
        )
        self.publish_target_menu.grid(row=0, column=1, padx=(0, 18), sticky="ew")
        ctk.CTkLabel(settings, text="所有者").grid(row=0, column=2, padx=(0, 8))
        self.owner_entry = ctk.CTkEntry(settings, border_color="#BDBDBD")
        self.owner_entry.insert(0, self.settings.active_owner)
        self.owner_entry.grid(row=0, column=3, padx=(0, 18), sticky="ew")
        ctk.CTkLabel(settings, text="仓库").grid(row=0, column=4, padx=(0, 8))
        self.repo_entry = ctk.CTkEntry(settings, border_color="#BDBDBD")
        self.repo_entry.insert(0, self.settings.active_repository)
        self.repo_entry.grid(row=0, column=5, padx=(0, 10), sticky="ew")
        regions = ctk.CTkFrame(remote, fg_color="transparent")
        regions.grid(row=2, column=0, padx=18, pady=12, sticky="ew")
        regions.grid_columnconfigure((0, 1, 2), weight=1, uniform="publish")
        region_specs = (
            (
                "发布当前游戏",
                "当前卡带的 DLC、补丁、AppInfo 与 catalog.json",
            ),
            (
                "发布客户端",
                "完整程序更新包与双源更新清单",
            ),
            (
                "维护基础设施",
                "历史模块归档，以及卡带与公告入口",
            ),
        )
        region_frames = []
        for column, (title, hint) in enumerate(region_specs):
            frame = ctk.CTkFrame(
                regions, fg_color="#F7F9FC", border_width=1,
                border_color="#D8DEE6", corner_radius=10,
            )
            frame.grid(
                row=0, column=column, padx=5, pady=0, sticky="nsew"
            )
            ctk.CTkLabel(
                frame, text=title, font=("Microsoft YaHei UI", 16, "bold"),
                text_color=BLUE, anchor="w",
            ).pack(fill="x", padx=14, pady=(12, 2))
            ctk.CTkLabel(
                frame, text=hint, text_color=MUTED, anchor="w",
                justify="left", wraplength=300,
            ).pack(fill="x", padx=14, pady=(0, 8))
            region_frames.append(frame)

        game_region, client_region, infrastructure_region = region_frames
        advanced = ctk.CTkFrame(
            remote, fg_color="#F7F9FC", border_width=1,
            border_color="#D8DEE6", corner_radius=10,
        )
        self.publish_advanced_frame = advanced
        self.check_gitlink_button = ctk.CTkButton(
            advanced,
            text="检查仓库",
            width=160,
            fg_color=LIGHT_BLUE,
            command=self.check_gitlink,
        )
        self.create_repository_button = ctk.CTkButton(
            advanced,
            text="创建新仓库",
            width=140,
            fg_color=LIGHT_BLUE,
            command=self.create_repository,
        )
        self.adopt_remote_button = ctk.CTkButton(
            advanced,
            text="采用远程附件",
            width=145,
            fg_color=LIGHT_BLUE,
            command=self.adopt_remote_assets,
        )
        self.publish_button = ctk.CTkButton(
            game_region,
            text="发布当前游戏到所选源",
            width=210,
            fg_color=BLUE,
            command=self.publish_release,
        )
        self.publish_button.pack(fill="x", padx=14, pady=(4, 14))
        self.publish_update_button = ctk.CTkButton(
            advanced,
            text="单源发布程序更新",
            width=150,
            fg_color=BLUE,
            command=self.publish_update_release,
        )
        self.publish_update_mirror_button = ctk.CTkButton(
            client_region,
            text="双源镜像发布更新",
            width=170,
            fg_color=LIGHT_BLUE,
            command=lambda: self.publish_update_release(mirror=True),
        )
        self.publish_update_mirror_button.pack(fill="x", padx=14, pady=(4, 14))
        self.publish_module_archive_button = ctk.CTkButton(
            advanced,
            text="单源发布模块归档",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.publish_module_archive,
        )
        self.publish_hub_single_button = ctk.CTkButton(
            advanced,
            text="单源发布卡带中心",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.publish_cartridge_hub,
        )
        self.publish_module_archive_mirror_button = ctk.CTkButton(
            infrastructure_region,
            text="双源镜像归档",
            width=150,
            fg_color=LIGHT_BLUE,
            command=lambda: self.publish_module_archive(mirror=True),
        )
        self.publish_module_archive_mirror_button.pack(
            fill="x", padx=14, pady=(4, 6)
        )
        ctk.CTkButton(
            infrastructure_region, text="打开卡带管理",
            fg_color=LIGHT_BLUE,
            command=lambda: self.tabs.set("卡带管理"),
        ).pack(fill="x", padx=14, pady=(0, 14))

        self.publish_advanced_button = ctk.CTkButton(
            remote, text="展开高级操作 ▾", width=160,
            fg_color="transparent", border_width=1,
            border_color="#B8C5D1", text_color=TEXT,
            command=self._toggle_publish_advanced,
        )
        self.publish_advanced_button.grid(
            row=3, column=0, padx=22, pady=(0, 8), sticky="w"
        )
        ctk.CTkLabel(
            advanced,
            text="单源与仓库维护",
            font=("Microsoft YaHei UI", 14, "bold"),
            text_color=TEXT,
        ).pack(side="left", padx=(12, 8), pady=10)
        for button in (
            self.check_gitlink_button,
            self.create_repository_button,
            self.adopt_remote_button,
            self.publish_update_button,
            self.publish_module_archive_button,
            self.publish_hub_single_button,
        ):
            button.pack(side="left", padx=4, pady=10)
        self.token_entry = ctk.CTkEntry(
            advanced,
            width=230,
            show="●",
            placeholder_text="发布令牌",
            border_color="#BDBDBD",
        )
        self.token_entry.pack(side="right", padx=4)
        if self.settings.active_token:
            self.token_entry.insert(0, self.settings.active_token)
        for entry in (self.owner_entry, self.repo_entry, self.token_entry):
            entry.bind("<FocusOut>", lambda _event: self._save_active_settings())
        transfer = ctk.CTkFrame(remote, fg_color="transparent")
        transfer.grid(row=5, column=0, padx=22, pady=(0, 10), sticky="ew")
        transfer.grid_columnconfigure(1, weight=1)
        self.upload_status = ctk.CTkLabel(
            transfer, text="等待发布", width=250, anchor="w", text_color=MUTED
        )
        self.upload_status.grid(row=0, column=0, padx=(0, 12), sticky="w")
        self.upload_progress = ctk.CTkProgressBar(
            transfer, height=14, progress_color=BLUE
        )
        self.upload_progress.grid(row=0, column=1, padx=8, sticky="ew")
        self.upload_progress.set(0)
        self.publish_pause_button = ctk.CTkButton(
            transfer,
            text="暂停发布",
            width=110,
            fg_color=LIGHT_BLUE,
            state="disabled",
            command=self.toggle_publish_pause,
        )
        self.publish_pause_button.grid(row=0, column=2, padx=(12, 0))
        self.log = ctk.CTkTextbox(
            remote,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
            text_color=TEXT,
        )
        self.log.grid(row=6, column=0, padx=20, pady=(0, 18), sticky="nsew")
        self._log("令牌从本地私密配置或输入框读取，不会输出到日志。")

    def _toggle_publish_advanced(self) -> None:
        self._publish_advanced_visible = not self._publish_advanced_visible
        if self._publish_advanced_visible:
            self.publish_advanced_frame.grid(
                row=4, column=0, padx=22, pady=(0, 10), sticky="ew"
            )
            self.publish_advanced_button.configure(text="收起高级操作 ▴")
        else:
            self.publish_advanced_frame.grid_remove()
            self.publish_advanced_button.configure(text="展开高级操作 ▾")

    def _build_remote_tab(self) -> None:
        self.remote_tab.grid_rowconfigure(1, weight=1)
        self.remote_tab.grid_columnconfigure((0, 1), weight=1)
        toolbar = ctk.CTkFrame(
            self.remote_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        toolbar.grid(row=0, column=0, columnspan=2, padx=8, pady=(8, 4), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)
        self.remote_status = ctk.CTkLabel(
            toolbar, text="选择当前游戏后刷新远程 Release", text_color=MUTED, anchor="w"
        )
        self.remote_status.grid(row=0, column=0, padx=18, pady=14, sticky="ew")
        self.remote_refresh_button = ctk.CTkButton(
            toolbar,
            text="刷新远程",
            width=110,
            fg_color=LIGHT_BLUE,
            command=self.refresh_remote_resources,
        )
        self.remote_refresh_button.grid(row=0, column=1, padx=4, pady=10)
        self.remote_delete_all_button = ctk.CTkButton(
            toolbar,
            text="全部删除",
            width=110,
            fg_color="transparent",
            border_width=1,
            border_color=RED,
            text_color=RED,
            hover_color="#FFEBEE",
            state="disabled",
            command=self.delete_all_remote_resources,
        )
        self.remote_delete_all_button.grid(row=0, column=2, padx=4, pady=10)
        ctk.CTkButton(
            toolbar,
            text="选择文件上传",
            width=130,
            fg_color=BLUE,
            command=self.choose_remote_upload,
        ).grid(row=0, column=3, padx=(4, 14), pady=10)

        local_card = ctk.CTkFrame(
            self.remote_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        local_card.grid(row=1, column=0, padx=(8, 5), pady=(4, 8), sticky="nsew")
        remote_card = ctk.CTkFrame(
            self.remote_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        remote_card.grid(row=1, column=1, padx=(5, 8), pady=(4, 8), sticky="nsew")
        for card in (local_card, remote_card):
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            local_card,
            text="本地发布文件",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, padx=18, pady=(14, 6), sticky="w")
        self.remote_asset_title = ctk.CTkLabel(
            remote_card,
            text="GitLink Release 附件",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color=BLUE,
        )
        self.remote_asset_title.grid(row=0, column=0, padx=18, pady=(14, 6), sticky="w")
        self.local_output_list = ctk.CTkScrollableFrame(
            local_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0"
        )
        self.local_output_list.grid(
            row=1, column=0, padx=14, pady=(4, 14), sticky="nsew"
        )
        self.remote_asset_list = ctk.CTkScrollableFrame(
            remote_card, fg_color="#FAFAFA", border_width=1, border_color="#E0E0E0"
        )
        self.remote_asset_list.grid(
            row=1, column=0, padx=14, pady=(4, 14), sticky="nsew"
        )

    def _build_cartridge_management_tab(self) -> None:
        self.cartridges_tab.grid_rowconfigure(1, weight=1)
        self.cartridges_tab.grid_columnconfigure(0, weight=1)

        toolbar = self._card(self.cartridges_tab, 0, "卡带统一管理")
        toolbar.grid_rowconfigure(3, weight=0)
        self.hub_summary = ctk.CTkLabel(
            toolbar,
            text="正在读取卡带…",
            text_color=TEXT,
            anchor="w",
            justify="left",
        )
        self.hub_summary.grid(row=1, column=0, padx=22, pady=(0, 4), sticky="ew")
        self.hub_hint = ctk.CTkLabel(
            toolbar,
            text=(
                "完整主表会统一生成；GitLink 发布时按卡带逐项比较，"
                "只上传新增或发生变化的文档。"
            ),
            text_color=MUTED,
            anchor="w",
        )
        self.hub_hint.grid(row=2, column=0, padx=22, pady=(0, 10), sticky="ew")

        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.grid(row=3, column=0, padx=18, pady=(0, 10), sticky="ew")
        for column in range(5):
            actions.grid_columnconfigure(column, weight=1, uniform="hub_actions")
        self.hub_refresh_button = ctk.CTkButton(
            actions,
            text="刷新卡带",
            fg_color=LIGHT_BLUE,
            command=self.refresh_cartridge_management,
        )
        self.hub_refresh_button.grid(row=0, column=0, padx=4, sticky="ew")
        self.announcement_manage_button = ctk.CTkButton(
            actions,
            text="管理公告",
            fg_color=LIGHT_BLUE,
            command=self.open_announcement_manager,
        )
        self.announcement_manage_button.grid(
            row=0, column=1, padx=4, sticky="ew"
        )
        self.hub_generate_button = ctk.CTkButton(
            actions,
            text="重新生成全部",
            fg_color=LIGHT_BLUE,
            command=self.generate_client_hub,
        )
        self.hub_generate_button.grid(row=0, column=2, padx=4, sticky="ew")
        ctk.CTkButton(
            actions,
            text="打开 hub 目录",
            fg_color=LIGHT_BLUE,
            command=self.open_hub_output_folder,
        ).grid(row=0, column=3, padx=4, sticky="ew")
        self.hub_publish_button = ctk.CTkButton(
            actions,
            text="一键双端发布卡带",
            fg_color=BLUE,
            command=self.publish_cartridge_hub_mirror,
        )
        self.hub_publish_button.grid(row=0, column=4, padx=4, sticky="ew")

        transfer = ctk.CTkFrame(toolbar, fg_color="transparent")
        transfer.grid(row=4, column=0, padx=22, pady=(0, 14), sticky="ew")
        transfer.grid_columnconfigure(1, weight=1)
        self.hub_upload_status = ctk.CTkLabel(
            transfer,
            text="等待发布",
            width=235,
            anchor="w",
            text_color=MUTED,
        )
        self.hub_upload_status.grid(row=0, column=0, padx=(0, 12), sticky="w")
        self.hub_upload_progress = ctk.CTkProgressBar(
            transfer, height=14, progress_color=BLUE
        )
        self.hub_upload_progress.grid(row=0, column=1, padx=8, sticky="ew")
        self.hub_upload_progress.set(0)
        self.hub_publish_pause_button = ctk.CTkButton(
            transfer,
            text="暂停发布",
            width=110,
            fg_color=LIGHT_BLUE,
            state="disabled",
            command=self.toggle_publish_pause,
        )
        self.hub_publish_pause_button.grid(row=0, column=2, padx=(12, 0))

        list_card = self._card(self.cartridges_tab, 1, "全部游戏卡带")
        list_card.grid_rowconfigure(1, weight=1)
        self.cartridge_list = ctk.CTkScrollableFrame(
            list_card,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
        )
        self.cartridge_list.grid(
            row=1, column=0, padx=16, pady=(2, 16), sticky="nsew"
        )

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
            ("原版备份 DLL", "patch_original_backup_name"),
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

    def refresh_cartridge_management(self) -> None:
        profiles = self.workspace.list_games()
        hub_dir = self.workspace.output_dir / "hub"
        for child in self.cartridge_list.winfo_children():
            child.destroy()
        generated = 0
        for profile in profiles:
            document = hub_dir / f"cartridge_{profile.game_id}.json"
            if document.is_file():
                generated += 1
            row = ctk.CTkFrame(
                self.cartridge_list,
                fg_color=CARD,
                border_width=1,
                border_color="#E0E0E0",
                corner_radius=8,
            )
            row.pack(fill="x", padx=4, pady=4)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                row,
                text=profile.display_name,
                width=190,
                anchor="w",
                font=("Microsoft YaHei UI", 14, "bold"),
                text_color=TEXT,
            ).grid(row=0, column=0, padx=(14, 8), pady=10, sticky="w")
            ctk.CTkLabel(
                row,
                text=f"{profile.game_id}  ·  Release {profile.release_tag}",
                anchor="w",
                text_color=MUTED,
            ).grid(row=0, column=1, padx=8, pady=10, sticky="ew")
            ctk.CTkLabel(
                row,
                text="已生成" if document.is_file() else "待生成",
                width=72,
                text_color="#2E7D32" if document.is_file() else MUTED,
            ).grid(row=0, column=2, padx=8, pady=10)
            ctk.CTkButton(
                row,
                text="编辑卡带",
                width=92,
                fg_color=LIGHT_BLUE,
                command=lambda game_id=profile.game_id: self.open_cartridge_config(
                    game_id
                ),
            ).grid(row=0, column=3, padx=(8, 12), pady=7)
        if not profiles:
            ctk.CTkLabel(
                self.cartridge_list, text="尚未配置游戏卡带", text_color=MUTED
            ).pack(pady=24)
        target = (
            f"{self.owner_entry.get().strip()}/{self.repo_entry.get().strip()}"
            if hasattr(self, "owner_entry")
            else "尚未配置仓库"
        )
        self.hub_summary.configure(
            text=(
                f"共 {len(profiles)} 张卡带 · 本地已生成 {generated} 张 · "
                f"公告 {self.workspace.announcement_status()} · "
                f"发布目标 {target} / hub"
            )
        )
        self._schedule_scrollable_reset(self.cartridge_list)

    def open_announcement_manager(self) -> None:
        existing = getattr(self, "announcement_manager_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        try:
            draft = self.workspace.load_announcement_draft()
        except AnnouncementValidationError as error:
            messagebox.showerror("公告配置异常", str(error))
            return

        window = ctk.CTkToplevel(self)
        self.announcement_manager_window = window
        window.title("管理启动公告")
        window.geometry("720x610")
        window.minsize(620, 540)
        window.configure(fg_color=PAGE)
        window.transient(self)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(
            window,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        card.grid(row=0, column=0, padx=18, pady=18, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(6, weight=1)
        ctk.CTkLabel(
            card,
            text="客户端启动公告",
            font=("Microsoft YaHei UI", 22, "bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, columnspan=2, padx=22, pady=(20, 4), sticky="w")
        ctk.CTkLabel(
            card,
            text="保存后会在下一次生成或发布 hub 时生效；停用会保留草稿并停止远端发布。",
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="ew")

        self.announcement_enabled = ctk.CTkCheckBox(
            card,
            text="启用并随 hub 发布",
            fg_color=BLUE,
            hover_color=BRAND,
        )
        self.announcement_enabled.grid(
            row=2, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="w"
        )
        if draft.enabled:
            self.announcement_enabled.select()

        ctk.CTkLabel(card, text="公告版本 ID", text_color=TEXT).grid(
            row=3, column=0, padx=(22, 12), pady=6, sticky="w"
        )
        self.announcement_id_entry = ctk.CTkEntry(
            card, border_width=2, border_color="#BDBDBD"
        )
        self.announcement_id_entry.grid(
            row=3, column=1, padx=(0, 22), pady=6, sticky="ew"
        )
        self.announcement_id_entry.insert(0, draft.announcement_id)

        ctk.CTkLabel(card, text="公告标题", text_color=TEXT).grid(
            row=4, column=0, padx=(22, 12), pady=6, sticky="w"
        )
        self.announcement_title_entry = ctk.CTkEntry(
            card, border_width=2, border_color="#BDBDBD"
        )
        self.announcement_title_entry.grid(
            row=4, column=1, padx=(0, 22), pady=6, sticky="ew"
        )
        self.announcement_title_entry.insert(0, draft.title)

        date_row = ctk.CTkFrame(card, fg_color="transparent")
        date_row.grid(row=5, column=0, columnspan=2, padx=22, pady=6, sticky="ew")
        date_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(date_row, text="更新日期", text_color=TEXT).grid(
            row=0, column=0, padx=(0, 12), sticky="w"
        )
        self.announcement_date_entry = ctk.CTkEntry(
            date_row, width=170, border_width=2, border_color="#BDBDBD"
        )
        self.announcement_date_entry.grid(row=0, column=1, sticky="w")
        self.announcement_date_entry.insert(0, draft.updated_at)
        ctk.CTkLabel(
            date_row,
            text="版本 ID 改变后，已选择“不再提示”的客户端也会重新显示公告。",
            text_color=MUTED,
            anchor="e",
        ).grid(row=0, column=2, padx=(14, 0), sticky="e")

        body_frame = ctk.CTkFrame(card, fg_color="transparent")
        body_frame.grid(
            row=6, column=0, columnspan=2, padx=22, pady=(8, 10), sticky="nsew"
        )
        body_frame.grid_columnconfigure(0, weight=1)
        body_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(body_frame, text="公告正文", text_color=TEXT).grid(
            row=0, column=0, pady=(0, 6), sticky="w"
        )
        self.announcement_body = ctk.CTkTextbox(
            body_frame,
            fg_color="#FAFAFA",
            border_width=2,
            border_color="#BDBDBD",
            wrap="word",
        )
        self.announcement_body.grid(row=1, column=0, sticky="nsew")
        self.announcement_body.insert("1.0", draft.body)

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(
            row=7, column=0, columnspan=2, padx=22, pady=(4, 20), sticky="ew"
        )
        for column in range(3):
            actions.grid_columnconfigure(column, weight=1, uniform="announcement")
        ctk.CTkButton(
            actions,
            text="预览公告",
            fg_color=LIGHT_BLUE,
            command=self.preview_announcement,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(
            actions,
            text="保存公告",
            fg_color=BLUE,
            command=self.save_announcement,
        ).grid(row=0, column=1, padx=5, sticky="ew")
        ctk.CTkButton(
            actions,
            text="关闭",
            fg_color="#9E9E9E",
            command=window.destroy,
        ).grid(row=0, column=2, padx=(5, 0), sticky="ew")
        window.grab_set()
        window.focus_force()

    def _announcement_editor_value(self) -> AnnouncementDraft:
        return AnnouncementDraft(
            announcement_id=self.announcement_id_entry.get(),
            title=self.announcement_title_entry.get(),
            updated_at=self.announcement_date_entry.get(),
            body=self.announcement_body.get("1.0", "end"),
            enabled=bool(self.announcement_enabled.get()),
        )

    def preview_announcement(self) -> None:
        try:
            draft = self._announcement_editor_value().validate()
        except AnnouncementValidationError as error:
            messagebox.showerror("无法预览公告", str(error))
            return
        messagebox.showinfo(
            "公告预览",
            f"{draft.title}\n{draft.updated_at}\n\n{draft.body}",
            parent=self.announcement_manager_window,
        )

    def save_announcement(self) -> None:
        draft = self._announcement_editor_value()
        if draft.enabled:
            try:
                draft = draft.validate()
            except AnnouncementValidationError as error:
                messagebox.showerror("无法启用公告", str(error))
                return
        elif self.workspace.announcement_path.is_file() and not messagebox.askyesno(
            "确认停用公告",
            "停用后会保留当前草稿；下一次发布 hub 时将从 Release 移除 announcement.json。是否继续？",
            parent=self.announcement_manager_window,
        ):
            return
        if not self._begin_background_mutation(
            "announcement-save", "正在保存客户端启动公告"
        ):
            return
        try:
            self.workspace.save_announcement_draft(draft)
            self.refresh_cartridge_management()
            state = "已启用" if draft.enabled else "已保存为停用草稿"
            self._log(f"客户端启动公告{state}：{draft.announcement_id or '未填写版本 ID'}")
            messagebox.showinfo(
                "公告已保存",
                f"公告{state}。下一次生成或发布 hub 时会自动同步。",
                parent=self.announcement_manager_window,
            )
        except (AnnouncementValidationError, OSError) as error:
            messagebox.showerror("公告保存失败", str(error))
        finally:
            self._end_background_mutation("announcement-save")

    def open_cartridge_config(self, game_id: str) -> None:
        profile = next(
            (item for item in self.workspace.list_games() if item.game_id == game_id),
            None,
        )
        if profile is None:
            messagebox.showerror("卡带不存在", f"找不到游戏卡带：{game_id}")
            return
        self.profile = profile
        self.refresh()
        self.tabs.set("卡带配置")

    def _update_freshness_summary(self) -> None:
        if not hasattr(self, "freshness_summary"):
            return
        try:
            report = self.workspace.refresh_resource_freshness(self.profile)
        except Exception:
            report = self.workspace.load_freshness(self.profile)
        if report is None or not report.resources_updated_at:
            self.freshness_summary.configure(
                text="资源提交时间：尚未读取到本地 DLC 包",
                text_color=MUTED,
            )
            return
        self.freshness_summary.configure(
            text=report.summary,
            text_color=TEXT,
        )

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

    @staticmethod
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

    @staticmethod
    def _acceptance_display_path(path: Path | None, limit: int = 92) -> str:
        if path is None:
            return "尚未选择"
        text = str(path)
        return text if len(text) <= limit else "…" + text[-(limit - 1):]

    @staticmethod
    def _reset_scrollable_frame(frame) -> None:
        """Synchronize a rebuilt CTk scroll canvas and show its first row."""
        try:
            frame.update_idletasks()
            canvas = frame._parent_canvas
            bounds = canvas.bbox("all")
            if bounds is not None:
                canvas.configure(scrollregion=bounds)
            canvas.yview_moveto(0.0)
        except (AttributeError, TclError):
            return

    def _schedule_scrollable_reset(self, frame) -> None:
        """Reset only after Tk has propagated the replacement row sizes."""
        def after_layout() -> None:
            try:
                self.after(20, lambda: self._reset_scrollable_frame(frame))
            except TclError:
                return

        try:
            self.after_idle(after_layout)
        except TclError:
            return

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
            ctk.CTkButton(
                row,
                text="上传",
                width=64,
                fg_color=BLUE,
                command=lambda value=path: self.upload_remote_file(value),
            ).pack(side="right", padx=7, pady=6)
        self._schedule_scrollable_reset(self.local_output_list)

    def _show_remote_message(self, message: str) -> None:
        for child in self.remote_asset_list.winfo_children():
            child.destroy()
        ctk.CTkLabel(self.remote_asset_list, text=message, text_color=MUTED).pack(
            pady=24
        )
        self._schedule_scrollable_reset(self.remote_asset_list)

    def _fill_remote_assets(self, assets: tuple[RemoteAsset, ...]) -> None:
        for child in self.remote_asset_list.winfo_children():
            child.destroy()
        if not assets:
            ctk.CTkLabel(
                self.remote_asset_list, text="当前 Release 暂无附件", text_color=MUTED
            ).pack(pady=24)
            self._schedule_scrollable_reset(self.remote_asset_list)
            return
        for asset in sorted(assets, key=lambda item: item.name.casefold()):
            row = ctk.CTkFrame(
                self.remote_asset_list,
                fg_color=CARD,
                border_width=1,
                border_color="#E0E0E0",
                corner_radius=8,
            )
            row.pack(fill="x", padx=4, pady=4)
            text = asset.name + (
                f"  ·  {asset.display_size}" if asset.display_size else ""
            )
            ctk.CTkLabel(row, text=text, anchor="w", text_color=TEXT).pack(
                side="left", fill="x", expand=True, padx=10, pady=9
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
                command=lambda value=asset: self.delete_remote_resource(value),
            ).pack(side="right", padx=7, pady=6)
        self._schedule_scrollable_reset(self.remote_asset_list)

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
        if not self._begin_background_mutation(
            "game-add", "正在新增游戏卡带"
        ):
            return
        try:
            game_id = simpledialog.askstring(
                "新增游戏卡带", "输入游戏 ID（如 crusader_kings_3）：", parent=self
            )
            if not game_id:
                return
            display = (
                simpledialog.askstring("新增游戏卡带", "输入显示名称：", parent=self)
                or game_id
            )
            steam_app_id = (
                simpledialog.askstring(
                    "新增游戏卡带", "输入 Steam App ID：", parent=self
                )
                or ""
            )
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

    def build_all(self) -> None:
        if not self._begin_background_mutation(
            "build", "正在构建发布文件"
        ):
            return
        self.build_button.configure(state="disabled", text="正在构建…")
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
        position = f"[{index}/{total}] " if index > 0 and total > 0 else ""
        subject = f" {name}" if name else ""
        suffix = f" · {detail}" if detail else ""
        self._log(f"{position}{stage}{subject}{suffix}")

    def _build_done(self, game_id: str, resources: int, files: int, size: int) -> None:
        self._build_operation_active = False
        self._end_background_mutation("build")
        self._poll_build_progress()
        self.build_button.configure(state="normal", text="生成全部发布文件")
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
        self.refresh_acceptance()

    def _build_failed(self, message: str) -> None:
        self._build_operation_active = False
        self._end_background_mutation("build")
        self._poll_build_progress()
        self.build_button.configure(state="normal", text="生成全部发布文件")
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

    def refresh_remote_resources(self) -> None:
        if not self._begin_remote_operation("正在读取远程资源…"):
            return
        if self._publish_target() == "github":
            try:
                client = self._github_repository_client()
                profile = self.profile
            except GitHubPublisherError as error:
                self._remote_failed(str(error))
                return

            def github_work() -> None:
                try:
                    release = self._github_remote_release(client, profile)
                    self._post_ui(lambda: self._remote_loaded(profile, release))
                except Exception as error:
                    self._post_ui(lambda value=str(error): self._remote_failed(value))

            threading.Thread(target=github_work, daemon=True).start()
            return
        try:
            manager, profile = self._remote_manager()
        except (GitLinkError, OSError) as error:
            self._remote_failed(str(error))
            return

        def work() -> None:
            try:
                release = manager.get_release(profile.release_tag)
                self._post_ui(lambda: self._remote_loaded(profile, release))
            except Exception as error:
                message = str(error)
                self._post_ui(lambda value=message: self._remote_failed(value))

        threading.Thread(target=work, daemon=True).start()

    def choose_remote_upload(self) -> None:
        initial = self.workspace.output_dir / self.profile.game_id
        path = filedialog.askopenfilename(
            title="选择要上传到当前 Release 的文件",
            initialdir=initial if initial.is_dir() else None,
        )
        if path:
            self.upload_remote_file(Path(path))

    def upload_remote_file(self, path: Path) -> None:
        if not messagebox.askyesno(
            "确认上传",
            f"上传 {path.name} 到 {self.profile.display_name} 的 {self.profile.release_tag} Release？\n\n存在同名附件时将安全替换。",
        ):
            return
        if not self._begin_remote_operation(f"正在上传 {path.name}…"):
            return
        if self._publish_target() == "github":
            try:
                client = self._github_repository_client()
                profile = self.profile
            except GitHubPublisherError as error:
                self._remote_failed(str(error))
                return

            def github_work() -> None:
                try:
                    release = client.ensure_release(profile.release_tag)
                    client.upload_asset(release, path, replace_existing=True)
                    updated = self._github_remote_release(client, profile)
                    self._post_ui(
                        lambda: self._remote_mutation_done(
                            profile, "上传", path.name, (), updated
                        )
                    )
                except Exception as error:
                    self._post_ui(lambda value=str(error): self._remote_failed(value))

            threading.Thread(target=github_work, daemon=True).start()
            return
        try:
            manager, profile = self._remote_manager()
        except (GitLinkError, OSError) as error:
            self._remote_failed(str(error))
            return

        def work() -> None:
            try:
                result = manager.upload_file(profile, path)
                release = manager.get_release(profile.release_tag)
                self._post_ui(
                    lambda: self._remote_mutation_done(
                        profile,
                        result.action,
                        result.asset.name,
                        result.warnings,
                        release,
                    )
                )
            except Exception as error:
                message = str(error)
                self._post_ui(lambda value=message: self._remote_failed(value))

        threading.Thread(target=work, daemon=True).start()

    def delete_remote_resource(self, asset: RemoteAsset) -> None:
        if not messagebox.askyesno(
            "确认删除远程资源",
            f"从 {self.profile.release_tag} Release 永久删除：\n{asset.name}\n\n此操作无法撤销，是否继续？",
        ):
            return
        if not self._begin_remote_operation(f"正在删除 {asset.name}…"):
            return
        if self._publish_target() == "github":
            try:
                client = self._github_repository_client()
                profile = self.profile
            except GitHubPublisherError as error:
                self._remote_failed(str(error))
                return

            def github_work() -> None:
                try:
                    client.delete_asset(int(asset.asset_id))
                    updated = self._github_remote_release(client, profile)
                    self._post_ui(
                        lambda: self._remote_mutation_done(
                            profile, "删除", asset.name, (), updated
                        )
                    )
                except Exception as error:
                    self._post_ui(lambda value=str(error): self._remote_failed(value))

            threading.Thread(target=github_work, daemon=True).start()
            return
        try:
            manager, profile = self._remote_manager()
            repo = manager.repository
            state = self.workspace.load_publish_state(profile, repo.owner, repo.name)
            upload_id = self._publish_upload_id(state, asset.name)
        except (GitLinkError, OSError) as error:
            self._remote_failed(str(error))
            return

        def work() -> None:
            try:
                result = manager.delete_asset(profile, asset.asset_id, upload_id)
                self._remove_publish_state_assets(profile, state, (asset.name,))
                release = manager.get_release(profile.release_tag)
                self._post_ui(
                    lambda: self._remote_mutation_done(
                        profile,
                        result.action,
                        result.asset.name,
                        result.warnings,
                        release,
                    )
                )
            except Exception as error:
                message = str(error)
                self._post_ui(lambda value=message: self._remote_failed(value))

        threading.Thread(target=work, daemon=True).start()

    def delete_all_remote_resources(self) -> None:
        release = self._current_remote_release
        if release is None or not release.assets:
            messagebox.showinfo("没有远程附件", "当前 Release 没有可删除的附件")
            return
        if not messagebox.askyesno(
            "确认删除全部远程附件",
            f"将从 {self.profile.release_tag} Release 永久删除全部 {len(release.assets)} 个附件。\n\n"
            "此操作无法撤销，是否继续？",
        ):
            return
        if not self._begin_remote_operation("正在删除全部远程附件…"):
            return
        if self._publish_target() == "github":
            try:
                client = self._github_repository_client()
                profile = self.profile
            except GitHubPublisherError as error:
                self._remote_failed(str(error))
                return

            def github_work() -> None:
                deleted = []
                failures = []
                for asset in release.assets:
                    try:
                        client.delete_asset(int(asset.asset_id))
                        deleted.append(asset)
                    except Exception as error:
                        failures.append(f"{asset.name}：{error}")
                try:
                    updated = self._github_remote_release(client, profile)
                    result = RemoteBulkDeleteResult(
                        tuple(deleted), tuple(failures), updated
                    )
                    self._post_ui(
                        lambda value=result: self._remote_bulk_delete_done(profile, value)
                    )
                except Exception as error:
                    self._post_ui(lambda value=str(error): self._remote_failed(value))

            threading.Thread(target=github_work, daemon=True).start()
            return
        try:
            manager, profile = self._remote_manager()
            repo = manager.repository
            state = self.workspace.load_publish_state(profile, repo.owner, repo.name)
            upload_ids = {
                asset.name.casefold(): self._publish_upload_id(state, asset.name)
                for asset in release.assets
            }
        except (GitLinkError, OSError) as error:
            self._remote_failed(str(error))
            return

        def work() -> None:
            try:
                result = manager.delete_all_assets(profile, upload_ids)
                self._remove_publish_state_assets(
                    profile, state, tuple(asset.name for asset in result.deleted)
                )
                self._post_ui(
                    lambda value=result: self._remote_bulk_delete_done(profile, value)
                )
            except Exception as error:
                self._post_ui(lambda value=str(error): self._remote_failed(value))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _publish_upload_id(state: dict[str, object], name: str) -> str:
        assets = state.get("assets")
        value = assets.get(name) if isinstance(assets, dict) else None
        return str(value.get("attachment_id", "")) if isinstance(value, dict) else ""

    def _remove_publish_state_assets(
        self, profile: GameProfile, state: dict[str, object], names: tuple[str, ...]
    ) -> None:
        assets = state.get("assets")
        if not isinstance(assets, dict):
            return
        for name in names:
            assets.pop(name, None)
        self.workspace.save_publish_state(profile, state)

    def _remote_manager(self) -> tuple[RemoteResourceManager, GameProfile]:
        repository = self._repository()
        token = self.token_entry.get().strip() or None
        return RemoteResourceManager(
            GitLinkAttachmentClient(token), repository
        ), self.profile

    def _github_remote_release(
        self, client: GitHubReleaseClient, profile: GameProfile
    ) -> RemoteRelease | None:
        release = client.get_release_by_tag(profile.release_tag)
        if release is None:
            return None
        assets = tuple(
            RemoteAsset(
                asset_id=str(asset["id"]),
                name=str(asset.get("name") or ""),
                display_size=self._format_transfer_size(float(asset.get("size") or 0)),
                url=str(asset.get("browser_download_url") or ""),
            )
            for asset in release.assets
            if asset.get("id") is not None and asset.get("name")
        )
        return RemoteRelease(
            release_id=str(release.release_id),
            tag=release.tag,
            name=release.tag,
            body="",
            assets=assets,
        )

    def _begin_remote_operation(self, message: str) -> bool:
        if self._remote_operation_active:
            messagebox.showinfo("远程操作进行中", "请等待当前远程操作完成")
            return False
        if not self._begin_background_mutation(
            "remote", "正在处理 GitLink 远程资源"
        ):
            return False
        self._remote_operation_active = True
        self.remote_refresh_button.configure(state="disabled")
        self.remote_delete_all_button.configure(state="disabled")
        self.remote_status.configure(text=message)
        return True

    def _remote_loaded(
        self, profile: GameProfile, release: RemoteRelease | None
    ) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("remote")
        self.remote_refresh_button.configure(state="normal")
        if profile.game_id != self.profile.game_id:
            return
        if release is None:
            self._current_remote_release = None
            self.remote_delete_all_button.configure(state="disabled")
            self.remote_status.configure(
                text=f"{profile.release_tag} · Release 尚未创建"
            )
            self._fill_remote_assets(())
            return
        self._current_remote_release = release
        self.remote_delete_all_button.configure(
            state="normal" if release.assets else "disabled"
        )
        self.remote_status.configure(
            text=f"{release.tag} · {len(release.assets)} 个远程附件"
        )
        self._fill_remote_assets(release.assets)

    def _remote_mutation_done(
        self,
        profile: GameProfile,
        action: str,
        name: str,
        warnings: tuple[str, ...],
        release: RemoteRelease | None,
    ) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("remote")
        self.remote_refresh_button.configure(state="normal")
        self._log(f"远程资源{action}完成：{name}")
        if profile.game_id == self.profile.game_id:
            if release is None:
                self._current_remote_release = None
                self.remote_delete_all_button.configure(state="disabled")
                self.remote_status.configure(
                    text=f"{profile.release_tag} · Release 尚未创建"
                )
                self._fill_remote_assets(())
            else:
                self._current_remote_release = release
                self.remote_delete_all_button.configure(
                    state="normal" if release.assets else "disabled"
                )
                self.remote_status.configure(
                    text=f"{release.tag} · {len(release.assets)} 个远程附件"
                )
                self._fill_remote_assets(release.assets)
        if warnings:
            messagebox.showwarning("操作完成但有警告", "\n".join(warnings))
        else:
            messagebox.showinfo("远程操作完成", f"已{action}：{name}")

    def _remote_bulk_delete_done(
        self, profile: GameProfile, result: RemoteBulkDeleteResult
    ) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("remote")
        self.remote_refresh_button.configure(state="normal")
        release = result.release
        if profile.game_id == self.profile.game_id:
            self._current_remote_release = release
            assets = release.assets if release else ()
            self.remote_delete_all_button.configure(
                state="normal" if assets else "disabled"
            )
            self.remote_status.configure(
                text=f"{profile.release_tag} · {len(assets)} 个远程附件"
            )
            self._fill_remote_assets(assets)
        summary = f"远程附件删除完成：成功 {len(result.deleted)} 个，失败 {len(result.failures)} 个。"
        self._log(summary)
        if result.failures:
            messagebox.showwarning(
                "部分附件删除失败", summary + "\n\n" + "\n".join(result.failures)
            )
        else:
            messagebox.showinfo("全部删除完成", summary)

    def _remote_failed(self, message: str) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("remote")
        self.remote_refresh_button.configure(state="normal")
        release = self._current_remote_release
        self.remote_delete_all_button.configure(
            state="normal" if release and release.assets else "disabled"
        )
        self.remote_status.configure(text="远程操作失败")
        self._log(f"远程操作失败：{message}")
        messagebox.showerror("远程操作失败", message)

    def check_gitlink(self) -> None:
        if not self._save_active_settings():
            return
        if self._publish_target() == "github":
            self._check_github_repository()
            return
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
                self._post_ui(lambda: self._gitlink_check_done(repo, profile, release))
            except (GitLinkError, OSError) as error:
                message = str(error)
                self._post_ui(lambda value=message: self._gitlink_check_failed(value))

        threading.Thread(target=work, daemon=True).start()

    def _gitlink_check_done(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        release: RemoteRelease | None,
    ) -> None:
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
        if not self._save_active_settings():
            return
        if self._publish_target() == "github":
            self._create_github_repository()
            return
        try:
            repo = self._repository()
        except GitLinkError as error:
            messagebox.showerror("创建失败", str(error))
            return
        if not messagebox.askyesno(
            "创建新仓库", f"确认创建公开资源仓库 {repo.owner}/{repo.name}？"
        ):
            return
        if not self._begin_background_mutation(
            "repository-create", "正在创建 GitLink 资源仓库"
        ):
            return
        try:
            self.gitlink.create_repository(
                repo, "SignRiver DLC Hub public release assets"
            )
            self._log(
                f"新仓库创建完成：https://www.gitlink.org.cn/{repo.owner}/{repo.name}"
            )
        except GitLinkError as error:
            messagebox.showerror("创建失败", str(error))
        finally:
            self._end_background_mutation("repository-create")

    def _github_repository_client(self) -> GitHubReleaseClient:
        owner = self.owner_entry.get().strip()
        name = self.repo_entry.get().strip()
        token = self.token_entry.get().strip()
        if not owner or not name:
            raise GitHubPublisherError("请填写 GitHub 所有者和仓库名")
        if not token:
            raise GitHubPublisherError("请填写 GitHub token")
        return GitHubReleaseClient(GitHubRepository(owner, name), token)

    def _check_github_repository(self) -> None:
        try:
            client = self._github_repository_client()
        except GitHubPublisherError as error:
            messagebox.showerror("GitHub 检查失败", str(error))
            return
        if not self._begin_background_mutation(
            "repository-check", "正在检查 GitHub 仓库"
        ):
            return
        self.check_gitlink_button.configure(state="disabled", text="正在检查…")

        def worker() -> None:
            try:
                info = client.repository_info()
                self._post_ui(lambda info=info: self._github_check_done(info))
            except (GitHubPublisherError, OSError) as error:
                message = str(error)
                self._post_ui(lambda value=message: self._github_check_failed(value))

        threading.Thread(target=worker, daemon=True).start()

    def _github_check_done(self, info: dict[str, object]) -> None:
        self._end_background_mutation("repository-check")
        self.check_gitlink_button.configure(state="normal", text="检查仓库")
        full_name = str(info.get("full_name") or "GitHub 仓库")
        visibility = "公开" if not bool(info.get("private")) else "私有"
        detail = f"{full_name} 可以访问（{visibility}仓库）。"
        self._log(f"GitHub API 检查成功：{detail}")
        messagebox.showinfo("GitHub 检查完成", detail)

    def _github_check_failed(self, message: str) -> None:
        self._end_background_mutation("repository-check")
        self.check_gitlink_button.configure(state="normal", text="检查仓库")
        self._log(f"GitHub API 检查失败：{message}")
        messagebox.showerror("GitHub 检查失败", message)

    def _create_github_repository(self) -> None:
        try:
            client = self._github_repository_client()
        except GitHubPublisherError as error:
            messagebox.showerror("创建失败", str(error))
            return
        repo = client.repository
        if not messagebox.askyesno(
            "创建新仓库", f"确认创建公开 GitHub 仓库 {repo.owner}/{repo.name}？"
        ):
            return
        if not self._begin_background_mutation(
            "repository-create", "正在创建 GitHub 仓库"
        ):
            return
        self.create_repository_button.configure(state="disabled", text="正在创建…")

        def worker() -> None:
            try:
                created = client.create_repository(
                    "SignRiver DLC Hub public release assets"
                )
                self._post_ui(
                    lambda created=created: self._github_repository_created(created)
                )
            except (GitHubPublisherError, OSError) as error:
                message = str(error)
                self._post_ui(
                    lambda value=message: self._github_repository_create_failed(value)
                )

        threading.Thread(target=worker, daemon=True).start()

    def _github_repository_created(self, repository: GitHubRepository) -> None:
        self._end_background_mutation("repository-create")
        self.create_repository_button.configure(state="normal", text="创建新仓库")
        detail = f"新仓库已创建：https://github.com/{repository.owner}/{repository.name}"
        self._log(detail)
        messagebox.showinfo("创建完成", detail)

    def _github_repository_create_failed(self, message: str) -> None:
        self._end_background_mutation("repository-create")
        self.create_repository_button.configure(state="normal", text="创建新仓库")
        self._log(f"GitHub 创建失败：{message}")
        messagebox.showerror("创建失败", message)

    def adopt_remote_assets(self) -> None:
        try:
            assets = self.workspace.publish_assets(self.profile)
            repo = self._repository()
            previous_state = self.workspace.load_publish_state(
                self.profile, repo.owner, repo.name
            )
            manager, profile = self._remote_manager()
        except (WorkspaceError, GitLinkError) as error:
            messagebox.showerror("无法采用远程附件", str(error))
            return
        if not messagebox.askyesno(
            "确认采用远程 DLC",
            "此操作不会上传、替换或删除任何远程文件。\n\n"
            "程序会把 Release 中名称和显示大小均与本地一致的 DLC ZIP "
            "写入本地发布记录，之后一键发布会直接复用。\n\n"
            "GitLink 未提供远程 SHA-256，无法核对文件内容。"
            "请只采用你刚刚手动上传并确认完整的附件。是否继续？",
        ):
            return
        if not self._begin_remote_operation("正在核对远程 DLC 附件…"):
            return
        self.adopt_remote_button.configure(state="disabled", text="正在核对…")
        self.publish_button.configure(state="disabled")
        self.game_menu.configure(state="disabled")
        self._log(f"开始采用远程附件：{repo.owner}/{repo.name} · {profile.release_tag}")

        def work() -> None:
            try:
                result = manager.adopt_matching_release_assets(
                    profile, assets, previous_state
                )
                self.workspace.save_publish_state(profile, result.state)
                self._post_ui(lambda: self._adoption_done(profile, result))
            except Exception as error:
                message = str(error)
                self._post_ui(lambda value=message: self._adoption_failed(value))

        threading.Thread(target=work, daemon=True).start()

    def _adoption_done(self, profile: GameProfile, result) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("remote")
        self.remote_refresh_button.configure(state="normal")
        self.adopt_remote_button.configure(state="normal", text="采用远程附件")
        self.publish_button.configure(state="normal")
        self.game_menu.configure(state="normal")
        summary = (
            f"远程附件采用完成：新增采用 {len(result.adopted)} 个，"
            f"已在管理 {len(result.already_managed)} 个，跳过 {len(result.skipped)} 个。"
        )
        self.remote_status.configure(text=summary)
        self._log(summary)
        for name in result.adopted:
            self._log(f"采用：{name}")
        if result.skipped:
            detail = "\n".join(result.skipped[:12])
            if len(result.skipped) > 12:
                detail += f"\n……另有 {len(result.skipped) - 12} 项"
            messagebox.showwarning("采用完成，但有跳过项目", f"{summary}\n\n{detail}")
        else:
            messagebox.showinfo("采用远程附件完成", summary)

    def _adoption_failed(self, message: str) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("remote")
        self.remote_refresh_button.configure(state="normal")
        self.adopt_remote_button.configure(state="normal", text="采用远程附件")
        self.publish_button.configure(state="normal")
        self.game_menu.configure(state="normal")
        self.remote_status.configure(text="采用远程附件失败")
        self._log(f"采用远程附件失败：{message}")
        messagebox.showerror("采用远程附件失败", message)

    def publish_release(self) -> None:
        if not self._save_active_settings():
            return
        self._active_publish_scope = "game"
        self._upload_control = UploadControl()
        if self._publish_target() == "github":
            self._publish_release_github()
            return
        if not self._begin_background_mutation(
            "publish", "正在上传 Release"
        ):
            return
        try:
            assets = self.workspace.publish_assets(self.profile)
            repo = self._repository()
            previous_state = self.workspace.load_publish_state(
                self.profile, repo.owner, repo.name
            )
        except (WorkspaceError, GitLinkError, OSError) as error:
            self._end_background_mutation("publish")
            messagebox.showerror("无法发布", str(error))
            return
        if not messagebox.askyesno(
            "确认增量发布",
            f"同步 {len(assets)} 个文件到\n{repo.owner}/{repo.name} · {self.profile.release_tag}\n\n未变化文件将复用远程附件；AppInfo 每次强制更新。是否继续？",
        ):
            self._end_background_mutation("publish")
            return
        token = self.token_entry.get().strip() or None
        self._publish_resume_context = (repo, self.profile, assets, token)
        if not self._start_publish(repo, self.profile, assets, previous_state, token):
            self._publish_resume_context = None
            self._end_background_mutation("publish")

    def publish_update_release(self, *, mirror: bool = False) -> None:
        """Publish a built module/full ZIP and its client update manifest."""
        if not self._save_active_settings():
            return
        package_name = filedialog.askopenfilename(
            title="选择程序更新包",
            initialdir=self._update_package_dir(),
            filetypes=[("ZIP 文件", "*.zip")],
        )
        if not package_name:
            return
        package = Path(package_name)
        try:
            package_info = inspect_update_package(package)
        except ValueError as error:
            messagebox.showerror("程序更新", str(error), parent=self)
            return
        version = package_info.version
        kind = package_info.kind
        asked = self._ask_update_notes(version, kind)
        if asked is None:
            return
        notes, mandatory = asked
        mandatory = messagebox.askyesno(
            "程序更新", "是否强制此版本更新？", parent=self
        )
        operation = "正在镜像发布程序更新" if mirror else "正在发布程序更新"
        if not self._begin_background_mutation("update-publish", operation):
            return
        owner, repository, token = (
            self.owner_entry.get().strip(),
            self.repo_entry.get().strip(),
            self.token_entry.get().strip(),
        )
        target = self._publish_target()
        self.publish_update_button.configure(state="disabled", text="正在发布…")
        self.publish_update_mirror_button.configure(state="disabled")
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_sample = None
        self._upload_speed = 0.0
        self._active_publish_scope = "game"
        self._upload_control = UploadControl()
        self.upload_progress.set(0)
        self.upload_status.configure(text="正在准备程序更新发布…")

        def worker() -> None:
            try:
                draft = UpdateReleaseDraft(
                    version=version.strip(), kind=kind, package=package,
                    notes=notes, mandatory=mandatory,
                )
                self._update_publish_resume = (draft, mirror, target, owner, repository, token)
                if mirror:
                    self._publish_update_mirror(draft)
                    published_target = "GitLink + GitHub"
                else:
                    manifest = write_update_manifest(
                        self.workspace.output_dir / "updates" / UPDATE_MANIFEST_ASSET,
                        channel="stable",
                        releases=[draft.release_dict(release_asset_url(
                            target, owner, repository, package.name
                        ))],
                    )
                    self._publish_update_target(target, owner, repository, token, package, manifest)
                    published_target = target
                self._post_ui(
                    lambda: self._publish_update_done(version.strip(), published_target)
                )
            except (UploadPaused, GitHubUploadPaused) as error:
                self._post_ui(
                    lambda value=str(error): self._publish_update_paused(value)
                )
            except Exception as error:
                self._post_ui(lambda message=str(error): self._publish_update_failed(message))

        threading.Thread(
            target=worker, daemon=True, name="update-release-publish"
        ).start()

    def _publish_update_mirror(self, draft: UpdateReleaseDraft) -> None:
        """Upload the identical package to both hosts before either manifest."""
        targets = (
            ("gitlink", self.settings.owner, self.settings.repository, self.settings.token),
            ("github", self.settings.github_owner, self.settings.github_repository, self.settings.github_token),
        )
        if not all(owner and repository and token for _target, owner, repository, token in targets):
            raise ValueError("双源镜像发布需要在本地配置中填写 GitLink 和 GitHub 的完整凭据")
        manifests = []
        for target, owner, repository, _token in targets:
            manifests.append((target, owner, repository, _token, write_update_manifest(
                self.workspace.output_dir / "updates" / target / UPDATE_MANIFEST_ASSET,
                channel="stable",
                releases=[draft.release_dict(release_asset_url(
                    target, owner, repository, draft.package.name
                ))],
            )))
        # Package first: a newly visible manifest can never reference an asset
        # that has not reached its source Release yet.
        for index, (target, owner, repository, token, _manifest) in enumerate(
            manifests, start=1
        ):
            self._publish_update_target(
                target,
                owner,
                repository,
                token,
                draft.package,
                None,
                progress_start=index - 1,
                progress_total=4,
            )
        for index, (target, owner, repository, token, manifest) in enumerate(
            manifests, start=3
        ):
            self._publish_update_target(
                target,
                owner,
                repository,
                token,
                None,
                manifest,
                progress_start=index - 1,
                progress_total=4,
            )

    def publish_module_archive(self, *, mirror: bool = False) -> None:
        """Publish every verified module snapshot from the standard archive directory."""
        if not self._save_active_settings():
            return
        archive_dir = self._module_archive_dir()
        packages = tuple(sorted(archive_dir.glob("SignRiver-DLC-Hub-module-v*.zip")))
        if not packages:
            messagebox.showerror(
                "模块归档",
                f"归档目录中没有模块 ZIP：\n{archive_dir}\n\n"
                "请先执行 tools\\build_module.py --all-versions app\\versions。",
                parent=self,
            )
            return
        try:
            archives = tuple((package, inspect_module_archive(package)) for package in packages)
        except ValueError as error:
            messagebox.showerror("模块归档", f"归档校验失败：{error}", parent=self)
            return
        target = self._publish_target()
        destination = "GitLink + GitHub" if mirror else target
        versions = ", ".join(archive.version for _package, archive in archives)
        if not messagebox.askyesno(
            "确认发布模块归档",
            f"归档目录：{archive_dir}\n已识别 {len(archives)} 个版本：{versions}\n\n"
            f"将上传到 {destination} 的 {MODULE_ARCHIVE_RELEASE_TAG} Release。"
            "此操作不会发布客户端更新。是否继续？",
            parent=self,
        ):
            return
        if not self._begin_background_mutation("module-archive", "正在发布模块归档"):
            return
        selected_owner = self.owner_entry.get().strip()
        selected_repository = self.repo_entry.get().strip()
        selected_token = self.token_entry.get().strip()
        self.publish_module_archive_button.configure(state="disabled", text="正在归档…")
        self.publish_module_archive_mirror_button.configure(state="disabled")
        self.upload_progress.set(0)
        self.upload_status.configure(text=f"正在归档 {len(archives)} 个模块版本…")

        def worker() -> None:
            try:
                targets: tuple[tuple[str, str, str, str], ...]
                if mirror:
                    targets = (
                        ("gitlink", self.settings.owner, self.settings.repository, self.settings.token),
                        ("github", self.settings.github_owner, self.settings.github_repository, self.settings.github_token),
                    )
                    if not all(owner and repository and token for _target, owner, repository, token in targets):
                        raise ValueError("双源镜像归档需要在本地配置中填写 GitLink 和 GitHub 的完整凭据")
                else:
                    targets = ((target, selected_owner, selected_repository, selected_token),)
                total = len(archives) * len(targets)
                for target_index, (host, owner, repository, token) in enumerate(targets):
                    for archive_index, (package, _archive) in enumerate(archives):
                        self._publish_update_target(
                            host, owner, repository, token, package, None,
                            progress_start=target_index * len(archives) + archive_index,
                            progress_total=total,
                            release_tag=MODULE_ARCHIVE_RELEASE_TAG,
                            release_name="SignRiver Module Archives",
                        )
                self._post_ui(lambda: self._publish_module_archive_done(versions, destination))
            except Exception as error:
                self._post_ui(lambda message=str(error): self._publish_module_archive_failed(message))

        threading.Thread(
            target=worker, daemon=True, name="module-archive-publish"
        ).start()

    @staticmethod
    def _module_archive_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent.parent / "modules"
        return Path(__file__).resolve().parents[2] / "dist" / "modules"

    @staticmethod
    def _update_package_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent.parent / "updates"
        return Path(__file__).resolve().parents[2] / "dist" / "updates"

    @staticmethod
    def _update_paths(package: Path | None, manifest: Path | None) -> tuple[Path, ...]:
        return tuple(path for path in (package, manifest) if path is not None)

    def _publish_update_target(
        self, target: str, owner: str, repository: str, token: str,
        package: Path | None, manifest: Path | None,
        *,
        progress_start: int = 0,
        progress_total: int | None = None,
        release_tag: str = UPDATE_RELEASE_TAG,
        release_name: str = "SignRiver Updates",
    ) -> None:
        paths = self._update_paths(package, manifest)
        total = progress_total or len(paths)
        target_label = "GitHub" if target == "github" else "GitLink"

        def progress_callback(index: int, path: Path):
            name = f"{target_label} · {path.name}"
            size = path.stat().st_size
            self._queue_upload_progress(index, total, name, 0, size)
            return lambda sent, upload_size: self._queue_upload_progress(
                index, total, name, sent, upload_size
            )

        if target == "github":
                    client = GitHubReleaseClient(
                        GitHubRepository(owner, repository), token
                    )
                    if paths:
                        progress_callback(progress_start + 1, paths[0])
                    release = client.ensure_release(
                        release_tag, name=release_name
                    )
                    for offset, path in enumerate(paths, start=1):
                        callback = progress_callback(progress_start + offset, path)
                        client.upload_asset(
                            release,
                            path,
                            replace_existing=True,
                            progress=callback,
                            should_pause=lambda: bool(
                                self._upload_control
                                and self._upload_control.pause_requested
                            ),
                        )
                        callback(path.stat().st_size, path.stat().st_size)
        elif target == "gitlink":
                    manager = RemoteResourceManager(
                        GitLinkAttachmentClient(token or None),
                        GitLinkRepository(owner, repository),
                    )
                    for offset, path in enumerate(paths, start=1):
                        callback = progress_callback(progress_start + offset, path)
                        manager.upload_file_to_release(
                            release_tag,
                            release_name,
                            path,
                            progress=callback,
                            control=self._upload_control,
                        )
                        callback(path.stat().st_size, path.stat().st_size)
        else:
            raise ValueError(f"unsupported update target: {target}")

    def _publish_update_done(self, version: str, target: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self.upload_progress.set(1)
        self.upload_status.configure(
            text=f"程序更新 {version} 已发布完成 · {target}"
        )
        self._end_background_mutation("update-publish")
        self.publish_update_button.configure(state="normal", text="单源发布程序更新")
        self.publish_update_mirror_button.configure(state="normal")
        message = f"程序更新 {version} 已发布到 {target} 的 {UPDATE_RELEASE_TAG} Release"
        self._log(message)
        messagebox.showinfo("程序更新发布完成", message, parent=self)


    def _default_update_notes(self, version: str, kind: str) -> str:
        """Default release notes the maintainer can edit before publishing."""
        if kind == "module":
            return f"\u300c{version}\u300d\u6a21\u5757\u66f4\u65b0\uff1a\u4fee\u590d\u95ee\u9898\u5e76\u4f18\u5316\u4f7f\u7528\u4f53\u9a8c\uff0c\u5efa\u8bae\u5c3d\u5feb\u66f4\u65b0\u3002"
        return f"\u300c{version}\u300d\u7248\u672c\u66f4\u65b0\uff1a\u4fee\u590d\u95ee\u9898\u5e76\u4f18\u5316\u4f7f\u7528\u4f53\u9a8c\uff0c\u5efa\u8bae\u5c3d\u5feb\u66f4\u65b0\u3002"

    def _ask_update_notes(self, version: str, kind: str) -> tuple[str, bool] | None:
        """Custom styled dialog: editable default notes + mandatory checkbox."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("\u7a0b\u5e8f\u66f4\u65b0\u53d1\u5e03")
        dialog.geometry("660x480")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        result: dict[str, object] = {}

        ctk.CTkLabel(
            dialog,
            text=f"\u5df2\u8bc6\u522b\uff1a\u7248\u672c {version} \u00b7 \u7c7b\u578b {kind}",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(22, 2))
        ctk.CTkLabel(
            dialog,
            text="\u66f4\u65b0\u8bf4\u660e\uff08\u9ed8\u8ba4\u5df2\u751f\u6210\uff0c\u53ef\u76f4\u63a5\u4fee\u6539\uff09\uff1a",
            anchor="w",
        ).pack(anchor="w", padx=28, pady=(6, 4))

        textbox = ctk.CTkTextbox(
            dialog, width=600, height=230, font=ctk.CTkFont(size=14)
        )
        textbox.pack(padx=28, pady=(4, 12))
        textbox.insert("1.0", self._default_update_notes(version, kind))

        mandatory_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            dialog,
            text="\u5f3a\u5236\u6b64\u7248\u672c\u66f4\u65b0\uff08\u7528\u6237\u65e0\u6cd5\u8df3\u8fc7\uff09",
            variable=mandatory_var,
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", padx=28, pady=(0, 16))

        button_row = ctk.CTkFrame(dialog, fg_color="transparent")
        button_row.pack(fill="x", padx=28, pady=(0, 22))

        def confirm() -> None:
            notes_text = textbox.get("1.0", "end").strip()
            result["value"] = (notes_text, bool(mandatory_var.get()))
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        ctk.CTkButton(
            button_row, text="\u53d6\u6d88", width=110, fg_color="#9E9E9E",
            command=cancel,
        ).pack(side="right", padx=(10, 0))
        ctk.CTkButton(
            button_row, text="\u786e\u8ba4\u53d1\u5e03", width=140,
            command=confirm,
        ).pack(side="right")
        dialog.wait_window()
        value = result.get("value")
        return value if isinstance(value, tuple) else None

    def _publish_update_paused(self, message: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_control = None
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="\u53d1\u5e03\u5df2\u6682\u505c")
        self.publish_update_button.configure(state="disabled", text="\u53d1\u5e03\u5df2\u6682\u505c")
        self.publish_update_mirror_button.configure(state="disabled")
        pause_button.configure(state="normal", text="\u7ee7\u7eed\u53d1\u5e03")
        status_label.configure(text="\u5df2\u6682\u505c\uff1b\u7ee7\u7eed\u65f6\u4f1a\u4ece\u5934\u91cd\u65b0\u4e0a\u4f20")
        self._log(f"{message}\u3002\u5df2\u6682\u505c\uff1b\u70b9\u51fb\u7ee7\u7eed\u53d1\u5e03\u5c06\u91cd\u65b0\u4e0a\u4f20\u3002")

    def _resume_update_publish(self) -> None:
        resume = getattr(self, "_update_publish_resume", None)
        if resume is None:
            return
        draft, mirror, target, owner, repository, token = resume
        if not self._begin_background_mutation(
            "update-publish", "\u6b63\u5728\u7ee7\u7eed\u53d1\u5e03\u7a0b\u5e8f\u66f4\u65b0"
        ):
            return
        self._upload_control = UploadControl()
        self.upload_progress.set(0)
        self.upload_status.configure(text="\u6b63\u5728\u7ee7\u7eed\u53d1\u5e03\u7a0b\u5e8f\u66f4\u65b0\u2026")
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        pause_button.configure(state="normal", text="\u6682\u505c\u53d1\u5e03")
        self._log("\u7ee7\u7eed\u53d1\u5e03\uff1a\u91cd\u65b0\u4e0a\u4f20\uff08GitHub \u8986\u76d6\u3001GitLink \u590d\u7528\uff09\u3002")

        def worker() -> None:
            try:
                if mirror:
                    self._publish_update_mirror(draft)
                    published_target = "GitLink + GitHub"
                else:
                    manifest = write_update_manifest(
                        self.workspace.output_dir / "updates" / UPDATE_MANIFEST_ASSET,
                        channel="stable",
                        releases=[draft.release_dict(release_asset_url(
                            target, owner, repository, draft.package.name
                        ))],
                    )
                    self._publish_update_target(
                        target, owner, repository, token,
                        draft.package, manifest,
                    )
                    published_target = target
                self._post_ui(
                    lambda: self._publish_update_done(draft.version, published_target)
                )
            except (UploadPaused, GitHubUploadPaused) as error:
                self._post_ui(
                    lambda value=str(error): self._publish_update_paused(value)
                )
            except Exception as error:
                self._post_ui(
                    lambda message=str(error): self._publish_update_failed(message)
                )

        threading.Thread(
            target=worker, daemon=True, name="resume-update-publish"
        ).start()

    def _publish_update_failed(self, message: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self.upload_status.configure(text="程序更新发布失败，请查看下方日志")
        self._end_background_mutation("update-publish")
        self.publish_update_button.configure(state="normal", text="单源发布程序更新")
        self.publish_update_mirror_button.configure(state="normal")
        self._log(f"程序更新发布失败：{message}")
        messagebox.showerror("程序更新发布失败", message, parent=self)

    def _publish_module_archive_done(self, version: str, target: str) -> None:
        self.upload_progress.set(1)
        self.upload_status.configure(text=f"模块归档 {version} 已发布完成 · {target}")
        self._end_background_mutation("module-archive")
        self.publish_module_archive_button.configure(
            state="normal", text="单源发布模块归档"
        )
        self.publish_module_archive_mirror_button.configure(state="normal")
        message = f"模块归档 {version} 已发布到 {target} 的 {MODULE_ARCHIVE_RELEASE_TAG} Release"
        self._log(message)
        messagebox.showinfo("模块归档发布完成", message, parent=self)

    def _publish_module_archive_failed(self, message: str) -> None:
        self.upload_status.configure(text="模块归档发布失败，请查看下方日志")
        self._end_background_mutation("module-archive")
        self.publish_module_archive_button.configure(
            state="normal", text="单源发布模块归档"
        )
        self.publish_module_archive_mirror_button.configure(state="normal")
        self._log(f"模块归档发布失败：{message}")
        messagebox.showerror("模块归档发布失败", message, parent=self)

    def _publish_scope_controls(self):
        if self._active_publish_scope == "hub":
            return (
                self.hub_publish_button,
                self.hub_publish_pause_button,
                self.hub_upload_status,
                self.hub_upload_progress,
            )
        return (
            self.publish_button,
            self.publish_pause_button,
            self.upload_status,
            self.upload_progress,
        )

    def _set_publish_buttons_available(self, available: bool) -> None:
        state = "normal" if available else "disabled"
        self.publish_button.configure(state=state, text="发布当前游戏到所选源")
        self.publish_update_button.configure(state=state, text="单源发布程序更新")
        self.publish_update_mirror_button.configure(state=state)
        self.publish_module_archive_button.configure(
            state=state, text="单源发布模块归档"
        )
        self.publish_module_archive_mirror_button.configure(state=state)
        self.hub_publish_button.configure(state=state, text="一键双端发布卡带")
        self.publish_hub_single_button.configure(state=state)

    def _publish_target(self) -> str:
        return "github" if self.publish_target_menu.get() == "GitHub" else "gitlink"

    def _save_active_settings(self) -> bool:
        if self.settings_path is None:
            return True
        self.settings = self.settings.with_active_values(
            self.owner_entry.get().strip(),
            self.repo_entry.get().strip(),
            self.token_entry.get().strip(),
        )
        try:
            self.settings.save(self.settings_path)
        except PublisherSettingsError as error:
            self._log(f"无法保存本地发布配置：{error}")
            messagebox.showerror("保存本地配置失败", str(error))
            return False
        return True

    def _on_publish_target_changed(self, display_name: str) -> None:
        if not self._save_active_settings():
            return
        target = "github" if display_name == "GitHub" else "gitlink"
        self.settings = self.settings.with_publish_target(target)
        self.owner_entry.delete(0, "end")
        self.repo_entry.delete(0, "end")
        self.token_entry.delete(0, "end")
        self.owner_entry.insert(0, self.settings.active_owner)
        self.repo_entry.insert(0, self.settings.active_repository)
        if self.settings.active_token:
            self.token_entry.insert(0, self.settings.active_token)
        self.repository = GitLinkRepository(
            self.settings.active_owner, self.settings.active_repository
        )
        self._sync_publish_target_controls()
        self._save_active_settings()
        self._log(
            f"发布目标已切换为 {display_name}："
            f"{self.settings.active_owner}/{self.settings.active_repository}"
        )
        if hasattr(self, "cartridge_list"):
            self.refresh_cartridge_management()

    def _sync_publish_target_controls(self) -> None:
        is_github = self._publish_target() == "github"
        self.check_gitlink_button.configure(text="检查仓库")
        self.create_repository_button.configure(text="创建新仓库")
        self.token_entry.configure(
            placeholder_text="GitHub token" if is_github else "GitLink 私有令牌"
        )
        self.adopt_remote_button.configure(
            state="disabled" if is_github else "normal",
            text="GitHub 暂不支持采用" if is_github else "采用远程附件",
        )
        if hasattr(self, "remote_asset_title"):
            self.remote_asset_title.configure(
                text="GitHub Release 附件" if is_github else "GitLink Release 附件"
            )

    def _publish_release_github(self) -> None:
        if not self._begin_background_mutation(
            "publish", "正在上传 GitHub Release"
        ):
            return
        try:
            assets = self.workspace.publish_assets(self.profile)
        except (WorkspaceError, OSError) as error:
            self._end_background_mutation("publish")
            messagebox.showerror("无法发布", str(error))
            return
        owner = self.owner_entry.get().strip()
        name = self.repo_entry.get().strip()
        token = self.token_entry.get().strip()
        if not owner or not name:
            self._end_background_mutation("publish")
            messagebox.showerror("无法发布", "GitHub owner 和仓库名不能为空")
            return
        if not token:
            self._end_background_mutation("publish")
            messagebox.showerror("无法发布", "请填写 GitHub token")
            return
        if not messagebox.askyesno(
            "确认发布到 GitHub",
            f"上传 {len(assets)} 个文件到\n"
            f"{owner}/{name} · {self.profile.release_tag}\n\n"
            "同名附件会被替换。是否继续？",
        ):
            self._end_background_mutation("publish")
            return
        self._start_github_publish(owner, name, token, self.profile, assets)

    def _start_github_publish(
        self,
        owner: str,
        name: str,
        token: str,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        completed: frozenset[str] = frozenset(),
    ) -> None:
        publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="正在发布…")
        self.adopt_remote_button.configure(state="disabled")
        self._upload_control = UploadControl()
        self._github_publish_resume_context = (
            owner, name, token, profile, assets, completed,
        )
        pause_button.configure(state="normal", text="暂停发布")
        status_label.configure(text="正在准备 GitHub 上传…")
        progress_bar.set(0)

        def worker() -> None:
            try:
                client = GitHubReleaseClient(
                    GitHubRepository(owner, name), token
                )
                release = client.ensure_release(profile.release_tag)
                total = len(assets)
                completed_names = set(completed)
                reusable_assets = {
                    str(item.get("name")): int(item.get("size") or 0)
                    for item in release.assets
                    if item.get("name") and item.get("size") is not None
                }
                for index, asset in enumerate(assets, start=1):
                    if (
                        asset.name in completed_names
                        or (
                            asset.name != profile.appinfo_name
                            and reusable_assets.get(asset.name) == asset.size_bytes
                        )
                    ):
                        completed_names.add(asset.name)
                        self._queue_upload_progress(
                            index, total, asset.name, asset.size_bytes, asset.size_bytes
                        )
                        self._post_ui(
                            lambda i=index, value=asset.name: self._log(
                                f"[{i}/{total}] 复用 GitHub 附件 {value}"
                            )
                        )
                        continue
                    self._queue_upload_progress(
                        index, total, asset.name, 0, asset.size_bytes
                    )
                    client.upload_asset(
                        release,
                        asset.path,
                        replace_existing=True,
                        progress=lambda sent, size, i=index, value=asset.name: (
                            self._queue_upload_progress(i, total, value, sent, size)
                        ),
                        should_pause=lambda: bool(
                            self._upload_control and self._upload_control.pause_requested
                        ),
                    )
                    completed_names.add(asset.name)
                    self._queue_upload_progress(
                        index, total, asset.name, asset.size_bytes, asset.size_bytes
                    )
                self._post_ui(
                    lambda: self._github_publish_done(owner, name, profile, total)
                )
            except GitHubUploadPaused as error:
                self._post_ui(
                    lambda value=str(error), done=frozenset(completed_names): (
                        self._github_publish_paused(value, done)
                    )
                )
            except (GitHubPublisherError, OSError) as error:
                message = str(error)
                self._post_ui(
                    lambda message=message: self._github_publish_failed(message)
                )

        threading.Thread(target=worker, daemon=True).start()

    def _github_publish_done(
        self, owner: str, name: str, profile: GameProfile, total: int
    ) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("publish")
        _publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self._sync_publish_target_controls()
        pause_button.configure(state="disabled", text="暂停发布")
        status_label.configure(text=f"GitHub 发布完成 · {total} 个文件")
        progress_bar.set(1)
        self._upload_control = None
        self._github_publish_resume_context = None
        summary = f"已发布到 GitHub {owner}/{name} · {profile.release_tag}"
        self._log(summary)
        if self._active_publish_scope == "hub":
            self.refresh_cartridge_management()
        messagebox.showinfo("发布完成", summary)

    def _github_publish_failed(self, message: str) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("publish")
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self._sync_publish_target_controls()
        pause_button.configure(state="disabled", text="暂停发布")
        status_label.configure(text="GitHub 发布失败")
        self._upload_control = None
        self._github_publish_resume_context = None
        self._log(f"GitHub 发布失败：{message}")
        messagebox.showerror("GitHub 发布失败", message)

    def _start_publish(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        previous_state: dict[str, object],
        token: str | None,
    ) -> bool:
        if not self._begin_background_mutation(
            "publish",
            "正在上传 Release",
            resume=self._upload_control is None,
        ):
            return False
        self._upload_control = UploadControl()
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_sample = None
        self._upload_speed = 0.0
        publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="正在发布…")
        self.adopt_remote_button.configure(state="disabled")
        pause_button.configure(state="normal", text="暂停发布")
        status_label.configure(text="正在准备上传…")
        progress_bar.set(0)
        self._log(
            f"开始单文件确认发布 {profile.display_name}：共 {len(assets)} 个文件。"
        )
        threading.Thread(
            target=self._publish_worker,
            args=(repo, profile, assets, previous_state, token),
            daemon=True,
        ).start()
        return True

    def _publish_worker(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        previous_state: dict[str, object],
        token: str | None,
    ) -> None:
        try:
            client = GitLinkAttachmentClient(token)
            manager = RemoteResourceManager(client, repo)

            def progress(index: int, total: int, name: str, stage: str) -> None:
                self._post_ui(
                    lambda i=index, count=total, value=name, action=stage: self._log(
                        f"[{i}/{count}] {action} {value}"
                    )
                )

            def upload_progress(
                index: int, total: int, name: str, sent: int, size: int
            ) -> None:
                self._queue_upload_progress(index, total, name, sent, size)

            def checkpoint(state: dict[str, object]) -> None:
                self.workspace.save_publish_state(profile, state)

            result = manager.sync_release(
                profile,
                assets,
                previous_state,
                force_upload=frozenset({profile.appinfo_name}),
                progress=progress,
                upload_progress=upload_progress,
                upload_control=self._upload_control,
                checkpoint=checkpoint,
            )
            warnings = result.warnings
            try:
                self.workspace.save_publish_state(profile, result.state)
            except OSError as error:
                warnings = (
                    *warnings,
                    f"Release 已更新，但本地发布状态保存失败；下次可能重新上传：{error}",
                )
            self._post_ui(
                lambda value=result, notes=warnings: self._publish_done(
                    repo,
                    profile,
                    value.action,
                    value.uploaded,
                    value.reused,
                    value.removed,
                    notes,
                )
            )
        except UploadPaused as error:
            self._post_ui(lambda value=str(error): self._publish_paused(value))
        except Exception as error:
            message = str(error)
            self._post_ui(lambda value=message: self._publish_failed(value))

    def _publish_done(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        action: str,
        uploaded: int,
        reused: int,
        removed: int,
        warnings: tuple[str, ...],
    ) -> None:
        self._end_background_mutation("publish")
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        _publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self.adopt_remote_button.configure(state="normal")
        pause_button.configure(state="disabled", text="暂停发布")
        progress_bar.set(1)
        status_label.configure(text="发布完成")
        self._publish_resume_context = None
        self._upload_control = None
        if not self.settings.token:
            self.token_entry.delete(0, "end")
        summary = f"Release {action}完成：上传 {uploaded}，复用 {reused}，清理旧附件 {removed}。"
        self._log(summary)
        if self._active_publish_scope == "hub":
            self.refresh_cartridge_management()
        if warnings:
            messagebox.showwarning(
                "发布完成但有警告", f"{summary}\n\n" + "\n".join(warnings)
            )
        else:
            messagebox.showinfo(
                "发布完成",
                f"资源已发布到 {repo.owner}/{repo.name} 的 {profile.release_tag} Release。\n\n{summary}",
            )

    def _publish_failed(self, message: str) -> None:
        self._end_background_mutation("publish")
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self.adopt_remote_button.configure(state="normal")
        pause_button.configure(state="disabled", text="暂停发布")
        status_label.configure(text="发布中断；已确认文件已保留")
        self._publish_resume_context = None
        self._upload_control = None
        self._log(
            f"发布中断：{message}。已确认的文件不会重新上传，可再次点击发布继续。"
        )
        messagebox.showerror(
            "发布中断",
            f"{message}\n\n此前已确认到 Release 的文件已保留，再次发布会从未完成文件继续。",
        )

    def toggle_publish_pause(self) -> None:
        control = self._upload_control
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        if control is not None:
            control.request_pause()
            pause_button.configure(state="disabled", text="正在暂停…")
            status_label.configure(text="正在中止当前文件上传…")
            return
        if getattr(self, "_update_publish_resume", None) is not None:
            self._resume_update_publish()
            return
        github_context = self._github_publish_resume_context
        if github_context is not None:
            owner, name, token, profile, assets, completed = github_context
            if not self._begin_background_mutation(
                "publish", "正在继续上传 GitHub Release"
            ):
                return
            self._log("继续 GitHub 发布：当前文件将从头上传，已完成文件会跳过。")
            self._start_github_publish(
                owner, name, token, profile, assets, completed,
            )
            return
        context = self._publish_resume_context
        if context is None:
            return
        repo, profile, assets, token = context
        try:
            previous_state = self.workspace.load_publish_state(
                profile, repo.owner, repo.name
            )
        except OSError as error:
            messagebox.showerror("无法继续发布", str(error))
            return
        self._log("继续发布：当前未完成文件将从头上传，已确认文件直接复用。")
        self._start_publish(repo, profile, assets, previous_state, token)

    def _publish_paused(self, message: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_control = None
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="发布已暂停")
        self.adopt_remote_button.configure(state="disabled")
        pause_button.configure(state="normal", text="继续发布")
        status_label.configure(text="已暂停；继续时当前文件从头上传")
        self._log(f"{message}。已确认文件已保存；继续时当前文件会从头上传。")

    def _github_publish_paused(
        self, message: str, completed: frozenset[str]
    ) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        context = self._github_publish_resume_context
        if context is None:
            return
        owner, name, token, profile, assets, _previous_completed = context
        self._github_publish_resume_context = (
            owner, name, token, profile, assets, completed,
        )
        self._upload_control = None
        self._end_background_mutation("publish")
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="发布已暂停")
        pause_button.configure(state="normal", text="继续发布")
        status_label.configure(text="已暂停；继续时当前文件会从头上传")
        self._log(f"{message}。已完成的 GitHub 文件将保留，继续时会跳过。")

    def _show_upload_progress(
        self, index: int, total: int, name: str, sent: int, size: int
    ) -> None:
        now = time.monotonic()
        if self._upload_sample is None or self._upload_sample[0] != name:
            self._upload_sample = (name, sent, now)
            self._upload_speed = 0.0
        else:
            _, previous_sent, previous_time = self._upload_sample
            elapsed = now - previous_time
            if elapsed > 0:
                current_speed = max(0.0, sent - previous_sent) / elapsed
                self._upload_speed = (
                    current_speed
                    if self._upload_speed <= 0
                    else self._upload_speed * 0.65 + current_speed * 0.35
                )
            self._upload_sample = (name, sent, now)
        ratio = min(1.0, sent / size) if size else 0.0
        _publish_button, _pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        progress_bar.set(ratio)
        status_label.configure(
            text=(
                f"[{index}/{total}] {name} · {ratio * 100:.1f}% · "
                f"{self._format_transfer_size(sent)}/{self._format_transfer_size(size)} · "
                f"{self._format_transfer_size(self._upload_speed)}/s"
            )
        )

    @staticmethod
    def _format_transfer_size(value: float) -> str:
        if value >= 1024**3:
            return f"{value / 1024**3:.2f} GiB"
        if value >= 1024**2:
            return f"{value / 1024**2:.1f} MiB"
        if value >= 1024:
            return f"{value / 1024:.1f} KiB"
        return f"{value:.0f} B"

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
        if not self._begin_background_mutation(
            "local-action", "正在修改本地发布资源"
        ):
            return
        try:
            command()
            self.refresh()
            messagebox.showinfo("完成", success)
        except (WorkspaceError, OSError) as error:
            messagebox.showerror("操作失败", str(error))
        finally:
            self._end_background_mutation("local-action")

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

    def generate_client_hub(self) -> None:
        if not self._begin_background_mutation(
            "hub-generate", "正在生成客户端卡带中心"
        ):
            return
        self.hub_generate_button.configure(state="disabled", text="正在生成…")
        self.hub_publish_button.configure(state="disabled")
        default_game_id = "stellaris"

        def worker() -> None:
            try:
                assets = self.workspace.hub_publish_assets(
                    default_game_id=default_game_id
                )
                self._post_ui(lambda: self._hub_generation_done(assets))
            except Exception as error:
                self._post_ui(
                    lambda value=str(error): self._hub_generation_failed(value)
                )

        threading.Thread(target=worker, daemon=True).start()

    def _hub_generation_done(self, assets: tuple[PublishAsset, ...]) -> None:
        self._end_background_mutation("hub-generate")
        self.hub_generate_button.configure(state="normal", text="重新生成全部")
        self.hub_publish_button.configure(state="normal")
        self.refresh_cartridge_management()
        hub_dir = self.workspace.output_dir / "hub"
        self._log(
            f"客户端卡带中心已生成到 {hub_dir}："
            + "、".join(asset.name for asset in assets)
        )
        messagebox.showinfo(
            "生成完成",
            f"已生成 {len(assets)} 个 hub 文件。\n\n"
            "可直接点击“发布 hub Release”，无需手动上传。",
        )

    def _hub_generation_failed(self, message: str) -> None:
        self._end_background_mutation("hub-generate")
        self.hub_generate_button.configure(state="normal", text="重新生成全部")
        self.hub_publish_button.configure(state="normal")
        self.hub_upload_status.configure(text="生成失败")
        self._log(f"客户端卡带中心生成失败：{message}")
        messagebox.showerror("生成失败", message)

    def publish_cartridge_hub_mirror(self) -> None:
        """Regenerate the hub once and publish the same assets to both hosts."""
        profiles = self.workspace.list_games()
        if not profiles:
            messagebox.showerror("无法发布", "尚未配置任何游戏卡带")
            return
        if not self._save_active_settings():
            return
        targets = (
            (
                "GitLink", self.settings.owner, self.settings.repository,
                self.settings.token,
            ),
            (
                "GitHub", self.settings.github_owner,
                self.settings.github_repository, self.settings.github_token,
            ),
        )
        if not all(owner and repository and token for _, owner, repository, token in targets):
            messagebox.showerror(
                "无法双端发布",
                "请先在高级操作中分别填写并保存 GitLink 和 GitHub 的仓库及令牌。",
            )
            return
        if not messagebox.askyesno(
            "确认双端发布卡带中心",
            f"将重新生成 {len(profiles)} 张客户端卡带，并依次同步到：\n\n"
            f"GitLink · {targets[0][1]}/{targets[0][2]} · hub\n"
            f"GitHub · {targets[1][1]}/{targets[1][2]} · hub\n\n"
            "任一端失败时，已经完成的另一端会保留。是否继续？",
        ):
            return
        if not self._begin_background_mutation(
            "publish", "正在双端发布卡带中心"
        ):
            return
        self._active_publish_scope = "hub"
        self._set_publish_buttons_available(False)
        self.hub_generate_button.configure(state="disabled")
        self.hub_publish_button.configure(state="disabled", text="正在双端发布…")
        self.hub_upload_status.configure(text="正在生成完整卡带主表…")
        self.hub_upload_progress.set(0)
        self._upload_control = UploadControl()
        default_game_id = "stellaris"

        def worker() -> None:
            stage = "GitLink"
            try:
                assets = self.workspace.hub_publish_assets(
                    default_game_id=default_game_id
                )
                total = len(assets) * 2
                profile = self.workspace.hub_release_profile()
                gitlink_repo = GitLinkRepository(targets[0][1], targets[0][2])
                previous_state = self.workspace.load_publish_state(
                    profile, gitlink_repo.owner, gitlink_repo.name
                )
                manager = RemoteResourceManager(
                    GitLinkAttachmentClient(targets[0][3]), gitlink_repo
                )

                def gitlink_progress(
                    index: int, count: int, name: str, stage: str
                ) -> None:
                    self._post_ui(
                        lambda i=index, value=name, action=stage: self._log(
                            f"[GitLink {i}/{len(assets)}] {action} {value}"
                        )
                    )

                def gitlink_upload(
                    index: int, count: int, name: str, sent: int, size: int
                ) -> None:
                    self._queue_upload_progress(index, total, name, sent, size)

                result = manager.sync_release(
                    profile, assets, previous_state,
                    progress=gitlink_progress,
                    upload_progress=gitlink_upload,
                    upload_control=self._upload_control,
                    checkpoint=lambda state: self.workspace.save_publish_state(
                        profile, state
                    ),
                )
                self.workspace.save_publish_state(profile, result.state)
                self._post_ui(
                    lambda: self._log("GitLink hub Release 已同步完成，开始 GitHub。")
                )

                stage = "GitHub"
                github = GitHubReleaseClient(
                    GitHubRepository(targets[1][1], targets[1][2]),
                    targets[1][3],
                )
                release = github.ensure_release(profile.release_tag)
                reusable = {
                    str(item.get("name")): int(item.get("size") or 0)
                    for item in release.assets
                    if item.get("name") and item.get("size") is not None
                }
                for index, asset in enumerate(assets, start=1):
                    overall = len(assets) + index
                    if reusable.get(asset.name) == asset.size_bytes:
                        self._queue_upload_progress(
                            overall, total, asset.name,
                            asset.size_bytes, asset.size_bytes,
                        )
                        self._post_ui(
                            lambda i=index, value=asset.name: self._log(
                                f"[GitHub {i}/{len(assets)}] 复用附件 {value}"
                            )
                        )
                        continue
                    github.upload_asset(
                        release, asset.path, replace_existing=True,
                        progress=lambda sent, size, i=overall, value=asset.name: (
                            self._queue_upload_progress(
                                i, total, value, sent, size
                            )
                        ),
                        should_pause=lambda: bool(
                            self._upload_control
                            and self._upload_control.pause_requested
                        ),
                    )
                    self._post_ui(
                        lambda i=index, value=asset.name: self._log(
                            f"[GitHub {i}/{len(assets)}] 已上传 {value}"
                        )
                    )
                self._post_ui(
                    lambda count=len(assets): self._hub_mirror_publish_done(count)
                )
            except (UploadPaused, GitHubUploadPaused) as error:
                self._post_ui(
                    lambda value=f"{stage}：{error}": self._hub_mirror_publish_failed(
                        value, paused=True
                    )
                )
            except Exception as error:
                self._post_ui(
                    lambda value=f"{stage}：{error}": self._hub_mirror_publish_failed(value)
                )

        threading.Thread(
            target=worker, daemon=True, name="hub-mirror-publish"
        ).start()

    def _hub_mirror_publish_done(self, count: int) -> None:
        self._end_background_mutation("publish")
        self._upload_control = None
        self._set_publish_buttons_available(True)
        self.hub_generate_button.configure(state="normal")
        self.hub_upload_progress.set(1)
        self.hub_upload_status.configure(text="GitLink + GitHub 发布完成")
        self._log(f"卡带中心双端发布完成：每端 {count} 个附件。")
        self.refresh_cartridge_management()
        messagebox.showinfo(
            "卡带中心发布完成",
            "hub Release 已同步到 GitLink 和 GitHub。",
        )

    def _hub_mirror_publish_failed(
        self, message: str, *, paused: bool = False
    ) -> None:
        self._end_background_mutation("publish")
        self._upload_control = None
        self._set_publish_buttons_available(True)
        self.hub_generate_button.configure(state="normal")
        self.hub_publish_pause_button.configure(state="disabled", text="暂停发布")
        self.hub_upload_status.configure(
            text="双端发布已暂停" if paused else "双端发布失败"
        )
        self._log(f"卡带中心双端发布未完成：{message}")
        if paused:
            messagebox.showinfo("卡带中心发布已暂停", message)
        else:
            messagebox.showerror("卡带中心双端发布失败", message)

    def publish_cartridge_hub(self) -> None:
        profiles = self.workspace.list_games()
        if not profiles:
            messagebox.showerror("无法发布", "尚未配置任何游戏卡带")
            return
        owner = self.owner_entry.get().strip()
        repository_name = self.repo_entry.get().strip()
        if not owner or not repository_name:
            messagebox.showerror("无法发布", "请先在“构建与发布”中填写仓库信息")
            return
        target_name = "GitHub" if self._publish_target() == "github" else "GitLink"
        sync_note = (
            "GitHub 会按同名附件更新完整卡带中心。"
            if self._publish_target() == "github"
            else "未变化的卡带会直接复用；新增、修改和已删除的卡带会按主表同步。"
        )
        if not messagebox.askyesno(
            "确认发布卡带中心",
            f"重新生成 {len(profiles)} 张客户端卡带并同步到\n"
            f"{target_name} {owner}/{repository_name} · hub\n\n"
            f"{sync_note}是否继续？",
        ):
            return
        if not self._begin_background_mutation(
            "publish", "正在生成并上传 hub Release"
        ):
            return
        self._active_publish_scope = "hub"
        self._set_publish_buttons_available(False)
        self.hub_generate_button.configure(state="disabled")
        self.hub_upload_status.configure(text="正在生成完整卡带主表…")
        self.hub_upload_progress.set(0)
        token = self.token_entry.get().strip() or None
        profile = self.workspace.hub_release_profile()
        repo = GitLinkRepository(owner, repository_name)
        default_game_id = "stellaris"

        def worker() -> None:
            try:
                assets = self.workspace.hub_publish_assets(
                    default_game_id=default_game_id
                )
                previous_state = self.workspace.load_publish_state(
                    profile, owner, repository_name
                )
                self._post_ui(
                    lambda: self._hub_publish_prepared(
                        repo, profile, assets, previous_state, token
                    )
                )
            except Exception as error:
                self._post_ui(
                    lambda value=str(error): self._hub_publish_prepare_failed(value)
                )

        threading.Thread(target=worker, daemon=True).start()

    def _hub_publish_prepared(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        previous_state: dict[str, object],
        token: str | None,
    ) -> None:
        self.hub_generate_button.configure(state="normal")
        self.refresh_cartridge_management()
        if self._publish_target() == "github":
            if not token:
                self._hub_publish_prepare_failed("请填写 GitHub token")
                return
            self._start_github_publish(
                repo.owner, repo.name, token, profile, assets
            )
            return
        self._publish_resume_context = (repo, profile, assets, token)
        if not self._start_publish(repo, profile, assets, previous_state, token):
            self._publish_resume_context = None
            self._hub_publish_prepare_failed("无法启动 hub Release 发布")

    def _hub_publish_prepare_failed(self, message: str) -> None:
        self._end_background_mutation("publish")
        self._set_publish_buttons_available(True)
        self.hub_generate_button.configure(state="normal")
        self.hub_publish_pause_button.configure(state="disabled", text="暂停发布")
        self.hub_upload_status.configure(text="发布准备失败")
        self._log(f"hub Release 发布准备失败：{message}")
        messagebox.showerror("无法发布卡带中心", message)

    def export_client_hub(self) -> None:
        self.tabs.set("卡带管理")
        self.generate_client_hub()

    def open_hub_output_folder(self) -> None:
        path = self.workspace.output_dir / "hub"
        path.mkdir(parents=True, exist_ok=True)
        self._open(path)

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

    def _close_publisher(self) -> None:
        active = self.acceptance.active_preparations()
        if active:
            games = ", ".join(
                str(value.get("game_id", "未知游戏")) for value in active
            )
            if not messagebox.askyesno(
                "存在未恢复的测试环境",
                f"以下游戏仍保留人工构造的测试环境：\n{games}\n\n"
                "直接退出不会自动恢复游戏文件。确定仍要退出吗？",
            ):
                return
        background = self._active_background_mutations()
        if background:
            detail = "\n".join(f"• {label}" for label in background)
            if self._upload_control is not None:
                messagebox.showwarning(
                    "发布仍在进行，暂时无法退出",
                    f"以下后台操作尚未安全结束：\n{detail}\n\n"
                    "请先点击“暂停发布”，并等待界面明确显示“发布已暂停”后再退出。\n"
                    "现在直接关闭可能中断当前附件，并使远程附件与本地发布记录不一致。",
                )
            else:
                messagebox.showwarning(
                    "后台操作尚未完成",
                    f"以下后台操作尚未安全结束：\n{detail}\n\n"
                    "请等待操作完成后再退出，以免留下不完整的本地文件或发布状态。",
                )
            return
        self._ui_pump_running = False
        self.destroy()
