from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import customtkinter as ctk
from tkinter import BooleanVar, filedialog, messagebox

from .signriver_app.adapters import AdapterRegistry
from .signriver_app.adapters.builtin import create_builtin_adapters
from .signriver_app.application import DlcInstallService, DownloadQueue, GameDiscoveryService, StellarisCatalogService
from .signriver_app.domain import DownloadSpec, DownloadState, InstallHealth, UserSettings
from .signriver_app.infrastructure.catalog import GitLinkReleaseSource, GitLinkSourceConfig
from .signriver_app.infrastructure.catalog import inspect_stellaris_package
from .signriver_app.infrastructure.cache import CacheMaintenance
from .signriver_app.infrastructure.downloads import DownloadManager, DownloadPolicy
from .signriver_app.infrastructure.diagnostics import DiagnosticExporter
from .signriver_app.infrastructure.installs import StellarisInstallEngine
from .signriver_app.infrastructure.persistence import (
    Database,
    DownloadTaskRepository,
    GameInstallationRepository,
    InstallReceiptRepository,
    UserSettingsRepository,
)


class DlcHubApplication:
    def __init__(self, context) -> None:
        self.context = context
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        self.window = ctk.CTk()
        self.window.title("SignRiver DLC Hub")
        self.window.geometry("960x900")
        self.window.minsize(780, 720)
        self.discovery = None
        release_source = GitLinkReleaseSource(
            GitLinkSourceConfig("signriver", "file-warehouse")
        )
        self.catalog = StellarisCatalogService(
            release_source, manifest_loader=release_source.read_asset
        )
        self.user_settings = UserSettings()
        self.settings_repository = None
        self.download_manager = DownloadManager(self.context.paths.cache)
        self.cache_maintenance = CacheMaintenance(self.context.paths.cache)
        self.diagnostic_exporter = DiagnosticExporter(
            self.context.paths.root, self.context.paths.data
        )
        self.last_log_content = ""
        self.catalog_entries = ()
        self.catalog_snapshot = None
        self.catalog_rows = {}
        self.selected_dlc_ids = set()
        self.dlc_selection_vars = {}
        self.download_repository = None
        self.download_queue = None
        self.install_repository = None
        self.install_service = None
        self.task_refresh_pending = False
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
        try:
            registry = AdapterRegistry(create_builtin_adapters())
            database = Database(self.context.paths.data / "hub.db")
            self.settings_repository = UserSettingsRepository(database)
            self.user_settings = self.settings_repository.load()
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
                max_concurrent=self.user_settings.download_concurrency,
                on_change=self._queue_download_event,
                verifier_for=lambda _spec: inspect_stellaris_package,
            )
        except Exception:
            self.context.logger.exception("Unable to initialize game discovery")
        self._build_ui()
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self._show_recovered_downloads()
        self.window.after(900, self._show_onboarding)
        self.window.after(1200, self._update_global_status)
        self.window.after(350, self._scan_games)
        self.window.after(500, self._refresh_catalog)
        if self.context.updates.enabled and self.context.updates.check_on_startup:
            self.window.after(800, self._check_update)

    def _build_ui(self) -> None:
        shell = ctk.CTkFrame(self.window, fg_color="transparent")
        shell.pack(fill="both", expand=True)
        sidebar = ctk.CTkFrame(shell, width=150, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(
            sidebar, text="SignRiver", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", padx=18, pady=(28, 22))
        self.navigation_buttons = {}
        for page_name in ("DLC 库", "下载任务", "日志", "设置", "关于"):
            button = ctk.CTkButton(
                sidebar, text=page_name, anchor="w", width=116,
                fg_color="transparent", text_color=("gray15", "gray85"),
                hover_color=("gray80", "gray25"),
                command=lambda page_name=page_name: self._show_page(page_name),
            )
            button.pack(fill="x", padx=14, pady=3)
            self.navigation_buttons[page_name] = button
        self.global_status = ctk.CTkLabel(
            sidebar, text="网络：等待\n任务：0\n缓存：计算中",
            justify="left", anchor="w", text_color=("gray35", "gray70"),
        )
        self.global_status.pack(side="bottom", fill="x", padx=18, pady=(8, 22))
        self.global_notice = ctk.CTkLabel(
            sidebar, text="", justify="left", anchor="w", wraplength=115,
        )
        self.global_notice.pack(side="bottom", fill="x", padx=18, pady=4)

        container = ctk.CTkScrollableFrame(shell, fg_color="transparent")
        container.pack(side="right", fill="both", expand=True, padx=28, pady=24)

        topbar = ctk.CTkFrame(container, fg_color="transparent")
        topbar.pack(fill="x", pady=(0, 24))
        title_group = ctk.CTkFrame(topbar, fg_color="transparent")
        title_group.pack(side="left")
        ctk.CTkLabel(
            title_group, text="SignRiver DLC Hub",
            font=ctk.CTkFont(size=30, weight="bold"),
        ).pack(anchor="w")
        self.top_health = ctk.CTkLabel(
            title_group, text="Stellaris · 等待路径检测",
            text_color=("gray35", "gray70"), font=ctk.CTkFont(size=14),
        )
        self.top_health.pack(anchor="w", pady=(3, 0))
        profile_group = ctk.CTkFrame(topbar, fg_color="transparent")
        profile_group.pack(side="right")
        ctk.CTkLabel(
            profile_group, text="SignRiver", font=ctk.CTkFont(weight="bold")
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            profile_group, text="主页", width=58,
            command=lambda: self._open_external_link(
                "https://www.gitlink.org.cn/signriver"
            ),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            profile_group, text="资源仓库", width=78,
            command=lambda: self._open_external_link(
                "https://www.gitlink.org.cn/signriver/file-warehouse"
            ),
        ).pack(side="left", padx=3)

        game_card = ctk.CTkFrame(container)
        self.game_card = game_card
        game_card.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(
            game_card,
            text="游戏检测",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(18, 4))
        selector_row = ctk.CTkFrame(game_card, fg_color="transparent")
        selector_row.pack(fill="x", padx=24, pady=(2, 8))
        ctk.CTkLabel(selector_row, text="当前游戏").pack(side="left")
        self.game_selector = ctk.CTkOptionMenu(
            selector_row, values=list(self.supported_games),
            command=self._select_game, width=190,
        )
        self.game_selector.set(self.selected_game_name)
        self.game_selector.pack(side="left", padx=(10, 0))
        self.platform_status = ctk.CTkLabel(
            selector_row, text="Steam · App 281990",
            text_color=("gray40", "gray70"),
        )
        self.platform_status.pack(side="right")
        self.game_status = ctk.CTkLabel(
            game_card,
            text="Stellaris · 等待扫描",
            anchor="w",
        )
        self.game_status.pack(fill="x", padx=24)
        self.game_path = ctk.CTkLabel(
            game_card,
            text="尚未检测游戏路径",
            anchor="w",
            text_color=("gray40", "gray70"),
            wraplength=760,
        )
        self.game_path.pack(fill="x", padx=24, pady=(2, 12))

        game_actions = ctk.CTkFrame(game_card, fg_color="transparent")
        game_actions.pack(fill="x", padx=24, pady=(0, 18))
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

        catalog_card = ctk.CTkFrame(container)
        self.catalog_card = catalog_card
        catalog_card.pack(fill="x", pady=(0, 18))
        catalog_header = ctk.CTkFrame(catalog_card, fg_color="transparent")
        catalog_header.pack(fill="x", padx=24, pady=(16, 6))
        ctk.CTkLabel(
            catalog_header,
            text="DLC 目录",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")
        self.catalog_refresh_button = ctk.CTkButton(
            catalog_header,
            text="刷新目录",
            command=self._refresh_catalog,
            width=100,
        )
        self.catalog_refresh_button.pack(side="right")
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
            text_color=("gray40", "gray70"),
        )
        self.catalog_preview.pack(fill="x", padx=24, pady=(2, 16))
        catalog_tools = ctk.CTkFrame(catalog_card, fg_color="transparent")
        catalog_tools.pack(fill="x", padx=24, pady=(0, 8))
        self.catalog_search = ctk.CTkEntry(
            catalog_tools, placeholder_text="搜索 DLC 编号或名称", width=240
        )
        self.catalog_search.pack(side="left")
        self.catalog_search.bind("<KeyRelease>", lambda _event: self._render_catalog_rows())
        self.catalog_filter = ctk.CTkOptionMenu(
            catalog_tools,
            values=["全部状态", "未下载", "进行中", "已暂停", "已完成", "失败"],
            command=lambda _value: self._render_catalog_rows(),
            width=110,
        )
        self.catalog_filter.pack(side="left", padx=(8, 0))
        self.download_selected_button = ctk.CTkButton(
            catalog_tools, text="下载所选", command=self._download_selected, width=100
        )
        self.download_selected_button.pack(side="right")
        self.select_visible_button = ctk.CTkButton(
            catalog_tools, text="全选结果", command=self._select_visible, width=90
        )
        self.select_visible_button.pack(side="right", padx=(0, 8))
        self.dlc_list_frame = ctk.CTkScrollableFrame(
            catalog_card, height=220, fg_color="transparent"
        )
        self.dlc_list_frame.pack(fill="x", padx=18, pady=(0, 16))
        self.dlc_list_frame.grid_columnconfigure(1, weight=1)

        card = ctk.CTkFrame(container)
        self.about_card = card
        card.pack(fill="x")
        ctk.CTkLabel(
            card,
            text="模块化更新框架已就绪",
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

        settings_card = ctk.CTkFrame(container)
        self.settings_card = settings_card
        settings_card.pack(fill="x", pady=(18, 0))
        ctk.CTkLabel(
            settings_card, text="下载设置",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(18, 8))
        settings_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_row.pack(fill="x", padx=24)
        ctk.CTkLabel(settings_row, text="同时下载").pack(side="left")
        self.concurrency_menu = ctk.CTkOptionMenu(
            settings_row, values=[str(value) for value in range(1, 9)], width=70
        )
        self.concurrency_menu.set(str(self.user_settings.download_concurrency))
        self.concurrency_menu.pack(side="left", padx=(8, 20))
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
        self.settings_status = ctk.CTkLabel(
            utility_row, text="设置修改后重启程序生效", anchor="e"
        )
        self.settings_status.pack(side="right")
        ctk.CTkLabel(
            settings_card,
            text="设置会在下次启动时应用，不会中断当前下载。",
            text_color=("gray40", "gray70"),
        ).pack(anchor="w", padx=24, pady=(0, 18))

        self.task_card = ctk.CTkFrame(container)
        task_header = ctk.CTkFrame(self.task_card, fg_color="transparent")
        task_header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(
            task_header, text="下载任务", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            task_header, text="刷新", command=self._refresh_task_page, width=80
        ).pack(side="right")
        ctk.CTkButton(
            task_header, text="清除失败/取消记录",
            command=self._clear_terminal_tasks, width=110,
        ).pack(side="right", padx=(0, 8))
        self.task_list_frame = ctk.CTkScrollableFrame(
            self.task_card, height=480, fg_color="transparent"
        )
        self.task_list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        self.log_card = ctk.CTkFrame(container)
        log_header = ctk.CTkFrame(self.log_card, fg_color="transparent")
        log_header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(
            log_header, text="运行日志", font=ctk.CTkFont(size=18, weight="bold")
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
        self.log_level_filter = ctk.CTkOptionMenu(
            log_tools, values=["全部", "INFO", "WARNING", "ERROR"], width=100,
            command=lambda _value: self._refresh_log_preview(),
        )
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
        self.log_preview = ctk.CTkTextbox(self.log_card, height=520, wrap="word")
        self.log_preview.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.log_preview.configure(state="disabled")
        self.window.after(50, self._refresh_log_preview)

        self.footer_label = ctk.CTkLabel(
            container,
            text="Stellaris Steam 已接入 · 模块化多游戏架构",
            text_color=("gray45", "gray65"),
        )
        self.footer_label.pack(anchor="w", pady=(24, 0))
        self.page_sections = {
            "DLC 库": (self.game_card, self.catalog_card),
            "下载任务": (self.task_card,),
            "日志": (self.log_card,),
            "设置": (self.settings_card,),
            "关于": (self.about_card, self.footer_label),
        }
        self._show_page("DLC 库")

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
        allowed_hosts = {"www.gitlink.org.cn", "gitlink.org.cn"}
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            messagebox.showerror("链接被阻止", "只允许打开预先配置的 GitLink HTTPS 链接。", parent=self.window)
            return
        webbrowser.open(url)

    def _show_page(self, page_name: str) -> None:
        self.current_page = page_name
        for sections in self.page_sections.values():
            for section in sections:
                section.pack_forget()
        for section in self.page_sections[page_name]:
            section.pack(fill="x", pady=(0, 18))
        for name, button in self.navigation_buttons.items():
            button.configure(
                fg_color=("gray75", "gray30") if name == page_name else "transparent"
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
            DownloadState.PAUSED: "已暂停",
            DownloadState.RETRYING: "等待重试",
            DownloadState.VERIFYING: "校验中",
            DownloadState.READY: "已完成",
            DownloadState.CANCELLED: "已取消",
            DownloadState.FAILED: "失败",
            DownloadState.CORRUPT: "坏包",
        }
        for snapshot in snapshots:
            row = ctk.CTkFrame(self.task_list_frame)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(
                row, text=snapshot.spec.filename, anchor="w"
            ).pack(fill="x", padx=14, pady=(10, 2))
            state = labels.get(snapshot.state, str(snapshot.state))
            speed = (
                f" · {snapshot.speed_bytes_per_second / 1024:.1f} KiB/s"
                if snapshot.speed_bytes_per_second else ""
            )
            error = f" · {snapshot.error}" if snapshot.error else ""
            ctk.CTkLabel(
                row,
                text=(
                    f"{state} · {snapshot.bytes_downloaded / 1024:.1f} KiB"
                    f"{speed}{error}"
                ),
                anchor="w", text_color=("gray40", "gray70"),
            ).pack(fill="x", padx=14, pady=(0, 4))
            actions = ctk.CTkFrame(row, fg_color="transparent")
            actions.pack(fill="x", padx=14, pady=(0, 10))
            if snapshot.state in {
                DownloadState.QUEUED, DownloadState.DOWNLOADING,
                DownloadState.RETRYING, DownloadState.VERIFYING,
            }:
                ctk.CTkButton(
                    actions, text="暂停", width=64,
                    command=lambda task_id=snapshot.spec.task_id: self._task_action(task_id, "pause"),
                ).pack(side="left")
                ctk.CTkButton(
                    actions, text="取消", width=64,
                    command=lambda task_id=snapshot.spec.task_id: self._task_action(task_id, "cancel"),
                ).pack(side="left", padx=(6, 0))
            elif snapshot.state in {DownloadState.PAUSED, DownloadState.FAILED}:
                ctk.CTkButton(
                    actions, text="继续" if snapshot.state is DownloadState.PAUSED else "重试",
                    width=64,
                    command=lambda task_id=snapshot.spec.task_id: self._task_action(task_id, "resume"),
                ).pack(side="left")
                if snapshot.state is DownloadState.PAUSED:
                    ctk.CTkButton(
                        actions, text="取消", width=64,
                        command=lambda task_id=snapshot.spec.task_id: self._task_action(task_id, "cancel"),
                    ).pack(side="left", padx=(6, 0))

    def _schedule_task_refresh(self) -> None:
        if self.task_refresh_pending:
            return
        self.task_refresh_pending = True
        self.window.after(250, self._refresh_task_page)

    def _task_action(self, task_id: str, action: str) -> None:
        if self.download_queue is None:
            return
        try:
            if action == "pause":
                self.download_queue.pause(task_id)
            elif action == "cancel":
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

    def _save_settings(self) -> None:
        try:
            limit_text = self.bandwidth_entry.get().strip()
            settings = UserSettings(
                download_concurrency=int(self.concurrency_menu.get()),
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
            "4. 只有可信清单验证通过时才开放自动安装。\n\n"
            "当前 GitLink ste Release 尚无可信清单，因此可以浏览和下载，安装保持禁用。",
            parent=self.window,
        )
        self.user_settings = UserSettings(
            self.user_settings.download_concurrency,
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
            text_color=("#b42318", "#ff8a80") if error else ("#147d64", "#5adbb5"),
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

    def _update_global_status(self) -> None:
        snapshots = self.download_queue.snapshots() if self.download_queue is not None else ()
        active_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.RETRYING, DownloadState.VERIFYING,
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
                snapshot = self.catalog.refresh_snapshot()
                self.window.after(0, lambda snapshot=snapshot: self._show_catalog(snapshot))
            except Exception as error:
                self.context.logger.exception("DLC catalog refresh failed")
                message = str(error)
                self.window.after(0, lambda message=message: self._show_catalog_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _show_catalog(self, snapshot) -> None:
        self.catalog_online = True
        self.catalog_snapshot = snapshot
        entries = snapshot.entries
        self.catalog_entries = entries
        self.catalog_refresh_button.configure(state="normal")
        self.catalog_status.configure(
            text=f"Stellaris · 已读取 {len(entries)} 个 DLC 资源 · {snapshot.trust_reason}"
        )
        if not entries:
            self.catalog_preview.configure(text="Release 中没有符合命名规则的 DLC ZIP")
            return
        first = entries[0]
        size = first.asset.display_size or "大小未知"
        self.catalog_preview.configure(
            text=f"首项：{first.dlc_id} · {first.display_name} · {size}"
        )
        self._render_catalog_rows()

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
        snapshots = {}
        if self.download_queue is not None:
            snapshots = {item.spec.task_id: item for item in self.download_queue.snapshots()}
        visible_entries = self._visible_catalog_entries(snapshots)
        valid_ids = {entry.dlc_id for entry in self.catalog_entries}
        self.selected_dlc_ids.intersection_update(valid_ids)
        self.dlc_selection_vars.clear()
        for index, entry in enumerate(visible_entries):
            row = ctk.CTkFrame(self.dlc_list_frame)
            row.grid(row=index, column=0, columnspan=8, sticky="ew", pady=3)
            row.grid_columnconfigure(2, weight=1)
            selected = BooleanVar(value=entry.dlc_id in self.selected_dlc_ids)
            self.dlc_selection_vars[entry.dlc_id] = selected
            ctk.CTkCheckBox(
                row, text="", width=22, variable=selected,
                command=lambda entry=entry, selected=selected: self._set_selected(
                    entry.dlc_id, selected.get()
                ),
            ).grid(row=0, column=0, padx=(10, 0), pady=8)
            ctk.CTkLabel(row, text=entry.dlc_id.upper(), width=62).grid(
                row=0, column=1, padx=(2, 6), pady=8
            )
            ctk.CTkLabel(row, text=entry.display_name, anchor="w").grid(
                row=0, column=2, sticky="ew", padx=4
            )
            status = ctk.CTkLabel(
                row, text=entry.asset.display_size or "大小未知", width=150, anchor="e"
            )
            status.grid(row=0, column=3, padx=6)
            action = ctk.CTkButton(
                row, text="下载", width=68,
                command=lambda entry=entry: self._start_entry_download(entry),
            )
            action.grid(row=0, column=4, padx=4)
            pause = ctk.CTkButton(
                row, text="暂停", width=58, state="disabled",
                command=lambda entry=entry: self._pause_entry(entry),
            )
            pause.grid(row=0, column=5, padx=4)
            cancel = ctk.CTkButton(
                row, text="取消", width=58, state="disabled",
                command=lambda entry=entry: self._cancel_entry(entry),
            )
            cancel.grid(row=0, column=6, padx=(4, 10))
            manage = ctk.CTkButton(
                row, text="未验证", width=68, state="disabled",
                command=lambda entry=entry: self._manage_entry(entry),
            )
            manage.grid(row=0, column=7, padx=4)
            uninstall = ctk.CTkButton(
                row, text="卸载", width=58, state="disabled",
                command=lambda entry=entry: self._uninstall_entry(entry),
            )
            uninstall.grid(row=0, column=8, padx=(4, 10))
            task_id = f"stellaris-{entry.dlc_id}"
            self.catalog_rows[task_id] = (status, action, pause, cancel, manage, uninstall)
            if task_id in snapshots:
                self._show_download_state(snapshots[task_id])
            self._show_install_state(entry)
        if not visible_entries:
            ctk.CTkLabel(
                self.dlc_list_frame, text="没有符合当前搜索和筛选条件的 DLC"
            ).grid(row=0, column=0, padx=12, pady=24)

    def _visible_catalog_entries(self, snapshots):
        query = self.catalog_search.get().strip().casefold()
        selected_filter = self.catalog_filter.get()
        result = []
        for entry in self.catalog_entries:
            if query and query not in entry.dlc_id.casefold() and query not in entry.display_name.casefold():
                continue
            snapshot = snapshots.get(f"stellaris-{entry.dlc_id}")
            state = snapshot.state if snapshot else None
            groups = {
                "未下载": state is None or state is DownloadState.CANCELLED,
                "进行中": state in {
                    DownloadState.QUEUED, DownloadState.DOWNLOADING,
                    DownloadState.RETRYING, DownloadState.VERIFYING,
                },
                "已暂停": state is DownloadState.PAUSED,
                "已完成": state is DownloadState.READY,
                "失败": state in {DownloadState.FAILED, DownloadState.CORRUPT},
            }
            if selected_filter != "全部状态" and not groups[selected_filter]:
                continue
            result.append(entry)
        return tuple(result)

    def _set_selected(self, dlc_id: str, selected: bool) -> None:
        if selected:
            self.selected_dlc_ids.add(dlc_id)
        else:
            self.selected_dlc_ids.discard(dlc_id)

    def _select_visible(self) -> None:
        snapshots = {}
        if self.download_queue is not None:
            snapshots = {item.spec.task_id: item for item in self.download_queue.snapshots()}
        visible = self._visible_catalog_entries(snapshots)
        for entry in visible:
            self.selected_dlc_ids.add(entry.dlc_id)
            variable = self.dlc_selection_vars.get(entry.dlc_id)
            if variable is not None:
                variable.set(True)

    def _download_selected(self) -> None:
        selected = [
            entry for entry in self.catalog_entries
            if entry.dlc_id in self.selected_dlc_ids
        ]
        if not selected:
            self.catalog_preview.configure(text="请先勾选至少一个 DLC")
            return
        started = 0
        for entry in selected:
            try:
                self._start_entry_download(entry, show_error=False)
                started += 1
            except Exception:
                self.context.logger.exception("Unable to enqueue selected DLC")
        self.catalog_preview.configure(
            text=f"已提交 {started} 个下载任务；同时最多下载 2 个"
        )

    def _start_entry_download(self, entry, *, show_error: bool = True) -> None:
        trusted = self._trusted_asset(entry.dlc_id)
        spec = DownloadSpec(
            task_id=f"stellaris-{entry.dlc_id}",
            url=entry.asset.download_url,
            filename=entry.asset.name,
            expected_size=trusted.size if trusted else None,
            expected_sha256=trusted.sha256 if trusted else None,
            supports_range=False,
        )

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
        except Exception as error:
            if show_error:
                self.catalog_preview.configure(text=str(error))
            else:
                raise

    def _download_finished(self, future) -> None:
        try:
            result = future.result()
            self.context.logger.info(
                "DLC download finished: task=%s state=%s sha256=%s",
                result.spec.task_id, result.state, result.sha256,
            )
            self.window.after(
                0,
                lambda result=result: self._notify(
                    f"{result.spec.filename}：{'下载完成' if result.state is DownloadState.READY else result.state.value}",
                    error=result.state in {DownloadState.FAILED, DownloadState.CORRUPT},
                ),
            )
        except Exception:
            self.context.logger.exception("DLC queue task crashed")
            self.window.after(0, lambda: self._notify("下载任务异常退出", error=True))

    def _queue_download_event(self, snapshot) -> None:
        def apply() -> None:
            self._show_download_state(snapshot)
            if getattr(self, "current_page", None) == "下载任务":
                self._schedule_task_refresh()
        self.window.after(0, apply)

    def _show_recovered_downloads(self) -> None:
        if self.download_queue is None:
            return
        try:
            recovered = self.download_queue.restore()
        except Exception:
            self.context.logger.exception("Unable to recover download tasks")
            return
        if recovered:
            self.catalog_preview.configure(
                text=f"已恢复 {len(recovered)} 个未完成下载任务；刷新目录后可重新开始"
            )

    def _pause_entry(self, entry) -> None:
        if self.download_queue is not None:
            try:
                self.download_queue.pause(f"stellaris-{entry.dlc_id}")
            except (KeyError, ValueError):
                pass

    def _cancel_entry(self, entry) -> None:
        if self.download_queue is not None:
            try:
                self.download_queue.cancel(f"stellaris-{entry.dlc_id}")
            except (KeyError, ValueError):
                pass

    def _trusted_asset(self, dlc_id: str):
        if self.catalog_snapshot is None or not self.catalog_snapshot.installation_allowed:
            return None
        return next(
            (item for item in self.catalog_snapshot.trusted_assets if item.dlc_id == dlc_id),
            None,
        )

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

    def _show_install_state(self, entry) -> None:
        row = self.catalog_rows.get(f"stellaris-{entry.dlc_id}")
        if row is None:
            return
        _status, _action, _pause, _cancel, manage, uninstall = row
        receipt = self._active_receipt(entry.dlc_id)
        if receipt is not None and self.current_installation is not None:
            manage.configure(state="normal", text="检查")
            uninstall.configure(state="normal")
            return
        uninstall.configure(state="disabled")
        if self.current_installation is None:
            manage.configure(state="disabled", text="无路径")
        elif self._trusted_asset(entry.dlc_id) is None:
            manage.configure(state="disabled", text="未验证")
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
                    self.window.after(
                        0, lambda audit=audit: self._show_audit_result(entry, audit)
                    )
                except Exception as error:
                    self.context.logger.exception("DLC audit failed")
                    message = str(error)
                    self.window.after(0, lambda message=message: messagebox.showerror(
                        "检查失败", message, parent=self.window
                    ))

            threading.Thread(target=inspect_worker, daemon=True).start()
            return
        download = self._ready_download(entry.dlc_id)
        trusted = self._trusted_asset(entry.dlc_id)
        if download is None or trusted is None:
            return
        if not messagebox.askyesno(
            "确认安装", f"将 {entry.display_name} 安装到当前 Stellaris 目录？",
            parent=self.window,
        ):
            return
        self._run_install_action(
            lambda: self.install_service.install(
                download.result_path, self.current_installation.root,
                expected_sha256=trusted.sha256,
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
        if self.install_service is None or self.current_installation is None:
            return
        if not messagebox.askyesno(
            "确认卸载", f"安全卸载 {entry.display_name}？修改过的文件不会被静默删除。",
            parent=self.window,
        ):
            return
        self._run_install_action(
            lambda: self.install_service.uninstall(
                "stellaris", entry.dlc_id, self.current_installation.root
            ),
            entry,
            "卸载完成",
        )

    def _run_install_action(self, operation, entry, success_text: str) -> None:
        def worker() -> None:
            try:
                operation()
                self.window.after(0, lambda: self._finish_install_action(entry, success_text))
            except Exception as error:
                self.context.logger.exception("DLC install action failed")
                message = str(error)
                self.window.after(0, lambda message=message: messagebox.showerror(
                    "操作失败", message, parent=self.window
                ))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_install_action(self, entry, text: str) -> None:
        self._show_install_state(entry)
        self._notify(f"{entry.display_name}：{text}")
        messagebox.showinfo(text, f"{entry.display_name}：{text}", parent=self.window)

    def _close(self) -> None:
        if self.download_queue is not None:
            self.download_queue.shutdown(wait=False)
        self.window.destroy()

    def _show_download_state(self, snapshot) -> None:
        labels = {
            DownloadState.DOWNLOADING: "下载中",
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
        row = self.catalog_rows.get(task_id)
        if row is None:
            return
        status, action, pause, cancel, _manage, _uninstall = row
        status.configure(text=(
            f"{label} · {snapshot.bytes_downloaded / 1024:.1f} KB"
            f"{speed_text}{eta_text}"
        ))
        terminal = {
            DownloadState.READY, DownloadState.PAUSED, DownloadState.CANCELLED,
            DownloadState.FAILED, DownloadState.CORRUPT,
        }
        if snapshot.state in terminal:
            action.configure(
                state="normal",
                text="继续" if snapshot.state in {DownloadState.PAUSED, DownloadState.FAILED} else "重新下载",
            )
            pause.configure(state="disabled")
            cancel.configure(
                state="normal" if snapshot.state is DownloadState.PAUSED else "disabled"
            )
        elif snapshot.state in {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.RETRYING, DownloadState.VERIFYING,
        }:
            action.configure(state="disabled", text="下载中")
            pause.configure(state="normal")
            cancel.configure(state="normal")
        entry = next(
            (item for item in self.catalog_entries if f"stellaris-{item.dlc_id}" == task_id),
            None,
        )
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
                self.window.after(0, lambda report=report: self._on_game_scanned(report))
            except Exception as error:
                self.context.logger.exception("Game discovery failed")
                message = str(error)
                self.window.after(
                    0,
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
                self.window.after(
                    0,
                    lambda installation=installation: self._show_installation(
                        installation
                    ),
                )
            except Exception as error:
                self.context.logger.exception("Manual game path validation failed")
                message = str(error)
                self.window.after(
                    0,
                    lambda message=message: self._show_game_error(message),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_installation(self, installation) -> None:
        self.current_installation = installation
        self._set_game_buttons("normal")
        version = installation.metadata.get("rawVersion")
        version_text = f" · {version}" if isinstance(version, str) else ""
        self.game_status.configure(text=f"Stellaris · Steam{version_text}")
        self.game_path.configure(text=str(installation.root))
        self.open_game_button.configure(state="normal")
        self.launch_game_button.configure(state="normal")
        self.top_health.configure(text=f"Stellaris · 路径正常{version_text}")
        self._render_catalog_rows()

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
                self.window.after(0, lambda: self._on_checked(release))
            except Exception as error:
                self.context.logger.exception("Update check failed")
                message = str(error)
                self.window.after(0, lambda message=message: self._show_error(message))

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

            self.window.after(0, apply)

        def worker() -> None:
            try:
                self.context.updates.install(release, progress)
                self.window.after(0, lambda: self._installed(release.version))
            except Exception as error:
                # Full packages are intentionally handled as a browser download in v0.1.
                if hasattr(error, "url"):
                    self.window.after(
                        0,
                        lambda error=error: self._open_full_update(error),
                    )
                    return
                self.context.logger.exception("Update installation failed")
                message = str(error)
                self.window.after(0, lambda message=message: self._show_error(message))

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
