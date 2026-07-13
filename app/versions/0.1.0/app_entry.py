from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path
from queue import Empty, SimpleQueue
from urllib.parse import urlparse

import customtkinter as ctk
from tkinter import BooleanVar, TclError, filedialog, messagebox

from .signriver_app.adapters import AdapterRegistry
from .signriver_app.adapters.builtin import create_builtin_adapters
from .signriver_app.adapters.stellaris import discover_installed_dlc, remove_installed_dlc
from .signriver_app.application import DlcInstallService, DownloadQueue, GameDiscoveryService, StellarisCatalogService
from .signriver_app.domain import DownloadSpec, DownloadState, InstallHealth, UserSettings
from .signriver_app.infrastructure.catalog import GitLinkReleaseSource, GitLinkSourceConfig
from .signriver_app.infrastructure.catalog import inspect_stellaris_package
from .signriver_app.infrastructure.cache import CacheMaintenance
from .signriver_app.infrastructure.downloads import DownloadManager, DownloadPolicy
from .signriver_app.infrastructure.diagnostics import DiagnosticExporter
from .signriver_app.infrastructure.installs import StellarisInstallEngine
from .signriver_app.infrastructure.speed_test import measure_download_speed
from .signriver_app.infrastructure.persistence import (
    Database,
    DownloadTaskRepository,
    GameInstallationRepository,
    InstallReceiptRepository,
    UserSettingsRepository,
)


UI = {
    "brand": "#3A7EBF",
    "primary": "#1976D2",
    "primary_hover": "#1565C0",
    "secondary": "#42A5F5",
    "secondary_hover": "#1E88E5",
    "page": "#F5F7FA",
    "card": "#FFFFFF",
    "panel": "#FAFAFA",
    "border": "#E0E0E0",
    "input_border": "#BDBDBD",
    "text": "#212121",
    "text_secondary": "#3E454A",
    "muted": "#9E9E9E",
    "on_blue": "#FFFFFF",
    "success": "#2E7D32",
    "danger": "#E53935",
    "danger_hover": "#C62828",
    "danger_surface": "#FFF1F0",
    "danger_surface_hover": "#FFE1DE",
}


def _card(parent, **kwargs):
    return ctk.CTkFrame(
        parent,
        fg_color=UI["card"],
        border_color=UI["border"],
        border_width=1,
        corner_radius=14,
        **kwargs,
    )


def _combo_box(parent, *, values, width, command=None):
    options = {
        "values": values,
        "width": width,
        "state": "readonly",
        "fg_color": UI["card"],
        "border_color": UI["input_border"],
        "border_width": 1,
        "button_color": UI["primary"],
        "button_hover_color": UI["primary_hover"],
        "text_color": UI["text"],
        "dropdown_fg_color": UI["card"],
        "dropdown_hover_color": "#EAF3FB",
        "dropdown_text_color": UI["text"],
        "corner_radius": 8,
    }
    if command is not None:
        options["command"] = command
    return ctk.CTkComboBox(parent, **options)


class DlcHubApplication:
    def __init__(self, context) -> None:
        self.context = context
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        self.window = ctk.CTk()
        self.window.title("SignRiver DLC Hub")
        self.window.geometry("1120x840")
        self.window.minsize(1000, 700)
        self.window.configure(fg_color=UI["page"])
        self.ui_events = SimpleQueue()
        self.pending_download_snapshots = {}
        self.pending_download_lock = threading.Lock()
        self.ui_event_pump_running = True
        self.discovery = None
        release_source = GitLinkReleaseSource(
            GitLinkSourceConfig("signriver", "file-warehouse")
        )
        self.catalog = StellarisCatalogService(release_source)
        self.user_settings = UserSettings()
        self.settings_repository = None
        self.download_manager = DownloadManager(self.context.paths.cache)
        self.cache_maintenance = CacheMaintenance(self.context.paths.cache)
        self.diagnostic_exporter = DiagnosticExporter(
            self.context.paths.root, self.context.paths.data
        )
        self.last_log_content = ""
        self.catalog_entries = ()
        self.catalog_rows = {}
        self.simple_status_labels = {}
        self.catalog_selection_widgets = {}
        self.catalog_entry_frames = {}
        self.catalog_name_labels = {}
        self.catalog_view_mode = "simple"
        self.simple_catalog_columns = 5
        self.selected_dlc_ids = set()
        self.catalog_selection_initialized = False
        self.dlc_selection_vars = {}
        self.batch_download_state = "idle"
        self.batch_download_task_ids = ()
        self.batch_pause_poll_pending = False
        self.batch_cancel_poll_pending = False
        self.auto_install_worker_running = False
        self.auto_install_attempted = set()
        self.speed_test_running = False
        self.download_repository = None
        self.download_queue = None
        self.install_repository = None
        self.install_service = None
        self.task_refresh_pending = False
        self.compact_layout = None
        self.supported_games = {
            "Stellaris · Steam": {
                "game_id": "stellaris",
                "platform": "Steam",
                "store_app_id": "281990",
            }
        }
        self.selected_game_name = "Stellaris · Steam"
        self.catalog_online = False
        self.notice_serial = 0
        self.current_installation = None
        self.installed_dlc_paths = {}
        try:
            registry = AdapterRegistry(create_builtin_adapters())
            database = Database(self.context.paths.data / "hub.db")
            self.settings_repository = UserSettingsRepository(database)
            stored_settings = self.settings_repository.load()
            self.user_settings = UserSettings(
                download_concurrency=1,
                bandwidth_limit_kib=stored_settings.bandwidth_limit_kib,
                onboarding_completed=stored_settings.onboarding_completed,
            )
            if stored_settings.download_concurrency != 1:
                self.settings_repository.save(self.user_settings)
            self.download_manager = DownloadManager(
                self.context.paths.cache,
                policy=DownloadPolicy(
                    max_bytes_per_second=(
                        self.user_settings.bandwidth_limit_kib * 1024
                        if self.user_settings.bandwidth_limit_kib else None
                    )
                ),
            )
            repository = GameInstallationRepository(database)
            self.download_repository = DownloadTaskRepository(database)
            self.install_repository = InstallReceiptRepository(database)
            self.install_service = DlcInstallService(
                StellarisInstallEngine(self.context.paths.data),
                self.install_repository,
            )
            self.discovery = GameDiscoveryService(registry, repository)
            self.download_queue = DownloadQueue(
                self.download_manager,
                repository=self.download_repository,
                max_concurrent=1,
                on_change=self._queue_download_event,
                verifier_for=self._package_verifier_for,
            )
        except Exception:
            self.context.logger.exception("Unable to initialize game discovery")
        self._build_ui()
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.after(50, self._drain_ui_events)
        self._show_recovered_downloads()
        self.window.after(900, self._show_onboarding)
        self.window.after(1200, self._update_global_status)
        self.window.after(350, self._scan_games)
        self.window.after(500, self._refresh_catalog)
        if self.context.updates.enabled and self.context.updates.check_on_startup:
            self.window.after(800, self._check_update)

    def _build_ui(self) -> None:
        shell = ctk.CTkFrame(self.window, fg_color=UI["page"])
        shell.pack(fill="both", expand=True)
        sidebar = ctk.CTkFrame(
            shell, width=174, corner_radius=0, fg_color=UI["card"],
            border_width=0,
        )
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.sidebar = sidebar
        ctk.CTkLabel(
            sidebar, text="SignRiver", text_color=UI["primary"],
            font=ctk.CTkFont(size=23, weight="bold")
        ).pack(anchor="w", padx=22, pady=(30, 4))
        ctk.CTkLabel(
            sidebar, text="DLC HUB", text_color=UI["muted"],
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=23, pady=(0, 24))
        self.navigation_buttons = {}
        for page_name in ("DLC 库", "下载任务", "日志", "设置", "关于"):
            button = ctk.CTkButton(
                sidebar, text=page_name, anchor="w", width=130, height=38,
                fg_color="transparent", text_color=UI["text_secondary"],
                hover_color="#EAF3FB", corner_radius=9,
                command=lambda page_name=page_name: self._show_page(page_name),
            )
            button.pack(fill="x", padx=14, pady=3)
            self.navigation_buttons[page_name] = button
        self.global_status = ctk.CTkLabel(
            sidebar, text="网络：等待\n任务：0\n缓存：计算中",
            justify="left", anchor="w", text_color=UI["muted"],
        )
        self.global_status.pack(side="bottom", fill="x", padx=18, pady=(8, 22))
        self.global_notice = ctk.CTkLabel(
            sidebar, text="", justify="left", anchor="w", wraplength=128,
        )
        self.global_notice.pack(side="bottom", fill="x", padx=18, pady=4)

        container = ctk.CTkFrame(shell, fg_color=UI["page"], corner_radius=0)
        container.pack(side="right", fill="both", expand=True, padx=30, pady=24)
        self.content_container = container

        topbar = ctk.CTkFrame(
            container, fg_color=UI["brand"], corner_radius=14, height=104
        )
        topbar.pack(fill="x", pady=(0, 24))
        title_group = ctk.CTkFrame(topbar, fg_color="transparent")
        title_group.pack(side="left", padx=24, pady=20)
        ctk.CTkLabel(
            title_group, text="SignRiver DLC Hub",
            text_color=UI["on_blue"],
            font=ctk.CTkFont(size=30, weight="bold"),
        ).pack(anchor="w")
        self.top_health = ctk.CTkLabel(
            title_group, text="Stellaris · 等待路径检测",
            text_color="#E8F2FA", font=ctk.CTkFont(size=14),
        )
        self.top_health.pack(anchor="w", pady=(3, 0))
        profile_group = ctk.CTkFrame(topbar, fg_color="transparent")
        profile_group.pack(side="right", padx=22, pady=24)
        ctk.CTkLabel(
            profile_group, text="SignRiver", text_color=UI["on_blue"],
            font=ctk.CTkFont(weight="bold")
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            profile_group, text="GitHub", width=68,
            command=lambda: self._open_external_link(
                "https://github.com/sign-river/SignRiver-DLC-Hub"
            ),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            profile_group, text="资源仓库", width=78,
            command=lambda: self._open_external_link(
                "https://www.gitlink.org.cn/signriver/file-warehouse"
            ),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            profile_group, text="B站", width=52,
            command=lambda: self._open_external_link(
                "https://space.bilibili.com/504574253?spm_id_from=333.1007.0.0"
            ),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            profile_group, text="QQ群 1061299021", width=118,
            command=self._copy_qq_group,
        ).pack(side="left", padx=(3, 0))

        self.page_host = ctk.CTkFrame(container, fg_color=UI["page"], corner_radius=0)
        self.page_host.pack(fill="both", expand=True)

        game_card = _card(self.page_host)
        self.game_card = game_card
        game_card.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(
            game_card,
            text="游戏检测",
            text_color=UI["primary"],
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(12, 2))
        selector_row = ctk.CTkFrame(game_card, fg_color="transparent")
        selector_row.pack(fill="x", padx=24, pady=(0, 2))
        ctk.CTkLabel(selector_row, text="当前游戏").pack(side="left")
        self.game_selector = _combo_box(
            selector_row, values=list(self.supported_games), width=190,
            command=self._select_game,
        )
        self.game_selector.set(self.selected_game_name)
        self.game_selector.pack(side="left", padx=(10, 0))
        self.platform_status = ctk.CTkLabel(
            selector_row, text="Steam · App 281990",
            text_color=UI["muted"],
        )
        self.platform_status.pack(side="right")
        self.game_status = ctk.CTkLabel(
            selector_row,
            text="Stellaris · 等待扫描",
            anchor="w",
            text_color=UI["text_secondary"],
        )
        self.game_status.pack(side="left", padx=(14, 0))
        self.game_path = ctk.CTkLabel(
            game_card,
            text="尚未检测游戏路径",
            anchor="w",
            text_color=UI["text_secondary"],
            wraplength=760,
        )
        self.game_path.pack(fill="x", padx=24, pady=(2, 8))

        game_actions = ctk.CTkFrame(game_card, fg_color="transparent")
        game_actions.pack(fill="x", padx=24, pady=(0, 12))
        self.game_scan_button = ctk.CTkButton(
            game_actions,
            text="重新扫描",
            command=self._scan_games,
            width=110,
        )
        self.game_scan_button.pack(side="left")
        self.game_path_button = ctk.CTkButton(
            game_actions,
            text="选择目录",
            command=self._choose_game_path,
            width=110,
        )
        self.game_path_button.pack(side="left", padx=(10, 0))
        self.open_game_button = ctk.CTkButton(
            game_actions,
            text="打开目录",
            command=self._open_game_directory,
            state="disabled",
            width=110,
        )
        self.open_game_button.pack(side="right", padx=(10, 0))
        self.launch_game_button = ctk.CTkButton(
            game_actions,
            text="启动游戏",
            command=self._launch_game,
            state="disabled",
            width=110,
        )
        self.launch_game_button.pack(side="right")

        catalog_card = _card(self.page_host)
        self.catalog_card = catalog_card
        catalog_card.pack(fill="x", pady=(0, 18))
        catalog_header = ctk.CTkFrame(catalog_card, fg_color="transparent")
        catalog_header.pack(fill="x", padx=24, pady=(16, 6))
        ctk.CTkLabel(
            catalog_header,
            text="DLC 列表",
            text_color=UI["primary"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")
        self.catalog_refresh_button = ctk.CTkButton(
            catalog_header,
            text="刷新目录",
            command=self._refresh_catalog,
            width=100,
        )
        self.catalog_refresh_button.pack(side="right")
        self.advanced_view_button = ctk.CTkButton(
            catalog_header,
            text="高级管理",
            command=self._toggle_catalog_view,
            width=100,
        )
        self.advanced_view_button.pack(side="right", padx=(0, 8))
        self.catalog_status = ctk.CTkLabel(
            catalog_card,
            text="等待读取 GitLink · ste Release",
            anchor="w",
        )
        self.catalog_status.pack(fill="x", padx=24)
        self.catalog_preview = ctk.CTkLabel(
            catalog_card,
            text="下载和安装功能尚未启用",
            anchor="w",
            text_color=UI["muted"],
        )
        self.catalog_preview.pack(fill="x", padx=24, pady=(2, 16))
        catalog_tools = ctk.CTkFrame(catalog_card, fg_color="transparent")
        catalog_tools.pack(fill="x", padx=24, pady=(0, 8))
        self.catalog_search = ctk.CTkEntry(
            catalog_tools, placeholder_text="搜索 DLC 编号或名称", width=240
        )
        self.catalog_search.pack(side="left")
        self.catalog_search.bind("<KeyRelease>", lambda _event: self._render_catalog_rows())
        self.catalog_filter = _combo_box(
            catalog_tools,
            values=["全部状态", "未下载", "进行中", "已暂停", "已完成", "失败"],
            command=lambda _value: self._render_catalog_rows(),
            width=110,
        )
        self.catalog_filter.set("全部状态")
        self.catalog_filter.pack(side="left", padx=(8, 0))
        self.download_selected_button = ctk.CTkButton(
            catalog_tools, text="一键下载所选", command=self._download_selected, width=124
        )
        self.download_selected_button.pack(side="right")
        self.cancel_all_downloads_button = ctk.CTkButton(
            catalog_tools, text="取消全部下载",
            command=self._cancel_all_downloads, width=104,
        )
        self.cancel_all_downloads_button.pack(side="right", padx=(0, 8))
        self.selection_toggle_button = ctk.CTkButton(
            catalog_tools, text="全选", command=self._toggle_visible_selection,
            width=86,
        )
        self.selection_toggle_button.pack(side="right", padx=(0, 8))
        catalog_management_tools = ctk.CTkFrame(catalog_card, fg_color="transparent")
        catalog_management_tools.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkButton(
            catalog_management_tools, text="一键移除补丁",
            command=self._show_patch_removal_placeholder, width=112,
        ).pack(side="right")
        ctk.CTkButton(
            catalog_management_tools, text="卸载全部 DLC",
            command=self._uninstall_all_dlc, width=112,
        ).pack(side="right", padx=(0, 8))
        self.dlc_list_frame = ctk.CTkScrollableFrame(
            catalog_card, height=250, fg_color=UI["panel"], corner_radius=10,
            border_width=1, border_color=UI["border"],
            scrollbar_button_color=UI["input_border"],
            scrollbar_button_hover_color=UI["muted"],
        )
        self.dlc_list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        for column in range(4):
            self.dlc_list_frame.grid_columnconfigure(column, weight=1, uniform="dlc")

        card = _card(self.page_host)
        self.about_card = card
        card.pack(fill="x")
        ctk.CTkLabel(
            card,
            text="模块化更新框架已就绪",
            text_color=UI["primary"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(22, 6))
        ctk.CTkLabel(
            card,
            text=(
                f"应用模块 v{self.context.app_version}  ·  "
                f"启动器 v{self.context.launcher_version}  ·  API {self.context.api_version}"
            ),
        ).pack(anchor="w", padx=24)

        self.progress = ctk.CTkProgressBar(card, mode="determinate")
        self.progress.set(0)
        self.progress.pack(fill="x", padx=24, pady=(22, 6))
        self.status = ctk.CTkLabel(card, text="尚未检查更新", anchor="w")
        self.status.pack(fill="x", padx=24)

        self.update_button = ctk.CTkButton(
            card,
            text="检查更新",
            command=self._check_update,
            width=140,
        )
        self.update_button.pack(anchor="e", padx=24, pady=22)

        settings_card = _card(self.page_host)
        self.settings_card = settings_card
        settings_card.pack(fill="x", pady=(18, 0))
        ctk.CTkLabel(
            settings_card, text="下载设置", text_color=UI["primary"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(18, 8))
        settings_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_row.pack(fill="x", padx=24)
        ctk.CTkLabel(settings_row, text="下载模式").pack(side="left")
        ctk.CTkLabel(
            settings_row,
            text="单线程顺序下载（固定）",
            text_color=UI["text_secondary"],
        ).pack(side="left", padx=(8, 24))
        ctk.CTkLabel(settings_row, text="限速 KiB/s（留空不限速）").pack(side="left")
        self.bandwidth_entry = ctk.CTkEntry(settings_row, width=110)
        if self.user_settings.bandwidth_limit_kib:
            self.bandwidth_entry.insert(0, str(self.user_settings.bandwidth_limit_kib))
        self.bandwidth_entry.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            settings_row, text="保存设置", command=self._save_settings, width=90
        ).pack(side="right")

        utility_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        utility_row.pack(fill="x", padx=24, pady=(12, 8))
        ctk.CTkButton(
            utility_row, text="打开缓存目录",
            command=lambda: self._open_path(self.context.paths.cache), width=110,
        ).pack(side="left")
        ctk.CTkButton(
            utility_row, text="分析并清理缓存",
            command=self._cleanup_cache, width=120,
        ).pack(side="left", padx=(8, 0))
        self.speed_test_button = ctk.CTkButton(
            utility_row, text="测试下载速度",
            command=self._run_speed_test, width=110,
        )
        self.speed_test_button.pack(side="left", padx=(8, 0))
        self.settings_status = ctk.CTkLabel(
            utility_row, text="设置修改后重启程序生效", anchor="e"
        )
        self.settings_status.pack(side="right")
        ctk.CTkLabel(
            settings_card,
            text="设置会在下次启动时应用，不会中断当前下载。",
            text_color=UI["muted"],
        ).pack(anchor="w", padx=24, pady=(0, 18))

        self.task_card = _card(self.page_host)
        task_header = ctk.CTkFrame(self.task_card, fg_color="transparent")
        task_header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(
            task_header, text="下载任务", text_color=UI["primary"],
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            task_header, text="刷新", command=self._refresh_task_page, width=80
        ).pack(side="right")
        ctk.CTkButton(
            task_header, text="清除失败/取消记录",
            command=self._clear_terminal_tasks, width=110,
        ).pack(side="right", padx=(0, 8))
        ctk.CTkButton(
            task_header, text="清除全部记录",
            command=self._clear_all_tasks, width=100,
        ).pack(side="right", padx=(0, 8))
        self.task_list_frame = ctk.CTkScrollableFrame(
            self.task_card, height=480, fg_color=UI["panel"], corner_radius=10,
            border_width=1, border_color=UI["border"],
        )
        self.task_list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        self.log_card = _card(self.page_host)
        log_header = ctk.CTkFrame(self.log_card, fg_color="transparent")
        log_header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(
            log_header, text="运行日志", text_color=UI["primary"],
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            log_header, text="打开日志目录",
            command=lambda: self._open_path(self.context.paths.data / "logs"), width=110,
        ).pack(side="right")
        ctk.CTkButton(
            log_header, text="刷新", command=self._refresh_log_preview, width=80
        ).pack(side="right", padx=(0, 8))
        log_tools = ctk.CTkFrame(self.log_card, fg_color="transparent")
        log_tools.pack(fill="x", padx=24, pady=(0, 8))
        self.log_level_filter = _combo_box(
            log_tools, values=["全部", "INFO", "WARNING", "ERROR"], width=100,
            command=lambda _value: self._refresh_log_preview(),
        )
        self.log_level_filter.set("全部")
        self.log_level_filter.pack(side="left")
        self.log_search = ctk.CTkEntry(
            log_tools, placeholder_text="筛选日志关键词", width=220
        )
        self.log_search.pack(side="left", padx=(8, 0))
        self.log_search.bind("<KeyRelease>", lambda _event: self._refresh_log_preview())
        ctk.CTkButton(
            log_tools, text="复制当前日志", command=self._copy_log, width=105
        ).pack(side="right")
        ctk.CTkButton(
            log_tools, text="导出诊断包", command=self._export_diagnostics, width=100
        ).pack(side="right", padx=(0, 8))
        self.log_preview = ctk.CTkTextbox(
            self.log_card, height=520, wrap="word", fg_color=UI["panel"],
            border_width=1, border_color=UI["border"], text_color=UI["text_secondary"],
            corner_radius=10,
        )
        self.log_preview.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.log_preview.configure(state="disabled")
        self.window.after(50, self._refresh_log_preview)

        self.footer_label = ctk.CTkLabel(
            self.page_host,
            text="Stellaris Steam 已接入 · 模块化多游戏架构",
            text_color=UI["muted"],
        )
        self.footer_label.pack(anchor="w", pady=(24, 0))
        self.page_sections = {
            "DLC 库": (self.game_card, self.catalog_card),
            "下载任务": (self.task_card,),
            "日志": (self.log_card,),
            "设置": (self.settings_card,),
            "关于": (self.about_card, self.footer_label),
        }
        self._apply_visual_theme(shell)
        self._show_page("DLC 库")
        self.window.bind("<Configure>", self._on_window_resize, add="+")

    def _on_window_resize(self, event) -> None:
        if event.widget is not self.window:
            return
        compact = event.width < 1080
        columns = 4 if compact else 5
        layout_changed = compact != self.compact_layout
        columns_changed = columns != self.simple_catalog_columns
        if layout_changed:
            self.compact_layout = compact
            self.sidebar.configure(width=150 if compact else 174)
            self.content_container.pack_configure(
                padx=20 if compact else 30,
                pady=18 if compact else 24,
            )
            available = max(560, event.width - (210 if compact else 260))
            self.game_path.configure(wraplength=available)
            self.catalog_status.configure(wraplength=available)
        if columns_changed:
            self.simple_catalog_columns = columns
            if self.catalog_entries and self.catalog_view_mode == "simple":
                self.window.after_idle(self._render_catalog_rows)

    def _apply_visual_theme(self, root) -> None:
        """Apply the shared visual language to static and newly-created widgets."""
        navigation = set(getattr(self, "navigation_buttons", {}).values())
        self._style_widget(root, navigation)
        self._apply_visual_theme_to_children(root, navigation)

    def _style_widget(self, widget, navigation) -> None:
        if isinstance(widget, ctk.CTkButton) and widget not in navigation:
            text = str(widget.cget("text"))
            if (
                text in {"取消", "卸载"}
                or text.startswith("清除")
                or text.startswith("取消全部")
                or text.startswith("卸载全部")
            ):
                widget.configure(
                    fg_color=UI["danger_surface"],
                    hover_color=UI["danger_surface_hover"],
                    text_color=UI["danger"], border_width=1,
                    border_color=UI["danger"], corner_radius=8, height=34,
                )
                return
            elif text in {"下载所选", "一键下载所选", "启动游戏", "保存设置", "检查更新", "安装"}:
                colors = (UI["primary"], UI["primary_hover"])
            else:
                colors = (UI["secondary"], UI["secondary_hover"])
            widget.configure(
                fg_color=colors[0], hover_color=colors[1],
                text_color=UI["on_blue"], border_width=0,
                corner_radius=8, height=34,
            )
        elif isinstance(widget, ctk.CTkEntry):
            widget.configure(
                fg_color=UI["panel"], border_color=UI["input_border"],
                text_color=UI["text"], placeholder_text_color=UI["muted"],
                corner_radius=8,
            )
        elif isinstance(widget, ctk.CTkComboBox):
            widget.configure(
                fg_color=UI["card"], border_color=UI["input_border"],
                border_width=1, button_color=UI["primary"],
                button_hover_color=UI["primary_hover"], text_color=UI["text"],
                dropdown_fg_color=UI["card"], dropdown_hover_color="#EAF3FB",
                dropdown_text_color=UI["text"], corner_radius=8,
            )
        elif isinstance(widget, ctk.CTkCheckBox):
            widget.configure(
                fg_color=UI["primary"], hover_color=UI["primary_hover"],
                border_color=UI["input_border"], corner_radius=5,
            )
        elif isinstance(widget, ctk.CTkProgressBar):
            widget.configure(
                fg_color=UI["border"], progress_color=UI["primary"],
                corner_radius=6,
            )

    def _apply_visual_theme_to_children(self, root, navigation) -> None:
        for widget in root.winfo_children():
            self._style_widget(widget, navigation)
            self._apply_visual_theme_to_children(widget, navigation)

    def _set_game_buttons(self, state: str) -> None:
        self.game_scan_button.configure(state=state)
        self.game_path_button.configure(state=state)

    def _select_game(self, display_name: str) -> None:
        try:
            game = self.supported_games[display_name]
        except KeyError:
            return
        self.selected_game_name = display_name
        self.platform_status.configure(
            text=f"{game['platform']} · App {game['store_app_id']}"
        )
        self.top_health.configure(text=f"{display_name} · 正在刷新")
        self._scan_games()
        self._refresh_catalog()

    def _open_external_link(self, url: str) -> None:
        parsed = urlparse(url)
        allowed_hosts = {
            "github.com", "space.bilibili.com",
            "www.gitlink.org.cn", "gitlink.org.cn",
        }
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            messagebox.showerror(
                "链接被阻止", "只允许打开预先配置的项目 HTTPS 链接。",
                parent=self.window,
            )
            return
        webbrowser.open(url)

    def _copy_qq_group(self) -> None:
        group_number = "1061299021"
        self.window.clipboard_clear()
        self.window.clipboard_append(group_number)
        self.window.update_idletasks()
        self._notify(f"QQ群号已复制：{group_number}")

    def _show_page(self, page_name: str) -> None:
        self.current_page = page_name
        for sections in self.page_sections.values():
            for section in sections:
                section.pack_forget()
        sections = self.page_sections[page_name]
        for index, section in enumerate(sections):
            if page_name == "DLC 库" and section is self.catalog_card:
                section.pack(fill="both", expand=True)
            elif page_name in {"下载任务", "日志"}:
                section.pack(fill="both", expand=True)
            elif page_name == "关于" and section is self.footer_label:
                section.pack(anchor="w", pady=(18, 0))
            else:
                bottom = 18 if index < len(sections) - 1 else 0
                section.pack(fill="x", pady=(0, bottom))
        for name, button in self.navigation_buttons.items():
            button.configure(
                fg_color=UI["primary"] if name == page_name else "transparent",
                text_color=UI["on_blue"] if name == page_name else UI["text_secondary"],
                hover_color=UI["primary_hover"] if name == page_name else "#EAF3FB",
            )
        if page_name == "下载任务":
            self._refresh_task_page()
        elif page_name == "日志":
            self._refresh_log_preview()

    def _refresh_task_page(self) -> None:
        self.task_refresh_pending = False
        for child in self.task_list_frame.winfo_children():
            child.destroy()
        snapshots = self.download_queue.snapshots() if self.download_queue is not None else ()
        if not snapshots:
            ctk.CTkLabel(
                self.task_list_frame, text="暂无下载任务"
            ).pack(pady=40)
            return
        labels = {
            DownloadState.QUEUED: "排队中",
            DownloadState.DOWNLOADING: "下载中",
            DownloadState.PAUSING: "正在暂停",
            DownloadState.PAUSED: "已暂停",
            DownloadState.RETRYING: "等待重试",
            DownloadState.VERIFYING: "校验中",
            DownloadState.READY: "已完成",
            DownloadState.CANCELLED: "已取消",
            DownloadState.FAILED: "失败",
            DownloadState.CORRUPT: "坏包",
        }
        for snapshot in snapshots:
            row = ctk.CTkFrame(
                self.task_list_frame, fg_color=UI["card"], corner_radius=10,
                border_width=1, border_color=UI["border"], height=68,
            )
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)
            active = snapshot.state in {
                DownloadState.QUEUED, DownloadState.DOWNLOADING,
                DownloadState.PAUSING, DownloadState.RETRYING,
                DownloadState.VERIFYING,
            }
            is_batch_task = snapshot.spec.task_id in self.batch_download_task_ids
            if active or snapshot.state in {DownloadState.PAUSED, DownloadState.FAILED}:
                actions = ctk.CTkFrame(row, fg_color="transparent", height=34)
                actions.pack(side="right", padx=(8, 12), pady=16)
                if snapshot.state is DownloadState.FAILED or (
                    snapshot.state is DownloadState.PAUSED and not is_batch_task
                ):
                    ctk.CTkButton(
                        actions,
                        text="重试" if snapshot.state is DownloadState.FAILED else "重新下载",
                        width=72,
                        command=lambda task_id=snapshot.spec.task_id: self._task_action(
                            task_id, "resume"
                        ),
                    ).pack(side="left")
                if active or snapshot.state is DownloadState.PAUSED:
                    ctk.CTkButton(
                        actions, text="取消", width=64,
                        command=lambda task_id=snapshot.spec.task_id: self._task_action(
                            task_id, "cancel"
                        ),
                    ).pack(side="left", padx=(6, 0))
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True, padx=(14, 4), pady=7)
            ctk.CTkLabel(
                info, text=snapshot.spec.filename, anchor="w", height=23,
            ).pack(fill="x")
            state = labels.get(snapshot.state, str(snapshot.state))
            speed = (
                f" · {snapshot.speed_bytes_per_second / 1024:.1f} KiB/s"
                if snapshot.speed_bytes_per_second else ""
            )
            error_states = {
                DownloadState.RETRYING, DownloadState.FAILED, DownloadState.CORRUPT,
            }
            error = (
                f" · {snapshot.error}"
                if snapshot.error and snapshot.state in error_states else ""
            )
            ctk.CTkLabel(
                info,
                text=(
                    f"{state} · {snapshot.bytes_downloaded / 1024:.1f} KiB"
                    f"{speed}{error}"
                ),
                anchor="w", height=20, text_color=("gray40", "gray70"),
            ).pack(fill="x")
            self._apply_visual_theme_to_children(
                row, set(self.navigation_buttons.values())
            )

    def _schedule_task_refresh(self) -> None:
        if self.task_refresh_pending:
            return
        self.task_refresh_pending = True
        self.window.after(600, self._refresh_task_page)

    def _task_action(self, task_id: str, action: str) -> None:
        if self.download_queue is None:
            return
        try:
            if action == "cancel":
                self.download_queue.cancel(task_id)
            elif action == "resume":
                future = self.download_queue.resume(task_id)
                future.add_done_callback(self._download_finished)
            self._schedule_task_refresh()
        except Exception as error:
            messagebox.showerror("任务操作失败", str(error), parent=self.window)

    def _clear_terminal_tasks(self) -> None:
        if self.download_queue is None:
            return
        count = self.download_queue.clear_terminal()
        self._refresh_task_page()
        self.catalog_preview.configure(text=f"已清除 {count} 条终态任务记录")

    def _clear_all_tasks(self) -> None:
        if self.download_queue is None:
            return
        snapshots = self.download_queue.snapshots()
        if not snapshots:
            self._refresh_task_page()
            return
        if not messagebox.askyesno(
            "清除全部下载记录",
            "只清除任务历史，不删除下载缓存或已安装 DLC。\n"
            "正在运行的任务需要先暂停或取消。是否继续？",
            parent=self.window,
        ):
            return
        try:
            count = self.download_queue.clear_all()
            self.batch_download_task_ids = ()
            self._set_batch_download_state("idle")
            self._refresh_task_page()
            self.catalog_preview.configure(text=f"已清除全部 {count} 条下载任务记录")
        except ValueError:
            messagebox.showwarning(
                "仍有下载任务运行",
                "请先暂停或取消当前下载任务，再清除全部记录。",
                parent=self.window,
            )
        except Exception as error:
            self.context.logger.exception("Unable to clear all download tasks")
            messagebox.showerror("清除记录失败", str(error), parent=self.window)

    def _cleanup_cache(self) -> None:
        snapshots = self.download_queue.snapshots() if self.download_queue is not None else ()
        protected = [
            item.result_path for item in snapshots
            if item.state is DownloadState.READY and item.result_path is not None
        ]
        if self.install_repository is not None:
            try:
                protected.extend(
                    self.context.paths.cache / "packages" / receipt.package_sha256
                    for receipt in self.install_repository.active()
                )
            except Exception:
                self.context.logger.exception("Unable to enumerate installed package references")
        active_ids = [
            item.spec.task_id for item in snapshots
            if item.state not in {
                DownloadState.READY, DownloadState.CANCELLED,
                DownloadState.FAILED, DownloadState.CORRUPT,
            }
        ]
        try:
            usage = self.cache_maintenance.usage_bytes()
            plan = self.cache_maintenance.plan(
                protected_paths=protected, active_task_ids=active_ids
            )
            if not plan.paths:
                self.settings_status.configure(
                    text=f"缓存 {usage / 1048576:.1f} MiB，无可安全清理内容"
                )
                return
            if not messagebox.askyesno(
                "确认清理缓存",
                f"当前缓存 {usage / 1048576:.1f} MiB。\n"
                f"将删除 {plan.file_count} 个无引用/隔离文件，释放约 "
                f"{plan.bytes_to_remove / 1048576:.1f} MiB。是否继续？",
                parent=self.window,
            ):
                return
            self.cache_maintenance.execute(plan)
            self.settings_status.configure(
                text=f"已清理 {plan.file_count} 个文件，释放 {plan.bytes_to_remove / 1048576:.1f} MiB"
            )
        except Exception as error:
            self.context.logger.exception("Cache cleanup failed")
            messagebox.showerror("缓存清理失败", str(error), parent=self.window)

    def _run_speed_test(self) -> None:
        if self.speed_test_running:
            return
        self.speed_test_running = True
        self.speed_test_button.configure(state="disabled", text="正在测速……")
        self.settings_status.configure(text="正在从 GitLink 下载测速文件……")
        url = "https://gitlink.org.cn/signriver/file-warehouse/releases/download/test/test.bin"

        def worker() -> None:
            try:
                result = measure_download_speed(url)
                self._post_ui(lambda result=result: self._finish_speed_test(result))
            except Exception as error:
                self.context.logger.exception("Download speed test failed")
                message = str(error)
                self._post_ui(lambda message=message: self._finish_speed_test_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_speed_test(self, result) -> None:
        self.speed_test_running = False
        self.speed_test_button.configure(state="normal", text="测试下载速度")
        self.settings_status.configure(
            text=(
                f"测速结果：{result.mebibytes_per_second:.2f} MiB/s · "
                f"{result.megabits_per_second:.1f} Mbps · "
                f"{result.bytes_downloaded / 1024**2:.1f} MiB"
            )
        )

    def _finish_speed_test_error(self, message: str) -> None:
        self.speed_test_running = False
        self.speed_test_button.configure(state="normal", text="测试下载速度")
        self.settings_status.configure(text="测速失败")
        messagebox.showerror("测速失败", message, parent=self.window)

    def _save_settings(self) -> None:
        try:
            limit_text = self.bandwidth_entry.get().strip()
            settings = UserSettings(
                download_concurrency=1,
                bandwidth_limit_kib=int(limit_text) if limit_text else None,
                onboarding_completed=self.user_settings.onboarding_completed,
            )
            if self.settings_repository is None:
                raise RuntimeError("设置存储不可用")
            self.settings_repository.save(settings)
            self.user_settings = settings
            self.settings_status.configure(text="已保存，重启后生效")
        except Exception as error:
            self.context.logger.exception("Unable to save user settings")
            messagebox.showerror("设置无效", str(error), parent=self.window)

    def _show_onboarding(self) -> None:
        if self.user_settings.onboarding_completed:
            return
        messagebox.showinfo(
            "欢迎使用 SignRiver DLC Hub",
            "使用流程：\n\n"
            "1. 程序自动检测 Stellaris，也可以手动选择目录。\n"
            "2. 刷新 DLC 目录并选择需要的内容下载。\n"
            "3. 下载完成后进行完整性检查。\n"
            "4. 包结构和 DLC 编号校验通过后自动安装到当前游戏目录。\n\n"
            "程序会识别游戏目录中已有的 DLC，并以灰色状态显示，避免重复下载。",
            parent=self.window,
        )
        self.user_settings = UserSettings(
            1,
            self.user_settings.bandwidth_limit_kib,
            True,
        )
        if self.settings_repository is not None:
            try:
                self.settings_repository.save(self.user_settings)
            except Exception:
                self.context.logger.exception("Unable to persist onboarding completion")

    def _notify(self, message: str, *, error: bool = False) -> None:
        self.notice_serial += 1
        serial = self.notice_serial
        self.global_notice.configure(
            text=message,
            text_color=UI["danger"] if error else UI["success"],
        )
        if error:
            self.window.bell()
        self.window.after(
            6000,
            lambda serial=serial: (
                self.global_notice.configure(text="")
                if serial == self.notice_serial else None
            ),
        )

    def _post_ui(self, callback) -> None:
        """Queue a UI callback without touching Tk from a worker thread."""
        self.ui_events.put(callback)

    def _drain_ui_events(self) -> None:
        if not self.ui_event_pump_running:
            return
        for _ in range(250):
            try:
                callback = self.ui_events.get_nowait()
            except Empty:
                break
            try:
                callback()
            except Exception:
                self.context.logger.exception("Unable to apply queued UI event")
        with self.pending_download_lock:
            snapshots = tuple(self.pending_download_snapshots.values())
            self.pending_download_snapshots.clear()
        for snapshot in snapshots:
            try:
                self._apply_download_event(snapshot)
            except Exception:
                self.context.logger.exception(
                    "Unable to apply download UI event: task=%s",
                    snapshot.spec.task_id,
                )
        if self.ui_event_pump_running:
            self.window.after(50, self._drain_ui_events)

    def _update_global_status(self) -> None:
        snapshots = self.download_queue.snapshots() if self.download_queue is not None else ()
        active_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        active = [item for item in snapshots if item.state in active_states]
        speed = sum(item.speed_bytes_per_second or 0 for item in active)
        try:
            usage = self.cache_maintenance.usage_bytes()
            cache_text = f"{usage / 1048576:.1f} MiB"
        except OSError:
            cache_text = "不可用"
        self.global_status.configure(text=(
            f"网络：{'已连接' if self.catalog_online else '未连接'}\n"
            f"任务：{len(active)} · {speed / 1024:.1f} KiB/s\n"
            f"缓存：{cache_text}"
        ))
        self.window.after(2000, self._update_global_status)

    def _open_path(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.as_uri())
        except Exception as error:
            messagebox.showerror("无法打开目录", str(error), parent=self.window)

    def _refresh_log_preview(self) -> None:
        path = self.context.paths.data / "logs" / "launcher.log"
        try:
            if path.is_file():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
                level = self.log_level_filter.get()
                query = self.log_search.get().strip().casefold()
                if level != "全部":
                    lines = [line for line in lines if f"| {level} |" in line]
                if query:
                    lines = [line for line in lines if query in line.casefold()]
                lines = lines[-200:]
                content = "\n".join(lines) or "日志文件为空"
            else:
                content = "尚未生成日志文件"
        except OSError as error:
            content = f"无法读取日志：{error}"
        self.last_log_content = content
        self.log_preview.configure(state="normal")
        self.log_preview.delete("1.0", "end")
        self.log_preview.insert("1.0", content)
        self.log_preview.see("end")
        self.log_preview.configure(state="disabled")

    def _copy_log(self) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(self.last_log_content)
        self.window.update_idletasks()

    def _export_diagnostics(self) -> None:
        try:
            snapshots = self.download_queue.snapshots() if self.download_queue is not None else ()
            output = self.diagnostic_exporter.export(
                app_version=self.context.app_version,
                launcher_version=self.context.launcher_version,
                settings=self.user_settings,
                snapshots=snapshots,
                log_path=self.context.paths.data / "logs" / "launcher.log",
            )
            if messagebox.askyesno(
                "诊断包已导出",
                f"已生成：{output.name}\n\n是否打开所在目录？",
                parent=self.window,
            ):
                self._open_path(output.parent)
        except Exception as error:
            self.context.logger.exception("Diagnostic export failed")
            messagebox.showerror("诊断导出失败", str(error), parent=self.window)

    def _refresh_catalog(self) -> None:
        self.catalog_refresh_button.configure(state="disabled")
        self.catalog_status.configure(text="正在读取 GitLink · ste Release……")

        def worker() -> None:
            try:
                entries = self.catalog.refresh()
                self._post_ui(lambda entries=entries: self._show_catalog(entries))
            except Exception as error:
                self.context.logger.exception("DLC catalog refresh failed")
                message = str(error)
                self._post_ui(lambda message=message: self._show_catalog_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _show_catalog(self, entries) -> None:
        self.catalog_online = True
        self._refresh_installed_dlc_paths()
        self.catalog_entries = entries
        if entries and not self.catalog_selection_initialized:
            self.selected_dlc_ids = {
                entry.dlc_id for entry in entries
                if not self._is_entry_installed(entry)
            }
            self.catalog_selection_initialized = True
        self.catalog_refresh_button.configure(state="normal")
        self.catalog_status.configure(
            text=f"Stellaris · 已读取 {len(entries)} 个 DLC 资源"
        )
        if not entries:
            self.catalog_preview.configure(text="Release 中没有符合命名规则的 DLC ZIP")
            return
        self.catalog_preview.configure(
            text="勾选需要的内容后一键下载；包结构校验通过后会自动安装到当前游戏目录"
        )
        self._render_catalog_rows()
        self._reconcile_catalog_cache()
        self._schedule_ready_installs()

    def _reconcile_catalog_cache(self) -> None:
        if self.download_queue is None or not self.catalog_entries:
            return
        specs = tuple(self._download_spec_for_entry(entry) for entry in self.catalog_entries)

        def worker() -> None:
            try:
                recovered = self.download_queue.reconcile_cached(specs)
                if recovered:
                    self._post_ui(
                        lambda count=len(recovered): self._on_cache_reconciled(count)
                    )
            except Exception:
                self.context.logger.exception("Unable to reconcile cached DLC packages")

        threading.Thread(target=worker, daemon=True).start()

    def _on_cache_reconciled(self, count: int) -> None:
        self.catalog_preview.configure(text=f"已从缓存恢复 {count} 个已下载 DLC")
        self._render_catalog_rows()
        self._schedule_ready_installs()

    def _show_catalog_error(self, message: str) -> None:
        self.catalog_online = False
        self.catalog_refresh_button.configure(state="normal")
        self.catalog_status.configure(text="DLC 目录读取失败")
        self.catalog_preview.configure(text=message)
        self._notify("DLC 目录刷新失败", error=True)

    def _render_catalog_rows(self) -> None:
        for child in self.dlc_list_frame.winfo_children():
            child.destroy()
        self.catalog_rows.clear()
        self.simple_status_labels.clear()
        self.catalog_selection_widgets.clear()
        self.catalog_entry_frames.clear()
        self.catalog_name_labels.clear()
        snapshots = {}
        if self.download_queue is not None:
            snapshots = {item.spec.task_id: item for item in self.download_queue.snapshots()}
        visible_entries = self._visible_catalog_entries(snapshots)
        valid_ids = {entry.dlc_id for entry in self.catalog_entries}
        self.selected_dlc_ids.intersection_update(valid_ids)
        self.dlc_selection_vars.clear()
        if self.catalog_view_mode == "simple":
            self._render_simple_catalog_rows(visible_entries, snapshots)
        else:
            self._render_advanced_catalog_rows(visible_entries, snapshots)
        if not visible_entries:
            ctk.CTkLabel(
                self.dlc_list_frame, text="没有符合当前搜索和筛选条件的 DLC"
            ).grid(row=0, column=0, columnspan=3, padx=12, pady=24)
        self._update_selection_toggle_button(visible_entries)

    def _reset_catalog_scroll(self) -> None:
        """Recalculate the catalog canvas and move its viewport to the first row."""
        try:
            self.dlc_list_frame.update_idletasks()
            canvas = self.dlc_list_frame._parent_canvas
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(0.0)
        except (AttributeError, TclError):
            # The callback may run while the window is closing.
            return

    def _schedule_catalog_scroll_reset(self) -> None:
        def after_layout() -> None:
            try:
                self.window.after(10, self._reset_catalog_scroll)
            except TclError:
                return

        self.window.after_idle(after_layout)

    def _toggle_catalog_view(self) -> None:
        # Reset the old, taller view before replacing its rows.  Otherwise the
        # compact view can inherit a scroll offset beyond its new content.
        self._reset_catalog_scroll()
        if self.catalog_view_mode == "simple":
            self.catalog_view_mode = "advanced"
            self.advanced_view_button.configure(text="返回简洁视图")
            self.catalog_preview.configure(
                text="高级管理：可逐项下载、取消、检查和卸载"
            )
        else:
            self.catalog_view_mode = "simple"
            self.advanced_view_button.configure(text="高级管理")
            self.catalog_preview.configure(
                text="简洁视图：勾选需要的内容后可一键下载"
            )
        self._render_catalog_rows()
        self._schedule_catalog_scroll_reset()

    def _render_simple_catalog_rows(self, visible_entries, snapshots) -> None:
        columns = self.simple_catalog_columns
        for column in range(5):
            active = column < columns
            self.dlc_list_frame.grid_columnconfigure(
                column, weight=1 if active else 0,
                uniform="dlc" if active else "",
            )
        for index, entry in enumerate(visible_entries):
            task_id = f"stellaris-{entry.dlc_id}"
            installed = self._is_entry_installed(entry)
            if installed:
                self.selected_dlc_ids.discard(entry.dlc_id)
            cell = ctk.CTkFrame(
                self.dlc_list_frame,
                fg_color=UI["panel"] if installed else UI["card"],
                corner_radius=6,
                border_width=1, border_color=UI["border"],
            )
            cell.grid(
                row=index // columns, column=index % columns, sticky="nsew",
                padx=2, pady=1,
            )
            cell.grid_columnconfigure(1, weight=1)
            selected = BooleanVar(
                value=entry.dlc_id in self.selected_dlc_ids and not installed
            )
            self.dlc_selection_vars[entry.dlc_id] = selected
            checkbox = ctk.CTkCheckBox(
                cell, text="", width=18, checkbox_width=18, checkbox_height=18,
                variable=selected,
                state="disabled" if installed else "normal",
                command=lambda entry=entry, selected=selected: self._set_selected(
                    entry.dlc_id, selected.get()
                ),
            )
            checkbox.grid(row=0, column=0, padx=(5, 2), pady=4)
            name_label = ctk.CTkLabel(
                cell, text=entry.display_name, anchor="w",
                text_color=UI["muted"] if installed else UI["text"],
                font=ctk.CTkFont(size=11, weight="bold"),
            )
            name_label.grid(row=0, column=1, sticky="ew", padx=(1, 3), pady=3)
            status_text, status_color = self._simple_entry_status(
                entry, snapshots.get(task_id)
            )
            status = ctk.CTkLabel(
                cell, text=status_text, anchor="w", text_color=status_color,
                font=ctk.CTkFont(size=9),
            )
            status.grid(row=0, column=2, sticky="e", padx=(0, 5), pady=3)
            self.simple_status_labels[task_id] = status
            self.catalog_selection_widgets[entry.dlc_id] = checkbox
            self.catalog_entry_frames[entry.dlc_id] = cell
            self.catalog_name_labels[entry.dlc_id] = name_label
            self._apply_visual_theme_to_children(
                cell, set(self.navigation_buttons.values())
            )

    def _render_advanced_catalog_rows(self, visible_entries, snapshots) -> None:
        self.dlc_list_frame.grid_columnconfigure(0, weight=1, uniform="")
        for column in range(1, 4):
            self.dlc_list_frame.grid_columnconfigure(column, weight=0, uniform="")
        for index, entry in enumerate(visible_entries):
            installed = self._is_entry_installed(entry)
            if installed:
                self.selected_dlc_ids.discard(entry.dlc_id)
            row = ctk.CTkFrame(
                self.dlc_list_frame,
                fg_color=UI["panel"] if installed else UI["card"],
                corner_radius=9,
                border_width=1, border_color=UI["border"],
            )
            row.grid(row=index, column=0, columnspan=8, sticky="ew", pady=3)
            row.grid_columnconfigure(2, weight=1)
            selected = BooleanVar(
                value=entry.dlc_id in self.selected_dlc_ids and not installed
            )
            self.dlc_selection_vars[entry.dlc_id] = selected
            checkbox = ctk.CTkCheckBox(
                row, text="", width=22, variable=selected,
                state="disabled" if installed else "normal",
                command=lambda entry=entry, selected=selected: self._set_selected(
                    entry.dlc_id, selected.get()
                ),
            )
            checkbox.grid(row=0, column=0, padx=(10, 0), pady=8)
            ctk.CTkLabel(row, text=entry.dlc_id.upper(), width=58).grid(
                row=0, column=1, padx=(2, 6), pady=8
            )
            name_label = ctk.CTkLabel(
                row, text=entry.display_name, anchor="w",
                text_color=UI["muted"] if installed else UI["text"],
            )
            name_label.grid(row=0, column=2, sticky="ew", padx=4)
            status = ctk.CTkLabel(
                row, text=entry.asset.display_size or "大小未知", width=80, anchor="e"
            )
            status.grid(row=0, column=3, padx=6)
            action = ctk.CTkButton(
                row, text="下载", width=56,
                command=lambda entry=entry: self._start_entry_download(entry),
            )
            action.grid(row=0, column=4, padx=4)
            cancel = ctk.CTkButton(
                row, text="取消", width=50, state="disabled",
                command=lambda entry=entry: self._cancel_entry(entry),
            )
            cancel.grid(row=0, column=5, padx=(4, 10))
            manage = ctk.CTkButton(
                row, text="未验证", width=58, state="disabled",
                command=lambda entry=entry: self._manage_entry(entry),
            )
            manage.grid(row=0, column=6, padx=4)
            uninstall = ctk.CTkButton(
                row, text="卸载", width=50, state="disabled",
                command=lambda entry=entry: self._uninstall_entry(entry),
            )
            uninstall.grid(row=0, column=7, padx=(4, 10))
            task_id = f"stellaris-{entry.dlc_id}"
            self.catalog_rows[task_id] = (status, action, cancel, manage, uninstall)
            self.catalog_selection_widgets[entry.dlc_id] = checkbox
            self.catalog_entry_frames[entry.dlc_id] = row
            self.catalog_name_labels[entry.dlc_id] = name_label
            self._apply_visual_theme_to_children(
                row, set(self.navigation_buttons.values())
            )
            if task_id in snapshots:
                self._show_download_state(snapshots[task_id])
            self._show_install_state(entry)

    def _simple_entry_status(self, entry, snapshot=None) -> tuple[str, str]:
        if self._is_entry_installed(entry):
            return "已安装", UI["muted"]
        if snapshot is None or snapshot.state is DownloadState.CANCELLED:
            return "未下载", UI["muted"]
        states = {
            DownloadState.QUEUED: ("等待下载", UI["primary"]),
            DownloadState.PAUSING: ("正在暂停", UI["text_secondary"]),
            DownloadState.RETRYING: ("正在重连", UI["primary"]),
            DownloadState.VERIFYING: ("正在校验", UI["primary"]),
            DownloadState.READY: ("已下载", UI["success"]),
            DownloadState.PAUSED: ("已暂停", UI["text_secondary"]),
            DownloadState.FAILED: ("下载失败", UI["danger"]),
            DownloadState.CORRUPT: ("坏包已隔离", UI["danger"]),
        }
        if snapshot.state is DownloadState.DOWNLOADING:
            if snapshot.total_bytes:
                percent = min(snapshot.bytes_downloaded / snapshot.total_bytes * 100, 100)
                return f"下载中 {percent:.0f}%", UI["primary"]
            return "下载中", UI["primary"]
        return states.get(snapshot.state, ("未下载", UI["muted"]))

    def _visible_catalog_entries(self, snapshots):
        query = self.catalog_search.get().strip().casefold()
        selected_filter = self.catalog_filter.get()
        result = []
        for entry in self.catalog_entries:
            if query and query not in entry.dlc_id.casefold() and query not in entry.display_name.casefold():
                continue
            snapshot = snapshots.get(f"stellaris-{entry.dlc_id}")
            state = snapshot.state if snapshot else None
            installed = self._is_entry_installed(entry)
            groups = {
                "未下载": not installed and (
                    state is None or state is DownloadState.CANCELLED
                ),
                "进行中": state in {
                    DownloadState.QUEUED, DownloadState.DOWNLOADING,
                    DownloadState.PAUSING, DownloadState.RETRYING,
                    DownloadState.VERIFYING,
                },
                "已暂停": state is DownloadState.PAUSED,
                "已完成": installed or state is DownloadState.READY,
                "失败": state in {DownloadState.FAILED, DownloadState.CORRUPT},
            }
            if selected_filter != "全部状态" and not groups[selected_filter]:
                continue
            result.append(entry)
        return tuple(result)

    def _set_selected(self, dlc_id: str, selected: bool) -> None:
        entry = next((item for item in self.catalog_entries if item.dlc_id == dlc_id), None)
        if entry is not None and self._is_entry_installed(entry):
            self.selected_dlc_ids.discard(dlc_id)
            return
        if selected:
            self.selected_dlc_ids.add(dlc_id)
        else:
            self.selected_dlc_ids.discard(dlc_id)
        self._update_selection_toggle_button()

    def _selectable_visible_entries(self, visible_entries=None):
        if visible_entries is None:
            snapshots = {}
            if self.download_queue is not None:
                snapshots = {
                    item.spec.task_id: item for item in self.download_queue.snapshots()
                }
            visible_entries = self._visible_catalog_entries(snapshots)
        return tuple(
            entry for entry in visible_entries if not self._is_entry_installed(entry)
        )

    def _update_selection_toggle_button(self, visible_entries=None) -> None:
        selectable = self._selectable_visible_entries(visible_entries)
        all_selected = bool(selectable) and all(
            entry.dlc_id in self.selected_dlc_ids for entry in selectable
        )
        self.selection_toggle_button.configure(
            text="取消全选" if all_selected else "全选"
        )

    def _toggle_visible_selection(self) -> None:
        selectable = self._selectable_visible_entries()
        all_selected = bool(selectable) and all(
            entry.dlc_id in self.selected_dlc_ids for entry in selectable
        )
        if all_selected:
            self._clear_visible_selection()
        else:
            self._select_visible()

    def _select_visible(self) -> None:
        snapshots = {}
        if self.download_queue is not None:
            snapshots = {item.spec.task_id: item for item in self.download_queue.snapshots()}
        visible = self._visible_catalog_entries(snapshots)
        for entry in visible:
            if self._is_entry_installed(entry):
                continue
            self.selected_dlc_ids.add(entry.dlc_id)
            variable = self.dlc_selection_vars.get(entry.dlc_id)
            if variable is not None:
                variable.set(True)
        self._update_selection_toggle_button(visible)

    def _clear_visible_selection(self) -> None:
        snapshots = {}
        if self.download_queue is not None:
            snapshots = {
                item.spec.task_id: item for item in self.download_queue.snapshots()
            }
        visible = self._visible_catalog_entries(snapshots)
        for entry in visible:
            self.selected_dlc_ids.discard(entry.dlc_id)
            variable = self.dlc_selection_vars.get(entry.dlc_id)
            if variable is not None:
                variable.set(False)
        self._update_selection_toggle_button(visible)

    def _download_selected(self) -> None:
        if self.batch_download_state == "cancelling":
            return
        if self.batch_download_state == "running":
            self._pause_batch_download()
            return
        if self.batch_download_state in {"pausing", "paused", "resuming"}:
            self._continue_batch_download()
            return
        self._start_selected_batch()

    def _start_selected_batch(self) -> None:
        if self.download_queue is None:
            self._show_catalog_error("下载队列初始化失败，请查看日志")
            return
        selected = [
            entry for entry in self.catalog_entries
            if entry.dlc_id in self.selected_dlc_ids
        ]
        if not selected:
            self.catalog_preview.configure(text="请先勾选至少一个 DLC")
            return
        snapshots = {}
        if self.download_queue is not None:
            snapshots = {
                item.spec.task_id: item for item in self.download_queue.snapshots()
            }
        active_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        started = 0
        skipped = 0
        failed = 0
        batch_task_ids = []
        for entry in selected:
            task_id = f"stellaris-{entry.dlc_id}"
            snapshot = snapshots.get(task_id)
            if self._is_entry_installed(entry) or (
                snapshot is not None and snapshot.state is DownloadState.READY
            ):
                skipped += 1
                continue
            if snapshot is not None and snapshot.state in active_states:
                batch_task_ids.append(task_id)
                skipped += 1
                continue
            try:
                self._start_entry_download(entry, show_error=False)
                batch_task_ids.append(task_id)
                started += 1
            except Exception:
                self.context.logger.exception("Unable to enqueue selected DLC")
                failed += 1
        self.batch_download_task_ids = tuple(dict.fromkeys(batch_task_ids))
        if self.batch_download_task_ids:
            self._set_batch_download_state("running")
        else:
            self._set_batch_download_state("idle")
        self.catalog_preview.configure(
            text=(
                f"已开始 {started} 个下载任务"
                f"，跳过 {skipped} 个已下载/已安装/进行中项目"
                f"，提交失败 {failed} 个"
                "；任务将按列表顺序逐个下载"
            )
        )

    def _set_batch_download_state(self, state: str) -> None:
        self.batch_download_state = state
        text, enabled = {
            "idle": ("一键下载所选", True),
            "running": ("暂停下载", True),
            "pausing": ("继续下载", True),
            "paused": ("继续下载", True),
            "resuming": ("正在继续…", False),
            "cancelling": ("正在取消…", False),
        }[state]
        self.download_selected_button.configure(
            text=text,
            state="normal" if enabled else "disabled",
            fg_color=UI["primary"],
            hover_color=UI["primary_hover"],
        )
        self.cancel_all_downloads_button.configure(
            state="disabled" if state == "cancelling" else "normal"
        )

    def _cancel_all_downloads(self) -> None:
        if self.download_queue is None or self.batch_download_state == "cancelling":
            return
        unfinished_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.PAUSED,
            DownloadState.RETRYING, DownloadState.VERIFYING,
        }
        unfinished = tuple(
            item.spec.task_id for item in self.download_queue.snapshots()
            if item.state in unfinished_states
        )
        if not unfinished:
            self.catalog_preview.configure(text="当前没有可以取消的下载任务")
            return
        if not messagebox.askyesno(
            "取消全部下载",
            "将取消当前下载和全部排队任务，并删除未完成半包。\n"
            "已经下载完成或安装完成的 DLC 会保留。是否继续？",
            parent=self.window,
        ):
            return
        self.batch_download_task_ids = unfinished
        self._set_batch_download_state("cancelling")
        requested = self.download_queue.cancel_many(unfinished)
        self.catalog_preview.configure(text=f"正在取消 {requested} 个未完成下载任务……")
        self._schedule_cancel_poll()

    def _schedule_cancel_poll(self) -> None:
        if self.batch_cancel_poll_pending:
            return
        self.batch_cancel_poll_pending = True
        self.window.after(100, self._poll_cancel_all)

    def _poll_cancel_all(self) -> None:
        self.batch_cancel_poll_pending = False
        if self.batch_download_state != "cancelling" or self.download_queue is None:
            return
        active_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.PAUSED,
            DownloadState.RETRYING, DownloadState.VERIFYING,
        }
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        }
        if any(
            self.download_queue.is_active(task_id)
            or (
                snapshots.get(task_id) is not None
                and snapshots[task_id].state in active_states
            )
            for task_id in self.batch_download_task_ids
        ):
            self._schedule_cancel_poll()
            return
        self.batch_download_task_ids = ()
        self.selected_dlc_ids.clear()
        for variable in self.dlc_selection_vars.values():
            variable.set(False)
        self._set_batch_download_state("idle")
        self.catalog_preview.configure(
            text="全部未完成下载已取消；已清空选择，可以重新勾选需要的 DLC"
        )

    def _pause_batch_download(self) -> None:
        if self.download_queue is None or not self.batch_download_task_ids:
            self._set_batch_download_state("idle")
            return
        self._set_batch_download_state("pausing")
        requested = self.download_queue.pause_many(self.batch_download_task_ids)
        self.catalog_preview.configure(
            text=(
                f"正在暂停批量下载：已向 {requested} 个未完成任务发送暂停请求；"
                "当前半包会删除，已经完成的 DLC 会保留"
            )
        )
        self._schedule_batch_pause_poll()

    def _continue_batch_download(self) -> None:
        if self.batch_download_state == "pausing":
            self._set_batch_download_state("resuming")
            self._schedule_batch_pause_poll()
            return
        if self.batch_download_state == "paused":
            self._resume_paused_batch()

    def _schedule_batch_pause_poll(self) -> None:
        if self.batch_pause_poll_pending:
            return
        self.batch_pause_poll_pending = True
        self.window.after(100, self._poll_batch_pause)

    def _poll_batch_pause(self) -> None:
        self.batch_pause_poll_pending = False
        if self.batch_download_state not in {"pausing", "resuming"}:
            return
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        } if self.download_queue is not None else {}
        settling = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        if any(
            self.download_queue.is_active(task_id)
            or (
                snapshots.get(task_id) is not None
                and snapshots[task_id].state in settling
            )
            for task_id in self.batch_download_task_ids
        ):
            self._schedule_batch_pause_poll()
            return
        if self.batch_download_state == "resuming":
            self._resume_paused_batch()
            return
        self._set_batch_download_state("paused")
        self.catalog_preview.configure(
            text="批量下载已暂停；半包已删除，点击“继续下载”会从未完成的 DLC 重新下载"
        )

    def _resume_paused_batch(self) -> None:
        if self.download_queue is None:
            self._set_batch_download_state("idle")
            return
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        }
        resumed = 0
        active = 0
        active_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        for task_id in self.batch_download_task_ids:
            snapshot = snapshots.get(task_id)
            if snapshot is None:
                continue
            if snapshot.state in {DownloadState.PAUSED, DownloadState.FAILED}:
                try:
                    future = self.download_queue.resume(task_id)
                    future.add_done_callback(self._download_finished)
                    resumed += 1
                except (KeyError, ValueError):
                    self.context.logger.exception("Unable to resume batch task %s", task_id)
            elif snapshot.state in active_states:
                active += 1
        if resumed or active:
            self._set_batch_download_state("running")
            self.catalog_preview.configure(
                text=f"批量下载已继续；{resumed} 个未完成 DLC 将从头下载"
            )
        else:
            self._set_batch_download_state("idle")
            self.batch_download_task_ids = ()

    def _update_batch_download_state(self, snapshot) -> None:
        if snapshot.spec.task_id not in self.batch_download_task_ids:
            return
        if self.batch_download_state in {"pausing", "resuming"}:
            self._schedule_batch_pause_poll()
            return
        if self.batch_download_state != "running" or self.download_queue is None:
            return
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        }
        terminal = {
            DownloadState.READY, DownloadState.CANCELLED,
            DownloadState.FAILED, DownloadState.CORRUPT,
        }
        batch = [
            snapshots[task_id] for task_id in self.batch_download_task_ids
            if task_id in snapshots
        ]
        if batch and all(item.state in terminal for item in batch):
            completed = sum(item.state is DownloadState.READY for item in batch)
            failed = sum(
                item.state in {DownloadState.FAILED, DownloadState.CORRUPT}
                for item in batch
            )
            self._set_batch_download_state("idle")
            self.batch_download_task_ids = ()
            self.catalog_preview.configure(
                text=f"批量下载结束：完成 {completed} 个，失败 {failed} 个"
            )

    def _start_entry_download(self, entry, *, show_error: bool = True):
        spec = self._download_spec_for_entry(entry)
        self.auto_install_attempted.discard(spec.task_id)

        if self.download_queue is None:
            self._show_catalog_error("下载队列初始化失败，请查看日志")
            return
        try:
            existing = {
                item.spec.task_id: item for item in self.download_queue.snapshots()
            }.get(spec.task_id)
            if existing and existing.state in {DownloadState.PAUSED, DownloadState.FAILED}:
                future = self.download_queue.resume(spec.task_id)
            else:
                future = self.download_queue.enqueue(spec)
            future.add_done_callback(self._download_finished)
            return future
        except Exception as error:
            if show_error:
                self.catalog_preview.configure(text=str(error))
            else:
                raise
        return None

    def _download_spec_for_entry(self, entry) -> DownloadSpec:
        return DownloadSpec(
            task_id=f"stellaris-{entry.dlc_id}",
            url=entry.asset.download_url,
            filename=entry.asset.name,
            expected_size=None,
            expected_sha256=None,
            supports_range=False,
        )

    def _download_finished(self, future) -> None:
        try:
            result = future.result()
            if (
                result.state is DownloadState.READY
                and result.result_path is not None
                and result.sha256 is not None
                and self.install_service is not None
                and self.current_installation is not None
            ):
                entry = next((
                    item for item in self.catalog_entries
                    if f"stellaris-{item.dlc_id}" == result.spec.task_id
                ), None)
                if entry is not None and not self._is_entry_installed(entry):
                    self.auto_install_attempted.add(result.spec.task_id)
                    try:
                        self.install_service.install(
                            result.result_path,
                            self.current_installation.root,
                            expected_sha256=result.sha256,
                        )
                        self._post_ui(
                            lambda entry=entry: self._on_auto_install_success(entry)
                        )
                    except Exception as error:
                        self.context.logger.exception(
                            "Automatic DLC installation failed: dlc=%s",
                            entry.dlc_id,
                        )
                        message = str(error)
                        self._post_ui(
                            lambda entry=entry, message=message:
                            self._on_auto_install_failure(entry, message)
                        )
            self.context.logger.info(
                "DLC download finished: task=%s state=%s sha256=%s",
                result.spec.task_id, result.state, result.sha256,
            )
            if result.spec.task_id not in self.batch_download_task_ids:
                self._post_ui(
                    lambda result=result: self._notify(
                        f"{result.spec.filename}：{'下载完成' if result.state is DownloadState.READY else result.state.value}",
                        error=result.state in {DownloadState.FAILED, DownloadState.CORRUPT},
                    )
                )
        except Exception:
            self.context.logger.exception("DLC queue task crashed")
            self._post_ui(lambda: self._notify("下载任务异常退出", error=True))

    def _queue_download_event(self, snapshot) -> None:
        # Keep only the newest progress snapshot per task between UI ticks.
        with self.pending_download_lock:
            self.pending_download_snapshots[snapshot.spec.task_id] = snapshot

    def _apply_download_event(self, snapshot) -> None:
        self._show_download_state(snapshot)
        self._update_batch_download_state(snapshot)
        if snapshot.state is DownloadState.READY:
            self._schedule_ready_installs()
        if getattr(self, "current_page", None) == "下载任务":
            self._schedule_task_refresh()

    def _show_recovered_downloads(self) -> None:
        if self.download_queue is None:
            return
        try:
            recovered = self.download_queue.restore()
        except Exception:
            self.context.logger.exception("Unable to recover download tasks")
            return
        if recovered:
            ready = sum(item.state is DownloadState.READY for item in recovered)
            unfinished = sum(
                item.state in {DownloadState.PAUSED, DownloadState.FAILED}
                for item in recovered
            )
            self.catalog_preview.configure(
                text=f"已恢复 {ready} 个缓存包和 {unfinished} 个未完成任务"
            )

    def _cancel_entry(self, entry) -> None:
        if self.download_queue is not None:
            try:
                self.download_queue.cancel(f"stellaris-{entry.dlc_id}")
            except (KeyError, ValueError):
                pass

    def _package_verifier_for(self, spec: DownloadSpec):
        expected_dlc_id = spec.task_id.removeprefix("stellaris-")

        def verify(path: Path):
            metadata = inspect_stellaris_package(path)
            if metadata.dlc_id.casefold() != expected_dlc_id.casefold():
                raise ValueError(
                    f"package DLC ID mismatch: expected {expected_dlc_id}, "
                    f"got {metadata.dlc_id}"
                )
            return metadata

        return verify

    def _installed_dlc_path(self, dlc_id: str) -> Path | None:
        return self.installed_dlc_paths.get(dlc_id.casefold())

    def _refresh_installed_dlc_paths(self) -> None:
        self.installed_dlc_paths = (
            discover_installed_dlc(self.current_installation.root)
            if self.current_installation is not None else {}
        )

    def _is_entry_installed(self, entry) -> bool:
        return self._installed_dlc_path(entry.dlc_id) is not None

    def _active_receipt(self, dlc_id: str):
        if self.install_repository is None:
            return None
        try:
            return self.install_repository.find_active("stellaris", dlc_id)
        except Exception:
            self.context.logger.exception("Unable to read install receipt")
            return None

    def _ready_download(self, dlc_id: str):
        if self.download_queue is None:
            return None
        return next((
            item for item in self.download_queue.snapshots()
            if item.spec.task_id == f"stellaris-{dlc_id}"
            and item.state is DownloadState.READY
            and item.result_path is not None
            and item.sha256 is not None
        ), None)

    def _schedule_ready_installs(self) -> None:
        if (
            self.auto_install_worker_running
            or self.install_service is None
            or self.current_installation is None
            or self.download_queue is None
        ):
            return
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        }
        jobs = []
        for entry in self.catalog_entries:
            task_id = f"stellaris-{entry.dlc_id}"
            snapshot = snapshots.get(task_id)
            if (
                snapshot is None
                or snapshot.state is not DownloadState.READY
                or snapshot.result_path is None
                or snapshot.sha256 is None
                or task_id in self.auto_install_attempted
                or self._is_entry_installed(entry)
            ):
                continue
            jobs.append((entry, snapshot))
            self.auto_install_attempted.add(task_id)
        if not jobs:
            return
        self.auto_install_worker_running = True
        game_root = self.current_installation.root
        service = self.install_service

        def worker() -> None:
            for entry, snapshot in jobs:
                try:
                    current = self.current_installation
                    if current is None or current.root != game_root:
                        break
                    service.install(
                        snapshot.result_path,
                        game_root,
                        expected_sha256=snapshot.sha256,
                    )
                    self._post_ui(
                        lambda entry=entry: self._on_auto_install_success(entry)
                    )
                except Exception as error:
                    self.context.logger.exception(
                        "Automatic DLC installation failed: dlc=%s", entry.dlc_id
                    )
                    message = str(error)
                    self._post_ui(
                        lambda entry=entry, message=message:
                        self._on_auto_install_failure(entry, message)
                    )
            self._post_ui(self._on_auto_install_worker_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_install_success(self, entry) -> None:
        self._refresh_installed_dlc_paths()
        self._show_install_state(entry)
        self.catalog_preview.configure(text=f"{entry.display_name} 已自动安装到游戏目录")
        self._notify(f"{entry.display_name}：安装完成")

    def _on_auto_install_failure(self, entry, message: str) -> None:
        self.catalog_preview.configure(
            text=f"{entry.display_name} 下载完成，但自动安装失败：{message}"
        )
        self._notify(f"{entry.display_name}：自动安装失败", error=True)

    def _on_auto_install_worker_done(self) -> None:
        self.auto_install_worker_running = False
        self._schedule_ready_installs()

    def _show_install_state(self, entry) -> None:
        task_id = f"stellaris-{entry.dlc_id}"
        installed = self._is_entry_installed(entry)
        checkbox = self.catalog_selection_widgets.get(entry.dlc_id)
        frame = self.catalog_entry_frames.get(entry.dlc_id)
        name_label = self.catalog_name_labels.get(entry.dlc_id)
        if installed:
            self.selected_dlc_ids.discard(entry.dlc_id)
            variable = self.dlc_selection_vars.get(entry.dlc_id)
            if variable is not None:
                variable.set(False)
        if checkbox is not None:
            checkbox.configure(state="disabled" if installed else "normal")
        if frame is not None:
            frame.configure(fg_color=UI["panel"] if installed else UI["card"])
        if name_label is not None:
            name_label.configure(text_color=UI["muted"] if installed else UI["text"])
        simple_status = self.simple_status_labels.get(task_id)
        if simple_status is not None:
            snapshot = None
            if self.download_queue is not None:
                snapshot = next((
                    item for item in self.download_queue.snapshots()
                    if item.spec.task_id == task_id
                ), None)
            text, color = self._simple_entry_status(entry, snapshot)
            simple_status.configure(text=text, text_color=color)
        row = self.catalog_rows.get(task_id)
        if row is None:
            return
        _status, _action, _cancel, manage, uninstall = row
        receipt = self._active_receipt(entry.dlc_id)
        if installed:
            _status.configure(text="已安装", text_color=UI["muted"])
            _action.configure(state="disabled", text="已安装")
            _cancel.configure(state="disabled")
            uninstall.configure(state="normal")
            if receipt is not None:
                manage.configure(state="normal", text="检查")
            else:
                manage.configure(state="disabled", text="已存在")
            return
        if receipt is not None and self.current_installation is not None:
            manage.configure(state="normal", text="检查")
            uninstall.configure(state="normal")
            return
        uninstall.configure(state="disabled")
        if self.current_installation is None:
            manage.configure(state="disabled", text="无路径")
        elif self._ready_download(entry.dlc_id) is None:
            manage.configure(state="disabled", text="先下载")
        else:
            manage.configure(state="normal", text="安装")

    def _manage_entry(self, entry) -> None:
        if self.install_service is None or self.current_installation is None:
            return
        receipt = self._active_receipt(entry.dlc_id)
        if receipt is not None:
            game_root = self.current_installation.root
            download = self._ready_download(entry.dlc_id)

            def inspect_worker() -> None:
                try:
                    audit = next(
                        item.audit for item in self.install_service.audit(
                            "stellaris", game_root
                        ) if item.receipt.dlc_id == entry.dlc_id
                    )
                    if audit.health is not InstallHealth.HEALTHY and audit.missing and download is not None:
                        audit = self.install_service.repair_missing(
                            "stellaris", entry.dlc_id, download.result_path, game_root
                        )
                    self._post_ui(
                        lambda audit=audit: self._show_audit_result(entry, audit)
                    )
                except Exception as error:
                    self.context.logger.exception("DLC audit failed")
                    message = str(error)
                    self._post_ui(lambda message=message: messagebox.showerror(
                        "检查失败", message, parent=self.window
                    ))

            threading.Thread(target=inspect_worker, daemon=True).start()
            return
        download = self._ready_download(entry.dlc_id)
        if download is None or download.sha256 is None:
            return
        if not messagebox.askyesno(
            "确认安装", f"将 {entry.display_name} 安装到当前 Stellaris 目录？",
            parent=self.window,
        ):
            return
        self._run_install_action(
            lambda: self.install_service.install(
                download.result_path, self.current_installation.root,
                expected_sha256=download.sha256,
            ),
            entry,
            "安装完成",
        )

    def _show_audit_result(self, entry, audit) -> None:
        if audit.health is InstallHealth.HEALTHY:
            detail = "安装文件完整。"
        else:
            detail = (
                f"仍缺失 {len(audit.missing)}，被修改 {len(audit.modified)}，"
                f"未知文件 {len(audit.unknown)}。\n"
                "程序只自动补回缺失文件，不覆盖修改或删除未知文件。"
            )
        messagebox.showinfo("检查结果", f"{entry.display_name}\n{detail}", parent=self.window)
        self._show_install_state(entry)

    def _uninstall_entry(self, entry) -> None:
        if self.current_installation is None:
            return
        self._refresh_installed_dlc_paths()
        if self._installed_dlc_path(entry.dlc_id) is None:
            self._show_install_state(entry)
            return
        if not messagebox.askyesno(
            "确认卸载 DLC",
            f"将从游戏目录中移除 {entry.display_name}。\n"
            "无论它由本程序还是其他方式安装，对应 DLC 目录都会被完整删除。\n"
            "请先关闭游戏。是否继续？",
            parent=self.window,
        ):
            return
        self._start_dlc_removal({entry.dlc_id: entry.display_name}, "卸载 DLC")

    def _uninstall_all_dlc(self) -> None:
        if self.current_installation is None:
            messagebox.showwarning("尚未检测游戏", "请先选择有效的 Stellaris 目录。", parent=self.window)
            return
        self._refresh_installed_dlc_paths()
        installed = dict(self.installed_dlc_paths)
        if not installed:
            self.catalog_preview.configure(text="当前游戏目录中没有检测到可卸载的 DLC")
            return
        names = {
            entry.dlc_id: entry.display_name for entry in self.catalog_entries
        }
        if not messagebox.askyesno(
            "卸载全部 DLC",
            f"检测到 {len(installed)} 个 DLC 目录。\n"
            "将移除所有符合 dlcNNN_<名称> 规则的 DLC，无论它们由何种方式安装。\n"
            "此操作不可撤销，请先关闭游戏。是否继续？",
            parent=self.window,
        ):
            return
        targets = {
            dlc_id: names.get(dlc_id, dlc_id.upper()) for dlc_id in installed
        }
        self._start_dlc_removal(targets, "卸载全部 DLC")

    def _start_dlc_removal(self, targets: dict[str, str], title: str) -> None:
        game_root = self.current_installation.root
        repository = self.install_repository
        self.catalog_preview.configure(text=f"正在移除 {len(targets)} 个 DLC……")

        def worker() -> None:
            removed = []
            failures = []
            for dlc_id, display_name in targets.items():
                try:
                    remove_installed_dlc(game_root, dlc_id)
                    if repository is not None:
                        receipt = repository.find_active("stellaris", dlc_id)
                        if receipt is not None:
                            repository.mark_uninstalled(
                                receipt.transaction_id, restore_previous=False
                            )
                    removed.append(display_name)
                except Exception as error:
                    self.context.logger.exception(
                        "Unable to remove installed DLC: %s", dlc_id
                    )
                    failures.append(f"{display_name}：{error}")
            self._post_ui(
                lambda: self._finish_dlc_removal(title, removed, failures)
            )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_dlc_removal(self, title: str, removed, failures) -> None:
        self._refresh_installed_dlc_paths()
        self._render_catalog_rows()
        self.catalog_preview.configure(
            text=f"已移除 {len(removed)} 个 DLC；失败 {len(failures)} 个"
        )
        detail = f"成功移除 {len(removed)} 个 DLC。"
        if failures:
            detail += "\n\n失败项目：\n" + "\n".join(failures[:8])
            if len(failures) > 8:
                detail += f"\n……另有 {len(failures) - 8} 项"
        messagebox.showinfo(title, detail, parent=self.window)

    def _show_patch_removal_placeholder(self) -> None:
        messagebox.showinfo(
            "一键移除补丁",
            "按钮已预留，当前版本不会修改任何文件。\n"
            "待补充补丁识别规则后再接入实际移除逻辑。",
            parent=self.window,
        )

    def _run_install_action(self, operation, entry, success_text: str) -> None:
        def worker() -> None:
            try:
                operation()
                self._post_ui(lambda: self._finish_install_action(entry, success_text))
            except Exception as error:
                self.context.logger.exception("DLC install action failed")
                message = str(error)
                self._post_ui(lambda message=message: messagebox.showerror(
                    "操作失败", message, parent=self.window
                ))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_install_action(self, entry, text: str) -> None:
        self._refresh_installed_dlc_paths()
        self._render_catalog_rows()
        self._notify(f"{entry.display_name}：{text}")
        messagebox.showinfo(text, f"{entry.display_name}：{text}", parent=self.window)

    def _close(self) -> None:
        self.ui_event_pump_running = False
        if self.download_queue is not None:
            self.download_queue.shutdown(wait=False)
        self.window.destroy()

    def _show_download_state(self, snapshot) -> None:
        labels = {
            DownloadState.QUEUED: "等待下载",
            DownloadState.DOWNLOADING: "下载中",
            DownloadState.PAUSING: "正在暂停并清理半包",
            DownloadState.RETRYING: "连接中断，等待重试",
            DownloadState.VERIFYING: "正在校验包结构",
            DownloadState.READY: "下载并校验完成（尚未安装）",
            DownloadState.PAUSED: "已暂停；继续时需要整包重下",
            DownloadState.CANCELLED: "已取消",
            DownloadState.FAILED: "下载失败",
            DownloadState.CORRUPT: "坏包已隔离",
        }
        label = labels.get(snapshot.state, str(snapshot.state))
        speed = snapshot.speed_bytes_per_second
        speed_text = f" · {speed / 1024:.1f} KB/s" if speed else ""
        eta = snapshot.eta_seconds
        eta_text = f" · 约 {eta:.0f} 秒" if eta is not None and eta > 0 else ""
        task_id = snapshot.spec.task_id
        entry = next(
            (item for item in self.catalog_entries if f"stellaris-{item.dlc_id}" == task_id),
            None,
        )
        simple_status = self.simple_status_labels.get(task_id)
        if simple_status is not None and entry is not None:
            text, color = self._simple_entry_status(entry, snapshot)
            simple_status.configure(text=text, text_color=color)
        row = self.catalog_rows.get(task_id)
        if row is None:
            return
        status, action, cancel, _manage, _uninstall = row
        status.configure(text=(
            f"{label} · {snapshot.bytes_downloaded / 1024:.1f} KB"
            f"{speed_text}{eta_text}"
        ))
        terminal = {
            DownloadState.READY, DownloadState.PAUSED, DownloadState.CANCELLED,
            DownloadState.FAILED, DownloadState.CORRUPT,
        }
        if snapshot.state in terminal:
            if (
                snapshot.state is DownloadState.PAUSED
                and task_id in self.batch_download_task_ids
            ):
                action.configure(state="disabled", text="整批已暂停")
            else:
                action.configure(
                    state="normal",
                    text=(
                        "重试" if snapshot.state is DownloadState.FAILED
                        else "重新下载"
                    ),
                )
            cancel.configure(
                state="normal" if snapshot.state is DownloadState.PAUSED else "disabled"
            )
        elif snapshot.state in {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }:
            action.configure(
                state="disabled",
                text="正在暂停" if snapshot.state is DownloadState.PAUSING else "下载中",
            )
            cancel.configure(state="normal")
        if entry is not None:
            self._show_install_state(entry)

    def _scan_games(self) -> None:
        if self.discovery is None:
            self.game_status.configure(text="Stellaris · 初始化失败")
            self.game_path.configure(text="游戏发现服务不可用，请查看日志")
            return
        self._set_game_buttons("disabled")
        self.game_status.configure(text="Stellaris · 正在扫描 Steam 游戏库……")
        self.top_health.configure(text="Stellaris · 正在扫描路径")

        def worker() -> None:
            try:
                report = self.discovery.scan()
                self._post_ui(lambda report=report: self._on_game_scanned(report))
            except Exception as error:
                self.context.logger.exception("Game discovery failed")
                message = str(error)
                self._post_ui(
                    lambda message=message: self._show_game_error(message, popup=False),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_game_scanned(self, report) -> None:
        self._set_game_buttons("normal")
        installations = [
            installation
            for installation in report.available
            if installation.game_id == "stellaris"
        ]
        if not installations:
            self.current_installation = None
            self.game_status.configure(text="Stellaris · 未检测到有效安装")
            suffix = f"（扫描产生 {len(report.issues)} 条诊断信息）" if report.issues else ""
            self.game_path.configure(text=f"可使用“选择目录”手动指定 Stellaris 根目录{suffix}")
            self.open_game_button.configure(state="disabled")
            self.launch_game_button.configure(state="disabled")
            self.top_health.configure(text="Stellaris · 未检测到有效路径")
            return

        installation = next(
            (item for item in installations if item.selected),
            installations[0],
        )
        self._show_installation(installation)

    def _choose_game_path(self) -> None:
        if self.discovery is None:
            return
        selected = filedialog.askdirectory(
            title="选择 Stellaris 游戏根目录",
            parent=self.window,
            mustexist=True,
        )
        if not selected:
            return
        self._set_game_buttons("disabled")
        self.game_status.configure(text="Stellaris · 正在验证所选目录……")

        def worker() -> None:
            try:
                installation = self.discovery.add_manual(
                    "stellaris.steam",
                    Path(selected),
                    select=True,
                )
                self._post_ui(
                    lambda installation=installation: self._show_installation(
                        installation
                    ),
                )
            except Exception as error:
                self.context.logger.exception("Manual game path validation failed")
                message = str(error)
                self._post_ui(
                    lambda message=message: self._show_game_error(message),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_installation(self, installation) -> None:
        self.current_installation = installation
        self._refresh_installed_dlc_paths()
        self.auto_install_attempted.clear()
        self._set_game_buttons("normal")
        version = installation.metadata.get("rawVersion")
        version_text = f" · {version}" if isinstance(version, str) else ""
        self.game_status.configure(text=f"Stellaris · Steam{version_text}")
        self.game_path.configure(text=str(installation.root))
        self.open_game_button.configure(state="normal")
        self.launch_game_button.configure(state="normal")
        self.top_health.configure(text=f"Stellaris · 路径正常{version_text}")
        self.selected_dlc_ids = {
            dlc_id for dlc_id in self.selected_dlc_ids
            if not any(
                entry.dlc_id == dlc_id and self._is_entry_installed(entry)
                for entry in self.catalog_entries
            )
        }
        self._render_catalog_rows()
        self._schedule_ready_installs()

    def _show_game_error(self, message: str, *, popup: bool = True) -> None:
        self._set_game_buttons("normal")
        self.game_status.configure(text="Stellaris · 路径验证失败")
        self.game_path.configure(text=message)
        self.top_health.configure(text="Stellaris · 路径异常")
        if popup:
            messagebox.showerror("游戏路径无效", message, parent=self.window)

    def _open_game_directory(self) -> None:
        if self.current_installation is None:
            return
        try:
            if os.name == "nt":
                os.startfile(self.current_installation.root)  # type: ignore[attr-defined]
            else:
                webbrowser.open(self.current_installation.root.as_uri())
        except Exception as error:
            self._show_game_error(str(error))

    def _launch_game(self) -> None:
        webbrowser.open("steam://rungameid/281990")

    def _check_update(self) -> None:
        if not self.context.updates.enabled:
            messagebox.showinfo(
                "更新尚未配置",
                "请先在 config/update.json 中填写 manifest_url。",
                parent=self.window,
            )
            return
        self.update_button.configure(state="disabled")
        self.status.configure(text="正在检查更新……")

        def worker() -> None:
            try:
                release = self.context.updates.check()
                self._post_ui(lambda release=release: self._on_checked(release))
            except Exception as error:
                self.context.logger.exception("Update check failed")
                message = str(error)
                self._post_ui(lambda message=message: self._show_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _on_checked(self, release) -> None:
        if release is None:
            self.status.configure(text="当前已是最新版本")
            self.update_button.configure(state="normal")
            return
        answer = messagebox.askyesno(
            "发现新版本",
            f"发现 v{release.version}\n\n{release.notes or '是否立即安装？'}",
            parent=self.window,
        )
        if not answer:
            self.status.configure(text=f"已发现 v{release.version}，暂未安装")
            self.update_button.configure(state="normal")
            return
        self.status.configure(text=f"正在下载 v{release.version}……")

        def progress(current: int, total: int | None) -> None:
            def apply() -> None:
                if total:
                    self.progress.set(min(current / total, 1))
                    self.status.configure(
                        text=(
                            f"正在下载…… {current / 1048576:.1f}/"
                            f"{total / 1048576:.1f} MB"
                        )
                    )
                else:
                    self.status.configure(text=f"正在下载…… {current / 1048576:.1f} MB")

            self._post_ui(apply)

        def worker() -> None:
            try:
                self.context.updates.install(release, progress)
                self._post_ui(lambda: self._installed(release.version))
            except Exception as error:
                # Full packages are intentionally handled as a browser download in v0.1.
                if hasattr(error, "url"):
                    self._post_ui(
                        lambda error=error: self._open_full_update(error),
                    )
                    return
                self.context.logger.exception("Update installation failed")
                message = str(error)
                self._post_ui(lambda message=message: self._show_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _installed(self, version: str) -> None:
        self.progress.set(1)
        self.status.configure(text=f"v{version} 已安装，重启后生效")
        if messagebox.askyesno("更新完成", "模块更新已安全安装，是否立即重启？", parent=self.window):
            self.context.restart()
        self.update_button.configure(state="normal")

    def _open_full_update(self, error) -> None:
        self.status.configure(text=f"v{error.version} 需要完整更新")
        self.update_button.configure(state="normal")
        if messagebox.askyesno(
            "需要完整更新",
            "该版本包含启动器变更，需要重新下载完整压缩包。是否打开下载页面？",
            parent=self.window,
        ):
            webbrowser.open(error.url)

    def _show_error(self, message: str) -> None:
        self.status.configure(text="更新失败")
        self.update_button.configure(state="normal")
        messagebox.showerror("更新失败", message, parent=self.window)

    def run(self) -> None:
        self.window.mainloop()


def create_application(context) -> DlcHubApplication:
    return DlcHubApplication(context)
