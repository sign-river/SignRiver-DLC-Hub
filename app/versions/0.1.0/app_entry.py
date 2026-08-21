from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
import webbrowser
from dataclasses import replace
from pathlib import Path
from queue import Empty, SimpleQueue
from urllib.parse import urlparse

import customtkinter as ctk
from tkinter import BooleanVar, StringVar, TclError, filedialog, messagebox
from signriver_common.platforms import open_directory
from signriver_common.problems import (
    ProblemAction,
    ProblemCategory,
    ProblemCode,
    ProblemReport,
    ProblemSeverity,
    ProblemStatus,
    ProblemStore,
)

from .signriver_app.adapters import AdapterRegistry
from .signriver_app.application import (
    AnnouncementService,
    CartridgeCatalogError,
    CartridgeCatalogService,
    CatalogSnapshot,
    DlcInstallService,
    DownloadQueue,
    GameDiscoveryService,
    OriginalStateRestoreService,
    RestoreOriginalError,
)
from .signriver_app.domain import (
    Announcement,
    DownloadPurpose,
    DownloadSpec,
    DownloadState,
    InstallHealth,
    PatchBundle,
    PatchHealth,
    UserSettings,
)
from .signriver_app.infrastructure.cache import CacheMaintenance
from .signriver_app.infrastructure.catalog import (
    provider_display_name,
    repository_home_url,
    speed_test_url,
)
from .signriver_app.infrastructure.downloads import DownloadManager
from .signriver_app.infrastructure.diagnostics import DiagnosticExporter
from .signriver_app.infrastructure.installs import (
    InstallAccessError,
    InstallConflictError,
)
from .signriver_app.infrastructure.log_reader import read_tail_lines
from .signriver_app.infrastructure.patching import (
    PatchEngine,
    PatchError,
    RepairJournal,
)
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
    "primary_surface": "#EAF3FB",
    "primary_surface_hover": "#DCECF9",
    "primary_border": "#B8D7F2",
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

BUTTON_SECONDARY = {"fg_color": "transparent", "hover_color": UI["primary_surface"], "text_color": UI["primary"], "border_width": 1, "border_color": UI["primary_border"]}
BUTTON_NEUTRAL = {"fg_color": UI["panel"], "hover_color": UI["border"], "text_color": UI["text_secondary"]}
BUTTON_DANGER = {"fg_color": "transparent", "hover_color": UI["danger_surface"], "text_color": UI["danger"], "border_width": 1, "border_color": "#F3BBB5"}

# Keep in sync with signriver_launcher.product for packaging/UI naming.
PRODUCT_TITLE_ZH = "唏嘘南溪DLC一键解锁工具"
PRODUCT_HEADER_TITLE_ZH = "DLC一键解锁工具"
AUTHOR_EN = "SignRiver"
AUTHOR_CN = "唏嘘南溪"
USAGE_TUTORIAL_URL = "https://sign-river.github.io/p/signriver-dlc-hub/getting-started/"
BILIBILI_TUTORIAL_URL = "https://space.bilibili.com/504574253?spm_id_from=333.1007.0.0"
MICROSOFT_FALSE_POSITIVE_URL = "https://www.microsoft.com/en-us/wdsi/filesubmission"
WINDOWS_SECURITY_URI = "windowsdefender://threatsettings/"


class _PatchAssetVerificationError(RuntimeError):
    def __init__(
        self, code: ProblemCode, message: str, *, actual_sha256: str | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.actual_sha256 = actual_sha256


def _card(parent, **kwargs):
    return ctk.CTkFrame(
        parent,
        fg_color=UI["card"],
        border_color=UI["border"],
        border_width=1,
        corner_radius=14,
        **kwargs,
    )


def _settings_description(parent, text: str, **pack_kwargs):
    """Compact, read-only settings copy that expands only when it wraps."""
    label = ctk.CTkLabel(
        parent,
        text=text,
        text_color=UI["text_secondary"],
        font=ctk.CTkFont(size=13),
        anchor="w",
        justify="left",
        wraplength=760,
    )
    label.pack(fill="x", padx=24, **pack_kwargs)
    return label


def _blue_switch(parent, **kwargs):
    """Standard binary-setting switch with clear off and on states."""
    return ctk.CTkSwitch(
        parent,
        width=kwargs.pop("width", 154),
        height=30,
        switch_width=44,
        switch_height=24,
        corner_radius=12,
        border_width=1,
        fg_color="#AEBECD",
        border_color="#94A3B8",
        progress_color=UI["primary"],
        button_color="#F8FAFC",
        button_hover_color="#F8FAFC",
        text_color=UI["text_secondary"],
        font=ctk.CTkFont(size=13, weight="bold"),
        **kwargs,
    )


def _settings_header(parent, title: str, description: str):
    """Compact section heading for grouped settings."""
    header = ctk.CTkFrame(parent, fg_color="transparent")
    header.pack(fill="x", padx=22, pady=(18, 4))
    ctk.CTkLabel(
        header,
        text=title,
        text_color=UI["primary"],
        font=ctk.CTkFont(size=17, weight="bold"),
        anchor="w",
    ).pack(fill="x")
    ctk.CTkLabel(
        header,
        text=description,
        text_color=UI["text_secondary"],
        font=ctk.CTkFont(size=13),
        anchor="w",
    ).pack(fill="x", pady=(3, 0))
    return header


def _settings_group_body(parent):
    body = ctk.CTkFrame(parent, fg_color="transparent")
    body.pack(fill="x", padx=22, pady=(6, 8))
    return body


def _settings_row(parent, title: str, description: str, *, last: bool = False):
    """A desktop-style setting row: explanation on the left, control on the right."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(0, 0))
    row.grid_columnconfigure(0, weight=1)
    row.grid_columnconfigure(1, minsize=238)
    ctk.CTkLabel(
        row,
        text=title,
        text_color=UI["text"],
        font=ctk.CTkFont(size=15, weight="bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="w")
    description_label = ctk.CTkLabel(
        row,
        text=description,
        text_color=UI["text_secondary"],
        font=ctk.CTkFont(size=13),
        anchor="w",
        justify="left",
        wraplength=700,
    )
    description_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    action = ctk.CTkFrame(row, fg_color="transparent")
    action.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))
    if not last:
        ctk.CTkFrame(row, height=1, fg_color=UI["border"]).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(16, 16)
        )
    return row, action, description_label


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


class _InlineCatalogStatus:
    """Appends transient catalog feedback to the resource freshness line."""

    def __init__(self, label, freshness_text: str) -> None:
        self._label = label
        self._freshness_text = freshness_text
        self._message = ""

    def configure(self, **kwargs) -> None:
        if "text" in kwargs:
            self._message = kwargs["text"]
        self._render()

    def set_freshness_text(self, text: str) -> None:
        self._freshness_text = text
        self._render()

    def _render(self) -> None:
        text = self._freshness_text
        if self._message:
            text = f"{text} · {self._message}"
        self._label.configure(text=text, text_color=UI["muted"])


QQ_GROUP_JOIN_URL = "https://qm.qq.com/q/NQRer2RHmC"  # SignRiver DLC Hub 交流群


def _format_size(value: float) -> str:
    """Use the largest readable binary unit for user-facing byte counts."""
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            formatted = f"{amount:.1f}".rstrip("0").rstrip(".")
            return f"{formatted}{unit}"
        amount /= 1024
    return f"{amount:.1f}TB"


def _format_speed(value: float) -> str:
    return f"{_format_size(value)}/s"


class DlcHubApplication:
    def __init__(self, context) -> None:
        self.context = context
        self._configure_windows_app_identity()
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        self.window = ctk.CTk()
        # Build the whole UI while the window is hidden so users
        # never see a blank shell filling in gradually.
        self.window.withdraw()
        self.window.title(PRODUCT_TITLE_ZH)
        self.window.geometry("1120x840")
        self.window.minsize(1000, 700)
        self.window.configure(fg_color=UI["page"])
        self._apply_window_icon()
        self.ui_events = SimpleQueue()
        self.pending_download_snapshots = {}
        self.pending_download_lock = threading.Lock()
        self.update_download_active = False
        self.update_download_cancelling = False
        self.update_download_preparing = False
        self.update_download_version = ""
        self.update_download_current = 0
        self.update_download_total: int | None = None
        self.update_download_speed = 0.0
        self.update_download_started_at = 0.0
        self.update_download_cancel_event: threading.Event | None = None
        self.update_task_row = None
        self.update_task_status_label = None
        self.update_task_cancel_button = None
        self.ui_event_pump_running = True
        self.discovery = None
        self.adapter_registry = AdapterRegistry()
        self.cartridge_catalog = CartridgeCatalogService(
            self.context.paths.data / "cartridges",
            bootstrap_dir=self.context.paths.root / "config" / "cartridges",
            download_source="gitlink",
        )
        self.announcement_service = AnnouncementService(
            self.context.paths.data / "announcements",
            bootstrap_path=self.context.paths.root / "config" / "announcement.json",
            download_source="gitlink",
        )
        self.current_announcement: Announcement | None = None
        self.announcement_dialog = None
        # The searchable game picker is created only while the selector is open,
        # so the home page keeps its compact game-detection layout.
        self.game_picker = None
        self.game_picker_query: StringVar | None = None
        self.game_picker_search = None
        self.cartridge_loading = False
        self.cartridges: dict[str, object] = {}
        self.supported_games: dict[str, dict[str, str]] = {}
        # Defaults must exist before bootstrap cartridge activation; persisted
        # settings are loaded a few lines later and may re-activate if needed.
        self.user_settings = UserSettings()
        try:
            # Prefer packaged/cached documents so the first paint is not blocked
            # on GitLink.  A background refresh then replaces the hub index and
            # only downloads cartridges the user actually selects.
            self.cartridge_catalog.refresh_index(allow_network=False)
            loaded = self.cartridge_catalog.load_default_cartridge(allow_network=False)
            self._activate_loaded_cartridge(loaded, rebuild_services=False)
        except CartridgeCatalogError as error:
            self.context.logger.exception("Unable to load bootstrap game cartridges")
            raise RuntimeError(
                "没有可用的游戏支持数据。请确认安装包内容完整，"
                "或检查网络后重新启动。"
            ) from error
        self.patch_bundle: PatchBundle | None = None
        self.patch_workflow_state = "idle"
        self.patch_task_ids: tuple[str, ...] = ()
        self.pending_dlc_batch_task_ids: tuple[str, ...] = ()
        self.repair_workflow_active = False
        self.repair_phase = "idle"
        self.repair_prepare_task_ids: tuple[str, ...] = ()
        self.repair_requested_dlc_ids: tuple[str, ...] = ()
        self.repair_cleanup_errors: tuple[str, ...] = ()
        self.repair_game_selection_generation = -1
        self.repair_cartridge_id = ""
        self.repair_game_root: Path | None = None
        self.repair_journal = RepairJournal(self.context.paths.data)
        self.unlock_workflow_active = False
        self.unlock_requested_dlc_ids: tuple[str, ...] = ()
        self.unlock_failed_dlc_ids: set[str] = set()
        self.catalog_missing_patch_assets: tuple[str, ...] = ()
        # Filled after the current Release bundle is known.  Patch task IDs
        # include each GitLink attachment ID so stale generations cannot be
        # mistaken for the latest patch after an update.
        self.patch_task_roles: dict[str, str] = {}
        self.settings_repository = None
        self.download_manager = DownloadManager(self.context.paths.cache)
        self.cache_maintenance = CacheMaintenance(self.context.paths.cache)
        self.diagnostic_exporter = DiagnosticExporter(
            self.context.paths.root, self.context.paths.data
        )
        self.problem_store = ProblemStore(self.context.paths.data / "problems")
        self.recorded_download_failures: set[tuple[object, ...]] = set()
        self.selected_problem_event_id: str | None = None
        self.problem_rows: list[object] = []
        self.last_log_content = ""
        self.catalog_entries = ()
        self.catalog_rows = {}
        self.simple_status_labels = {}
        self.catalog_selection_widgets = {}
        self.catalog_entry_frames = {}
        self.catalog_name_labels = {}
        self.dlc_selection_vars = {}
        self.catalog_view_mode = "simple"
        self.displayed_catalog_view_mode = "simple"
        # Each catalog mode owns a persistent scroll frame and widget registry.
        # Switching views can therefore reveal an already-built tree instead of
        # destroying and recreating hundreds of CustomTkinter canvases.
        self.catalog_view_frames = {}
        self.catalog_view_widgets = {
            "simple": {
                "catalog_rows": self.catalog_rows,
                "simple_status_labels": self.simple_status_labels,
                "selection_widgets": self.catalog_selection_widgets,
                "entry_frames": self.catalog_entry_frames,
                "name_labels": self.catalog_name_labels,
                "selection_vars": self.dlc_selection_vars,
                "render_key": None,
            },
            "advanced": {
                "catalog_rows": {},
                "simple_status_labels": {},
                "selection_widgets": {},
                "entry_frames": {},
                "name_labels": {},
                "selection_vars": {},
                "render_key": None,
            },
        }
        self.catalog_render_generation = 0
        self.catalog_render_after_id = None
        self.simple_catalog_columns = 5
        self.selected_dlc_ids = set()
        self.catalog_selection_initialized = False
        self.batch_download_state = "idle"
        self.batch_download_task_ids = ()
        self.batch_pause_poll_pending = False
        self.batch_cancel_poll_pending = False
        self.auto_install_worker_running = False
        self.auto_install_attempted = set()
        self.auto_install_redownload_attempted = set()
        # READY cache is reusable data, not permission to modify a game.  Only
        # downloads explicitly requested during this session may auto-install.
        self.auto_install_requested_task_ids = set()
        self.speed_test_running = False
        self.download_repository = None
        self.download_queue = None
        self.install_repository = None
        self.install_service = None
        self.active_receipt_dlc_ids = frozenset()
        self.install_recovery_running = False
        self.install_recovery_failed = False
        self.install_recovery_key = None
        self.install_recovery_pending = None
        self.cache_cleanup_running = False
        self.manual_file_operation_token = None
        self.task_refresh_pending = False
        self.task_status_labels = {}
        self.task_row_states = {}
        self.task_rows = {}
        self.task_action_frames = {}
        self.task_action_keys = {}
        self.task_scroll_after_id = None
        self.task_scroll_target = None
        self.catalog_search_after_id = None
        self.log_search_after_id = None
        self.diagnostics_export_running = False
        self.cache_usage_bytes: int | None = None
        self.cache_usage_scan_running = False
        self.cache_usage_last_scan = 0.0
        self.cache_reconcile_lock = threading.Lock()
        self.cache_reconcile_running = False
        self.cache_reconcile_active_key = None
        self.cache_reconcile_pending = None
        self.compact_layout = None
        self.catalog_online = False
        self.notice_serial = 0
        self.current_installation = None
        self.game_selection_generation = 0
        self.download_source_generation = 0
        self.catalog_request_generation = 0
        self.installed_dlc_paths = {}
        try:
            database = Database(self.context.paths.data / "hub.db")
            self.settings_repository = UserSettingsRepository(database)
            stored_settings = self.settings_repository.load()
            self.user_settings = UserSettings(
                download_concurrency=1,
                bandwidth_limit_kib=None,
                onboarding_completed=stored_settings.onboarding_completed,
                download_never_timeout=stored_settings.download_never_timeout,
                download_source=stored_settings.download_source,
                announcement_mute_until_update=(
                    stored_settings.announcement_mute_until_update
                ),
                announcement_muted_id=stored_settings.announcement_muted_id,
            )
            if (
                stored_settings.download_concurrency != 1
                or stored_settings.bandwidth_limit_kib is not None
            ):
                self.settings_repository.save(self.user_settings)
            if self.user_settings.download_source != self.cartridge_catalog.download_source:
                self.cartridge_catalog.set_download_source(
                    self.user_settings.download_source
                )
                self.announcement_service.set_download_source(
                    self.user_settings.download_source
                )
                loaded = self.cartridge_catalog.load_default_cartridge(
                    allow_network=False
                )
                self._activate_loaded_cartridge(loaded, rebuild_services=False)
            elif (
                self.user_settings.download_source
                != self.announcement_service.download_source
            ):
                self.announcement_service.set_download_source(
                    self.user_settings.download_source
                )
            self.context.updates.set_download_source(
                self.user_settings.download_source
            )
            self.download_manager = DownloadManager(self.context.paths.cache)
            self.download_manager.configure_timeout(
                None if self.user_settings.download_never_timeout else 30
            )
            repository = GameInstallationRepository(database)
            self.download_repository = DownloadTaskRepository(database)
            self.install_repository = InstallReceiptRepository(database)
            self.install_service = DlcInstallService(
                self.cartridge.create_install_engine(self.context.paths.data),
                self.install_repository,
                game_id=self.cartridge.adapter.descriptor.game_id,
                package_inspector=self.cartridge.inspect_package,
            )
            self.discovery = GameDiscoveryService(self.adapter_registry, repository)
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
        self._update_problem_badge()
        self.main_window_origin = self._center_on_desktop(
            self.window, width=1120, height=840,
        )
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.after(50, self._drain_ui_events)
        self._show_recovered_downloads()
        self.window.after(900, self._refresh_announcement)
        self.window.after(1200, self._update_global_status)
        self.window.after(200, self._refresh_remote_cartridge_index)
        self.window.after(350, self._scan_games)
        self.window.after(500, self._refresh_catalog)
        if self.context.updates.enabled and self.context.updates.check_on_startup:
            self.window.after(800, self._auto_check_update)

    @staticmethod
    def _center_on_desktop(
        window, *, parent_bounds=None, width=None, height=None,
    ) -> tuple[int, int]:
        """Position a window once its requested layout dimensions are available."""
        window.update_idletasks()
        width = width or window.winfo_width()
        height = height or window.winfo_height()
        if parent_bounds is not None:
            parent_left, parent_top, parent_width, parent_height = parent_bounds
            left = parent_left + (parent_width - width) // 2
            top = parent_top + (parent_height - height) // 2
        else:
            desktop_width = window.winfo_screenwidth()
            desktop_height = window.winfo_screenheight()
            left = (desktop_width - width) // 2
            top = (desktop_height - height) // 2
        window.geometry(f"{width}x{height}{left:+d}{top:+d}")
        return left, top

    @staticmethod
    def _configure_windows_app_identity() -> None:
        """Pin a stable AppUserModelID so the taskbar can use our icon."""
        if os.name != "nt":
            return
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SignRiver.DLCHub.1"
            )
        except Exception:
            pass

    def _apply_window_icon(self) -> None:
        icon = Path(self.context.paths.root) / "config" / "app.ico"
        if not icon.is_file():
            return
        resolved = str(icon.resolve())
        try:
            # Use the multi-size ICO only. Feeding a 256px PNG through
            # iconphoto makes Windows taskbar downscale it into a blurry glyph.
            self.window.iconbitmap(default=resolved)
            self.window.iconbitmap(resolved)
        except TclError:
            self.context.logger.debug("Unable to apply ICO window icon", exc_info=True)
            return
        self.window.after(40, lambda: self._apply_native_windows_icons(resolved))
        self.window.after(200, lambda: self._apply_native_windows_icons(resolved))

    def _apply_native_windows_icons(self, ico_path: str) -> None:
        """Set ICON_SMALL / ICON_BIG via Win32 so the taskbar stays sharp."""
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x00000010
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            hwnd = int(self.window.winfo_id())
            try:
                frame = self.window.wm_frame()
                if frame:
                    hwnd = int(frame, 16)
            except (TclError, ValueError, TypeError):
                pass

            dpi = 96
            if hasattr(user32, "GetDpiForWindow"):
                try:
                    dpi = int(user32.GetDpiForWindow(hwnd)) or 96
                except Exception:
                    dpi = 96
            scale = max(dpi / 96.0, 1.0)
            # Prefer sizes that exist in app.ico.
            small = 16 if scale < 1.25 else 20 if scale < 1.75 else 24 if scale < 2.25 else 32
            big = 32 if scale < 1.25 else 40 if scale < 1.75 else 48 if scale < 2.25 else 64

            user32.LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.LoadImageW.restype = wintypes.HANDLE

            h_small = user32.LoadImageW(
                None, ico_path, IMAGE_ICON, small, small, LR_LOADFROMFILE
            )
            h_big = user32.LoadImageW(
                None, ico_path, IMAGE_ICON, big, big, LR_LOADFROMFILE
            )
            if h_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
                self._native_icon_small = h_small
            if h_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
                self._native_icon_big = h_big
            try:
                self.window.iconbitmap(default=ico_path)
                self.window.iconbitmap(ico_path)
            except TclError:
                pass
        except Exception:
            self.context.logger.debug("Unable to apply native Windows icons", exc_info=True)

    def _content_wraplength_for(self, widget, *, fallback: int = 420) -> int:
        """Wrap to the widget's real content box, undoing CTk's DPI multiply."""
        try:
            widget.update_idletasks()
            width = int(widget.winfo_width())
        except Exception:
            width = 0
        if width <= 1:
            try:
                self.page_host.update_idletasks()
                width = int(self.page_host.winfo_width())
            except Exception:
                width = fallback + 48
        # padx=24 on each side of help labels.
        usable = max(200, width - 48)
        try:
            scaling = float(self.window._get_window_scaling())
        except Exception:
            scaling = 1.0
        # Extra margin: CJK glyphs are wide and CTk rounds wraplength up.
        return max(180, int(usable / max(scaling, 1.0)) - 24)

    def _build_ui(self) -> None:
        shell = ctk.CTkFrame(self.window, fg_color=UI["page"])
        shell.pack(fill="both", expand=True)
        sidebar = ctk.CTkFrame(
            shell, width=188, corner_radius=0, fg_color=UI["card"],
            border_width=0,
        )
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.sidebar = sidebar
        ctk.CTkLabel(
            sidebar, text="唏嘘南溪", text_color=UI["primary"],
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(anchor="w", padx=18, pady=(30, 4))
        ctk.CTkLabel(
            sidebar, text="DLC一键解锁工具", text_color=UI["muted"],
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=19, pady=(0, 4))
        ctk.CTkLabel(
            sidebar,
            text=(
                f"程序 v{self.context.app_version}\n"
                f"启动器 v{self.context.launcher_version}"
            ),
            justify="left",
            anchor="w",
            text_color=UI["muted"],
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=19, pady=(0, 20))
        self.navigation_buttons = {}
        for page_name in ("DLC 库", "下载任务", "报错指南", "设置"):
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
            container, fg_color=UI["brand"], corner_radius=14, height=200
        )
        topbar.pack(fill="x", pady=(0, 24))
        topbar.grid_columnconfigure(0, weight=1)
        topbar.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(
            topbar, text=PRODUCT_HEADER_TITLE_ZH,
            anchor="w",
            text_color=UI["on_blue"],
            font=ctk.CTkFont(size=32, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(24, 18), pady=(22, 10))
        profile_group = ctk.CTkFrame(topbar, fg_color="transparent")
        profile_group.grid(row=0, column=1, sticky="e", padx=(18, 22), pady=(22, 10))
        ctk.CTkButton(
            profile_group, text="GitHub", width=68, height=42,
            command=lambda: self._open_external_link(
                "https://github.com/sign-river/SignRiver-DLC-Hub"
            ),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            profile_group, text="B站", width=52, height=42,
            command=lambda: self._open_external_link(BILIBILI_TUTORIAL_URL),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            profile_group, text="使用教程", width=78, height=42,
            command=self._open_usage_tutorial,
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            profile_group, text="QQ群 1061299021", width=132, height=42,
            command=self._copy_qq_group,
        ).pack(side="left", padx=(3, 0))
        status_band = ctk.CTkFrame(
            topbar, fg_color=UI["brand"], corner_radius=7, height=32
        )
        self.status_band = status_band
        status_band.grid(
            row=1, column=0, columnspan=2, sticky="ew",
            padx=(24, 22), pady=(0, 20),
        )
        status_band.grid_columnconfigure(0, weight=1)
        status_band.grid_propagate(False)
        self.top_health = ctk.CTkLabel(
            status_band,
            text=f"{self.cartridge.adapter.descriptor.display_name} · 等待路径检测",
            anchor="w",
            text_color="#E8F2FA", font=ctk.CTkFont(size=16),
        )
        self.top_health.grid(row=0, column=0, sticky="w", padx=(0, 18))
        ctk.CTkLabel(
            status_band,
            text=f"{AUTHOR_CN}|{AUTHOR_EN}  ·  开源免费 · 付费购买请立即退款",
            anchor="e",
            text_color="#DCECF8",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=1, sticky="e", padx=(18, 12))

        self.page_host = ctk.CTkFrame(container, fg_color=UI["page"], corner_radius=0)
        self.page_host.pack(fill="both", expand=True)

        # Top-centered snackbar for task completion/error feedback: visible in
        # the user's current view, colored, auto-dismissing, no modal popup.
        self.snackbar = ctk.CTkFrame(
            self.window, fg_color=UI["success"], corner_radius=0, border_width=0,
            width=460, height=44,
        )
        self.snackbar_label = ctk.CTkLabel(
            self.snackbar,
            text="",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=15, weight="bold"),
            wraplength=412,
        )
        self.snackbar_label.pack(fill="both", expand=True, padx=24, pady=10)
        self.snackbar.pack_propagate(False)
        self.snackbar.place_forget()

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
            selector_row, values=list(self.supported_games), width=220,
        )
        self._set_game_selector_text(self.selected_game_name)
        self.game_selector._canvas.tag_bind(
            "right_parts", "<Button-1>", self._open_game_picker_from_combo
        )
        self.game_selector._canvas.tag_bind(
            "dropdown_arrow", "<Button-1>", self._open_game_picker_from_combo
        )
        self.game_selector.bind("<Button-1>", self._open_game_picker_from_combo)
        self.game_selector.pack(side="left", padx=(10, 0))
        self.export_games_button = ctk.CTkButton(
            selector_row,
            text="复制游戏列表",
            command=self._copy_game_list,
            width=92,
            height=30,
            fg_color="transparent",
            hover_color=UI["primary_surface"],
            border_color=UI["primary_border"],
            border_width=1,
            text_color=UI["primary"],
            font=ctk.CTkFont(size=12),
        )
        self.export_games_button.pack(side="left", padx=(10, 0))
        self.platform_status = ctk.CTkLabel(
            selector_row,
            text=f"{self.cartridge.platform_name} · App {self.cartridge.store_app_id}",
            text_color=UI["muted"],
        )
        self.platform_status.pack(side="right")
        self.game_status = ctk.CTkLabel(
            selector_row,
            text=f"{self.cartridge.adapter.descriptor.display_name} · 等待扫描",
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
        self.catalog_qq_hint_wrap = ctk.CTkFrame(
            catalog_header, fg_color="transparent"
        )
        self.catalog_qq_hint_wrap.pack(side="right", padx=(0, 24))
        self.catalog_qq_hint_button = ctk.CTkLabel(
            self.catalog_qq_hint_wrap,
            text="资源有遗漏？反馈更新  →",
            text_color=UI["primary"],
            font=ctk.CTkFont(size=13),
        )
        self.catalog_qq_hint_button.pack()
        # A real drawn line keeps the underline perfectly flat across mixed
        # CJK/Latin text (Tk's underline attribute jumps between font fallbacks).
        self.catalog_qq_hint_underline = ctk.CTkFrame(
            self.catalog_qq_hint_wrap, height=2, fg_color=UI["primary"]
        )
        self.catalog_qq_hint_underline.place(relx=0, rely=1.0, relwidth=1, y=-4)
        for widget in (self.catalog_qq_hint_wrap, self.catalog_qq_hint_button):
            widget.bind(
                "<Button-1>", lambda _event: self._open_qq_group_hint()
            )
        try:
            self.catalog_qq_hint_button._label.configure(cursor="hand2")
        except Exception:
            pass
        self.catalog_status = ctk.CTkLabel(
            catalog_card,
            text=(
                f"等待读取 {provider_display_name(self.user_settings.download_source)}"
                f" · {self.cartridge.release_tag} Release"
            ),
            anchor="w",
        )
        self.catalog_status.pack(fill="x", padx=24)
        catalog_freshness_row = ctk.CTkFrame(catalog_card, fg_color="transparent")
        catalog_freshness_row.pack(fill="x", padx=24, pady=(2, 0))
        self.catalog_freshness = ctk.CTkLabel(
            catalog_freshness_row,
            text=self._freshness_status_text(),
            anchor="w",
            justify="left",
            text_color=UI["muted"],
            wraplength=760,
        )
        self.catalog_freshness.pack(side="left")
        self.catalog_patch_warning = ctk.CTkLabel(
            catalog_freshness_row,
            text="",
            anchor="w",
            text_color="#B26A00",
            font=ctk.CTkFont(size=13, weight="bold", underline=True),
        )
        self.catalog_patch_warning.pack(side="left", padx=(8, 0))
        self.catalog_patch_warning.bind(
            "<Button-1>",
            lambda _event: self._open_solution_article("patch_assets_missing"),
        )
        try:
            self.catalog_patch_warning._label.configure(cursor="hand2")
        except Exception:
            pass
        self.catalog_preview = _InlineCatalogStatus(
            self.catalog_freshness,
            self._freshness_status_text(),
        )
        catalog_command_bar = ctk.CTkFrame(
            catalog_card,
            fg_color=UI["panel"],
            border_width=1,
            border_color=UI["border"],
            corner_radius=10,
        )
        catalog_command_bar.pack(fill="x", padx=24, pady=(0, 10))
        catalog_command_bar.grid_columnconfigure(0, weight=1)

        catalog_secondary_actions = ctk.CTkFrame(
            catalog_command_bar, fg_color="transparent"
        )
        catalog_secondary_actions.grid(
            row=0, column=0, sticky="w", padx=(12, 10), pady=6
        )
        self.selection_toggle_button = ctk.CTkButton(
            catalog_secondary_actions,
            text="全选 DLC",
            command=self._toggle_visible_selection,
            width=96,
        )
        self.selection_toggle_button.grid(row=0, column=0)
        self.advanced_view_button = ctk.CTkButton(
            catalog_secondary_actions,
            text="逐项管理 DLC",
            command=self._toggle_catalog_view,
            width=120,
        )
        self.advanced_view_button.grid(row=0, column=1, padx=(8, 0))
        self.catalog_refresh_button = ctk.CTkButton(
            catalog_secondary_actions,
            text="刷新目录",
            command=self._refresh_catalog,
            width=100,
        )
        self.catalog_refresh_button.grid(row=0, column=2, padx=(8, 0))
        self.cancel_all_downloads_button = ctk.CTkButton(
            catalog_secondary_actions, text="取消全部下载",
            command=self._cancel_all_downloads, width=118,
        )
        self.cancel_all_downloads_button.grid(row=0, column=3, padx=(8, 0))
        self.cancel_all_downloads_button.grid_remove()
        self.catalog_more_actions_button = ctk.CTkButton(
            catalog_secondary_actions, text="更多操作  ▾",
            command=self._toggle_catalog_more_actions, width=112,
        )
        self.catalog_more_actions_button.grid(row=0, column=4, padx=(8, 0))

        self.catalog_more_actions = ctk.CTkFrame(
            catalog_command_bar, fg_color=UI["panel"], border_width=1,
            border_color=UI["border"], corner_radius=8,
        )
        catalog_management_tools = self.catalog_more_actions
        for column in range(3):
            catalog_management_tools.grid_columnconfigure(
                column, weight=1, uniform="catalog-management"
            )
        self.remove_patch_button = ctk.CTkButton(
            catalog_management_tools, text="一键移除补丁",
            command=self._remove_patch, width=112,
        )
        self.remove_patch_button.grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        self.restore_original_button = ctk.CTkButton(
            catalog_management_tools,
            text="移除本程序安装内容",
            command=self._restore_original_state,
            width=120,
            fg_color=UI["primary_surface"],
            hover_color=UI["primary_surface_hover"],
            text_color=UI["primary"],
            border_width=1,
            border_color=UI["primary_border"],
        )
        self.restore_original_button.grid(
            row=0, column=1, sticky="ew", padx=4
        )
        self.repair_button = ctk.CTkButton(
            catalog_management_tools, text="一键修复",
            command=self._one_click_repair, width=112,
        )
        self.repair_button.grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )
        primary_action_panel = ctk.CTkFrame(
            catalog_command_bar,
            fg_color=UI["primary_surface"],
            border_width=1,
            border_color=UI["primary_border"],
            corner_radius=10,
        )
        primary_action_panel.grid(
            row=0, column=1, padx=(0, 10), pady=6
        )
        self.download_selected_button = ctk.CTkButton(
            primary_action_panel,
            text="一键解锁",
            command=self._one_click_unlock,
            width=176,
            height=44,
            corner_radius=12,
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.download_selected_button.pack(padx=4, pady=3)
        # Realize the full expandable area before the window becomes visible.
        # Do not force an idle redraw from the click callback: doing so paints
        # this row before the outer card has moved the DLC list below it.
        self.catalog_more_actions.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10)
        )
        catalog_command_bar.update_idletasks()
        self.catalog_more_actions.grid_remove()
        def create_catalog_list_frame(parent=catalog_card):
            return ctk.CTkScrollableFrame(
                parent, height=250, fg_color=UI["panel"], corner_radius=10,
                border_width=1, border_color=UI["border"],
                scrollbar_button_color=UI["input_border"],
                scrollbar_button_hover_color=UI["muted"],
            )

        self.dlc_list_frame = create_catalog_list_frame()
        self.catalog_view_frames["simple"] = self.dlc_list_frame
        self.advanced_catalog_card = _card(self.page_host)
        advanced_header = ctk.CTkFrame(self.advanced_catalog_card, fg_color="transparent")
        advanced_header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(advanced_header, text="DLC 高级管理", text_color=UI["primary"], font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkButton(advanced_header, text="刷新目录", width=96, command=self._refresh_catalog).pack(side="right")
        ctk.CTkButton(advanced_header, text="← 返回 DLC 列表", width=118, command=self._return_to_simple_catalog).pack(side="right", padx=(0, 8))
        ctk.CTkLabel(self.advanced_catalog_card, text="逐项管理 DLC 的下载、取消、校验和卸载操作。", text_color=UI["text_secondary"], anchor="w").pack(fill="x", padx=24, pady=(0, 10))
        advanced_tools = ctk.CTkFrame(self.advanced_catalog_card, fg_color="transparent")
        advanced_tools.pack(fill="x", padx=24, pady=(0, 10))
        advanced_tools.grid_columnconfigure(0, weight=1)
        self.catalog_search = ctk.CTkEntry(advanced_tools, placeholder_text="搜索 DLC 编号或名称")
        self.catalog_search.grid(row=0, column=0, sticky="ew")
        self.catalog_search.bind("<KeyRelease>", self._schedule_catalog_search)
        self.catalog_filter = _combo_box(advanced_tools, values=["全部状态", "未下载", "进行中", "已暂停", "已完成", "失败"], command=lambda _value: self._render_catalog_rows(), width=110)
        self.catalog_filter.set("全部状态")
        self.catalog_filter.grid(row=0, column=1, padx=(8, 0))
        self.catalog_view_frames["advanced"] = create_catalog_list_frame(self.advanced_catalog_card)
        self.dlc_list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        for column in range(4):
            self.dlc_list_frame.grid_columnconfigure(column, weight=1, uniform="dlc")

        settings_list = ctk.CTkScrollableFrame(
            self.page_host,
            fg_color=UI["page"],
            corner_radius=0,
            scrollbar_button_color=UI["input_border"],
            scrollbar_button_hover_color=UI["muted"],
        )
        self.settings_list = settings_list
        self.settings_description_boxes = []

        settings_hint = ctk.CTkLabel(
            settings_list,
            text="管理下载、程序与日常偏好；更改会自动保存。",
            text_color=UI["text_secondary"],
            font=ctk.CTkFont(size=14),
            anchor="w",
        )
        settings_hint.pack(fill="x", padx=4, pady=(2, 14))

        network_card = _card(settings_list)
        self.source_card = network_card
        self.speed_test_card = network_card
        self.resilience_card = network_card
        _settings_header(network_card, "下载与网络", "下载源、连接质量与等待策略")
        network_body = _settings_group_body(network_card)

        source_row, source_action, source_description = _settings_row(
            network_body,
            "下载源",
            "用于读取资源、公告和程序更新；切换后会刷新本地资源目录。",
        )
        self.settings_description_boxes.append(source_description)
        self.download_source_menu = _combo_box(
            source_action,
            values=["GitLink", "GitHub"],
            width=148,
            command=self._on_download_source_selected,
        )
        self.download_source_menu.set(
            provider_display_name(self.user_settings.download_source)
        )
        self.download_source_menu.pack(anchor="e")
        self.resource_repository_link = ctk.CTkLabel(
            source_row,
            text="打开当前下载源的资源仓库",
            text_color=UI["primary"],
            cursor="hand2",
            font=ctk.CTkFont(size=13, underline=True),
            anchor="w",
        )
        self.resource_repository_link.grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        self.resource_repository_link.bind(
            "<Button-1>", lambda _event: self._open_resource_repository()
        )

        speed_row, speed_action, speed_description = _settings_row(
            network_body,
            "网络测速",
            "从当前下载源获取短测试文件，帮助判断当前网络是否适合下载；文件不会保留。",
        )
        self.settings_description_boxes.append(speed_description)
        self.speed_test_button = ctk.CTkButton(
            speed_action,
            text="开始测速",
            command=self._run_speed_test,
            width=108,
        )
        self.speed_test_button.pack(anchor="e")
        self.speed_test_status = ctk.CTkLabel(
            speed_row,
            text="尚未测速",
            text_color=UI["muted"],
            font=ctk.CTkFont(size=13),
            anchor="w",
        )
        self.speed_test_status.grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )

        timeout_row, timeout_action, timeout_description = _settings_row(
            network_body,
            "超时检测",
            "默认会在长时间无响应时提醒。网络较慢或使用代理时，可关闭超时检测以继续等待。",
            last=True,
        )
        self.settings_description_boxes.append(timeout_description)
        self.download_never_timeout_var = BooleanVar(
            value=self.user_settings.download_never_timeout
        )
        self.download_never_timeout_switch = _blue_switch(
            timeout_action,
            text="",
            width=54,
            variable=self.download_never_timeout_var,
            command=self._toggle_download_never_timeout,
        )
        self.download_never_timeout_switch.pack(anchor="e")

        program_card = _card(settings_list)
        self.update_card = program_card
        self.cache_card = program_card
        _settings_header(program_card, "程序与存储", "程序更新、下载缓存与本地空间")
        program_body = _settings_group_body(program_card)

        update_row, update_action, update_description = _settings_row(
            program_body,
            "程序更新",
            "检查当前程序是否有可用更新；更新不会删除已下载的 DLC、游戏或本地缓存。",
        )
        self.settings_description_boxes.append(update_description)
        update_action.grid_columnconfigure(0, weight=1)
        update_action.grid_columnconfigure(1, weight=1)
        self.update_cancel_button = ctk.CTkButton(
            update_action,
            text="取消下载",
            command=self._cancel_update_download,
            width=96,
            fg_color=UI["danger_surface"],
            hover_color=UI["danger_surface_hover"],
            text_color=UI["danger"],
            border_width=1,
            border_color="#F3BBB5",
            state="disabled",
        )
        self.update_cancel_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.update_button = ctk.CTkButton(
            update_action,
            text="检查更新",
            command=self._check_update,
            width=108,
        )
        self.update_button.grid(row=0, column=1, sticky="ew")
        self.progress = ctk.CTkProgressBar(update_row, mode="determinate")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, sticky="ew", pady=(12, 6))
        self.status = ctk.CTkLabel(
            update_row,
            text=(
                f"当前程序 v{self.context.app_version} · "
                f"启动器 v{self.context.launcher_version} · 尚未检查更新"
            ),
            text_color=UI["muted"],
            font=ctk.CTkFont(size=13),
            anchor="w",
        )
        self.status.grid(row=3, column=0, sticky="w")
        self._set_update_activity_visible(False)

        cache_row, cache_action, cache_description = _settings_row(
            program_body,
            "缓存管理",
            "缓存会保留已下载的资源，便于下次使用；可在下方查看当前占用和各游戏的容量分布。",
            last=True,
        )
        self.settings_description_boxes.append(cache_description)
        # Cache actions belong to the storage summary, not beside its text.
        # Move the action frame below the overview after its controls exist.
        cache_action.grid_forget()
        for column in range(3):
            cache_action.grid_columnconfigure(column, weight=1)
        self.game_cache_cleanup_button = ctk.CTkButton(
            cache_action,
            text="清理当前游戏",
            command=self._cleanup_current_game_cache,
            width=104,
            fg_color=UI["primary_surface"],
            hover_color=UI["primary_surface_hover"],
            text_color=UI["primary"],
            border_width=1,
            border_color=UI["primary_border"],
        )
        self.game_cache_cleanup_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.cache_cleanup_button = ctk.CTkButton(
            cache_action,
            text="清理全部缓存",
            command=self._cleanup_cache,
            width=104,
            fg_color=UI["danger_surface"],
            hover_color=UI["danger_surface_hover"],
            text_color=UI["danger"],
            border_width=1,
            border_color="#F3BBB5",
        )
        self.cache_cleanup_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.open_cache_button = ctk.CTkButton(
            cache_action,
            text="打开目录",
            command=lambda: self._open_path(self.context.paths.cache),
            width=86,
            fg_color=UI["primary_surface"],
            hover_color=UI["primary_surface_hover"],
            text_color=UI["primary"],
            border_width=1,
            border_color=UI["primary_border"],
        )
        self.open_cache_button.grid(row=0, column=1, sticky="ew", padx=3)

        self.cache_overview = ctk.CTkFrame(
            cache_row,
            fg_color=UI["primary_surface"],
            corner_radius=8,
        )
        self.cache_overview.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0)
        )
        self.cache_overview.grid_columnconfigure(0, weight=1)
        self.cache_status = ctk.CTkLabel(
            self.cache_overview,
            text="缓存空间正在后台统计…",
            text_color=UI["text_secondary"],
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        self.cache_status.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))
        self.cache_usage_bar = ctk.CTkProgressBar(
            self.cache_overview,
            height=8,
            progress_color=UI["primary"],
            fg_color="#DCE7F1",
            corner_radius=4,
        )
        self.cache_usage_bar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.cache_usage_bar.set(0)
        self.cache_breakdown = ctk.CTkLabel(
            self.cache_overview,
            text="当前游戏 统计中  ·  其他游戏 统计中",
            text_color=UI["muted"],
            font=ctk.CTkFont(size=13),
            anchor="w",
        )
        self.cache_breakdown.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 10))
        cache_action.grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        general_card = _card(settings_list)
        self.announcement_card = general_card
        _settings_header(general_card, "常规设置", "日常提示与后续普通偏好")
        general_body = _settings_group_body(general_card)
        announcement_row, announcement_action, announcement_description = _settings_row(
            general_body,
            "公告提醒",
            "启动时会显示最新公告。关闭后，同一条公告不会重复弹出；有新公告时仍会显示。",
            last=True,
        )
        self.settings_description_boxes.append(announcement_description)
        self.announcement_mute_var = BooleanVar(
            value=self.user_settings.announcement_mute_until_update
        )
        self.announcement_mute_switch = _blue_switch(
            announcement_action,
            text="",
            width=54,
            variable=self.announcement_mute_var,
            command=self._toggle_announcement_mute,
        )
        self.announcement_mute_switch.pack(anchor="e")

        for index, card in enumerate((network_card, program_card, general_card)):
            card.pack(
                fill="x",
                padx=(0, 8),
                pady=(0, 12 if index < 2 else 0),
            )

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
        self.task_cancel_all_downloads_button = ctk.CTkButton(
            task_header,
            text="取消全部下载",
            command=self._cancel_all_downloads,
            width=100,
        )
        self.task_cancel_all_downloads_button.pack(side="right", padx=(0, 8))
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

        self.error_guide_card = _card(self.page_host)
        guide_header = ctk.CTkFrame(self.error_guide_card, fg_color="transparent")
        guide_header.pack(fill="x", padx=36, pady=(38, 6))
        ctk.CTkLabel(
            guide_header, text="帮助与诊断", text_color=UI["primary"],
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            self.error_guide_card,
            text="遇到问题时，可以先运行一键排错，或查看对应的处理方案、异常记录和运行日志。",
            text_color=UI["text_secondary"], anchor="w",
        ).pack(fill="x", padx=36, pady=(0, 12))
        guide_tips = ctk.CTkFrame(
            self.error_guide_card, fg_color=UI["primary_surface"],
            border_color=UI["primary_border"], border_width=1, corner_radius=10,
        )
        # Keep the title anchored near the top while giving the primary action
        # a deliberate, but not visually detached, breathing space below it.
        guide_tips.pack(fill="x", padx=36, pady=(8, 26))
        guide_tips_header = ctk.CTkFrame(guide_tips, fg_color="transparent")
        guide_tips_header.pack(fill="x", padx=16, pady=(11, 2))
        ctk.CTkLabel(guide_tips_header, text="一键排错", text_color=UI["primary"], font=ctk.CTkFont(size=16, weight="bold"), anchor="w").pack(side="left")
        ctk.CTkButton(guide_tips_header, text="开始一键排错  →", width=142, height=30, command=lambda: self._show_page("简单错误检测")).pack(side="right")
        ctk.CTkLabel(
            guide_tips,
            text=(
                "自动检查网络、文件、模块和运行环境中的常见问题；未发现异常不代表所有问题均已排除。"
            ),
            text_color=UI["text_secondary"], justify="left", anchor="w",
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", padx=16, pady=(0, 11))
        ctk.CTkLabel(self.error_guide_card, text="其他工具", text_color=UI["text"], font=ctk.CTkFont(size=15, weight="bold"), anchor="w").pack(fill="x", padx=36, pady=(0, 12))
        guide_actions = ctk.CTkFrame(self.error_guide_card, fg_color="transparent")
        guide_actions.pack(fill="x", padx=36, pady=(0, 26))
        for title, detail, target in (
            ("解决方案", "按现象查看对应的处理办法", "常见问题教程"),
            ("问题记录", "查看已记录的异常与处理建议", "问题记录"),
            ("运行日志", "查看详细运行信息", "运行日志"),
        ):
            tool = ctk.CTkFrame(
                guide_actions, height=72, fg_color=UI["card"],
                border_color="#E3E8EF", border_width=1, corner_radius=8,
            )
            tool.pack(fill="x", pady=(0, 8))
            tool.pack_propagate(False)
            arrow = ctk.CTkLabel(tool, text="→", text_color=UI["primary"], font=ctk.CTkFont(size=18), anchor="e")
            arrow.pack(side="right", padx=18)
            text_area = ctk.CTkFrame(tool, fg_color="transparent")
            text_area.pack(fill="both", expand=True, padx=(16, 8), pady=10)
            title_label = ctk.CTkLabel(text_area, text=title, text_color=UI["text"], font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
            title_label.pack(fill="x")
            detail_label = ctk.CTkLabel(text_area, text=detail, text_color=UI["muted"], font=ctk.CTkFont(size=12), anchor="w")
            detail_label.pack(fill="x", pady=(1, 0))
            for widget in (tool, text_area, title_label, detail_label, arrow):
                widget.bind("<Button-1>", lambda _event, target=target: self._show_page(target))
                widget.bind("<Enter>", lambda _event, card=tool: card.configure(fg_color=UI["primary_surface"]))
                widget.bind("<Leave>", lambda _event, card=tool: card.configure(fg_color=UI["card"]))
        guide_footer = ctk.CTkFrame(self.error_guide_card, fg_color="transparent")
        guide_footer.pack(side="bottom", fill="x", padx=36, pady=(0, 32))
        ctk.CTkLabel(guide_footer, text="仍然无法解决？", text_color=UI["text_secondary"], font=ctk.CTkFont(size=13, weight="bold"), anchor="w").pack(side="left")
        ctk.CTkLabel(guide_footer, text="导出诊断信息并发送给开发者，可以帮助快速定位问题。", text_color=UI["muted"], font=ctk.CTkFont(size=12), anchor="w").pack(side="left", padx=(12, 0))
        ctk.CTkButton(guide_footer, text="导出诊断 →", width=92, height=28, fg_color="transparent", hover_color=UI["primary_surface"], text_color=UI["primary"], command=self._export_diagnostics).pack(side="right")
        ctk.CTkFrame(self.error_guide_card, height=1, fg_color=UI["border"], corner_radius=0).pack(side="bottom", fill="x", padx=36, pady=(0, 18))

        self.guide_tutorial_card = _card(self.page_host)
        self._build_error_tutorial_page()
        self.quick_check_card = _card(self.page_host)
        self._build_quick_check_page()

        self.log_card = _card(self.page_host)
        log_command_area = ctk.CTkFrame(self.log_card, fg_color="transparent")
        log_command_area.pack(fill="x", padx=24, pady=(18, 8))
        log_command_area.grid_columnconfigure(0, weight=1)

        log_primary_area = ctk.CTkFrame(
            log_command_area, fg_color="transparent"
        )
        log_primary_area.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        log_primary_area.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            log_primary_area, text="运行日志", text_color=UI["primary"],
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ctk.CTkButton(
            log_primary_area, text="返回指南", width=92,
            command=lambda: self._show_page("报错指南"),
        ).grid(row=0, column=1, sticky="e", pady=(0, 8))

        log_tools = ctk.CTkFrame(log_primary_area, fg_color="transparent")
        log_tools.grid(row=1, column=0, sticky="ew")
        log_tools.grid_columnconfigure(1, weight=1)
        self.log_level_filter = _combo_box(
            log_tools, values=["全部", "INFO", "WARNING", "ERROR"], width=100,
            command=lambda _value: self._refresh_log_preview(),
        )
        self.log_level_filter.set("全部")
        self.log_level_filter.grid(row=0, column=0)
        self.log_search = ctk.CTkEntry(
            log_tools, placeholder_text="筛选日志关键词", width=220
        )
        self.log_search.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.log_search.bind("<KeyRelease>", self._schedule_log_refresh)

        log_action_grid = ctk.CTkFrame(
            log_command_area, fg_color="transparent"
        )
        log_action_grid.grid(row=0, column=1, sticky="ne")
        for column in range(2):
            log_action_grid.grid_columnconfigure(
                column, weight=1, uniform="log-actions"
            )
        ctk.CTkButton(
            log_action_grid, text="刷新",
            command=self._refresh_log_preview, width=128,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        ctk.CTkButton(
            log_action_grid, text="打开日志目录",
            command=lambda: self._open_path(self.context.paths.data / "logs"), width=128,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 4))
        self.diagnostics_export_button = ctk.CTkButton(
            log_action_grid, text="导出诊断包",
            command=self._export_diagnostics, width=128,
        )
        self.diagnostics_export_button.grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(4, 0)
        )
        ctk.CTkButton(
            log_action_grid, text="复制当前日志",
            command=self._copy_log, width=128,
        ).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(4, 0))
        self.log_preview = ctk.CTkTextbox(
            self.log_card, height=520, wrap="word", fg_color=UI["panel"],
            border_width=1, border_color=UI["border"], text_color=UI["text_secondary"],
            corner_radius=10,
        )
        self.log_preview.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.log_preview.configure(state="disabled")
        self.window.after(50, self._refresh_log_preview)

        self.problem_card = _card(self.page_host)
        problem_header = ctk.CTkFrame(self.problem_card, fg_color="transparent")
        problem_header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(
            problem_header, text="问题记录", text_color=UI["primary"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            problem_header, text="清空全部", width=88,
            fg_color=UI["danger"], hover_color=UI["danger_hover"],
            command=self._clear_problems,
        ).pack(side="right")
        ctk.CTkButton(
            problem_header, text="刷新", width=72,
            command=self._refresh_problem_center,
        ).pack(side="right", padx=(0, 8))
        ctk.CTkButton(
            problem_header, text="返回指南", width=92,
            command=lambda: self._show_page("报错指南"),
        ).pack(side="right", padx=(0, 8))
        problem_body = ctk.CTkFrame(self.problem_card, fg_color="transparent")
        problem_body.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.problem_list_panel = ctk.CTkFrame(problem_body, fg_color="transparent")
        self.problem_list_panel.pack(fill="both", expand=True)
        self.problem_list = ctk.CTkScrollableFrame(
            self.problem_list_panel, fg_color="#F7F8FA", corner_radius=8,
            border_width=0, scrollbar_button_color=UI["input_border"],
        )
        self.problem_list.pack(fill="both", expand=True)
        self.problem_detail_page = ctk.CTkFrame(
            problem_body, fg_color=UI["card"], corner_radius=0, border_width=0,
        )
        problem_detail_header = ctk.CTkFrame(self.problem_detail_page, fg_color="transparent")
        problem_detail_header.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkButton(
            problem_detail_header, text="← 返回记录", width=104,
            fg_color="transparent", hover_color=UI["primary_surface"],
            text_color=UI["primary"], command=self._show_problem_list,
        ).pack(side="left")
        self.problem_detail_content = ctk.CTkScrollableFrame(
            self.problem_detail_page, fg_color=UI["card"], corner_radius=0,
            border_width=0, scrollbar_button_color=UI["input_border"],
        )
        self.problem_detail_content.pack(fill="both", expand=True, padx=(16, 8), pady=(4, 8))
        self.problem_actions = ctk.CTkFrame(
            self.problem_detail_page, fg_color="transparent"
        )
        self.problem_actions.pack(fill="x", padx=16, pady=(6, 14))

        self.page_sections = {
            "DLC 库": (self.game_card, self.catalog_card),
            "高级DLC视图": (self.advanced_catalog_card,),
            "下载任务": (self.task_card,),
            "报错指南": (self.error_guide_card,),
            "常见问题教程": (self.guide_tutorial_card,),
            "简单错误检测": (self.quick_check_card,),
            "问题记录": (self.problem_card,),
            "运行日志": (self.log_card,),
            "设置": (self.settings_list,),
        }
        self._apply_visual_theme(shell)
        self._show_page("DLC 库")
        self.window.bind("<Configure>", self._on_window_resize, add="+")
        self.window.after(80, self._sync_help_wraplengths)
        self.window.after(250, self._sync_help_wraplengths)

    def _sync_help_wraplengths(self, window_width: int | None = None) -> None:
        del window_width  # measured from each card; kept for call-site compat
        for name in ("game_path", "catalog_status", "catalog_freshness"):
            widget = getattr(self, name, None)
            if widget is None or not widget.winfo_exists():
                continue
            parent = getattr(widget, "master", None) or self.window
            widget.configure(wraplength=self._content_wraplength_for(parent))
        for widget in self.settings_description_boxes:
            if not widget.winfo_exists():
                continue
            parent = getattr(widget, "master", None) or self.window
            widget.configure(wraplength=self._content_wraplength_for(parent))

    def _on_window_resize(self, event) -> None:
        if event.widget is not self.window:
            return
        compact = event.width < 1080
        columns = 4 if compact else 5
        layout_changed = compact != self.compact_layout
        columns_changed = columns != self.simple_catalog_columns
        self.window.after_idle(self._sync_help_wraplengths)
        if layout_changed:
            self.compact_layout = compact
            self.sidebar.configure(width=164 if compact else 188)
            self.content_container.pack_configure(
                padx=20 if compact else 30,
                pady=18 if compact else 24,
            )
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
            if widget is getattr(self, "game_selector", None):
                widget.configure(
                    fg_color="transparent", hover_color=UI["primary_surface"],
                    text_color=UI["text"], border_width=0, corner_radius=0, height=34,
                )
                return
            if widget is getattr(self, "game_selector_toggle", None):
                widget.configure(
                    fg_color=UI["primary"], hover_color=UI["primary_hover"],
                    text_color=UI["on_blue"], border_width=0, corner_radius=0, height=34,
                )
                return
            text = str(widget.cget("text"))
            if text in {"GitHub", "B站", "使用教程"} or text.startswith("QQ群"):
                widget.configure(
                    fg_color=UI["secondary"], hover_color=UI["secondary_hover"],
                    text_color=UI["on_blue"], border_width=0,
                    corner_radius=8, height=34,
                )
                return
            if widget is getattr(self, "download_selected_button", None):
                widget.configure(
                    fg_color=UI["primary"],
                    hover_color=UI["primary_hover"],
                    text_color=UI["on_blue"],
                    border_width=0,
                    corner_radius=12,
                    height=44,
                    font=ctk.CTkFont(size=18, weight="bold"),
                )
                return
            soft_primary_buttons = (
                getattr(self, "advanced_view_button", None),
                getattr(self, "catalog_refresh_button", None),
                getattr(self, "selection_toggle_button", None),
                getattr(self, "repair_button", None),
                getattr(self, "game_scan_button", None),
                getattr(self, "restore_original_button", None),
            )
            if any(widget is candidate for candidate in soft_primary_buttons):
                widget.configure(
                    fg_color=UI["primary_surface"],
                    hover_color=UI["primary_surface_hover"],
                    text_color=UI["primary"],
                    border_width=1,
                    border_color=UI["primary_border"],
                    corner_radius=8,
                    height=34,
                )
                return
            if (
                text in {"取消", "卸载", "一键移除补丁", "终止检测", "删除"}
                or text.startswith("清除")
                or text.startswith("取消全部")
                or text.startswith("卸载全部")
                or text.startswith("清理")
            ):
                widget.configure(
                    fg_color=UI["danger_surface"],
                    hover_color=UI["danger_surface_hover"],
                    text_color=UI["danger"], border_width=1,
                    border_color=UI["danger"], corner_radius=8, height=34,
                )
                return
            elif text in {
                "下载所选", "一键下载所选", "一键解锁工具", "一键修复",
                "启动游戏", "保存设置", "检查更新", "安装", "开始测速", "开始排错",
                "选择目录", "导出诊断 →", "GitHub", "B站", "使用教程",
            }:
                colors = (UI["primary"], UI["primary_hover"])
            elif text.startswith(("开始一键排错", "QQ群")):
                colors = (UI["primary"], UI["primary_hover"])
            elif text.startswith(("查看", "返回", "打开", "复制", "刷新", "重试", "重新下载", "选择", "导出")) or text in {"GitHub", "B站", "使用教程", "暂停检测", "继续检测", "全选", "检查", "下次公告更新前不再显示"} or text.startswith("QQ群"):
                widget.configure(
                    fg_color="transparent", hover_color=UI["primary_surface"],
                    text_color=UI["primary"], border_width=1,
                    border_color=UI["primary_border"], corner_radius=8, height=34,
                )
                return
            else:
                widget.configure(
                    fg_color=UI["panel"], hover_color=UI["border"],
                    text_color=UI["text_secondary"], border_width=0,
                    corner_radius=8, height=34,
                )
                return
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

    def _rebuild_supported_games_from_index(self) -> None:
        records = self.cartridge_catalog.selection_records()
        supported: dict[str, dict[str, str]] = {}
        for item in records:
            loaded = self.cartridge_catalog.get_loaded(item["game_id"])
            store_app_id = (
                loaded.document.store_app_id if loaded is not None else item["store_app_id"]
            )
            supported[item["selection_name"]] = {
                "game_id": item["game_id"],
                "platform": item["platform"],
                "store_app_id": store_app_id,
                "display_name": item["display_name"],
            }
        self.supported_games = supported

    def _activate_loaded_cartridge(self, loaded, *, rebuild_services: bool) -> None:
        cartridge = loaded.cartridge
        self.cartridges[cartridge.selection_name] = cartridge
        adapter_id = cartridge.adapter.descriptor.adapter_id
        if adapter_id not in self.adapter_registry:
            self.adapter_registry.register(cartridge.adapter)
        self.cartridge = cartridge
        self.patch_profile = cartridge.patch_profile
        self.catalog = cartridge.create_catalog(
            download_source=self.user_settings.download_source,
            cache_path=(self.context.paths.data / "catalogs" / self.user_settings.download_source / f"{cartridge.adapter.descriptor.game_id}.json"),
        )
        self.patch_engine = PatchEngine(
            cartridge.patch_profile, self.context.paths.data,
        )
        self.selected_game_name = cartridge.selection_name
        self._rebuild_supported_games_from_index()
        self.supported_games[cartridge.selection_name] = {
            "game_id": cartridge.adapter.descriptor.game_id,
            "platform": cartridge.platform_name,
            "store_app_id": cartridge.store_app_id,
            "display_name": cartridge.adapter.descriptor.display_name,
        }
        if rebuild_services and self.install_repository is not None:
            self.install_service = DlcInstallService(
                cartridge.create_install_engine(self.context.paths.data),
                self.install_repository,
                game_id=cartridge.adapter.descriptor.game_id,
                package_inspector=cartridge.inspect_package,
            )
        self._refresh_catalog_freshness_label()

    def _set_game_selector_text(self, display_name: str) -> None:
        self.game_selector.set(display_name)

    def _set_game_selector_state(self, state: str) -> None:
        self.game_selector.configure(state=state)

    def _open_game_picker_from_combo(self, _event=None):
        self._toggle_game_picker()
        return "break"

    def _sync_game_selector_values(self) -> None:
        values = list(self.supported_games)
        if not values:
            return
        self.game_selector.configure(values=values)
        current = self.selected_game_name
        self._set_game_selector_text(
            current if current in self.supported_games else values[0]
        )
        self._refresh_game_picker_results()

    def _toggle_game_picker(self) -> None:
        if str(self.game_selector.cget("state")) == "disabled":
            return
        if self.game_picker is None:
            self._show_game_picker()
        else:
            self._hide_game_picker()

    def _show_game_picker(self) -> None:
        if self.game_picker is not None:
            self.game_picker.lift()
            search = self.game_picker_search
            if search is not None and search.winfo_exists():
                self.game_picker.after(
                    20,
                    lambda popup=self.game_picker, target=search:
                    self._focus_game_picker_search(popup, target),
                )
            return
        popup = ctk.CTkToplevel(self.window)
        self.game_picker = popup
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.window)
        popup.configure(fg_color=UI["page"])
        popup.bind("<Escape>", lambda _event: self._hide_game_picker())
        popup.bind("<FocusOut>", self._schedule_game_picker_focus_check, add="+")

        shell = ctk.CTkFrame(
            popup,
            fg_color=UI["card"],
            border_color=UI["border"],
            border_width=1,
            corner_radius=12,
        )
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 8))
        ctk.CTkLabel(
            header,
            text="选择游戏",
            text_color=UI["text"],
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header,
            text="×",
            width=26,
            height=26,
            corner_radius=6,
            fg_color="transparent",
            hover_color=UI["panel"],
            text_color=UI["muted"],
            font=ctk.CTkFont(size=18),
            command=self._hide_game_picker,
        ).pack(side="right")
        ctk.CTkLabel(
            header,
            text="支持中文、英文和游戏标识搜索",
            text_color=UI["muted"],
            font=ctk.CTkFont(size=11),
        ).pack(side="right", padx=(0, 8))

        self.game_picker_query = StringVar(value="")
        self.game_picker_query.trace_add(
            "write", lambda *_args: self._refresh_game_picker_results()
        )
        search = ctk.CTkEntry(
            shell,
            textvariable=self.game_picker_query,
            placeholder_text="搜索游戏名称……",
            height=34,
            fg_color=UI["panel"],
            border_color=UI["input_border"],
            border_width=1,
            text_color=UI["text"],
            corner_radius=8,
        )
        search.pack(fill="x", padx=14, pady=(0, 10))
        self.game_picker_search = search
        self.game_picker_results = ctk.CTkScrollableFrame(
            shell,
            fg_color="transparent",
            scrollbar_button_color=UI["primary_border"],
            scrollbar_button_hover_color=UI["primary"],
            corner_radius=0,
        )
        self.game_picker_results.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._refresh_game_picker_results()

        self.window.update_idletasks()
        popup_width, popup_height = 410, 400
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = min(
            self.game_selector.winfo_rootx(),
            max(8, screen_width - popup_width - 8),
        )
        y = self.game_selector.winfo_rooty() + self.game_selector.winfo_height() + 4
        if y + popup_height > screen_height - 8:
            y = max(8, self.game_selector.winfo_rooty() - popup_height - 4)
        popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")
        popup.deiconify()
        popup.lift()
        # Toplevel 焦点会在第二次打开时先落回组合框；等窗口映射完成后
        # 强制交给搜索框，避免浮层可见但键盘输入仍被主窗口吞掉。
        popup.after_idle(
            lambda target=search: self._focus_game_picker_search(popup, target)
        )
        popup.after(
            30,
            lambda target=search: self._focus_game_picker_search(popup, target),
        )

    def _focus_game_picker_search(self, popup, search) -> None:
        """Focus the picker search only while its delayed callback is current."""
        if (
            popup is not self.game_picker
            or search is not self.game_picker_search
            or not popup.winfo_exists()
            or not search.winfo_exists()
        ):
            return
        try:
            search.focus_force()
        except TclError:
            # The close button can destroy the popup between winfo_exists()
            # and focus_force(); the popup is already gone, so no action remains.
            return

    def _schedule_game_picker_focus_check(self, _event=None) -> None:
        popup = self.game_picker
        if popup is not None:
            popup.after(80, lambda target=popup: self._hide_game_picker_if_unfocused(target))

    def _hide_game_picker_if_unfocused(self, popup) -> None:
        if popup is not self.game_picker:
            return
        focused = popup.focus_get()
        if focused is None or focused.winfo_toplevel() is not popup:
            self._hide_game_picker()

    def _hide_game_picker(self) -> None:
        popup = self.game_picker
        self.game_picker = None
        self.game_picker_query = None
        self.game_picker_search = None
        if popup is not None and popup.winfo_exists():
            popup.destroy()

    def _refresh_game_picker_results(self, *_args) -> None:
        popup = self.game_picker
        results = getattr(self, "game_picker_results", None)
        if popup is None or results is None or not popup.winfo_exists():
            return
        query = self.game_picker_query.get().strip().casefold() if self.game_picker_query else ""
        for child in results.winfo_children():
            child.destroy()
        matches: list[tuple[str, dict[str, str]]] = []
        for selection_name, game in self.supported_games.items():
            searchable = " ".join(
                (
                    selection_name,
                    game.get("display_name", ""),
                    game.get("game_id", ""),
                )
            ).casefold()
            if not query or query in searchable:
                matches.append((selection_name, game))
        if not matches:
            ctk.CTkLabel(
                results,
                text="没有找到匹配的游戏\n可尝试中文名、英文名或游戏标识",
                text_color=UI["muted"],
                justify="center",
                font=ctk.CTkFont(size=13),
            ).pack(fill="x", padx=12, pady=36)
            return
        for selection_name, game in matches:
            display_name = game.get("display_name") or selection_name
            is_current = selection_name == self.selected_game_name
            text = (
                f"{display_name}  ·  ✓ 当前选择"
                if is_current
                else display_name
            )
            ctk.CTkButton(
                results,
                text=text,
                command=lambda value=selection_name: self._choose_game_from_picker(value),
                anchor="w",
                height=54 if is_current else 40,
                fg_color=UI["primary_surface"] if is_current else UI["card"],
                hover_color=UI["primary_surface_hover"],
                border_color=UI["primary_border"] if is_current else UI["border"],
                border_width=1,
                text_color=UI["primary"] if is_current else UI["text"],
                corner_radius=8,
                font=ctk.CTkFont(size=13, weight="bold" if is_current else "normal"),
            ).pack(fill="x", padx=6, pady=3)

    def _choose_game_from_picker(self, display_name: str) -> None:
        self._hide_game_picker()
        self._select_game(display_name)

    def _refresh_remote_cartridge_index(self) -> None:
        if self.cartridge_loading:
            return

        def worker() -> None:
            try:
                index = self.cartridge_catalog.refresh_index(allow_network=True)
                active_id = self.cartridge.adapter.descriptor.game_id
                loaded = self.cartridge_catalog.load_cartridge(
                    active_id, allow_network=True,
                )
                self._post_ui(
                    lambda index=index, loaded=loaded: self._on_remote_index_ready(
                        index, loaded
                    )
                )
            except Exception as error:
                self.context.logger.warning(
                    "Remote cartridge index refresh failed: %s", error
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_remote_index_ready(self, index, loaded) -> None:
        previous_name = self.selected_game_name
        self._rebuild_supported_games_from_index()
        if loaded.cartridge.adapter.descriptor.game_id != self.cartridge.adapter.descriptor.game_id:
            # The background refresh started before the user selected another
            # game.  Its cartridge is stale and must not overwrite the picker.
            self._sync_game_selector_values()
            self._set_game_selector_text(self.selected_game_name)
            return
        if loaded.cartridge is not self.cartridge:
            self._activate_loaded_cartridge(loaded, rebuild_services=True)
        else:
            self.cartridges[loaded.cartridge.selection_name] = loaded.cartridge
            self.supported_games[loaded.cartridge.selection_name] = {
                "game_id": loaded.cartridge.adapter.descriptor.game_id,
                "platform": loaded.cartridge.platform_name,
                "store_app_id": loaded.cartridge.store_app_id,
                "display_name": loaded.cartridge.adapter.descriptor.display_name,
            }
        self._sync_game_selector_values()
        self._set_game_selector_text(self.selected_game_name)
        if previous_name != self.selected_game_name:
            self._select_game(self.selected_game_name)
        self._notify(f"已同步游戏列表（{len(index.cartridges)} 款）")

    def _select_game(self, display_name: str) -> None:
        if (
            display_name != self.selected_game_name
            and self._content_work_is_active()
        ):
            self._set_game_selector_text(self.selected_game_name)
            self._notify("请先取消或结束当前下载/安装任务，再切换游戏", error=True)
            return
        try:
            game = self.supported_games[display_name]
        except KeyError:
            return
        cartridge = self.cartridges.get(display_name)
        if cartridge is None:
            if self.cartridge_loading:
                self._set_game_selector_text(self.selected_game_name)
                self._notify("正在加载其他游戏的数据，请稍候", error=True)
                return
            self._start_lazy_cartridge_load(display_name, game["game_id"])
            return
        self._apply_selected_cartridge(display_name, game, cartridge)

    def _start_lazy_cartridge_load(self, display_name: str, game_id: str) -> None:
        self.cartridge_loading = True
        self._set_game_selector_state("disabled")
        self._set_game_buttons("disabled")
        self.catalog_preview.configure(text=f"正在加载 {display_name} 的支持数据……")
        generation = self.game_selection_generation

        def worker() -> None:
            try:
                loaded = self.cartridge_catalog.load_cartridge(
                    game_id, allow_network=True,
                )
                self._post_ui(
                    lambda: self._on_lazy_cartridge_loaded(
                        display_name, loaded, generation
                    )
                )
            except Exception as error:
                message = str(error) or "卡带加载失败"
                self._post_ui(
                    lambda message=message: self._on_lazy_cartridge_failed(
                        display_name, message
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_lazy_cartridge_loaded(self, display_name: str, loaded, generation: int) -> None:
        self.cartridge_loading = False
        self._set_game_selector_state("normal")
        self._set_game_buttons("normal")
        if generation != self.game_selection_generation:
            return
        self.cartridges[loaded.cartridge.selection_name] = loaded.cartridge
        adapter_id = loaded.cartridge.adapter.descriptor.adapter_id
        if adapter_id not in self.adapter_registry:
            self.adapter_registry.register(loaded.cartridge.adapter)
        game = {
            "game_id": loaded.cartridge.adapter.descriptor.game_id,
            "platform": loaded.cartridge.platform_name,
            "store_app_id": loaded.cartridge.store_app_id,
            "display_name": loaded.cartridge.adapter.descriptor.display_name,
        }
        self.supported_games[loaded.cartridge.selection_name] = game
        self._apply_selected_cartridge(
            loaded.cartridge.selection_name, game, loaded.cartridge
        )
        self._notify(f"已加载 {loaded.cartridge.selection_name} 的支持数据")

    def _on_lazy_cartridge_failed(self, display_name: str, message: str) -> None:
        self.cartridge_loading = False
        self._set_game_selector_state("normal")
        self._set_game_buttons("normal")
        self._set_game_selector_text(self.selected_game_name)
        self.catalog_preview.configure(text="游戏支持数据加载失败")
        messagebox.showerror(
            "无法加载游戏支持数据",
            f"{display_name}\n\n{message}",
            parent=self.window,
        )

    def _apply_selected_cartridge(self, display_name: str, game, cartridge) -> None:
        if cartridge is not self.cartridge:
            self.game_selection_generation += 1
            self.cartridge = cartridge
            self.patch_profile = cartridge.patch_profile
            self.catalog = cartridge.create_catalog(
                download_source=self.user_settings.download_source,
                cache_path=(self.context.paths.data / "catalogs" / self.user_settings.download_source / f"{cartridge.adapter.descriptor.game_id}.json"),
            )
            self.patch_engine = PatchEngine(
                cartridge.patch_profile, self.context.paths.data,
            )
            self.patch_task_roles = {}
            if self.install_repository is not None:
                self.install_service = DlcInstallService(
                    cartridge.create_install_engine(self.context.paths.data),
                    self.install_repository,
                    game_id=cartridge.adapter.descriptor.game_id,
                    package_inspector=cartridge.inspect_package,
                )
            self.patch_bundle = None
            self.catalog_patch_warning.configure(text="")
            self.current_installation = None
            self.catalog_entries = ()
            self.installed_dlc_paths = {}
            self.active_receipt_dlc_ids = frozenset()
            self.install_recovery_running = False
            self.install_recovery_failed = False
            self.install_recovery_key = None
            self.install_recovery_pending = None
            self.unlock_workflow_active = False
            self.unlock_requested_dlc_ids = ()
            self.unlock_failed_dlc_ids.clear()
            self.auto_install_requested_task_ids.clear()
            self.selected_dlc_ids.clear()
            self.catalog_selection_initialized = False
            self.catalog_online = False
            self._clear_catalog_views(f"正在读取 {display_name} 的 DLC 目录……")
            self.selection_toggle_button.configure(state="disabled", text="全选 DLC")
            self.download_selected_button.configure(
                state="disabled", text="正在读取目录……"
            )
        self.selected_game_name = display_name
        self._set_game_selector_text(display_name)
        self.platform_status.configure(
            text=f"{game['platform']} · App {game['store_app_id']}"
        )
        self.top_health.configure(text=f"{display_name} · 正在刷新")
        self._scan_games()
        self._refresh_catalog()

    def _content_work_is_active(self) -> bool:
        if (
            self.auto_install_worker_running
            or self.install_recovery_running
            or self.manual_file_operation_token is not None
            or self.cache_cleanup_running
            or self.diagnostics_export_running
            or self.batch_download_state != "idle"
            or self.patch_workflow_state != "idle"
        ):
            return True
        if self.download_queue is None:
            return False
        active_states = {
            DownloadState.QUEUED,
            DownloadState.DOWNLOADING,
            DownloadState.PAUSING,
            DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        return any(
            snapshot.state in active_states
            and self.download_queue.is_active(snapshot.spec.task_id)
            for snapshot in self.download_queue.snapshots()
        )

    def _dlc_task_id(self, dlc_id: str) -> str:
        return f"{self.cartridge.adapter.descriptor.game_id}-{dlc_id}"

    def _dlc_id_from_task(self, task_id: str) -> str:
        prefix = f"{self.cartridge.adapter.descriptor.game_id}-"
        return task_id.removeprefix(prefix)

    def _open_external_link(self, url: str) -> None:
        parsed = urlparse(url)
        allowed_hosts = {
            "github.com", "space.bilibili.com",
            "sign-river.github.io",
            "www.gitlink.org.cn", "gitlink.org.cn",
        }
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            messagebox.showerror(
                "链接被阻止", "只允许打开预先配置的项目 HTTPS 链接。",
                parent=self.window,
            )
            return
        webbrowser.open(url)

    def _open_usage_tutorial(self) -> None:
        choice = messagebox.askyesnocancel(
            "使用教程",
            "教程部署在 GitHub 上，需要使用代理才能访问。\n\n"
            "是：打开 GitHub 教程\n"
            "否：打开 B 站教程\n"
            "取消：暂不打开",
            parent=self.window,
        )
        if choice is True:
            self._open_external_link(USAGE_TUTORIAL_URL)
        elif choice is False:
            self._open_external_link(BILIBILI_TUTORIAL_URL)

    def _copy_qq_group(self) -> None:
        group_number = "1061299021"
        self.window.clipboard_clear()
        self.window.clipboard_append(group_number)
        self.window.update_idletasks()
        self._notify(f"QQ群号已复制：{group_number}")

    def _copy_game_list(self) -> None:
        names = [
            info.get("display_name") or name
            for name, info in self.supported_games.items()
        ]
        if not names:
            self._notify("当前没有可复制的游戏列表")
            return
        lines = ["本软件当前支持的游戏："]
        lines.extend(f"· {name}" for name in names)
        clipboard_text = "\n".join(lines)
        self.window.clipboard_clear()
        self.window.clipboard_append(clipboard_text)
        self.window.update_idletasks()
        self._notify(
            f"已复制 {len(names)} 款游戏列表到剪贴板"
        )

    def _open_qq_group_hint(self) -> None:
        if QQ_GROUP_JOIN_URL:
            webbrowser.open(QQ_GROUP_JOIN_URL)
            return
        group_number = "1061299021"
        self.window.clipboard_clear()
        self.window.clipboard_append(group_number)
        self.window.update_idletasks()
        self._notify("加群链接尚未配置，已复制群号")
        messagebox.showinfo(
            "QQ 群",
            f"加群链接尚未配置，已复制群号 {group_number}\n\n"
            "请粘贴到 QQ 搜索群号加群，谢谢！",
            parent=self.window,
        )

    def _build_error_tutorial_page(self) -> None:
        header = ctk.CTkFrame(self.guide_tutorial_card, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(
            header, text="解决方案", text_color=UI["primary"],
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header, text="返回指南", width=92,
            command=lambda: self._show_page("报错指南"),
        ).pack(side="right")
        self.solution_articles = {
            "download": ("下载或测速失败", "下载失败、测速偶发报错", (("heading", "建议操作"), ("text", "请先稍候重试；仍失败时切换下载源，并检查网络连接。"), ("button", "运行一键排错", "简单错误检测"))),
            "ssl": ("SSL / TLS 连接错误", "SSL、EOF 或证书相关报错", (("heading", "建议操作"), ("text", "检查代理、系统时间和网络连接；关闭后重新打开程序再试。"), ("button", "运行一键排错", "简单错误检测"))),
            "patch": ("DLC 或补丁异常", "DLC 未生效、补丁文件缺失或游戏无法启动", (("heading", "建议操作"), ("text", "先重新扫描游戏；再运行一键排错，并按问题记录中的建议操作。"), ("button", "查看问题记录", "问题记录"))),
            "patch_assets_missing": (
                "补丁资源缺失",
                "当前游戏的补丁资源未能从云端完整读取，暂时无法一键解锁。",
                (
                    ("heading", "请先刷新目录"),
                    (
                        "text",
                        "返回 DLC 列表后点击“刷新目录”。这会重新读取当前游戏的云端资源，不会删除本地 DLC，也不会修改游戏文件。",
                    ),
                    ("button", "前往 DLC 列表", "DLC 库"),
                    ("heading", "刷新后仍然缺失"),
                    (
                        "text",
                        "这通常表示云端补丁资源尚未上传完整或暂时不可用，用户侧无法通过验证文件、重装游戏或重复解锁解决。请附上游戏名称和提示截图，通过 QQ 群或视频评论区联系制作者处理。",
                    ),
                    ("action", "加入 QQ 群", self._open_qq_group_hint),
                    (
                        "action",
                        "前往 B 站评论区",
                        lambda: self._open_external_link(BILIBILI_TUTORIAL_URL),
                    ),
                ),
            ),
            "security": ("安全软件拦截", "文件下载或写入后消失", (("heading", "建议操作"), ("text", "在安全软件记录中核对文件来源和哈希；确认误报后仅恢复该文件，不要关闭整机防护。"), ("button", "查看问题记录", "问题记录"))),
            "update": ("程序更新与模块异常", "更新回滚、模块加载失败或程序意外退出", (("heading", "建议操作"), ("text", "重新检查更新；若问题仍然存在，请运行一键排错并导出诊断信息。"), ("button", "运行一键排错", "简单错误检测"))),
        }
        solution_search_bar = ctk.CTkFrame(
            self.guide_tutorial_card, fg_color="transparent"
        )
        solution_search_bar.pack(fill="x", padx=24, pady=(0, 10))
        solution_search_bar.grid_columnconfigure(0, weight=1)
        self.solution_search_query = StringVar(value="")
        self.solution_search = ctk.CTkEntry(
            solution_search_bar,
            textvariable=self.solution_search_query,
            placeholder_text="搜索解决方案标题、现象或处理方法",
            height=34,
        )
        self.solution_search.grid(row=0, column=0, sticky="ew")
        self.solution_search_mode = _combo_box(
            solution_search_bar,
            values=["模糊匹配", "精确匹配"],
            command=lambda _value: self._render_solution_articles(),
            width=104,
        )
        self.solution_search_mode.set("模糊匹配")
        self.solution_search_mode.grid(row=0, column=1, padx=(8, 0))
        self.solution_list = ctk.CTkScrollableFrame(
            self.guide_tutorial_card, fg_color="transparent", corner_radius=0,
        )
        self.solution_list.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.solution_search_query.trace_add(
            "write", lambda *_args: self._render_solution_articles()
        )
        self._render_solution_articles()
        self.solution_detail_page = ctk.CTkFrame(self.guide_tutorial_card, fg_color=UI["card"], corner_radius=0)
        detail_header = ctk.CTkFrame(self.solution_detail_page, fg_color="transparent")
        detail_header.pack(fill="x", padx=24, pady=(12, 4))
        ctk.CTkButton(detail_header, text="← 返回解决方案", width=120, fg_color="transparent", hover_color=UI["primary_surface"], text_color=UI["primary"], command=self._show_solution_list).pack(side="left")
        self.solution_detail_body = ctk.CTkScrollableFrame(self.solution_detail_page, fg_color="transparent", corner_radius=0)
        self.solution_detail_body.pack(fill="both", expand=True, padx=24, pady=(0, 18))

    @staticmethod
    def _normalize_solution_search_text(text: str) -> str:
        return "".join(character for character in text.casefold() if character.isalnum())

    def _solution_matches_search(self, article) -> bool:
        query = self._normalize_solution_search_text(self.solution_search_query.get())
        if not query:
            return True
        title, summary, blocks = article
        parts = [title, summary]
        for _kind, *values in blocks:
            if values and isinstance(values[0], str):
                parts.append(values[0])
        source = self._normalize_solution_search_text(" ".join(parts))
        if self.solution_search_mode.get() == "精确匹配":
            return query in source
        offset = 0
        for character in query:
            offset = source.find(character, offset)
            if offset < 0:
                return False
            offset += 1
        return True

    def _render_solution_articles(self) -> None:
        for child in self.solution_list.winfo_children():
            child.destroy()
        matches = [
            (article_id, article)
            for article_id, article in self.solution_articles.items()
            if self._solution_matches_search(article)
        ]
        if not matches:
            ctk.CTkLabel(
                self.solution_list,
                text="未找到匹配的解决方案，请尝试缩短关键词或切换匹配方式。",
                text_color=UI["muted"],
                anchor="w",
            ).pack(fill="x", padx=16, pady=20)
            return
        for article_id, (title, summary, _blocks) in matches:
            card = ctk.CTkFrame(self.solution_list, fg_color=UI["panel"], border_color=UI["border"], border_width=1, corner_radius=10)
            card.pack(fill="x", pady=6)
            title_label = ctk.CTkLabel(card, text=title, text_color=UI["text"], font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
            title_label.pack(fill="x", padx=16, pady=(12, 3))
            summary_label = ctk.CTkLabel(card, text=summary, text_color=UI["text_secondary"], anchor="w")
            summary_label.pack(fill="x", padx=16, pady=(0, 12))
            arrow = ctk.CTkLabel(card, text="→", text_color=UI["primary"], font=ctk.CTkFont(size=18), anchor="e")
            arrow.place(relx=1, rely=0.5, x=-18, anchor="e")
            def callback(_event, key=article_id) -> None:
                self._show_solution_detail(key)

            for widget in (card, title_label, summary_label, arrow):
                widget.bind("<Button-1>", callback)

    def _show_solution_detail(self, article_id: str) -> None:
        article = self.solution_articles.get(article_id)
        if article is None:
            return
        title, summary, blocks = article
        for child in self.solution_detail_body.winfo_children():
            child.destroy()
        self.solution_detail_images = []
        ctk.CTkLabel(self.solution_detail_body, text=title, text_color=UI["primary"], font=ctk.CTkFont(size=20, weight="bold"), anchor="w").pack(fill="x", pady=(8, 6))
        ctk.CTkLabel(self.solution_detail_body, text=summary, text_color=UI["text_secondary"], anchor="w").pack(fill="x", pady=(0, 18))
        for kind, *values in blocks:
            if kind == "heading":
                ctk.CTkLabel(self.solution_detail_body, text=values[0], text_color=UI["text"], font=ctk.CTkFont(size=15, weight="bold"), anchor="w").pack(fill="x", pady=(0, 6))
            elif kind == "text":
                ctk.CTkLabel(self.solution_detail_body, text=values[0], text_color=UI["text_secondary"], justify="left", anchor="w", wraplength=820).pack(fill="x", pady=(0, 16))
            elif kind == "image":
                image_path = Path(values[0])
                if image_path.is_file():
                    from PIL import Image
                    image = ctk.CTkImage(light_image=Image.open(image_path), size=values[1] if len(values) > 1 else (720, 405))
                    self.solution_detail_images.append(image)
                    ctk.CTkLabel(self.solution_detail_body, text="", image=image).pack(anchor="w", pady=(0, 16))
            elif kind == "button":
                ctk.CTkButton(self.solution_detail_body, text=values[0], width=132, command=lambda target=values[1]: self._show_page(target)).pack(anchor="w", pady=(0, 16))
            elif kind == "action":
                ctk.CTkButton(
                    self.solution_detail_body,
                    text=values[0],
                    width=148,
                    command=values[1],
                    fg_color="transparent",
                    hover_color=UI["primary_surface"],
                    text_color=UI["primary"],
                    border_width=1,
                    border_color=UI["primary_border"],
                ).pack(anchor="w", pady=(0, 10))
        self.solution_detail_page.update_idletasks()
        self.solution_list.pack_forget()
        self.solution_detail_page.pack(fill="both", expand=True)

    def _show_solution_list(self) -> None:
        self.solution_detail_page.pack_forget()
        self.solution_list.pack(fill="both", expand=True, padx=24, pady=(0, 18))

    def _build_quick_check_page(self) -> None:
        header = ctk.CTkFrame(self.quick_check_card, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(18, 8))
        ctk.CTkLabel(header, text="一键排错", text_color=UI["primary"], font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="返回指南", width=92, command=lambda: self._show_page("报错指南")).pack(side="right")
        ctk.CTkLabel(self.quick_check_card, text="仅检查常见环境问题，不会修改游戏文件、设置或网络配置；未发现异常不代表所有问题均已排除。", text_color=UI["text_secondary"], anchor="w").pack(fill="x", padx=24, pady=(0, 10))
        self.quick_check_output = ctk.CTkScrollableFrame(self.quick_check_card, height=360, fg_color=UI["panel"], border_color=UI["border"], border_width=1)
        self.quick_check_output.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        controls = ctk.CTkFrame(self.quick_check_card, fg_color="transparent")
        controls.pack(fill="x", padx=24, pady=(0, 18))
        self.quick_check_start_button = ctk.CTkButton(controls, text="开始排错", width=96, command=self._run_quick_check)
        self.quick_check_pause_button = ctk.CTkButton(controls, text="暂停检测", width=96, fg_color="transparent", hover_color=UI["primary_surface"], text_color=UI["primary"], command=self._toggle_quick_check_pause)
        self.quick_check_stop_button = ctk.CTkButton(controls, text="终止检测", width=96, fg_color="transparent", hover_color="#FDECEC", text_color=UI["danger"], command=self._terminate_quick_check)
        self.quick_check_copy_button = ctk.CTkButton(controls, text="复制检测结果", width=112, fg_color="transparent", hover_color=UI["primary_surface"], text_color=UI["primary"], command=self._copy_quick_check_result)
        controls.grid_columnconfigure(0, weight=1)
        self.quick_check_start_button.grid(row=0, column=1, padx=(0, 8))
        self.quick_check_pause_button.grid(row=0, column=2, padx=(0, 8))
        self.quick_check_stop_button.grid(row=0, column=3, padx=(0, 8))
        self.quick_check_copy_button.grid(row=0, column=4)
        self.quick_check_lines: list[str] = []
        self.quick_check_results: list[tuple[str, str | None]] = []
        self.quick_check_steps: list = []
        self.quick_check_running = False
        self.quick_check_paused = False
        self._set_quick_check_controls()

    def _run_quick_check(self) -> None:
        if self.quick_check_running:
            return
        self.quick_check_lines = ["一键排错结果", "", "正在检查常见环境问题……", ""]
        self.quick_check_results = []
        self.quick_check_steps = [
            self._quick_check_network,
            self._quick_check_game_directory,
            self._quick_check_patch_state,
            self._quick_check_recent_problems,
        ]
        self.quick_check_running = True
        self.quick_check_paused = False
        self._render_quick_check_output()
        self._set_quick_check_controls()
        self.window.after(30, self._advance_quick_check)

    def _quick_check_network(self) -> None:
        self._add_quick_check_result(f"网络目录状态：{'可连接' if self.catalog_online else '当前未连接或尚未验证'}", None if self.catalog_online else "download")

    def _quick_check_game_directory(self) -> None:
        installation = self.current_installation
        if installation is None:
            self._add_quick_check_result("游戏目录：未选择，请先重新扫描或手动选择目录。", "patch")
            return
        root = installation.root
        self._add_quick_check_result(f"游戏目录：{'存在' if root.is_dir() else '不存在'} · {root}", None if root.is_dir() else "patch")
        if root.is_dir():
            free = shutil.disk_usage(root).free
            self._add_quick_check_result(f"所在磁盘可用空间：{_format_size(free)}")

    def _quick_check_patch_state(self) -> None:
        installation = self.current_installation
        if installation is None or not installation.root.is_dir():
            self._add_quick_check_result("补丁状态：未检查（尚未找到有效游戏目录）。", "patch")
            return
        try:
            audit = self.patch_engine.audit_recorded(installation.root)
            health = audit.health.value
            self._add_quick_check_result(f"补丁状态：{health}", None if health == "healthy" else "patch")
        except Exception:
            self._add_quick_check_result("补丁状态：尚未安装或无法读取。", "patch")

    def _quick_check_recent_problems(self) -> None:
        try:
            recent = self.problem_store.list_reports()
            if recent:
                self._add_quick_check_result("近期异常：" + recent[0].summary, self._solution_id_for_problem_code(recent[0].code))
            else:
                self._add_quick_check_result("近期异常：未记录到异常")
        except Exception:
            self._add_quick_check_result("近期异常：无法读取问题记录。", "update")

    def _advance_quick_check(self) -> None:
        if not self.quick_check_running or self.quick_check_paused:
            return
        if not self.quick_check_steps:
            self.quick_check_lines.extend(("", "检测完成。此结果仅覆盖常见问题；如仍无法处理，请导出诊断信息。"))
            self.quick_check_running = False
            self._render_quick_check_output()
            self._set_quick_check_controls()
            return
        step = self.quick_check_steps.pop(0)
        try:
            step()
        except Exception as error:
            self.context.logger.exception("Quick check step failed")
            self._add_quick_check_result(f"检查项执行失败：{error}", "update")
        self._render_quick_check_output()
        self.window.after(220, self._advance_quick_check)

    def _toggle_quick_check_pause(self) -> None:
        if not self.quick_check_running:
            return
        self.quick_check_paused = not self.quick_check_paused
        self._set_quick_check_controls()
        if not self.quick_check_paused:
            self.window.after(0, self._advance_quick_check)

    def _terminate_quick_check(self) -> None:
        if not self.quick_check_running:
            return
        self.quick_check_running = False
        self.quick_check_paused = False
        self.quick_check_steps.clear()
        self.quick_check_lines.extend(("", "检测已由用户终止。"))
        self._render_quick_check_output()
        self._set_quick_check_controls()

    def _render_quick_check_output(self) -> None:
        for child in self.quick_check_output.winfo_children():
            child.destroy()
        if not self.quick_check_results:
            ctk.CTkLabel(self.quick_check_output, text="正在准备检查……", text_color=UI["muted"], anchor="w").pack(fill="x", padx=12, pady=12)
            return
        for index, (text, solution_id) in enumerate(self.quick_check_results, start=1):
            row = ctk.CTkFrame(self.quick_check_output, fg_color=UI["card"], border_color=UI["border"], border_width=1, corner_radius=8)
            row.pack(fill="x", padx=6, pady=(6, 0))
            ctk.CTkLabel(row, text=f"{index}. {text}", text_color=UI["danger"] if solution_id else UI["text_secondary"], anchor="w", justify="left", wraplength=760).pack(side="left", fill="x", expand=True, padx=12, pady=10)
            if solution_id:
                ctk.CTkButton(row, text="查看解决方案 →", width=128, height=28, command=lambda article_id=solution_id: self._open_solution_article(article_id)).pack(side="right", padx=10)

    def _add_quick_check_result(self, text: str, solution_id: str | None = None) -> None:
        self.quick_check_results.append((text, solution_id))
        self.quick_check_lines.append(f"{len(self.quick_check_results)}. {text}")

    def _open_solution_article(self, article_id: str) -> None:
        self._show_page("常见问题教程")
        self._show_solution_list()
        self._show_solution_detail(article_id)

    def _set_quick_check_controls(self) -> None:
        active = self.quick_check_running
        self.quick_check_start_button.configure(state="disabled" if active else "normal")
        self.quick_check_pause_button.configure(state="normal" if active else "disabled", text="继续检测" if self.quick_check_paused else "暂停检测")
        self.quick_check_stop_button.configure(state="normal" if active else "disabled")
        self.quick_check_copy_button.configure(state="normal" if self.quick_check_lines else "disabled")

    def _copy_quick_check_result(self) -> None:
        if not self.quick_check_lines:
            return
        self.window.clipboard_clear()
        self.window.clipboard_append("\n".join(self.quick_check_lines))
        self._notify("检测结果已复制")

    def _show_page(self, page_name: str) -> None:
        self.current_page = page_name
        # A page can contain dynamically rebuilt scrollable content.  Hide every
        # top-level page with all geometry managers before exposing the target,
        # otherwise a previous guide card may briefly remain above the detail page.
        for sections in self.page_sections.values():
            for section in sections:
                section.pack_forget()
                section.grid_forget()
                section.place_forget()
        self.page_host.update_idletasks()
        sections = self.page_sections[page_name]
        for index, section in enumerate(sections):
            if page_name == "DLC 库" and section is self.catalog_card:
                section.pack(fill="both", expand=True)
            elif page_name in {"高级DLC视图", "下载任务", "报错指南", "常见问题教程", "简单错误检测", "问题记录", "运行日志", "设置"}:
                section.pack(fill="both", expand=True)
            else:
                bottom = 18 if index < len(sections) - 1 else 0
                section.pack(fill="x", pady=(0, bottom))
        navigation_page = "DLC 库" if page_name == "高级DLC视图" else page_name
        for name, button in self.navigation_buttons.items():
            button.configure(
                fg_color=UI["primary"] if name == navigation_page else "transparent",
                text_color=UI["on_blue"] if name == navigation_page else UI["text_secondary"],
                hover_color=UI["primary_hover"] if name == navigation_page else "#EAF3FB",
            )
        if page_name == "下载任务":
            self._refresh_task_page()
        elif page_name == "问题记录":
            self._show_problem_list()
            self._refresh_problem_center()
        elif page_name == "运行日志":
            self._refresh_log_preview()

    def _refresh_task_page(self) -> None:
        self.task_refresh_pending = False
        snapshots = self.download_queue.snapshots() if self.download_queue is not None else ()
        has_update_download = self.update_download_active
        snapshot_ids = tuple(snapshot.spec.task_id for snapshot in snapshots)
        active_task_id = self._active_download_task_id(snapshots)
        if snapshot_ids and snapshot_ids == tuple(self.task_rows) and (
            has_update_download == (self.update_task_row is not None)
        ):
            try:
                rows_alive = all(row.winfo_exists() for row in self.task_rows.values())
            except TclError:
                rows_alive = False
            if rows_alive:
                for snapshot in snapshots:
                    self._update_task_row_snapshot(snapshot)
                self._schedule_task_scroll(active_task_id)
                return

        self.task_status_labels.clear()
        self.task_row_states.clear()
        self.task_rows.clear()
        self.task_action_frames.clear()
        self.task_action_keys.clear()
        self.update_task_row = None
        self.update_task_status_label = None
        self.update_task_cancel_button = None
        for child in self.task_list_frame.winfo_children():
            child.destroy()
        if not snapshots and not has_update_download:
            ctk.CTkLabel(
                self.task_list_frame, text="暂无下载任务"
            ).pack(pady=40)
            self._schedule_task_scroll(None)
            return
        if has_update_download:
            self._render_update_download_row()
        for snapshot in snapshots:
            row = ctk.CTkFrame(
                self.task_list_frame, fg_color=UI["card"], corner_radius=10,
                border_width=1, border_color=UI["border"], height=68,
            )
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)
            self.task_rows[snapshot.spec.task_id] = row
            self._render_task_row_actions(snapshot)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True, padx=(14, 4), pady=7)
            ctk.CTkLabel(
                info, text=snapshot.spec.filename, anchor="w", height=23,
            ).pack(fill="x")
            status_label = ctk.CTkLabel(
                info,
                text=self._task_status_text(snapshot),
                anchor="w", height=20, text_color=("gray40", "gray70"),
            )
            status_label.pack(fill="x")
            self.task_status_labels[snapshot.spec.task_id] = status_label
            self.task_row_states[snapshot.spec.task_id] = snapshot.state
            self._apply_visual_theme_to_children(
                row, set(self.navigation_buttons.values())
            )
        self._schedule_task_scroll(active_task_id)

    def _render_update_download_row(self) -> None:
        row = ctk.CTkFrame(
            self.task_list_frame, fg_color=UI["card"], corner_radius=10,
            border_width=1, border_color=UI["primary_border"], height=68,
        )
        row.pack(fill="x", pady=3)
        row.pack_propagate(False)
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(14, 4), pady=7)
        ctk.CTkLabel(
            info,
            text=f"程序更新 v{self.update_download_version}",
            anchor="w",
            height=23,
        ).pack(fill="x")
        status = ctk.CTkLabel(
            info,
            text=self._update_download_task_text(),
            anchor="w",
            height=20,
            text_color=("gray40", "gray70"),
        )
        status.pack(fill="x")
        cancel = ctk.CTkButton(
            row,
            text="取消",
            width=64,
            command=self._cancel_update_download,
            state=(
                "disabled"
                if self.update_download_cancelling or self.update_download_preparing
                else "normal"
            ),
        )
        cancel.pack(side="right", padx=(8, 12), pady=16)
        self.update_task_row = row
        self.update_task_status_label = status
        self.update_task_cancel_button = cancel
        self._apply_visual_theme_to_children(
            row, set(self.navigation_buttons.values())
        )

    def _update_download_task_text(self) -> str:
        state = (
            "正在取消" if self.update_download_cancelling
            else "正在准备" if self.update_download_preparing
            else "下载中"
        )
        total = self.update_download_total
        progress = (
            f"{_format_size(self.update_download_current)}/"
            f"{_format_size(total)}"
            if total else _format_size(self.update_download_current)
        )
        return f"{state} · {progress} · {_format_speed(self.update_download_speed)}"

    def _refresh_update_download_task(self) -> None:
        if getattr(self, "current_page", None) != "下载任务":
            return
        label = self.update_task_status_label
        if label is None:
            self._refresh_task_page()
            return
        label.configure(text=self._update_download_task_text())
        if self.update_task_cancel_button is not None:
            self.update_task_cancel_button.configure(
                state=(
                    "disabled"
                    if self.update_download_cancelling or self.update_download_preparing
                    else "normal"
                )
            )

    def _render_task_row_actions(self, snapshot) -> None:
        task_id = snapshot.spec.task_id
        row = self.task_rows.get(task_id)
        if row is None:
            return
        is_batch_task = task_id in self.batch_download_task_ids
        action_key = (snapshot.state, is_batch_task)
        if self.task_action_keys.get(task_id) == action_key:
            return
        previous = self.task_action_frames.pop(task_id, None)
        if previous is not None:
            previous.destroy()
        self.task_action_keys[task_id] = action_key
        active = snapshot.state in {
            DownloadState.QUEUED,
            DownloadState.DOWNLOADING,
            DownloadState.PAUSING,
            DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        if not active and snapshot.state not in {
            DownloadState.PAUSED, DownloadState.FAILED,
        }:
            return
        actions = ctk.CTkFrame(row, fg_color="transparent", height=34)
        actions.pack(side="right", padx=(8, 12), pady=16)
        if snapshot.state is DownloadState.FAILED or (
            snapshot.state is DownloadState.PAUSED and not is_batch_task
        ):
            ctk.CTkButton(
                actions,
                text="重试" if snapshot.state is DownloadState.FAILED else "重新下载",
                width=72,
                command=lambda task_id=task_id: self._task_action(task_id, "resume"),
            ).pack(side="left")
        if active or snapshot.state is DownloadState.PAUSED:
            ctk.CTkButton(
                actions,
                text="取消",
                width=64,
                command=lambda task_id=task_id: self._task_action(task_id, "cancel"),
            ).pack(side="left", padx=(6, 0))
        self.task_action_frames[task_id] = actions
        self._apply_visual_theme_to_children(
            actions, set(self.navigation_buttons.values())
        )

    def _update_task_row_snapshot(self, snapshot) -> bool:
        """Update one stable task row without rebuilding the scroll list."""
        task_id = snapshot.spec.task_id
        label = self.task_status_labels.get(task_id)
        if label is None:
            return False
        label.configure(text=self._task_status_text(snapshot))
        self._render_task_row_actions(snapshot)
        self.task_row_states[task_id] = snapshot.state
        return True

    @staticmethod
    def _active_download_task_id(snapshots) -> str | None:
        """Return the task currently doing work, excluding merely queued tasks."""
        active_states = {
            DownloadState.DOWNLOADING,
            DownloadState.PAUSING,
            DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        return next(
            (
                snapshot.spec.task_id
                for snapshot in snapshots
                if snapshot.state in active_states
            ),
            None,
        )

    def _reset_task_scroll(self, task_id: str | None) -> None:
        """Show the active download row, or the top when no task is active."""
        try:
            self.task_list_frame.update_idletasks()
            canvas = self.task_list_frame._parent_canvas
            bounds = canvas.bbox("all")
            if bounds is not None:
                canvas.configure(scrollregion=bounds)
            row = self.task_rows.get(task_id) if task_id is not None else None
            if row is None or bounds is None:
                canvas.yview_moveto(0.0)
                return
            content_height = max(1, bounds[3] - bounds[1])
            target_y = max(0, row.winfo_y() - bounds[1])
            canvas.yview_moveto(min(1.0, target_y / content_height))
        except (AttributeError, TclError):
            return

    def _schedule_task_scroll(self, task_id: str | None) -> None:
        """Coalesce scroll requests and position after geometry propagation."""
        self.task_scroll_target = task_id
        try:
            if self.task_scroll_after_id is not None:
                self.window.after_cancel(self.task_scroll_after_id)
            self.task_scroll_after_id = self.window.after(
                40, self._apply_scheduled_task_scroll
            )
        except TclError:
            return

    def _apply_scheduled_task_scroll(self) -> None:
        self.task_scroll_after_id = None
        self._reset_task_scroll(self.task_scroll_target)

    @staticmethod
    def _task_status_text(snapshot) -> str:
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
        state = labels.get(snapshot.state, str(snapshot.state))
        speed = (
            f" · {_format_speed(snapshot.speed_bytes_per_second)}"
            if snapshot.speed_bytes_per_second else ""
        )
        error_states = {
            DownloadState.RETRYING, DownloadState.FAILED, DownloadState.CORRUPT,
        }
        error = (
            f" · {snapshot.error}"
            if snapshot.error and snapshot.state in error_states else ""
        )
        return f"{state} · {_format_size(snapshot.bytes_downloaded)}{speed}{error}"

    def _update_task_page_snapshot(self, snapshot) -> None:
        """Update progress and controls in place; rebuild only for new tasks."""
        if getattr(self, "current_page", None) != "下载任务":
            return
        task_id = snapshot.spec.task_id
        previous_state = self.task_row_states.get(task_id)
        if not self._update_task_row_snapshot(snapshot):
            self._schedule_task_refresh()
            return
        if snapshot.state != previous_state and snapshot.state in {
            DownloadState.DOWNLOADING,
            DownloadState.READY,
            DownloadState.CANCELLED,
            DownloadState.FAILED,
            DownloadState.CORRUPT,
        }:
            snapshots = (
                self.download_queue.snapshots()
                if self.download_queue is not None else ()
            )
            self._schedule_task_scroll(self._active_download_task_id(snapshots))

    def _schedule_task_refresh(self) -> None:
        if self.task_refresh_pending:
            return
        self.task_refresh_pending = True
        self.window.after(600, self._refresh_task_page)

    def _task_action(self, task_id: str, action: str) -> None:
        if self.download_queue is None:
            return
        if action == "resume" and self.cache_cleanup_running:
            messagebox.showwarning(
                "缓存正在维护", "请等待缓存清理完成后再继续下载。",
                parent=self.window,
            )
            return
        try:
            if action == "cancel":
                self.auto_install_requested_task_ids.discard(task_id)
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
        self.auto_install_requested_task_ids.intersection_update(
            item.spec.task_id for item in self.download_queue.snapshots()
        )
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
            self.auto_install_requested_task_ids.clear()
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
        if self.cache_cleanup_running:
            return
        if self._content_work_is_active():
            messagebox.showwarning(
                "当前任务尚未结束",
                "请先等待下载、安装或补丁操作结束，再分析缓存。",
                parent=self.window,
            )
            return
        with self.cache_reconcile_lock:
            reconcile_running = self.cache_reconcile_running
        if reconcile_running:
            messagebox.showwarning(
                "缓存目录正在核对",
                "请等待当前资源目录的缓存核对完成后再分析和清理。",
                parent=self.window,
            )
            return
        snapshots = self.download_queue.snapshots() if self.download_queue is not None else ()
        active_ids = [
            item.spec.task_id for item in snapshots
            if item.state not in {
                DownloadState.READY, DownloadState.CANCELLED,
                DownloadState.FAILED, DownloadState.CORRUPT,
            }
        ]
        ready_paths = tuple(
            item.result_path for item in snapshots
            if item.state is DownloadState.READY and item.result_path is not None
        )
        repository = self.install_repository
        install_service = self.install_service
        self._set_cache_cleanup_running(True, "正在分析……")

        def worker() -> None:
            try:
                protected = list(ready_paths)
                if repository is not None:
                    protected.extend(
                        self.context.paths.cache / "packages" / receipt.game_id / receipt.package_sha256
                        for receipt in repository.active()
                    )
                usage = self.cache_maintenance.usage_bytes()
                plan = self.cache_maintenance.plan(
                    protected_paths=protected, active_task_ids=active_ids
                )
                maintenance = (
                    install_service.preview_install_maintenance()
                    if install_service is not None else None
                )
                self._post_ui(
                    lambda usage=usage, plan=plan, maintenance=maintenance:
                    self._confirm_cache_cleanup(usage, plan, maintenance)
                )
            except Exception as error:
                self.context.logger.exception("Cache cleanup analysis failed")
                message = str(error)
                self._post_ui(
                    lambda message=message:
                    self._finish_cache_cleanup_error(message)
                )

        threading.Thread(
            target=worker, daemon=True, name="cache-maintenance-preview"
        ).start()

    def _cleanup_current_game_cache(self) -> None:
        """Remove completed cache packages owned only by the selected game."""
        if self.cache_cleanup_running:
            return
        if self._content_work_is_active():
            messagebox.showwarning(
                "当前任务尚未结束",
                "请先等待下载、安装或补丁操作结束，再清理当前游戏缓存。",
                parent=self.window,
            )
            return
        game_id = self.cartridge.adapter.descriptor.game_id
        game_name = self.cartridge.adapter.descriptor.display_name
        snapshots = (
            self.download_queue.snapshots() if self.download_queue is not None else ()
        )
        self._set_cache_cleanup_running(True, "正在分析…")

        def worker() -> None:
            try:
                usage = self.cache_maintenance.game_usage(game_id, snapshots)
                plan = self.cache_maintenance.plan_game_cleanup(game_id, snapshots)
                self._post_ui(
                    lambda usage=usage, plan=plan:
                    self._confirm_current_game_cache_cleanup(game_name, usage, plan)
                )
            except Exception as error:
                self.context.logger.exception("Game cache cleanup analysis failed")
                self._post_ui(
                    lambda message=str(error):
                    self._finish_cache_cleanup_error(message)
                )

        threading.Thread(
            target=worker, daemon=True, name="game-cache-maintenance-preview"
        ).start()

    def _confirm_current_game_cache_cleanup(self, game_name, usage, plan) -> None:
        if not plan.paths:
            self.cache_status.configure(
                text=(
                    f"{game_name}：已识别 {usage.file_count} 个缓存文件，"
                    "没有可单独清理的内容"
                )
            )
            self._set_cache_cleanup_running(False, "分析并清理")
            return
        if not messagebox.askyesno(
            "确认清理游戏缓存",
            f"{game_name} 的已下载缓存：{usage.file_count} 个文件，"
            f"{_format_size(usage.bytes_used)}。\n\n"
            f"将删除该游戏的 {plan.file_count} 个缓存文件，"
            f"约 {_format_size(plan.bytes_to_remove)}。\n"
            "已安装的游戏文件不会受影响；以后需要时会重新下载。",
            parent=self.window,
        ):
            self._set_cache_cleanup_running(False, "分析并清理")
            return
        self.cache_cleanup_button.configure(text="正在清理…")

        def worker() -> None:
            try:
                self.cache_maintenance.execute(plan)
                invalidate_hashes = getattr(self.download_queue, "invalidate_hashes", None)
                if callable(invalidate_hashes):
                    invalidate_hashes(plan.paths)
                self._post_ui(
                    lambda plan=plan: self._finish_current_game_cache_cleanup(plan)
                )
            except Exception as error:
                self.context.logger.exception("Game cache cleanup failed")
                self._post_ui(
                    lambda message=str(error):
                    self._finish_cache_cleanup_error(message)
                )

        threading.Thread(
            target=worker, daemon=True, name="game-cache-maintenance-execute"
        ).start()

    def _finish_current_game_cache_cleanup(self, plan) -> None:
        self.cache_status.configure(
            text=f"已清理当前游戏 {plan.file_count} 个缓存文件、{_format_size(plan.bytes_to_remove)}"
        )
        self._set_cache_cleanup_running(False, "分析并清理")
        self._schedule_cache_usage_scan(force=True)
        self._reconcile_catalog_cache()

    def _set_cache_cleanup_running(self, running: bool, text: str) -> None:
        self.cache_cleanup_running = running
        self.cache_cleanup_button.configure(
            state="disabled" if running else "normal", text=text
        )
        if hasattr(self, "game_cache_cleanup_button"):
            self.game_cache_cleanup_button.configure(
                state="disabled" if running else "normal"
            )

    def _confirm_cache_cleanup(self, usage, plan, maintenance) -> None:
        transaction_count = len(maintenance.candidates) if maintenance is not None else 0
        transaction_bytes = (
            maintenance.reclaimable_bytes if maintenance is not None else 0
        )
        if not plan.paths and not transaction_count:
            self.cache_usage_bytes = usage
            self.cache_status.configure(
                text=f"缓存 {_format_size(usage)}，无可安全清理内容"
            )
            self._set_cache_cleanup_running(False, "分析并清理")
            return
        if not messagebox.askyesno(
            "确认清理缓存",
            f"当前下载缓存 {_format_size(usage)}。\n"
            f"· 无引用/隔离缓存：{plan.file_count} 个文件，约 "
            f"{_format_size(plan.bytes_to_remove)}；\n"
            f"· 已终结安装事务：{transaction_count} 个目录，约 "
            f"{_format_size(transaction_bytes)}。\n\n"
            "已安装 DLC、仍被引用的资源包、活动事务及其备份不会删除。是否继续？",
            parent=self.window,
        ):
            self._set_cache_cleanup_running(False, "分析并清理")
            return
        self.cache_cleanup_button.configure(text="正在清理……")
        install_service = self.install_service

        def worker() -> None:
            try:
                snapshots = (
                    self.download_queue.snapshots()
                    if self.download_queue is not None else ()
                )
                active_ids = [
                    item.spec.task_id for item in snapshots
                    if item.state not in {
                        DownloadState.READY, DownloadState.CANCELLED,
                        DownloadState.FAILED, DownloadState.CORRUPT,
                    }
                ]
                protected = [
                    item.result_path for item in snapshots
                    if item.state is DownloadState.READY
                    and item.result_path is not None
                ]
                if self.install_repository is not None:
                    protected.extend(
                        self.context.paths.cache / "packages" / receipt.game_id / receipt.package_sha256
                        for receipt in self.install_repository.active()
                    )
                fresh_plan = self.cache_maintenance.plan(
                    protected_paths=protected, active_task_ids=active_ids
                )
                invalidate_hashes = getattr(
                    self.download_queue, "invalidate_hashes", None
                )
                try:
                    self.cache_maintenance.execute(fresh_plan)
                finally:
                    # Cleanup can remove several candidates before Windows
                    # rejects one locked path.  Invalidate every candidate so
                    # no stale digest survives a partially successful pass.
                    if callable(invalidate_hashes):
                        invalidate_hashes(fresh_plan.paths)
                result = (
                    install_service.execute_install_maintenance()
                    if install_service is not None and transaction_count else None
                )
                self._post_ui(
                    lambda usage=usage, plan=fresh_plan, result=result:
                    self._finish_cache_cleanup(usage, plan, result)
                )
            except Exception as error:
                self.context.logger.exception("Cache cleanup failed")
                message = str(error)
                self._post_ui(
                    lambda message=message:
                    self._finish_cache_cleanup_error(message)
                )

        threading.Thread(
            target=worker, daemon=True, name="cache-maintenance-execute"
        ).start()

    def _finish_cache_cleanup(self, usage, plan, maintenance_result) -> None:
        removed_transactions = (
            len(maintenance_result.removed) if maintenance_result is not None else 0
        )
        failed_transactions = (
            len(maintenance_result.failed) if maintenance_result is not None else 0
        )
        self.cache_usage_bytes = max(0, usage - plan.bytes_to_remove)
        self.cache_status.configure(
            text=(
                f"已清理 {plan.file_count} 个缓存文件、"
                f"{removed_transactions} 个终态事务；失败 {failed_transactions} 项"
            )
        )
        self._set_cache_cleanup_running(False, "分析并清理")
        self._schedule_cache_usage_scan(force=True)
        self._reconcile_catalog_cache()
        if failed_transactions:
            messagebox.showwarning(
                "清理部分完成",
                f"缓存已完成清理，但有 {failed_transactions} 个安装事务目录因权限或占用被保留。",
                parent=self.window,
            )

    def _finish_cache_cleanup_error(self, message: str) -> None:
        self._set_cache_cleanup_running(False, "分析并清理")
        self.cache_status.configure(text="缓存分析或清理失败")
        self._schedule_cache_usage_scan(force=True)
        self._reconcile_catalog_cache()
        messagebox.showerror("缓存清理失败", message, parent=self.window)

    def _toggle_download_never_timeout(self) -> None:
        enabled = bool(self.download_never_timeout_var.get())
        previous = self.user_settings
        updated = replace(
            previous,
            download_concurrency=1,
            bandwidth_limit_kib=None,
            download_never_timeout=enabled,
        )
        try:
            if self.settings_repository is not None:
                self.settings_repository.save(updated)
            self.download_manager.configure_timeout(None if enabled else 30)
        except Exception as error:
            self.context.logger.exception("Unable to save download timeout setting")
            self.download_never_timeout_var.set(
                previous.download_never_timeout
            )
            messagebox.showerror(
                "保存设置失败", str(error), parent=self.window
            )
            return
        self.user_settings = updated
        self._notify("下载永不超时已开启" if enabled else "已恢复默认下载超时")

    def _toggle_announcement_mute(self) -> None:
        enabled = bool(self.announcement_mute_var.get())
        previous = self.user_settings
        muted_id = previous.announcement_muted_id
        if enabled and self.current_announcement is not None:
            muted_id = self.current_announcement.announcement_id
        updated = replace(
            previous,
            download_concurrency=1,
            bandwidth_limit_kib=None,
            announcement_mute_until_update=enabled,
            announcement_muted_id=muted_id if enabled else "",
        )
        try:
            if self.settings_repository is not None:
                self.settings_repository.save(updated)
        except Exception as error:
            self.context.logger.exception("Unable to save announcement mute setting")
            self.announcement_mute_var.set(
                previous.announcement_mute_until_update
            )
            messagebox.showerror(
                "保存设置失败", str(error), parent=self.window
            )
            return
        self.user_settings = updated
        self._notify(
            "已开启：下次公告更新前不再显示"
            if enabled
            else "已关闭：下次仍会显示公告"
        )

    def _open_resource_repository(self) -> None:
        self._open_external_link(
            repository_home_url(self.user_settings.download_source)
        )

    def _on_download_source_selected(self, display_name: str) -> None:
        selected = "github" if display_name == "GitHub" else "gitlink"
        if selected == self.user_settings.download_source:
            return
        if self._content_work_is_active() or self.cartridge_loading:
            self.download_source_menu.set(
                provider_display_name(self.user_settings.download_source)
            )
            self._notify("请先结束当前下载/安装任务，再切换下载源", error=True)
            return
        previous = self.user_settings
        updated = replace(
            previous,
            download_concurrency=1,
            bandwidth_limit_kib=None,
            download_source=selected,
        )
        try:
            if self.settings_repository is not None:
                self.settings_repository.save(updated)
        except Exception as error:
            self.context.logger.exception("Unable to save download source")
            self.download_source_menu.set(
                provider_display_name(previous.download_source)
            )
            messagebox.showerror("保存设置失败", str(error), parent=self.window)
            return
        self.user_settings = updated
        self.download_source_generation += 1
        source_generation = self.download_source_generation
        self.game_selection_generation += 1
        self.context.updates.set_download_source(selected)
        self.cartridge_catalog.set_download_source(selected)
        self.announcement_service.set_download_source(selected)
        self.cartridges.clear()
        self.catalog_preview.configure(
            text=f"已切换到 {provider_display_name(selected)}，正在重新加载……"
        )
        self._notify(
            f"下载和程序更新源已切换为 {provider_display_name(selected)}"
        )

        def worker() -> None:
            try:
                self.cartridge_catalog.refresh_index(allow_network=True)
                loaded = self.cartridge_catalog.load_default_cartridge(
                    allow_network=True,
                )
                self._post_ui(
                    lambda loaded=loaded: self._on_download_source_ready(
                        loaded, selected, source_generation
                    )
                )
            except Exception as error:
                try:
                    self.cartridge_catalog.refresh_index(allow_network=False)
                    loaded = self.cartridge_catalog.load_default_cartridge(
                        allow_network=False,
                    )
                    message = str(error)

                    def finish(loaded=loaded, message=message) -> None:
                        if not self._on_download_source_ready(
                            loaded, selected, source_generation
                        ):
                            return
                        self._notify(
                            f"远程主表不可用，已使用本地缓存（{message}）",
                            error=True,
                        )

                    self._post_ui(finish)
                except Exception as fatal:
                    message = str(fatal) or "切换下载源失败"
                    self._post_ui(
                        lambda message=message: messagebox.showerror(
                            "切换下载源失败", message, parent=self.window,
                        )
                    )

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_source_ready(
        self, loaded, source: str, source_generation: int,
    ) -> bool:
        if (
            source_generation != self.download_source_generation
            or source != self.user_settings.download_source
        ):
            return False
        if loaded.cartridge.adapter.descriptor.game_id != self.cartridge.adapter.descriptor.game_id:
            # The source refresh began for an earlier game.  A later user
            # selection is already loading its own cartridge; never restore
            # the old game's name or catalog over that newer selection.
            return True
        self._activate_loaded_cartridge(loaded, rebuild_services=True)
        self._sync_game_selector_values()
        self._set_game_selector_text(self.selected_game_name)
        self.platform_status.configure(
            text=(
                f"{self.cartridge.platform_name} · App "
                f"{self.cartridge.store_app_id}"
            )
        )
        self._scan_games()
        self._refresh_catalog()
        return True

    def _run_speed_test(self) -> None:
        if self.speed_test_running:
            return
        self.speed_test_running = True
        self.speed_test_button.configure(state="disabled", text="正在测速……")
        provider = provider_display_name(self.user_settings.download_source)
        self.speed_test_status.configure(text=f"正在从 {provider} 下载测速文件……")
        url = speed_test_url(self.user_settings.download_source)

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
        self.speed_test_button.configure(state="normal", text="重新测速")
        self.speed_test_status.configure(
            text=(
                f"测速结果：{_format_speed(result.mebibytes_per_second * 1048576)} · "
                f"{result.megabits_per_second:.1f} Mbps · "
                f"{_format_size(result.bytes_downloaded)}"
            )
        )

    def _finish_speed_test_error(self, message: str) -> None:
        self.speed_test_running = False
        self.speed_test_button.configure(state="normal", text="重新测速")
        self.speed_test_status.configure(text="测速失败")
        messagebox.showerror("测速失败", message, parent=self.window)

    def _refresh_announcement(self) -> None:
        """Fetch the remote notice in the background, then show it when needed."""

        def worker() -> None:
            announcement = None
            try:
                announcement = self.announcement_service.refresh(allow_network=True)
            except Exception as error:
                self.context.logger.warning(
                    "Remote announcement unavailable: %s", error
                )
                try:
                    announcement = self.announcement_service.refresh(
                        allow_network=False
                    )
                except Exception:
                    self.context.logger.exception(
                        "Unable to load cached or bootstrap announcement"
                    )
                    return
            self._post_ui(
                lambda announcement=announcement: self._finish_announcement_refresh(
                    announcement
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_announcement_refresh(self, announcement: Announcement) -> None:
        self.current_announcement = announcement
        if not self.announcement_service.should_display(
            announcement,
            mute_until_update=self.user_settings.announcement_mute_until_update,
            muted_id=self.user_settings.announcement_muted_id,
        ):
            return
        self._show_announcement_dialog(announcement)

    def _show_announcement_dialog(self, announcement: Announcement) -> None:
        existing = self.announcement_dialog
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    return
            except TclError:
                pass
            self.announcement_dialog = None

        dialog = ctk.CTkToplevel(self.window)
        self.announcement_dialog = dialog
        dialog.title(announcement.title or "公告")
        dialog.geometry("560x420")
        dialog.minsize(480, 360)
        dialog.configure(fg_color=UI["page"])
        dialog.transient(self.window)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_announcement_dialog())

        shell = ctk.CTkFrame(dialog, fg_color=UI["page"])
        shell.pack(fill="both", expand=True, padx=18, pady=18)
        ctk.CTkLabel(
            shell,
            text=announcement.title,
            text_color=UI["primary"],
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 10))
        body = ctk.CTkTextbox(
            shell,
            wrap="word",
            fg_color=UI["card"],
            border_width=1,
            border_color=UI["border"],
            text_color=UI["text_secondary"],
            corner_radius=10,
        )
        body.pack(fill="both", expand=True)
        body.insert("1.0", announcement.body)
        body.configure(state="disabled")

        actions = ctk.CTkFrame(shell, fg_color="transparent")
        actions.pack(fill="x", pady=(14, 0))
        ctk.CTkButton(
            actions,
            text="下次公告更新前不再显示",
            width=200,
            command=lambda: self._mute_and_close_announcement(announcement),
        ).pack(side="left")
        ctk.CTkButton(
            actions,
            text="关闭公告",
            width=110,
            command=self._close_announcement_dialog,
        ).pack(side="right")

        main_left, main_top = self.main_window_origin
        self._center_on_desktop(
            dialog,
            parent_bounds=(main_left, main_top, 1120, 840),
            width=560,
            height=420,
        )
        dialog.after(50, dialog.lift)
        dialog.after(80, dialog.focus_force)

    def _mute_and_close_announcement(self, announcement: Announcement) -> None:
        previous = self.user_settings
        updated = replace(
            previous,
            download_concurrency=1,
            bandwidth_limit_kib=None,
            announcement_mute_until_update=True,
            announcement_muted_id=announcement.announcement_id,
        )
        try:
            if self.settings_repository is not None:
                self.settings_repository.save(updated)
        except Exception as error:
            self.context.logger.exception("Unable to mute announcement")
            messagebox.showerror("保存设置失败", str(error), parent=self.window)
            return
        self.user_settings = updated
        if hasattr(self, "announcement_mute_var"):
            self.announcement_mute_var.set(True)
        self._close_announcement_dialog()
        self._notify("已开启：下次公告更新前不再显示")

    def _close_announcement_dialog(self) -> None:
        dialog = self.announcement_dialog
        self.announcement_dialog = None
        if dialog is None:
            return
        try:
            dialog.grab_release()
        except TclError:
            pass
        try:
            dialog.destroy()
        except TclError:
            pass

    def _notify(self, message: str, *, error: bool = False) -> None:
        self.notice_serial += 1
        serial = self.notice_serial
        snackbar = getattr(self, "snackbar", None)
        if snackbar is None:
            # Fallback before the UI is fully built.
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
            return
        icon = "\u26a0\ufe0f " if error else "\u2705 "
        rendered_message = f"{icon}{message}"
        # A fixed relative width made long game titles extend beyond the
        # snackbar and get clipped.  Keep short notices compact, expand for
        # longer text, then wrap once the window-safe maximum is reached.
        display_units = sum(2 if ord(character) > 0xFF else 1 for character in rendered_message)
        default_width = 460
        desired_width = max(default_width, 64 + display_units * 8)
        window_width = self.window.winfo_width()
        if window_width <= 1:
            window_width = self.window.winfo_reqwidth()
        available_width = max(360, window_width - 48)
        snackbar_width = min(desired_width, available_width)
        usable_units = max(1, (snackbar_width - 48) // 8)
        line_count = max(1, -(-display_units // usable_units))
        snackbar_height = 44 + (line_count - 1) * 22
        snackbar.configure(
            fg_color=UI["danger"] if error else UI["success"],
            width=snackbar_width,
            height=snackbar_height,
        )
        self.snackbar_label.configure(
            text=rendered_message,
            wraplength=max(300, snackbar_width - 48),
        )
        snackbar.place(relx=1.0, rely=0.16, anchor="ne")
        snackbar.lift()
        if error:
            self.window.bell()
        self.window.after(
            6000 if error else 4000,
            lambda serial=serial: (
                snackbar.place_forget()
                if serial == self.notice_serial else None
            ),
        )

    def _post_ui(self, callback) -> None:
        """Queue a UI callback without touching Tk from a worker thread."""
        if self.ui_event_pump_running:
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
        update_task_count = int(self.update_download_active)
        speed += self.update_download_speed if self.update_download_active else 0
        cache_text = (
            f"{_format_size(self.cache_usage_bytes)}"
            if self.cache_usage_bytes is not None
            else "统计中"
        )
        self.global_status.configure(text=(
            f"网络：{'已连接' if self.catalog_online else '未连接'}\n"
            f"任务：{len(active) + update_task_count} · {_format_speed(speed)}\n"
            f"缓存：{cache_text}"
        ))
        self._schedule_cache_usage_scan()
        self.window.after(2000, self._update_global_status)

    def _schedule_cache_usage_scan(self, *, force: bool = False) -> None:
        """Refresh cache usage off the Tk thread and never overlap scans."""
        if self.cache_usage_scan_running:
            return
        now = time.monotonic()
        if not force and now - self.cache_usage_last_scan < 30:
            return
        self.cache_usage_scan_running = True

        def worker() -> None:
            try:
                usage = self.cache_maintenance.usage_bytes()
                snapshots = (
                    self.download_queue.snapshots()
                    if self.download_queue is not None else ()
                )
                game_id = self.cartridge.adapter.descriptor.game_id
                game_usage = self.cache_maintenance.game_usage(game_id, snapshots)
            except Exception:
                self.context.logger.exception("Unable to calculate cache usage")
                usage = None
                game_usage = None
            self._post_ui(
                lambda usage=usage, game_usage=game_usage:
                self._finish_cache_usage_scan(usage, game_usage)
            )

        threading.Thread(
            target=worker, daemon=True, name="cache-usage-scan"
        ).start()

    def _finish_cache_usage_scan(self, usage: int | None, game_usage=None) -> None:
        self.cache_usage_scan_running = False
        self.cache_usage_last_scan = time.monotonic()
        if usage is not None:
            self.cache_usage_bytes = usage
        self._render_cache_storage_overview(usage, game_usage)

    def _render_cache_storage_overview(self, usage: int | None, game_usage=None) -> None:
        """Render the settings cache summary without doing file work on the UI thread."""
        if not hasattr(self, "cache_status"):
            return
        if usage is None:
            self.cache_status.configure(text="缓存空间暂时无法统计")
            self.cache_breakdown.configure(text="当前游戏 未知  ·  其他游戏 未知")
            self.cache_usage_bar.set(0)
            return

        game_bytes = 0
        game_files = 0
        if game_usage is not None:
            game_bytes = max(0, min(int(game_usage.bytes_used), usage))
            game_files = int(game_usage.file_count)
        other_bytes = max(0, usage - game_bytes)
        self.cache_status.configure(text=f"已使用 {_format_size(usage)}")
        if game_usage is None:
            self.cache_breakdown.configure(text="当前游戏 正在统计  ·  其他游戏 正在统计")
            self.cache_usage_bar.set(0)
            return
        game_name = self.cartridge.adapter.descriptor.display_name
        self.cache_breakdown.configure(
            text=(
                f"当前游戏（{game_name}） {_format_size(game_bytes)}"
                f"（{game_files} 个文件）  ·  其他游戏 {_format_size(other_bytes)}"
            )
        )
        self.cache_usage_bar.set(game_bytes / usage if usage else 0)

    def _open_path(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            open_directory(path)
        except Exception as error:
            messagebox.showerror("无法打开目录", str(error), parent=self.window)

    def _refresh_log_preview(self) -> None:
        path = self.context.paths.data / "logs" / "launcher.log"
        try:
            if path.is_file():
                lines = read_tail_lines(path, max_lines=500)
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
        if content == self.last_log_content:
            return
        self.last_log_content = content
        self.log_preview.configure(state="normal")
        self.log_preview.delete("1.0", "end")
        self.log_preview.insert("1.0", content)
        self.log_preview.see("end")
        self.log_preview.configure(state="disabled")

    def _schedule_log_refresh(self, _event=None) -> None:
        """Debounce searches so rapid typing never rebuilds the textbox."""
        try:
            if self.log_search_after_id is not None:
                self.window.after_cancel(self.log_search_after_id)
            self.log_search_after_id = self.window.after(
                160, self._apply_scheduled_log_refresh
            )
        except TclError:
            self.log_search_after_id = None

    def _apply_scheduled_log_refresh(self) -> None:
        self.log_search_after_id = None
        self._refresh_log_preview()

    def _copy_log(self) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(self.last_log_content)
        self.window.update_idletasks()

    def _export_diagnostics(self) -> None:
        if self.diagnostics_export_running:
            return
        self.diagnostics_export_running = True
        self.diagnostics_export_button.configure(
            state="disabled", text="正在导出……"
        )
        snapshots = (
            self.download_queue.snapshots()
            if self.download_queue is not None else ()
        )
        settings = self.user_settings

        def worker() -> None:
            try:
                output = self.diagnostic_exporter.export(
                    app_version=self.context.app_version,
                    launcher_version=self.context.launcher_version,
                    settings=settings,
                    snapshots=snapshots,
                    log_path=self.context.paths.data / "logs" / "launcher.log",
                    problems=self.problem_store.list_reports(),
                )
                self._post_ui(
                    lambda output=output: self._finish_diagnostic_export(output)
                )
            except Exception as error:
                self.context.logger.exception("Diagnostic export failed")
                message = str(error)
                self._post_ui(
                    lambda message=message: self._finish_diagnostic_export_error(
                        message
                    )
                )

        threading.Thread(
            target=worker, daemon=True, name="diagnostic-export"
        ).start()

    def _finish_diagnostic_export(self, output: Path) -> None:
        self.diagnostics_export_running = False
        self.diagnostics_export_button.configure(
            state="normal", text="导出诊断包"
        )
        if messagebox.askyesno(
            "诊断包已导出",
            f"已生成：{output.name}\n\n是否打开所在目录？",
            parent=self.window,
        ):
            self._open_path(output.parent)

    def _finish_diagnostic_export_error(self, message: str) -> None:
        self.diagnostics_export_running = False
        self.diagnostics_export_button.configure(
            state="normal", text="导出诊断包"
        )
        messagebox.showerror("诊断导出失败", message, parent=self.window)

    def _problem_detail_text(self, report: ProblemReport) -> str:
        status = "未解决" if report.status is ProblemStatus.OPEN else "已解决"
        lines = [
            f"{report.summary}",
            "",
            f"错误码：{report.code.value}",
            f"事件 ID：{report.event_id}",
            f"状态：{status}",
            f"严重程度：{report.severity.value}",
            f"阶段：{report.stage or '-'}",
            f"首次发生：{report.occurred_at}",
            f"最近发生：{report.last_occurred_at}",
            f"重试次数：{report.retry_count}",
        ]
        if report.task_id:
            lines.append(f"任务 ID：{report.task_id}")
        if report.filename:
            lines.append(f"文件：{report.filename}")
        if report.expected_sha256:
            lines.append(f"预期 SHA-256：{report.expected_sha256}")
        if report.actual_sha256:
            lines.append(f"实际 SHA-256：{report.actual_sha256}")
        lines.extend(("", "建议：", report.suggestion or "请导出诊断信息后反馈。"))
        if report.technical_details:
            lines.extend(("", "技术详情：", report.technical_details))
        return "\n".join(lines)

    def _record_problem(self, report: ProblemReport) -> ProblemReport:
        try:
            stored = self.problem_store.record(report)
        except Exception:
            self.context.logger.exception("Unable to persist problem report")
            return report
        self._update_problem_badge()
        if getattr(self, "current_page", None) == "问题记录":
            self._refresh_problem_center(select_event_id=stored.event_id)
        return stored

    def _update_problem_badge(self) -> None:
        button = getattr(self, "navigation_buttons", {}).get("报错指南")
        if button is None:
            return
        try:
            count = self.problem_store.unresolved_count()
        except Exception:
            self.context.logger.exception("Unable to count unresolved problems")
            count = 0
        button.configure(text=f"报错指南 ({count})" if count else "报错指南")

    def _refresh_problem_center(self, select_event_id: str | None = None) -> None:
        if not hasattr(self, "problem_list"):
            return
        try:
            reports = self.problem_store.list_reports()
        except Exception as error:
            self.context.logger.exception("Unable to load problem reports")
            reports = []
            self._notify(f"问题记录读取失败：{error}", error=True)
        self.problem_rows = reports
        for child in self.problem_list.winfo_children():
            child.destroy()
        if not reports:
            ctk.CTkLabel(
                self.problem_list, text="当前没有问题记录", text_color=UI["muted"]
            ).pack(anchor="w", padx=12, pady=12)
            self.selected_problem_event_id = None
            self._set_problem_detail(None)
            self._update_problem_badge()
            return
        for report in reports:
            status = "未解决" if report.status is ProblemStatus.OPEN else "已解决"
            selected = report.event_id == (select_event_id or self.selected_problem_event_id)
            row = ctk.CTkFrame(
                self.problem_list,
                fg_color=UI["primary_surface"] if selected else UI["card"],
                border_color=UI["primary_border"] if selected else UI["border"],
                border_width=1, corner_radius=8,
            )
            row.pack(fill="x", padx=8, pady=(8, 0))
            tag_color = UI["danger"] if report.status is ProblemStatus.OPEN else UI["success"]
            tag = ctk.CTkLabel(
                row, text=status, text_color=tag_color, fg_color=("#FDECEC" if report.status is ProblemStatus.OPEN else "#E7F5EC"),
                corner_radius=5, font=ctk.CTkFont(size=11, weight="bold"),
            )
            tag.pack(anchor="w", padx=12, pady=(10, 4))
            title = ctk.CTkLabel(
                row, text=report.summary, text_color=UI["text"], anchor="w",
                font=ctk.CTkFont(size=14, weight="bold"), wraplength=320,
            )
            title.pack(fill="x", padx=12)
            timestamp = ctk.CTkLabel(
                row, text=report.last_occurred_at.replace("T", " ")[:16],
                text_color=UI["muted"], anchor="w", font=ctk.CTkFont(size=11),
            )
            timestamp.pack(fill="x", padx=12, pady=(4, 10))
            def callback(_event, event_id=report.event_id) -> None:
                self._select_problem_from_card(event_id)

            for widget in (row, tag, title, timestamp):
                widget.bind("<Button-1>", callback)
        self._update_problem_badge()

    def _show_problem_list(self) -> None:
        """Return from a record detail page to the parent record list."""
        if not hasattr(self, "problem_list_panel"):
            return
        self.problem_detail_page.pack_forget()
        self.problem_list_panel.pack(fill="both", expand=True)

    def _solution_id_for_problem_code(self, code: ProblemCode) -> str:
        if code is ProblemCode.NET_TLS:
            return "ssl"
        elif code in {
            ProblemCode.NET_TIMEOUT, ProblemCode.NET_DNS, ProblemCode.NET_HTTP,
            ProblemCode.NET_CONNECTION,
        }:
            return "download"
        elif code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED:
            return "security"
        elif code.value.startswith(("PATCH-", "PKG-", "FS-")):
            return "patch"
        return "update"

    def _open_problem_solution(self, report: ProblemReport) -> None:
        self._open_solution_article(self._solution_id_for_problem_code(report.code))

    def _set_problem_detail(self, report: ProblemReport | None) -> None:
        for child in self.problem_detail_content.winfo_children():
            child.destroy()
        if report is None:
            ctk.CTkLabel(
                self.problem_detail_content, text="选择一条问题记录查看详情",
                text_color=UI["muted"],
            ).pack(anchor="w", padx=4, pady=16)
            self._render_problem_actions(None)
            return
        status = "未解决" if report.status is ProblemStatus.OPEN else "已解决"
        severity_labels = {"info": "提示", "warning": "警告", "error": "严重", "critical": "紧急"}
        severity = severity_labels.get(report.severity.value, report.severity.value)
        header = ctk.CTkFrame(self.problem_detail_content, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=(12, 10))
        ctk.CTkLabel(
            header, text=report.summary, text_color=UI["text"], anchor="w",
            font=ctk.CTkFont(size=20, weight="bold"), wraplength=600,
        ).pack(anchor="w")
        meta = ctk.CTkFrame(header, fg_color="transparent")
        meta.pack(fill="x", pady=(8, 0))
        for text, color, background in (
            (severity, UI["danger"] if report.severity.value in {"error", "critical"} else UI["primary"], "#FDECEC" if report.severity.value in {"error", "critical"} else UI["primary_surface"]),
            (status, UI["danger"] if report.status is ProblemStatus.OPEN else UI["success"], "#FDECEC" if report.status is ProblemStatus.OPEN else "#E7F5EC"),
            (report.code.value, UI["text_secondary"], UI["panel"]),
        ):
            ctk.CTkLabel(meta, text=text, text_color=color, fg_color=background, corner_radius=5,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        info = ctk.CTkFrame(self.problem_detail_content, fg_color=UI["panel"], corner_radius=8)
        info.pack(fill="x", padx=4, pady=(0, 12))
        ctk.CTkLabel(info, text="基础信息", text_color=UI["text"], anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 8))
        fields = (("发生时间", report.last_occurred_at), ("事件 ID", report.event_id), ("阶段", report.stage), ("平台", report.platform or "-"), ("程序版本", report.app_version or "-"), ("重复次数", str(report.retry_count)))
        for index, (label, value) in enumerate(fields):
            row, column = divmod(index, 2)
            ctk.CTkLabel(info, text=f"{label}\n{value}", text_color=UI["text_secondary"], anchor="w",
                         justify="left", font=ctk.CTkFont(size=12)).grid(row=row + 1, column=column, sticky="w", padx=14, pady=5)
        suggestion = ctk.CTkFrame(self.problem_detail_content, fg_color=UI["primary_surface"], corner_radius=8)
        suggestion.pack(fill="x", padx=4, pady=(0, 12))
        ctk.CTkLabel(suggestion, text="处理建议", text_color=UI["primary"], anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkButton(suggestion, text="查看对应解决方案  →", width=156,
                      command=lambda report=report: self._open_problem_solution(report)).pack(anchor="w", padx=14, pady=(0, 12))
        technical_header = ctk.CTkFrame(self.problem_detail_content, fg_color="transparent")
        technical_header.pack(fill="x", padx=4, pady=(0, 4))
        ctk.CTkLabel(technical_header, text="技术详情 / Traceback", text_color=UI["text"], anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(technical_header, text="复制", width=64, height=28, fg_color=UI["panel"], hover_color=UI["border"], text_color=UI["text_secondary"],
                      command=lambda: self._copy_problem_text(report.technical_details or self._problem_detail_text(report))).pack(side="right")
        technical = ctk.CTkTextbox(self.problem_detail_content, height=180, wrap="word", fg_color="#F3F4F6", text_color=UI["text_secondary"], border_width=0, corner_radius=8,
                                  font=ctk.CTkFont(family="Consolas", size=12))
        technical.pack(fill="x", padx=4, pady=(0, 12))
        technical.insert("1.0", report.technical_details or "未记录技术详情")
        technical.configure(state="disabled")
        self._render_problem_actions(report)

    def _select_problem(self, event_id: str, *, refresh_list: bool = True) -> None:
        report = self.problem_store.get(event_id)
        if report is None:
            self.selected_problem_event_id = None
            self._set_problem_detail(None)
            return
        self.selected_problem_event_id = report.event_id
        # Build and lay out the hidden detail view before removing the list.
        # Rebuilding the list first made the intermediate empty state visible.
        self._set_problem_detail(report)
        self.problem_detail_page.update_idletasks()
        self.problem_list_panel.pack_forget()
        self.problem_detail_page.pack(fill="both", expand=True)
        self.problem_detail_page.update_idletasks()
        if refresh_list:
            self.window.after_idle(
                lambda event_id=report.event_id: self._refresh_problem_center(
                    select_event_id=event_id
                )
            )

    def _select_problem_from_card(self, event_id: str) -> str:
        """Select one record and prevent nested card bindings from firing twice."""
        self._select_problem(event_id, refresh_list=False)
        return "break"

    def _render_problem_actions(self, report: ProblemReport | None) -> None:
        for child in self.problem_actions.winfo_children():
            child.destroy()
        if report is None:
            return
        labels = {
            ProblemAction.COPY_DETAILS: "复制详情",
            ProblemAction.COPY_HASH_INFO: "复制哈希",
            ProblemAction.OPEN_LOG_DIRECTORY: "打开日志目录",
            ProblemAction.OPEN_CACHE_DIRECTORY: "打开缓存目录",
            ProblemAction.EXPORT_DIAGNOSTICS: "导出诊断",
            ProblemAction.RETRY_TASK: "安全重试",
            ProblemAction.MARK_RESOLVED: "标记已解决",
            ProblemAction.DELETE: "删除",
            ProblemAction.OPEN_WINDOWS_SECURITY: "打开 Windows 安全中心",
            ProblemAction.OPEN_MICROSOFT_FALSE_POSITIVE: "提交误报",
        }
        for action in report.allowed_actions:
            if (
                action is ProblemAction.OPEN_WINDOWS_SECURITY
                and self.context.paths.platform != "windows"
            ):
                continue
            ctk.CTkButton(
                self.problem_actions,
                text=labels[action],
                width=116,
                command=lambda action=action, report=report: (
                    self._execute_problem_action(report, action)
                ),
            ).pack(side="left", padx=(0, 6), pady=3)

    def _copy_problem_text(self, text: str) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()
        self._notify("已复制问题信息")

    def _retry_problem_task(self, report: ProblemReport) -> None:
        if self.download_queue is None or not report.task_id:
            raise ValueError("该问题没有可重试的下载任务")
        snapshot = next(
            (item for item in self.download_queue.snapshots()
             if item.spec.task_id == report.task_id),
            None,
        )
        if snapshot is None:
            raise ValueError("下载任务记录不存在，请刷新目录后重试")
        if snapshot.state in {DownloadState.PAUSED, DownloadState.FAILED}:
            future = self.download_queue.resume(report.task_id)
        elif snapshot.state is DownloadState.CORRUPT:
            self.download_queue.forget((report.task_id,), delete_cached_packages=True)
            future = self.download_queue.enqueue(snapshot.spec)
        elif (
            snapshot.state is DownloadState.READY
            and (snapshot.result_path is None or not snapshot.result_path.is_file())
        ):
            self.download_queue.forget((report.task_id,))
            future = self.download_queue.enqueue(snapshot.spec)
        else:
            raise ValueError(f"任务当前状态不可重试：{snapshot.state.value}")
        future.add_done_callback(self._download_finished)
        self._notify(f"已重新开始下载：{snapshot.spec.filename}")

    def _execute_problem_action(
        self, report: ProblemReport, action: ProblemAction | str
    ) -> None:
        try:
            normalized = ProblemAction(action)
        except ValueError:
            self.context.logger.warning("Rejected unknown problem action: %r", action)
            return
        if normalized not in report.allowed_actions:
            self.context.logger.warning(
                "Rejected non-allowlisted problem action: %s event=%s",
                normalized.value, report.event_id,
            )
            return
        if (
            normalized is ProblemAction.OPEN_WINDOWS_SECURITY
            and self.context.paths.platform != "windows"
        ):
            return
        try:
            if normalized is ProblemAction.COPY_DETAILS:
                self._copy_problem_text(self._problem_detail_text(report))
            elif normalized is ProblemAction.COPY_HASH_INFO:
                self._copy_problem_text(
                    f"文件：{report.filename or '-'}\n"
                    f"预期 SHA-256：{report.expected_sha256 or '-'}\n"
                    f"实际 SHA-256：{report.actual_sha256 or '-'}"
                )
            elif normalized is ProblemAction.OPEN_LOG_DIRECTORY:
                self._open_path(self.context.paths.data / "logs")
            elif normalized is ProblemAction.OPEN_CACHE_DIRECTORY:
                self._open_path(self.context.paths.cache)
            elif normalized is ProblemAction.EXPORT_DIAGNOSTICS:
                self._export_diagnostics()
            elif normalized is ProblemAction.RETRY_TASK:
                self._retry_problem_task(report)
            elif normalized is ProblemAction.MARK_RESOLVED:
                self.problem_store.mark_resolved(report.event_id)
                self._show_problem_list()
                self._refresh_problem_center()
            elif normalized is ProblemAction.DELETE:
                self.problem_store.delete(report.event_id)
                self._show_problem_list()
                self._refresh_problem_center()
            elif normalized is ProblemAction.OPEN_WINDOWS_SECURITY:
                if not webbrowser.open(WINDOWS_SECURITY_URI):
                    raise RuntimeError("系统未接受 Windows 安全中心链接")
            elif normalized is ProblemAction.OPEN_MICROSOFT_FALSE_POSITIVE:
                if not webbrowser.open(MICROSOFT_FALSE_POSITIVE_URL):
                    raise RuntimeError("浏览器未接受 Microsoft 误报提交页面")
        except Exception as error:
            self.context.logger.exception(
                "Problem action failed: action=%s event=%s",
                normalized.value, report.event_id,
            )
            fallback = (
                "请手动打开“Windows 安全中心 → 病毒和威胁防护 → 保护历史记录”核对该文件。"
                if normalized is ProblemAction.OPEN_WINDOWS_SECURITY
                else str(error)
            )
            messagebox.showwarning("操作未完成", fallback, parent=self.window)

    def _clear_problems(self) -> None:
        if not messagebox.askyesno(
            "清空问题记录",
            "确定清空全部问题记录吗？此操作不会删除日志、缓存或下载文件。",
            parent=self.window,
        ):
            return
        try:
            self.problem_store.clear()
        except Exception as error:
            self.context.logger.exception("Unable to clear problem reports")
            messagebox.showerror("清空失败", str(error), parent=self.window)
            return
        self.selected_problem_event_id = None
        self._show_problem_list()
        self._refresh_problem_center()

    def _freshness_status_text(self, *, catalog_count: int | None = None) -> str:
        freshness = getattr(self.cartridge, "freshness", None)
        if freshness is None:
            return "资源提交时间：卡带未附带时间戳"
        summary = freshness.client_summary()
        if catalog_count is not None and freshness.package_count:
            if catalog_count != freshness.package_count:
                summary += (
                    f" · 当前目录 {catalog_count} 项"
                    f"（记录时收录 {freshness.package_count}）"
                )
        return summary

    def _refresh_catalog_freshness_label(self, *, catalog_count: int | None = None) -> None:
        if not hasattr(self, "catalog_freshness"):
            return
        text = self._freshness_status_text(catalog_count=catalog_count)
        if hasattr(self, "catalog_preview"):
            self.catalog_preview.set_freshness_text(text)
        else:
            self.catalog_freshness.configure(text=text, text_color=UI["muted"])

    def _refresh_catalog_capacity_summary(self) -> None:
        """Show known catalog and selected-DLC capacity beside the item count."""
        if self._uses_built_in_dlc_delivery():
            patch_suffix = "补丁资源已就绪" if self.patch_bundle is not None else "缺少补丁资源"
            self.catalog_status.configure(
                text=(
                    f"{self.cartridge.adapter.descriptor.display_name} · DLC 已随游戏本体安装"
                    f" · 无需下载 · {patch_suffix}"
                )
            )
            return
        entries = self.catalog_entries
        if not entries:
            return
        total_bytes = sum(
            entry.asset.size_bytes for entry in entries
            if entry.asset.size_bytes is not None
        )
        known_total_count = sum(
            entry.asset.size_bytes is not None for entry in entries
        )
        selected_entries = [
            entry for entry in entries if entry.dlc_id in self.selected_dlc_ids
        ]
        selected_bytes = sum(
            entry.asset.size_bytes for entry in selected_entries
            if entry.asset.size_bytes is not None
        )
        known_selected_count = sum(
            entry.asset.size_bytes is not None for entry in selected_entries
        )
        total_text = (
            _format_size(total_bytes) if known_total_count else "未知"
        )
        selected_text = (
            "0B" if not selected_entries
            else _format_size(selected_bytes) if known_selected_count else "未知"
        )
        patch_suffix = "" if self.patch_bundle is not None else "（缺少补丁资源）"
        self.catalog_status.configure(
            text=(
                f"{self.cartridge.adapter.descriptor.display_name} · "
                f"已读取 {len(entries)} 个 DLC 资源{patch_suffix} · "
                f"总容量（已知）：{total_text} · "
                f"当前选中 {len(selected_entries)} 项（{selected_text}）"
            )
        )

    def _uses_built_in_dlc_delivery(self) -> bool:
        """Whether this cartridge activates base-game DLC payloads by patch only."""
        return getattr(self.cartridge, "dlc_delivery_mode", "download_packages") == "built_in"

    @staticmethod
    def _built_in_dlc_message() -> str:
        return "DLC 已随游戏本体安装，无需额外下载；安装补丁后即可激活。"

    def _refresh_catalog(self) -> None:
        self.catalog_request_generation += 1
        request_generation = self.catalog_request_generation
        generation = self.game_selection_generation
        source = self.user_settings.download_source
        cartridge_id = self.cartridge.cartridge_id
        catalog = self.catalog
        self.catalog_refresh_button.configure(state="disabled")
        self.catalog_status.configure(
            text=(
                f"正在读取 {provider_display_name(self.user_settings.download_source)}"
                f" · {self.cartridge.release_tag} Release……"
            )
        )

        def worker() -> None:
            try:
                snapshot = catalog.refresh_snapshot()
                self._post_ui(
                    lambda snapshot=snapshot: self._show_catalog(
                        snapshot, generation=generation, cartridge_id=cartridge_id
                        , source=source, request_generation=request_generation
                    )
                )
            except Exception as error:
                self.context.logger.exception("DLC catalog refresh failed")
                message = str(error)
                self._post_ui(
                    lambda message=message: self._show_catalog_error(
                        message, generation=generation, cartridge_id=cartridge_id
                        , source=source, request_generation=request_generation
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_catalog(
        self, snapshot: CatalogSnapshot, *, generation: int | None = None,
        cartridge_id: str | None = None, source: str | None = None,
        request_generation: int | None = None,
    ) -> None:
        if generation is not None and generation != self.game_selection_generation:
            return
        if cartridge_id is not None and cartridge_id != self.cartridge.cartridge_id:
            return
        if source is not None and source != self.user_settings.download_source:
            return
        if request_generation is not None and request_generation != self.catalog_request_generation:
            return
        self.catalog_online = True
        entries = snapshot.entries
        self.catalog_entries = entries
        # Slug-based cartridges such as Civilization VI need the freshly
        # loaded catalog to map dlc001 IDs to native folders like Expansion1.
        # Scanning before assigning entries leaves them all looking absent on
        # the first refresh after switching games.
        self._refresh_installed_dlc_paths()
        self.patch_bundle = snapshot.patch_bundle
        self.patch_task_roles = (
            dict(self.cartridge.patch_task_roles(snapshot.patch_bundle))
            if snapshot.patch_bundle is not None
            else {}
        )
        self.catalog_missing_patch_assets = snapshot.missing_patch_assets
        if self._uses_built_in_dlc_delivery():
            self.selected_dlc_ids.clear()
            self.catalog_selection_initialized = True
            self.catalog_refresh_button.configure(state="normal")
            self._refresh_catalog_capacity_summary()
            self._refresh_catalog_freshness_label(catalog_count=0)
            self._clear_catalog_views(self._built_in_dlc_message())
            self.selection_toggle_button.configure(state="disabled", text="无需下载 DLC")
            self.advanced_view_button.configure(state="disabled")
            self._set_batch_download_state(self.batch_download_state)
            if snapshot.patch_bundle is None:
                self.catalog_patch_warning.configure(
                    text="补丁资源缺失，暂无法激活内置 DLC。"
                )
                self.catalog_preview.configure(text="请刷新目录后重试。")
            else:
                self.catalog_patch_warning.configure(text="")
                self.catalog_preview.configure(text=self._built_in_dlc_message())
            return
        # A refresh is a new user-facing selection session. Keep installed
        # entries disabled, and select every DLC that can currently be acted on.
        if entries:
            self.selected_dlc_ids = {
                entry.dlc_id for entry in entries
                if not self._is_entry_installed(entry)
            }
            self.catalog_selection_initialized = True
        self.catalog_refresh_button.configure(state="normal")
        self._refresh_catalog_capacity_summary()
        self._refresh_catalog_freshness_label(catalog_count=len(entries))
        if not entries:
            self.catalog_preview.configure(text="Release 中没有符合命名规则的 DLC ZIP")
            self._clear_catalog_views("当前 Release 中没有可用的 DLC 资源")
            self.selection_toggle_button.configure(state="disabled", text="全选 DLC")
            self.download_selected_button.configure(
                state="disabled", text="暂无可用 DLC"
            )
            return
        self.selection_toggle_button.configure(state="normal")
        self._set_batch_download_state(self.batch_download_state)
        if snapshot.patch_bundle is None:
            self.catalog_patch_warning.configure(
                text="补丁资源缺失，暂无法一键解锁。"
            )
            self.catalog_preview.configure(
                text="请刷新目录后重试。"
            )
        else:
            self.catalog_patch_warning.configure(text="")
            self.catalog_preview.configure(text="")
        self._render_catalog_rows()
        self._reconcile_catalog_cache()
        self._schedule_ready_installs()

    def _reconcile_catalog_cache(self) -> None:
        if (
            self.download_queue is None
            or not self.catalog_entries
            or self.cache_cleanup_running
        ):
            return
        # Filename-based package discovery is intentionally limited to DLC.
        # Patch files and AppInfo are versioned by Release attachment ID and
        # are reused only through their exact persisted task record.
        specs = tuple(
            self._download_spec_for_entry(entry) for entry in self.catalog_entries
        )

        generation = self.game_selection_generation
        cartridge = self.cartridge
        cartridge_id = cartridge.cartridge_id
        patch_task_roles = dict(self.patch_task_roles)
        request_key = (generation, cartridge_id, specs)

        def verifier_for(spec: DownloadSpec):
            return self._package_verifier_for_context(
                spec, cartridge=cartridge, patch_task_roles=patch_task_roles,
            )

        request = (
            request_key, generation, cartridge_id, specs, verifier_for,
        )
        with self.cache_reconcile_lock:
            if self.cache_reconcile_running:
                # Identical refreshes are satisfied by the active scan.  A
                # newer game/catalog replaces the pending request, keeping at
                # most one full-cache scan active and one waiting behind it.
                if self.cache_reconcile_active_key != request_key:
                    self.cache_reconcile_pending = request
                else:
                    # A -> B -> A means A is once again the newest desired
                    # result.  Do not run the now-stale B request afterwards.
                    self.cache_reconcile_pending = None
                return
            self.cache_reconcile_running = True
            self.cache_reconcile_active_key = request_key
        self._start_cache_reconcile(request)

    def _start_cache_reconcile(self, request) -> None:
        (
            _request_key, generation, cartridge_id, specs, verifier_for,
        ) = request
        queue = self.download_queue

        def worker() -> None:
            recovered_count = 0
            try:
                if queue is not None:
                    recovered = list(queue.reconcile_cached(
                        specs, verifier_for=verifier_for,
                    ))
                    recovered.extend(queue.reconcile_quarantined(
                        specs, verifier_for=verifier_for,
                    ))
                    recovered_count = len(recovered)
            except Exception:
                self.context.logger.exception("Unable to reconcile cached packages")
            finally:
                self._post_ui(lambda: self._finish_cache_reconcile(
                    request,
                    recovered_count,
                    generation=generation,
                    cartridge_id=cartridge_id,
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_cache_reconcile(
        self,
        request,
        count: int,
        *,
        generation: int,
        cartridge_id: str,
    ) -> None:
        if (
            count
            and generation == self.game_selection_generation
            and cartridge_id == self.cartridge.cartridge_id
        ):
            self._on_cache_reconciled(
                count, generation=generation, cartridge_id=cartridge_id,
            )

        next_request = None
        with self.cache_reconcile_lock:
            if self.cache_reconcile_active_key == request[0]:
                next_request = self.cache_reconcile_pending
                self.cache_reconcile_pending = None
                if next_request is None:
                    self.cache_reconcile_running = False
                    self.cache_reconcile_active_key = None
                else:
                    self.cache_reconcile_active_key = next_request[0]
        if next_request is not None:
            self._start_cache_reconcile(next_request)

    def _on_cache_reconciled(
        self,
        count: int,
        *,
        generation: int | None = None,
        cartridge_id: str | None = None, source: str | None = None,
        request_generation: int | None = None,
    ) -> None:
        if generation is not None and generation != self.game_selection_generation:
            return
        if cartridge_id is not None and cartridge_id != self.cartridge.cartridge_id:
            return
        if source is not None and source != self.user_settings.download_source:
            return
        if request_generation is not None and request_generation != self.catalog_request_generation:
            return
        self.catalog_preview.configure(text=f"已从缓存恢复 {count} 个已下载 DLC")
        self._schedule_ready_installs()

    def _show_catalog_error(
        self, message: str, *, generation: int | None = None,
        cartridge_id: str | None = None,
    ) -> None:
        if generation is not None and generation != self.game_selection_generation:
            return
        if cartridge_id is not None and cartridge_id != self.cartridge.cartridge_id:
            return
        self.catalog_online = False
        self.catalog_refresh_button.configure(state="normal")
        self.catalog_status.configure(text="DLC 目录读取失败")
        self.catalog_preview.configure(text=message)
        # Errors carrying a generation/cartridge pair come from a catalog
        # refresh.  The previous rows may belong to an older Release snapshot
        # (or even a different cartridge), so fail closed instead of leaving
        # stale callbacks available to the user.  Operation-level errors call
        # this helper without that context and must not discard a valid list.
        if generation is not None and cartridge_id is not None:
            self.catalog_entries = ()
            self.patch_bundle = None
            self.catalog_patch_warning.configure(text="")
            self.patch_task_roles = {}
            self.catalog_missing_patch_assets = ()
            self._clear_catalog_views("目录刷新失败，请重试")
            self.selection_toggle_button.configure(state="disabled", text="全选 DLC")
            self.download_selected_button.configure(
                state="disabled", text="目录不可用"
            )
        self._notify("DLC 目录刷新失败", error=True)

    def _schedule_catalog_search(self, _event=None) -> None:
        """Debounce expensive catalog filtering while the user is typing."""
        if self.catalog_search_after_id is not None:
            try:
                self.window.after_cancel(self.catalog_search_after_id)
            except TclError:
                return
        self.catalog_search_after_id = self.window.after(
            180, self._apply_catalog_search
        )

    def _apply_catalog_search(self) -> None:
        self.catalog_search_after_id = None
        self._render_catalog_rows()

    def _activate_catalog_view_storage(self, mode: str) -> None:
        """Point the legacy row aliases at one persistent catalog view."""
        state = self.catalog_view_widgets[mode]
        self.dlc_list_frame = self.catalog_view_frames[mode]
        self.catalog_rows = state["catalog_rows"]
        self.simple_status_labels = state["simple_status_labels"]
        self.catalog_selection_widgets = state["selection_widgets"]
        self.catalog_entry_frames = state["entry_frames"]
        self.catalog_name_labels = state["name_labels"]
        self.dlc_selection_vars = state["selection_vars"]

    def _clear_catalog_views(self, message: str) -> None:
        """Replace both persistent catalog canvases with one current empty state.

        Both views remain alive between toggles for performance.  Clearing only
        the visible view would therefore expose rows and callbacks belonging to
        the previously selected cartridge when the hidden view is opened.
        """
        self._cancel_catalog_render()
        for mode, frame in self.catalog_view_frames.items():
            for child in frame.winfo_children():
                child.destroy()
            state = self.catalog_view_widgets[mode]
            for key in (
                "catalog_rows",
                "simple_status_labels",
                "selection_widgets",
                "entry_frames",
                "name_labels",
                "selection_vars",
            ):
                state[key].clear()
            state["render_key"] = None
            ctk.CTkLabel(frame, text=message).grid(
                row=0, column=0, columnspan=8, padx=12, pady=24
            )
            self._schedule_scrollable_reset(frame)
        self._activate_catalog_view_storage(self.catalog_view_mode)

    def _catalog_render_key(self, visible_entries, snapshots) -> tuple:
        """Describe changes that require rebuilding the current widget tree."""
        entries = []
        for entry in visible_entries:
            snapshot = snapshots.get(self._dlc_task_id(entry.dlc_id))
            entries.append((
                entry.dlc_id,
                entry.display_name,
                entry.asset.asset_id,
                entry.asset.display_size,
                tuple(part.asset_id for part in entry.parts),
                self._is_entry_installed(entry),
                entry.dlc_id.casefold() in self.active_receipt_dlc_ids,
                snapshot.state.value if snapshot is not None else None,
            ))
        return (
            self.cartridge.cartridge_id,
            (
                str(self.current_installation.root)
                if self.current_installation is not None
                else None
            ),
            self.catalog_view_mode,
            self.simple_catalog_columns if self.catalog_view_mode == "simple" else 1,
            tuple(entries),
        )

    def _cancel_catalog_render(self) -> None:
        """Invalidate a pending incremental render before starting another one."""
        self.catalog_render_generation += 1
        callback_id = self.catalog_render_after_id
        self.catalog_render_after_id = None
        if callback_id is None:
            return
        try:
            self.window.after_cancel(callback_id)
        except TclError:
            return

    def _sync_cached_catalog_view(self, visible_entries, snapshots) -> None:
        """Refresh cheap progress/selection fields without rebuilding widgets."""
        active_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        for entry in visible_entries:
            installed = self._is_entry_installed(entry)
            variable = self.dlc_selection_vars.get(entry.dlc_id)
            if variable is not None:
                variable.set(entry.dlc_id in self.selected_dlc_ids and not installed)
            task_id = self._dlc_task_id(entry.dlc_id)
            snapshot = snapshots.get(task_id)
            status = self.simple_status_labels.get(task_id)
            if status is not None:
                text, color = self._simple_entry_status(entry, snapshot)
                status.configure(text=text, text_color=color)
            elif snapshot is not None and snapshot.state in active_states:
                # Active download progress changes without changing the render
                # key.  Advanced rows can update those labels in place.
                self._show_download_state(snapshot)
            if self.catalog_view_mode == "advanced":
                self._show_install_state(entry, snapshot)

    def _render_catalog_rows(self) -> None:
        self._cancel_catalog_render()
        self._activate_catalog_view_storage(self.catalog_view_mode)
        if self.catalog_view_mode == "advanced":
            self._refresh_active_receipt_dlc_ids()
        snapshots = {}
        if self.download_queue is not None:
            snapshots = {item.spec.task_id: item for item in self.download_queue.snapshots()}
        visible_entries = self._visible_catalog_entries(snapshots)
        valid_ids = {entry.dlc_id for entry in self.catalog_entries}
        self.selected_dlc_ids.intersection_update(valid_ids)
        render_key = self._catalog_render_key(visible_entries, snapshots)
        state = self.catalog_view_widgets[self.catalog_view_mode]
        if state["render_key"] == render_key:
            self._sync_cached_catalog_view(visible_entries, snapshots)
            self._show_catalog_view_frame(self.catalog_view_mode)
            self.advanced_view_button.configure(
                state="normal",
                text=(
                    "返回简洁视图"
                    if self.catalog_view_mode == "advanced"
                    else "切换高级视图"
                ),
            )
            self._update_selection_toggle_button(visible_entries)
            self._schedule_catalog_scroll_reset()
            return

        for child in self.dlc_list_frame.winfo_children():
            child.destroy()
        self.catalog_rows.clear()
        self.simple_status_labels.clear()
        self.catalog_selection_widgets.clear()
        self.catalog_entry_frames.clear()
        self.catalog_name_labels.clear()
        self.dlc_selection_vars.clear()
        state["render_key"] = None
        if not visible_entries:
            ctk.CTkLabel(
                self.dlc_list_frame, text="没有符合当前搜索和筛选条件的 DLC"
            ).grid(row=0, column=0, columnspan=3, padx=12, pady=24)
            state["render_key"] = render_key
            self.advanced_view_button.configure(
                state="normal",
                text=(
                    "返回简洁视图"
                    if self.catalog_view_mode == "advanced"
                    else "切换高级视图"
                ),
            )
            self._update_selection_toggle_button(visible_entries)
            self._schedule_catalog_scroll_reset()
            return

        generation = self.catalog_render_generation
        self.advanced_view_button.configure(state="disabled", text="正在准备视图…")
        self._render_catalog_batch(
            self.catalog_view_mode, visible_entries, snapshots,
            render_key, generation, 0,
        )

    def _render_catalog_batch(
        self, mode: str, visible_entries, snapshots,
        render_key: tuple, generation: int, start: int,
    ) -> None:
        """Build a few rows per UI tick so CustomTkinter never blocks Tk."""
        if generation != self.catalog_render_generation or mode != self.catalog_view_mode:
            return
        batch_size = 12 if mode == "simple" else 8
        end = min(start + batch_size, len(visible_entries))
        if mode == "simple":
            self._render_simple_catalog_rows(
                visible_entries, snapshots, start=start, end=end,
            )
        else:
            self._render_advanced_catalog_rows(
                visible_entries, snapshots, start=start, end=end,
            )
        if end >= len(visible_entries):
            self.catalog_render_after_id = None
            self.catalog_view_widgets[mode]["render_key"] = render_key
            self._show_catalog_view_frame(mode)
            self.advanced_view_button.configure(
                state="normal",
                text="返回简洁视图" if mode == "advanced" else "切换高级视图",
            )
            self._update_selection_toggle_button(visible_entries)
            self._schedule_catalog_scroll_reset()
            return
        try:
            self.catalog_render_after_id = self.window.after(
                1,
                lambda: self._render_catalog_batch(
                    mode, visible_entries, snapshots,
                    render_key, generation, end,
                ),
            )
        except TclError:
            self.catalog_render_after_id = None

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
            # A delayed callback may run while the window is closing.
            return

    def _schedule_scrollable_reset(self, frame) -> None:
        """Wait for geometry propagation before fixing the canvas viewport."""
        def after_layout() -> None:
            try:
                self.window.after(
                    20, lambda: self._reset_scrollable_frame(frame)
                )
            except TclError:
                return

        try:
            self.window.after_idle(after_layout)
        except TclError:
            return

    def _reset_catalog_scroll(self) -> None:
        """Recalculate the catalog canvas and move its viewport to the first row."""
        self._reset_scrollable_frame(self.dlc_list_frame)

    def _schedule_catalog_scroll_reset(self) -> None:
        if self.catalog_view_mode == "simple":
            self.advanced_view_button.configure(text="逐项管理 DLC")
        self._schedule_scrollable_reset(self.dlc_list_frame)

    def _show_catalog_view_frame(self, mode: str) -> None:
        """Swap persistent canvases without rebuilding the hidden view."""
        target = self.catalog_view_frames[mode]
        current = self.catalog_view_frames[self.displayed_catalog_view_mode]
        if current is not target:
            current.pack_forget()
            target.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.displayed_catalog_view_mode = mode
        self._activate_catalog_view_storage(mode)

    def _toggle_catalog_view(self) -> None:
        if self.catalog_render_after_id is not None:
            return
        if self.catalog_view_mode == "simple":
            self.catalog_view_mode = "advanced"
            self.advanced_view_button.configure(text="返回简洁视图")
            self.catalog_preview.configure(
                text="高级管理：可逐项下载、取消、检查和卸载"
            )
        else:
            self.catalog_view_mode = "simple"
            self.advanced_view_button.configure(text="切换高级视图")
            self.catalog_preview.configure(
                text="简洁视图：勾选需要的内容后可一键下载"
            )
        self._show_page("高级DLC视图" if self.catalog_view_mode == "advanced" else "DLC 库")
        self._render_catalog_rows()

    def _return_to_simple_catalog(self) -> None:
        self.catalog_view_mode = "simple"
        self._show_catalog_view_frame("simple")
        self._show_page("DLC 库")
        self._render_catalog_rows()

    def _render_simple_catalog_rows(
        self, visible_entries, snapshots, *, start: int = 0, end: int | None = None,
    ) -> None:
        columns = self.simple_catalog_columns
        if start == 0:
            for column in range(5):
                active = column < columns
                self.dlc_list_frame.grid_columnconfigure(
                    column, weight=1 if active else 0,
                    uniform="dlc" if active else "",
                )
        if end is None:
            end = len(visible_entries)
        for index, entry in enumerate(visible_entries[start:end], start=start):
            task_id = self._dlc_task_id(entry.dlc_id)
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

    def _render_advanced_catalog_rows(
        self, visible_entries, snapshots, *, start: int = 0, end: int | None = None,
    ) -> None:
        if start == 0:
            self.dlc_list_frame.grid_columnconfigure(0, weight=1, uniform="")
            for column in range(1, 4):
                self.dlc_list_frame.grid_columnconfigure(column, weight=0, uniform="")
            header = ctk.CTkFrame(
                self.dlc_list_frame, fg_color=UI["panel"], corner_radius=8,
                border_width=1, border_color=UI["border"],
            )
            header.grid(row=0, column=0, columnspan=8, sticky="ew", pady=(0, 6))
            header.grid_columnconfigure(2, weight=1)
            for column, title, width, anchor, padx in (
                (0, "选择", 48, "center", (8, 0)),
                (1, "DLC 编号", 68, "w", (2, 6)),
                (2, "名称", 0, "w", 4),
                (3, "大小", 80, "e", 6),
                (4, "下载", 56, "center", 4),
                (5, "取消", 50, "center", (4, 10)),
                (6, "安装路径", 58, "center", 4),
                (7, "卸载", 50, "center", (4, 10)),
            ):
                ctk.CTkLabel(
                    header, text=title, width=width, anchor=anchor,
                    text_color=UI["text_secondary"],
                    font=ctk.CTkFont(size=12, weight="bold"),
                ).grid(row=0, column=column, sticky="ew" if column == 2 else "", padx=padx, pady=7)
        if end is None:
            end = len(visible_entries)
        for index, entry in enumerate(visible_entries[start:end], start=start + 1):
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
            if entry.asset.size_bytes is not None:
                status.configure(text=_format_size(entry.asset.size_bytes))
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
            task_id = self._dlc_task_id(entry.dlc_id)
            self.catalog_rows[task_id] = (status, action, cancel, manage, uninstall)
            self.catalog_selection_widgets[entry.dlc_id] = checkbox
            self.catalog_entry_frames[entry.dlc_id] = row
            self.catalog_name_labels[entry.dlc_id] = name_label
            self._apply_visual_theme_to_children(
                row, set(self.navigation_buttons.values())
            )
            if task_id in snapshots:
                self._show_download_state(snapshots[task_id])
            self._show_install_state(entry, snapshots.get(task_id))

    @staticmethod
    def _catalog_asset_size_text(entry) -> str:
        """Keep the advanced catalog's size column independent of state text."""
        if entry.asset.size_bytes is not None:
            return _format_size(entry.asset.size_bytes)
        return entry.asset.display_size or "大小未知"

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
            snapshot = snapshots.get(self._dlc_task_id(entry.dlc_id))
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
        self._refresh_catalog_capacity_summary()

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
            text="取消全选" if all_selected else "全选 DLC"
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
        self._refresh_catalog_capacity_summary()

    def _toggle_catalog_more_actions(self) -> None:
        """Reveal low-frequency catalog maintenance actions on demand."""
        if self.catalog_more_actions.winfo_ismapped():
            self.catalog_more_actions_button.configure(text="更多操作  ▾")
            self.catalog_more_actions.grid_remove()
            return
        self.catalog_more_actions_button.configure(text="收起操作  ▴")
        self.catalog_more_actions.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10)
        )

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
        self._refresh_catalog_capacity_summary()

    def _one_click_unlock(self) -> None:
        """Button command: patch first, then download and install selected DLC."""
        if self.patch_workflow_state in {"downloading", "applying"}:
            self.catalog_preview.configure(text="补丁流程正在执行，请稍候……")
            return
        if self.batch_download_state == "installing":
            self.catalog_preview.configure(
                text="正在使用已下载缓存安装 DLC，请等待安装完成……"
            )
            return
        if self.batch_download_state == "cancelling":
            return
        if self.batch_download_state == "running":
            self._pause_batch_download()
            return
        if self.batch_download_state in {"pausing", "paused", "resuming"}:
            self._continue_batch_download()
            return
        self._start_unlock_workflow()

    def _start_unlock_workflow(self) -> None:
        """Kick off the patch phase; DLC downloads begin once patching succeeds."""
        if self.cache_cleanup_running:
            self.catalog_preview.configure(
                text="缓存正在维护，请等待完成后再执行一键解锁工具"
            )
            return
        if self.download_queue is None:
            self._show_catalog_error("下载队列初始化失败，请查看日志")
            return
        if self.current_installation is None:
            messagebox.showwarning(
                "尚未检测游戏",
                "请先选择或识别当前游戏的有效目录，再使用一键解锁工具。",
                parent=self.window,
            )
            return
        if not self._require_game_stopped("一键解锁工具"):
            return
        if self.patch_bundle is None:
            missing = ", ".join(self.catalog_missing_patch_assets) or "全部补丁资源"
            self._show_catalog_error(
                f"资源仓库缺少补丁文件：{missing}；请稍后重试或刷新目录"
            )
            return
        selected_entries = [
            entry for entry in self.catalog_entries
            if entry.dlc_id in self.selected_dlc_ids
        ]
        self.unlock_workflow_active = True
        self.unlock_requested_dlc_ids = tuple(
            entry.dlc_id for entry in selected_entries
        )
        self.unlock_failed_dlc_ids.clear()
        for entry in selected_entries:
            self.auto_install_attempted.discard(self._dlc_task_id(entry.dlc_id))
            self.auto_install_redownload_attempted.discard(
                self._dlc_task_id(entry.dlc_id)
            )
        # Remember whichever DLC the user asked for; if patch download is
        # already needed the batch launches automatically after patching.
        self.pending_dlc_batch_task_ids = tuple(
            self._dlc_task_id(entry.dlc_id) for entry in selected_entries
        )
        if self._patch_is_healthy():
            # Nothing to download or apply for the patch itself.  Fall through
            # to the DLC batch (or just tell the user the patch is already good
            # if they did not select any DLC).
            self._notify_patch_healthy_and_continue(selected_entries)
            return
        self._start_patch_downloads()

    def _notify_patch_healthy_and_continue(self, selected_entries) -> None:
        if not selected_entries:
            self.catalog_preview.configure(
                text=(
                    "补丁已经健康；内置 DLC 已随游戏本体提供，无需下载。"
                    if self._uses_built_in_dlc_delivery()
                    else "补丁已经健康；未勾选 DLC 时无需下载。"
                )
            )
            self._set_batch_download_state("idle")
            self._maybe_finish_unlock_workflow()
            return
        self._start_dlc_batch(selected_entries)

    def _start_dlc_batch(self, selected_entries) -> None:
        if self.cache_cleanup_running:
            self.catalog_preview.configure(
                text="缓存正在维护，请等待完成后再开始下载"
            )
            return
        if self.download_queue is None:
            self._show_catalog_error("下载队列初始化失败，请查看日志")
            return
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
        for entry in selected_entries:
            task_id = self._dlc_task_id(entry.dlc_id)
            snapshot = snapshots.get(task_id)
            cache_ready = (
                snapshot is not None
                and snapshot.state is DownloadState.READY
                and snapshot.result_path is not None
                and snapshot.result_path.is_file()
                and snapshot.sha256 is not None
            )
            if self._is_entry_installed(entry):
                self.auto_install_requested_task_ids.discard(task_id)
                skipped += 1
                continue
            self.auto_install_requested_task_ids.add(task_id)
            if cache_ready:
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
                self.auto_install_requested_task_ids.discard(task_id)
                self.unlock_failed_dlc_ids.add(entry.dlc_id)
                failed += 1
        self.batch_download_task_ids = tuple(dict.fromkeys(batch_task_ids))
        self.pending_dlc_batch_task_ids = ()
        if self.batch_download_task_ids:
            self._set_batch_download_state("running")
            # READY packages from an earlier run can be installed immediately
            # while the single download worker fetches only the missing ones.
            self._schedule_ready_installs()
        else:
            self._set_batch_download_state("idle")
            self._schedule_ready_installs()
        self.catalog_preview.configure(
            text=(
                f"补丁已完成 · 开始 {started} 个 DLC 下载任务"
                f"，跳过 {skipped} 个已下载/已安装/进行中项目"
                f"，提交失败 {failed} 个"
                "；任务将按列表顺序逐个下载"
            )
        )
        if not self.batch_download_task_ids:
            self._maybe_finish_unlock_workflow()

    def _set_batch_download_state(self, state: str) -> None:
        self.batch_download_state = state
        text, enabled = {
            "idle": ("一键解锁", True),
            "running": ("暂停下载", True),
            "installing": ("正在安装…", False),
            "pausing": ("继续下载", True),
            "paused": ("继续下载", True),
            "resuming": ("正在继续…", False),
            "cancelling": ("正在取消…", False),
            "patch_downloading": ("正在下载补丁…", False),
            "patch_applying": ("正在应用补丁…", False),
            "repairing": ("正在一键修复…", False),
            "restoring": ("正在恢复原版…", False),
        }[state]
        if state == "idle" and self._uses_built_in_dlc_delivery():
            text = "安装补丁并激活"
        if (
            enabled
            and (self.catalog_entries or self._uses_built_in_dlc_delivery())
            and self.patch_bundle is None
        ):
            text = "补丁资源缺失"
            enabled = False
        self.download_selected_button.configure(
            text=text,
            state="normal" if enabled else "disabled",
            fg_color=UI["primary"],
            hover_color=UI["primary_hover"],
        )
        if self.install_recovery_running:
            self.download_selected_button.configure(
                text="正在检查安装…", state="disabled"
            )
        elif self.install_recovery_failed:
            self.download_selected_button.configure(
                text="请重新扫描", state="disabled"
            )
        # During patch download/apply and cancel/repair/restore the DLC-level cancel
        # button must not tear down anything; the patch flow owns those tasks.
        interactive = state not in {
            "cancelling", "patch_downloading", "patch_applying", "repairing",
            "restoring", "installing",
        }
        cancelable_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.PAUSED,
            DownloadState.RETRYING, DownloadState.VERIFYING,
        }
        has_cancelable_download = bool(self.download_queue) and any(
            item.state in cancelable_states
            for item in self.download_queue.snapshots()
        )
        if interactive and has_cancelable_download:
            self.cancel_all_downloads_button.grid(
                row=0, column=3, padx=(8, 0)
            )
            self.cancel_all_downloads_button.configure(state="normal")
        else:
            self.cancel_all_downloads_button.grid_remove()
        task_cancel_button = getattr(self, "task_cancel_all_downloads_button", None)
        if task_cancel_button is not None:
            task_cancel_button.configure(
                state="normal" if interactive and has_cancelable_download else "disabled"
            )
        repair_button = getattr(self, "repair_button", None)
        remove_patch_button = getattr(self, "remove_patch_button", None)
        restore_original_button = getattr(self, "restore_original_button", None)
        if repair_button is not None:
            repair_button.configure(
                state="normal" if state == "idle" else "disabled"
            )
        if remove_patch_button is not None:
            remove_patch_button.configure(
                state="normal" if state == "idle" else "disabled"
            )
        if restore_original_button is not None:
            restore_original_button.configure(
                state="normal" if state == "idle" else "disabled"
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
        self.auto_install_requested_task_ids.difference_update(unfinished)
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
        self.unlock_workflow_active = False
        self.unlock_requested_dlc_ids = ()
        self.unlock_failed_dlc_ids.clear()
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
            self._set_batch_download_state(
                "installing" if self.auto_install_worker_running else "idle"
            )
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
            failed_task_ids = {
                item.spec.task_id for item in batch
                if item.state in {
                    DownloadState.FAILED,
                    DownloadState.CORRUPT,
                    DownloadState.CANCELLED,
                }
            }
            self.unlock_failed_dlc_ids.update(
                entry.dlc_id for entry in self.catalog_entries
                if self._dlc_task_id(entry.dlc_id) in failed_task_ids
            )
            self._set_batch_download_state(
                "installing" if self.auto_install_worker_running else "idle"
            )
            self.batch_download_task_ids = ()
            self.catalog_preview.configure(
                text=f"批量下载结束：完成 {completed} 个，失败 {failed} 个"
            )
            self._maybe_finish_unlock_workflow()

    def _start_entry_download(self, entry, *, show_error: bool = True):
        if self.cache_cleanup_running:
            if show_error:
                self.catalog_preview.configure(
                    text="缓存正在维护，请等待完成后再开始下载"
                )
            return None
        spec = self._download_spec_for_entry(entry)
        self.auto_install_attempted.discard(spec.task_id)
        self.auto_install_redownload_attempted.discard(spec.task_id)

        if self.download_queue is None:
            self._show_catalog_error("下载队列初始化失败，请查看日志")
            return
        self.auto_install_requested_task_ids.add(spec.task_id)
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
            self.auto_install_requested_task_ids.discard(spec.task_id)
            if show_error:
                self.catalog_preview.configure(text=str(error))
            else:
                raise
        return None

    def _download_spec_for_entry(self, entry) -> DownloadSpec:
        assets = entry.download_assets
        return DownloadSpec(
            task_id=self._dlc_task_id(entry.dlc_id),
            url=assets[0].download_url,
            filename=entry.asset.name,
            game_id=self.cartridge.adapter.descriptor.game_id,
            expected_size=None,
            expected_sha256=None,
            supports_range=False,
            part_urls=tuple(asset.download_url for asset in assets) if len(assets) > 1 else (),
        )

    def _download_finished(self, future) -> None:
        try:
            result = future.result()
            is_patch_task = result.spec.task_id in self.patch_task_roles
            if is_patch_task:
                self.context.logger.info(
                    "Patch download finished: task=%s state=%s",
                    result.spec.task_id, result.state,
                )
                # Advance the patch workflow on the UI thread so it can hand
                # off to the DLC batch (or abort with a proper message).
                self._post_ui(self._maybe_advance_patch_workflow)
                return
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

    def _record_download_problem(self, snapshot) -> None:
        if snapshot.state not in {DownloadState.FAILED, DownloadState.CORRUPT}:
            return
        if not snapshot.failure_code:
            return
        key = (
            snapshot.spec.task_id,
            snapshot.state.value,
            snapshot.failure_code,
            snapshot.attempt,
        )
        if key in self.recorded_download_failures:
            return
        self.recorded_download_failures.add(key)
        try:
            code = ProblemCode(snapshot.failure_code)
        except ValueError:
            code = ProblemCode.APP_UNEXPECTED
        if code.value.startswith("NET-"):
            category = ProblemCategory.NETWORK
        elif code.value.startswith("FS-"):
            category = ProblemCategory.FILESYSTEM
        elif code.value.startswith("PKG-"):
            category = ProblemCategory.INTEGRITY
        elif code.value.startswith("PATCH-"):
            category = ProblemCategory.PATCH
        else:
            category = ProblemCategory.APPLICATION
        security_interference = (
            code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED
        )
        actions = [
            ProblemAction.COPY_DETAILS,
            ProblemAction.OPEN_LOG_DIRECTORY,
            ProblemAction.OPEN_CACHE_DIRECTORY,
            ProblemAction.EXPORT_DIAGNOSTICS,
            ProblemAction.RETRY_TASK,
            ProblemAction.MARK_RESOLVED,
            ProblemAction.DELETE,
        ]
        if security_interference:
            actions.extend((
                ProblemAction.COPY_HASH_INFO,
                ProblemAction.OPEN_MICROSOFT_FALSE_POSITIVE,
            ))
            if self.context.paths.platform == "windows":
                actions.append(ProblemAction.OPEN_WINDOWS_SECURITY)
        summary = (
            "补丁文件疑似被安全软件拦截"
            if security_interference
            else (snapshot.error or f"下载任务失败：{snapshot.spec.filename}")
        )
        suggestion = (
            "请在系统安全软件界面核对文件来源和 SHA-256；确认误报后仅处理该次检测，"
            "再返回程序重试。不要关闭整机防护，也不要添加整目录排除项。"
            if security_interference
            else "请按问题详情检查网络、磁盘和缓存后安全重试。"
        )
        self._record_problem(ProblemReport.create(
            code=code,
            category=category,
            severity=ProblemSeverity.ERROR,
            stage=(
                snapshot.failure_stage.value
                if snapshot.failure_stage is not None
                else "download"
            ),
            summary=summary,
            suggestion=suggestion,
            technical_details=snapshot.error or "",
            app_version=self.context.app_version,
            launcher_version=self.context.launcher_version,
            platform=self.context.paths.platform,
            task_id=snapshot.spec.task_id,
            filename=snapshot.spec.filename,
            expected_sha256=snapshot.spec.expected_sha256,
            actual_sha256=snapshot.sha256,
            allowed_actions=actions,
        ))

    def _apply_download_event(self, snapshot) -> None:
        if snapshot.state is DownloadState.READY:
            try:
                resolved = self.problem_store.resolve_matching(
                    task_id=snapshot.spec.task_id
                )
            except Exception:
                self.context.logger.exception("Unable to resolve download problems")
            else:
                if resolved:
                    self._update_problem_badge()
        else:
            self._record_download_problem(snapshot)
        is_patch_task = snapshot.spec.task_id in self.patch_task_roles
        if not is_patch_task:
            self._show_download_state(snapshot)
            self._update_batch_download_state(snapshot)
            if snapshot.state is DownloadState.READY:
                self._schedule_ready_installs()
        else:
            # Patch downloads drive the unlock/repair state machine directly;
            # the DLC catalog rows never render them.
            if self.patch_workflow_state == "downloading":
                self._maybe_advance_patch_workflow()
        if getattr(self, "current_page", None) == "下载任务":
            self._update_task_page_snapshot(snapshot)

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
            self.auto_install_requested_task_ids.discard(
                self._dlc_task_id(entry.dlc_id)
            )
            try:
                self.download_queue.cancel(self._dlc_task_id(entry.dlc_id))
            except (KeyError, ValueError):
                pass

    def _package_verifier_for(self, spec: DownloadSpec):
        # Capture all cartridge-sensitive state now.  DownloadQueue may invoke
        # this verifier after a queued task has waited behind another game, and
        # cache reconciliation may finish after the user switches cartridges.
        return self._package_verifier_for_context(
            spec,
            cartridge=self.cartridge,
            patch_task_roles=dict(self.patch_task_roles),
        )

    def _package_verifier_for_context(
        self,
        spec: DownloadSpec,
        *,
        cartridge,
        patch_task_roles,
    ):
        role = patch_task_roles.get(spec.task_id)
        if role is not None:
            return self._patch_asset_verifier(role, spec.filename)
        prefix = f"{cartridge.adapter.descriptor.game_id}-"
        expected_dlc_id = spec.task_id.removeprefix(prefix)

        def verify(path: Path, actual_sha256: str):
            metadata = cartridge.inspect_package(
                path,
                asset_name=spec.filename,
                known_sha256=actual_sha256,
            )
            if metadata.dlc_id.casefold() != expected_dlc_id.casefold():
                raise ValueError(
                    f"package DLC ID mismatch: expected {expected_dlc_id}, "
                    f"got {metadata.dlc_id}"
                )
            return metadata

        return verify

    def _patch_asset_verifier(self, role: str, filename: str):
        """Return a verifier that rejects obviously-broken patch downloads."""
        expected_filename = filename

        def verify(path: Path, _actual_sha256: str):
            if path.stat().st_size == 0:
                raise ValueError(f"patch asset {expected_filename} is empty")
            if role == "appinfo_json":
                data = path.read_bytes()
                # Reuse the same parser the patch engine will run later; if the
                # file cannot be parsed here it will not become a valid ini.
                from .signriver_app.infrastructure.patching import parse_appinfo_document
                parse_appinfo_document(data)
            elif role == "unlocker_dll":
                with path.open("rb") as stream:
                    header = stream.read(8)
                binary_magic = (
                    header.startswith(b"MZ")
                    or header.startswith(b"\x7fELF")
                    or header[:4] in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"}
                )
                if not binary_magic:
                    raise ValueError(f"patch library {expected_filename} has an invalid binary format")
            return None

        return verify

    def _installed_dlc_path(self, dlc_id: str) -> Path | None:
        return self.installed_dlc_paths.get(dlc_id.casefold())

    def _refresh_installed_dlc_paths(self) -> None:
        self.installed_dlc_paths = (
            self.cartridge.discover_installed_dlc(
                self.current_installation.root, self.catalog_entries
            )
            if self.current_installation is not None else {}
        )

    def _is_entry_installed(self, entry) -> bool:
        return self._installed_dlc_path(entry.dlc_id) is not None

    def _active_receipt(self, dlc_id: str):
        if self.install_repository is None:
            return None
        try:
            return self.install_repository.find_active(
                self.cartridge.adapter.descriptor.game_id, dlc_id
            )
        except Exception:
            self.context.logger.exception("Unable to read install receipt")
            return None

    def _refresh_active_receipt_dlc_ids(self) -> None:
        if self.install_repository is None:
            self.active_receipt_dlc_ids = frozenset()
            return
        try:
            self.active_receipt_dlc_ids = frozenset(
                dlc_id.casefold() for dlc_id in self.install_repository.active_dlc_ids(
                    self.cartridge.adapter.descriptor.game_id
                )
            )
        except Exception:
            self.context.logger.exception("Unable to read active install receipt IDs")
            self.active_receipt_dlc_ids = frozenset()

    def _ready_download(self, dlc_id: str):
        if self.download_queue is None:
            return None
        return next((
            item for item in self.download_queue.snapshots()
            if item.spec.task_id == self._dlc_task_id(dlc_id)
            and item.state is DownloadState.READY
            and item.result_path is not None
            and item.sha256 is not None
        ), None)

    def _schedule_ready_installs(self) -> None:
        if (
            self.auto_install_worker_running
            or self.install_recovery_running
            or self.install_recovery_failed
            or self.install_service is None
            or self.current_installation is None
            or self.download_queue is None
        ):
            return
        try:
            game_state = self.cartridge.adapter.inspect(self.current_installation)
        except Exception:
            self.context.logger.exception(
                "Unable to verify game state before automatic installation"
            )
            return
        if game_state.running:
            self.catalog_preview.configure(
                text="游戏正在运行：已下载内容会保留，关闭游戏后再继续安装"
            )
            return
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        }
        jobs = []
        for entry in self.catalog_entries:
            task_id = self._dlc_task_id(entry.dlc_id)
            snapshot = snapshots.get(task_id)
            if (
                snapshot is None
                or snapshot.state is not DownloadState.READY
                or snapshot.result_path is None
                or snapshot.sha256 is None
                or task_id not in self.auto_install_requested_task_ids
                or task_id in self.auto_install_attempted
                or self._is_entry_installed(entry)
            ):
                continue
            jobs.append((entry, snapshot))
            self.auto_install_attempted.add(task_id)
        if not jobs:
            return
        self.auto_install_worker_running = True
        if self.batch_download_state == "idle":
            self._set_batch_download_state("installing")
            self.catalog_preview.configure(
                text=f"发现 {len(jobs)} 个已下载缓存，正在安装到游戏目录……"
            )
        game_root = self.current_installation.root
        service = self.install_service
        generation = self.game_selection_generation
        cartridge_id = self.cartridge.cartridge_id

        def worker() -> None:
            total = len(jobs)
            for index, (entry, snapshot) in enumerate(jobs, start=1):
                try:
                    current = self.current_installation
                    if (
                        current is None
                        or current.root != game_root
                        or generation != self.game_selection_generation
                        or cartridge_id != self.cartridge.cartridge_id
                    ):
                        break
                    self._post_ui(
                        lambda entry=entry, index=index, total=total:
                        self._on_auto_install_progress(
                            entry, index, total, generation, cartridge_id
                        )
                    )
                    receipt = service.install(
                        snapshot.result_path,
                        game_root,
                        expected_sha256=snapshot.sha256,
                    )
                    self._post_ui(
                        lambda entry=entry, receipt=receipt:
                        self._on_auto_install_success(
                            entry, receipt, generation, cartridge_id
                        )
                    )
                except Exception as error:
                    if isinstance(error, (InstallAccessError, InstallConflictError)):
                        # Access/locking failures are expected environmental
                        # conditions and already carry a clear user-facing
                        # recovery message. Keep diagnostics useful without a
                        # frightening full traceback for these cases.
                        self.context.logger.warning(
                            "Automatic DLC installation blocked: dlc=%s error=%s",
                            entry.dlc_id, error,
                        )
                    else:
                        self.context.logger.exception(
                            "Automatic DLC installation failed: dlc=%s", entry.dlc_id
                        )
                    message = str(error)
                    if self._cache_integrity_failure(error):
                        self._post_ui(
                            lambda entry=entry, snapshot=snapshot, message=message:
                            self._retry_invalid_cached_package(
                                entry, snapshot, message, generation, cartridge_id
                            )
                        )
                    else:
                        self._post_ui(
                            lambda entry=entry, message=message:
                            self._on_auto_install_failure(
                                entry, message, generation, cartridge_id
                            )
                        )
            self._post_ui(
                lambda: self._on_auto_install_worker_done(
                    generation, cartridge_id
                )
            )

        threading.Thread(
            target=worker, daemon=True, name="dlc-installer"
        ).start()

    def _on_auto_install_progress(
        self, entry, index: int, total: int, generation: int, cartridge_id: str
    ) -> None:
        if (
            generation != self.game_selection_generation
            or cartridge_id != self.cartridge.cartridge_id
        ):
            return
        if self.batch_download_state == "installing":
            self.download_selected_button.configure(
                text=f"安装中 {index}/{total}…", state="disabled"
            )
        self.catalog_preview.configure(
            text=f"正在安装 {index}/{total}：{entry.display_name}"
        )

    @staticmethod
    def _cache_integrity_failure(error: Exception) -> bool:
        message = str(error).casefold()
        return (
            isinstance(error, FileNotFoundError)
            or error.__class__.__name__ in {
                "BadZipFile", "PackageInspectionError"
            }
            or "package sha-256 changed before installation" in message
            or "not a valid zip" in message
        )

    def _retry_invalid_cached_package(
        self,
        entry,
        snapshot,
        message: str,
        generation: int,
        cartridge_id: str,
    ) -> None:
        task_id = snapshot.spec.task_id
        if (
            generation != self.game_selection_generation
            or cartridge_id != self.cartridge.cartridge_id
        ):
            return
        if task_id in self.auto_install_redownload_attempted:
            self._on_auto_install_failure(
                entry, message, generation, cartridge_id
            )
            return
        try:
            self.download_queue.invalidate_cached(task_id, reason=message)
            self.auto_install_redownload_attempted.add(task_id)
            self.auto_install_attempted.discard(task_id)
            future = self.download_queue.resume(task_id)
            future.add_done_callback(self._download_finished)
            self.batch_download_task_ids = tuple(dict.fromkeys(
                (*self.batch_download_task_ids, task_id)
            ))
            self._set_batch_download_state("running")
            self.catalog_preview.configure(
                text=f"{entry.display_name} 的缓存已损坏或丢失，正在自动重新下载一次"
            )
            self._notify(f"{entry.display_name}：缓存异常，已自动重下")
        except Exception as retry_error:
            self.context.logger.exception(
                "Unable to retry invalid cached package: dlc=%s", entry.dlc_id
            )
            self._on_auto_install_failure(
                entry, f"{message}；自动重下失败：{retry_error}",
                generation, cartridge_id,
            )

    def _on_auto_install_success(
        self, entry, receipt, generation: int, cartridge_id: str
    ) -> None:
        if (
            generation != self.game_selection_generation
            or cartridge_id != self.cartridge.cartridge_id
        ):
            return
        # The installer already returned the exact committed target. Updating
        # this one entry avoids rescanning every DLC directory after every
        # small package; the worker performs one full reconciliation at the end.
        self.installed_dlc_paths[entry.dlc_id.casefold()] = receipt.target_path
        self.auto_install_requested_task_ids.discard(
            self._dlc_task_id(entry.dlc_id)
        )
        self.active_receipt_dlc_ids = frozenset((
            *self.active_receipt_dlc_ids, entry.dlc_id.casefold()
        ))
        self._show_install_state(entry)
        self.catalog_preview.configure(text=f"{entry.display_name} 已自动安装到游戏目录")
        self._notify(f"{entry.display_name}：安装完成")
        self._maybe_finish_unlock_workflow()

    def _on_auto_install_failure(
        self, entry, message: str, generation: int, cartridge_id: str
    ) -> None:
        if (
            generation != self.game_selection_generation
            or cartridge_id != self.cartridge.cartridge_id
        ):
            return
        self.auto_install_requested_task_ids.discard(
            self._dlc_task_id(entry.dlc_id)
        )
        if self.unlock_workflow_active and entry.dlc_id in self.unlock_requested_dlc_ids:
            self.unlock_failed_dlc_ids.add(entry.dlc_id)
        self.catalog_preview.configure(
            text=f"{entry.display_name} 下载完成，但自动安装失败：{message}"
        )
        self._notify(f"{entry.display_name}：自动安装失败", error=True)
        self._maybe_finish_unlock_workflow()

    def _on_auto_install_worker_done(
        self, generation: int, cartridge_id: str
    ) -> None:
        self.auto_install_worker_running = False
        if (
            generation != self.game_selection_generation
            or cartridge_id != self.cartridge.cartridge_id
        ):
            return
        self._schedule_ready_installs()
        if (
            not self.auto_install_worker_running
            and self.batch_download_state == "installing"
        ):
            self._set_batch_download_state("idle")
        if not self.auto_install_worker_running and not self._content_work_is_active():
            self._refresh_installed_dlc_paths()
        self._maybe_finish_repair_workflow()
        self._maybe_finish_unlock_workflow()

    def _maybe_finish_unlock_workflow(self) -> None:
        """Show one success dialog only after patching and requested installs finish."""
        if (
            not self.unlock_workflow_active
            or self.repair_workflow_active
            or self.patch_workflow_state != "idle"
            or self.batch_download_state != "idle"
            or self.auto_install_worker_running
        ):
            return
        if self.current_installation is None:
            self.unlock_workflow_active = False
            self.unlock_requested_dlc_ids = ()
            self.unlock_failed_dlc_ids.clear()
            return
        self._refresh_installed_dlc_paths()
        missing = {
            dlc_id for dlc_id in self.unlock_requested_dlc_ids
            if self._installed_dlc_path(dlc_id) is None
        }
        if missing:
            if missing & self.unlock_failed_dlc_ids:
                self.unlock_workflow_active = False
                self.unlock_requested_dlc_ids = ()
                self.unlock_failed_dlc_ids.clear()
            return

        # DLC installation can take much longer than patch application. A
        # security product or a manual file operation may remove the patch in
        # that interval, so success must be based on a final content audit.
        try:
            patch_audit = self.patch_engine.audit_recorded(
                self.current_installation.root
            )
        except Exception:
            self.context.logger.exception("Final one-click patch audit failed")
            patch_audit = None
        if patch_audit is None or patch_audit.health is not PatchHealth.HEALTHY:
            affected = ()
            if patch_audit is not None:
                affected = (*patch_audit.missing, *patch_audit.modified)
            affected_text = (
                "\n\n异常文件：\n" + "\n".join(affected)
                if affected else ""
            )
            self.unlock_workflow_active = False
            self.unlock_requested_dlc_ids = ()
            self.unlock_failed_dlc_ids.clear()
            detail = (
                "DLC 已安装完成，但补丁在流程结束前被删除、隔离或修改，"
                "因此一键解锁工具尚未完成。请检查安全软件后重新点击一键解锁工具。"
                f"{affected_text}"
            )
            self.catalog_preview.configure(text="DLC 已安装，但补丁复检失败")
            self._notify("补丁复检失败", error=True)
            messagebox.showwarning(
                "一键解锁工具未完成", detail, parent=self.window
            )
            return

        installed_count = len(self.unlock_requested_dlc_ids)
        game_name = self.cartridge.adapter.descriptor.display_name
        self.unlock_workflow_active = False
        self.unlock_requested_dlc_ids = ()
        self.unlock_failed_dlc_ids.clear()
        if self._uses_built_in_dlc_delivery():
            detail = (
                f"{game_name} 的 DLC 已随游戏本体安装；补丁已经正确应用，"
                "无需下载额外 DLC。"
            )
        elif installed_count:
            detail = (
                f"{game_name} 的补丁已经正确应用，选择的 "
                f"{installed_count} 个 DLC 均已安装完成。"
            )
        else:
            detail = f"{game_name} 的补丁已经正确应用，当前无需安装额外 DLC。"
        self.catalog_preview.configure(text=f"一键解锁工具执行成功：{detail}")
        self._notify("一键解锁工具执行成功")
        messagebox.showinfo("一键解锁工具执行成功", detail, parent=self.window)

    def _show_install_state(self, entry, snapshot=None) -> None:
        task_id = self._dlc_task_id(entry.dlc_id)
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
            if snapshot is None and self.download_queue is not None:
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
        has_receipt = entry.dlc_id.casefold() in self.active_receipt_dlc_ids
        if installed:
            _status.configure(text=self._catalog_asset_size_text(entry), text_color=UI["text"])
            _action.configure(state="disabled", text="已安装")
            _cancel.configure(state="disabled")
            uninstall.configure(state="normal")
            if has_receipt:
                manage.configure(state="normal", text="检查")
                self._style_widget(manage, set(self.navigation_buttons.values()))
            else:
                manage.configure(state="disabled", text="已存在")
            return
        if has_receipt and self.current_installation is not None:
            manage.configure(state="normal", text="检查")
            self._style_widget(manage, set(self.navigation_buttons.values()))
            uninstall.configure(state="normal")
            return
        uninstall.configure(state="disabled")
        if self.current_installation is None:
            manage.configure(state="disabled", text="无路径")
        elif not (
            snapshot is not None
            and snapshot.state is DownloadState.READY
            and snapshot.result_path is not None
            and snapshot.sha256 is not None
        ) and self._ready_download(entry.dlc_id) is None:
            manage.configure(state="disabled", text="先下载")
        else:
            manage.configure(state="normal", text="安装")

    def _begin_manual_file_operation(self, label: str):
        if self.manual_file_operation_token is not None:
            messagebox.showwarning(
                "文件操作尚未结束",
                "请等待当前 DLC 检查、安装或卸载操作完成。",
                parent=self.window,
            )
            return None
        if (
            self.auto_install_worker_running
            or self.install_recovery_running
            or self.cache_cleanup_running
            or self.batch_download_state != "idle"
            or self.patch_workflow_state != "idle"
        ):
            messagebox.showwarning(
                "当前任务尚未结束",
                "请等待下载、自动安装、补丁或缓存维护完成后再操作单个 DLC。",
                parent=self.window,
            )
            return None
        installation = self.current_installation
        if installation is None:
            return None
        token = (
            object(), self.game_selection_generation,
            self.cartridge.cartridge_id,
            str(installation.root.resolve(strict=False)), label,
        )
        self.manual_file_operation_token = token
        self.catalog_preview.configure(text=f"正在{label}……")
        return token

    def _manual_file_operation_is_current(self, token) -> bool:
        if self.manual_file_operation_token != token:
            return False
        _marker, generation, cartridge_id, game_root, _label = token
        return (
            generation == self.game_selection_generation
            and cartridge_id == self.cartridge.cartridge_id
            and self.current_installation is not None
            and str(self.current_installation.root.resolve(strict=False)) == game_root
        )

    def _finish_manual_file_error(self, token, title: str, message: str) -> None:
        if self.manual_file_operation_token != token:
            return
        current = self._manual_file_operation_is_current(token)
        self.manual_file_operation_token = None
        if not current:
            return
        self.catalog_preview.configure(text=f"{title}：{message}")
        messagebox.showerror(title, message, parent=self.window)

    def _manage_entry(self, entry) -> None:
        if self.install_service is None or self.current_installation is None:
            return
        if not self._require_game_stopped("检查、修复或安装 DLC"):
            return
        receipt = self._active_receipt(entry.dlc_id)
        if receipt is not None:
            game_root = self.current_installation.root
            download = self._ready_download(entry.dlc_id)
            service = self.install_service
            game_id = self.cartridge.adapter.descriptor.game_id
            token = self._begin_manual_file_operation("检查 DLC")
            if token is None:
                return

            def inspect_worker() -> None:
                try:
                    audit = next(
                        item.audit for item in service.audit(
                            game_id, game_root
                        ) if item.receipt.dlc_id == entry.dlc_id
                    )
                    if audit.health is not InstallHealth.HEALTHY and audit.missing and download is not None:
                        audit = service.repair_missing(
                            game_id,
                            entry.dlc_id, download.result_path, game_root
                        )
                    self._post_ui(
                        lambda audit=audit:
                        self._finish_manual_audit(token, entry, audit)
                    )
                except Exception as error:
                    self.context.logger.exception("DLC audit failed")
                    message = str(error)
                    self._post_ui(
                        lambda message=message:
                        self._finish_manual_file_error(
                            token, "检查失败", message
                        )
                    )

            threading.Thread(target=inspect_worker, daemon=True).start()
            return
        download = self._ready_download(entry.dlc_id)
        if download is None or download.sha256 is None:
            return
        if not messagebox.askyesno(
            "确认安装",
            f"将 {entry.display_name} 安装到当前{self.cartridge.adapter.descriptor.display_name}目录？",
            parent=self.window,
        ):
            return
        service = self.install_service
        game_root = self.current_installation.root
        self._run_install_action(
            lambda: service.install(
                download.result_path, game_root,
                expected_sha256=download.sha256,
            ),
            entry,
            "安装完成",
        )

    def _finish_manual_audit(self, token, entry, audit) -> None:
        if self.manual_file_operation_token != token:
            return
        current = self._manual_file_operation_is_current(token)
        self.manual_file_operation_token = None
        if current:
            self._show_audit_result(entry, audit)

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
        if not self._require_game_stopped("卸载 DLC"):
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

    def _start_dlc_removal(self, targets: dict[str, str], title: str) -> None:
        game_root = self.current_installation.root
        repository = self.install_repository
        cartridge = self.cartridge
        game_id = cartridge.adapter.descriptor.game_id
        token = self._begin_manual_file_operation(title)
        if token is None:
            return
        self.auto_install_requested_task_ids.difference_update(
            self._dlc_task_id(dlc_id) for dlc_id in targets
        )
        self.catalog_preview.configure(text=f"正在移除 {len(targets)} 个 DLC……")

        def worker() -> None:
            removed = []
            failures = []
            for dlc_id, display_name in targets.items():
                try:
                    cartridge.remove_installed_dlc(game_root, dlc_id)
                    if repository is not None:
                        receipt = repository.find_active(
                            game_id, dlc_id
                        )
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
                lambda: self._finish_dlc_removal(
                    token, title, removed, failures
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_dlc_removal(self, token, title: str, removed, failures) -> None:
        if self.manual_file_operation_token != token:
            return
        current = self._manual_file_operation_is_current(token)
        self.manual_file_operation_token = None
        if not current:
            return
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

    # ---- Patch workflow (一键解锁工具 / 一键修复 / 一键移除补丁) ------------

    def _patch_download_specs(self) -> tuple[DownloadSpec, ...]:
        """Materialize the complete release-side patch payload when available."""
        bundle = self.patch_bundle
        if bundle is None:
            return ()
        assets_by_role = {
            "unlocker_dll": bundle.unlocker_dll,
            "original_dll": getattr(
                bundle, "original_dll", getattr(bundle, "original_backup_dll", None)
            ),
            "appinfo_json": bundle.appinfo_json,
        }
        return tuple(
            self._download_spec_for_patch(task_id, assets_by_role[role])
            for task_id, role in self.patch_task_roles.items()
        )

    def _download_spec_for_patch(self, task_id: str, asset) -> DownloadSpec:
        return DownloadSpec(
            task_id=task_id,
            url=asset.download_url,
            filename=asset.name,
            game_id=self.cartridge.adapter.descriptor.game_id,
            expected_size=asset.size_bytes,
            expected_sha256=asset.sha256,
            supports_range=False,
            purpose=(
                DownloadPurpose.PATCH_METADATA
                if asset.name.lower().endswith(".json")
                else DownloadPurpose.PATCH_BINARY
            ),
        )

    def _patch_asset_for(self, task_id: str):
        """Return the ReleaseAsset backing a patch download task, if known."""
        role = self.patch_task_roles.get(task_id)
        if role is None or self.patch_bundle is None:
            return None
        return {
            "unlocker_dll": self.patch_bundle.unlocker_dll,
            "original_dll": getattr(self.patch_bundle, "original_dll", None),
            "appinfo_json": self.patch_bundle.appinfo_json,
        }[role]

    def _patch_snapshots_by_task(self) -> dict[str, object]:
        if self.download_queue is None:
            return {}
        return {
            item.spec.task_id: item
            for item in self.download_queue.snapshots()
            if item.spec.task_id in self.patch_task_roles
        }

    def _patch_ready_paths(self) -> dict[str, Path] | None:
        """Return {role: cached_path} when both release-side patch assets are ready."""
        if self.patch_bundle is None:
            return None
        snapshots = self._patch_snapshots_by_task()
        specs = {
            spec.task_id: spec for spec in self._patch_download_specs()
        }
        paths: dict[str, Path] = {}
        for task_id, role in self.patch_task_roles.items():
            snapshot = snapshots.get(task_id)
            if snapshot is None or snapshot.state is not DownloadState.READY:
                return None
            if snapshot.result_path is None or not snapshot.result_path.is_file():
                return None
            paths[role] = snapshot.result_path
        # Extra sanity: make sure the ready cache still belongs to the latest
        # bundle we resolved.  The cache is content-addressed, so a stale
        # snapshot with a different filename means the bundle rotated.
        for task_id, snapshot in snapshots.items():
            expected = specs.get(task_id)
            if expected is None:
                continue
            if snapshot.spec.filename != expected.filename:
                return None
        return paths

    def _missing_ready_patch_asset(self):
        """Return a READY snapshot whose cached file vanished externally."""
        for snapshot in self._patch_snapshots_by_task().values():
            if snapshot.state is not DownloadState.READY:
                continue
            if snapshot.result_path is None or not snapshot.result_path.is_file():
                return snapshot
        return None

    @staticmethod
    def _patch_security_software_message(filename: str) -> str:
        return (
            f"补丁文件 {filename} 在写入后消失或无法访问，疑似被安全软件拦截。\n\n"
            "启发式检测既可能是误报，也可能是真实威胁。请先在系统安全软件中核对"
            "文件来源和 SHA-256；如确认属于误报，请仅在系统界面处理该次检测，然后"
            "返回程序重新下载。不要关闭整机防护，也不要添加整目录排除项。"
        )

    def _patch_is_healthy(self) -> bool:
        """True only when all installed patch files match recorded hashes."""
        if self.patch_bundle is None or self.current_installation is None:
            return False
        try:
            audit = self.patch_engine.audit_recorded(
                self.current_installation.root
            )
        except Exception:
            self.context.logger.exception("Patch audit failed")
            return False
        return audit.health is PatchHealth.HEALTHY

    @staticmethod
    def _valid_sha256(value: str | None) -> bool:
        if value is None or len(value) != 64:
            return False
        try:
            int(value, 16)
        except ValueError:
            return False
        return True

    def _patch_assets_missing_hash(self) -> tuple[object, ...]:
        if self.patch_bundle is None:
            return ()
        assets = (
            self.patch_bundle.unlocker_dll,
            getattr(
                self.patch_bundle,
                "original_dll",
                getattr(self.patch_bundle, "original_backup_dll", None),
            ),
            self.patch_bundle.appinfo_json,
        )
        return tuple(
            asset for asset in assets
            if asset is None or not self._valid_sha256(asset.sha256)
        )

    def _record_patch_problem(
        self,
        *,
        code: ProblemCode,
        stage: str,
        summary: str,
        suggestion: str,
        technical_details: str = "",
        asset=None,
        actual_sha256: str | None = None,
        task_id: str | None = None,
    ) -> ProblemReport:
        actions = [
            ProblemAction.COPY_DETAILS,
            ProblemAction.OPEN_LOG_DIRECTORY,
            ProblemAction.OPEN_CACHE_DIRECTORY,
            ProblemAction.EXPORT_DIAGNOSTICS,
            ProblemAction.MARK_RESOLVED,
            ProblemAction.DELETE,
        ]
        if task_id:
            actions.append(ProblemAction.RETRY_TASK)
        if code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED:
            actions.extend((
                ProblemAction.COPY_HASH_INFO,
                ProblemAction.OPEN_MICROSOFT_FALSE_POSITIVE,
            ))
            if self.context.paths.platform == "windows":
                actions.append(ProblemAction.OPEN_WINDOWS_SECURITY)
        category = (
            ProblemCategory.INTEGRITY
            if code.value.startswith("PKG-")
            else ProblemCategory.PATCH
        )
        return self._record_problem(ProblemReport.create(
            code=code,
            category=category,
            severity=ProblemSeverity.ERROR,
            stage=stage,
            summary=summary,
            suggestion=suggestion,
            technical_details=technical_details,
            app_version=self.context.app_version,
            launcher_version=self.context.launcher_version,
            platform=self.context.paths.platform,
            task_id=task_id,
            filename=getattr(asset, "name", None),
            expected_sha256=getattr(asset, "sha256", None),
            actual_sha256=actual_sha256,
            allowed_actions=actions,
        ))

    @staticmethod
    def _verify_patch_asset(path: Path, asset) -> str:
        expected_hash = str(asset.sha256).lower()
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        if asset.size_bytes is not None and size != asset.size_bytes:
            raise _PatchAssetVerificationError(
                ProblemCode.PKG_SIZE_MISMATCH,
                f"size mismatch: expected {asset.size_bytes}, actual {size}",
                actual_sha256=actual_hash,
            )
        if actual_hash != expected_hash:
            raise _PatchAssetVerificationError(
                ProblemCode.PKG_HASH_MISMATCH,
                f"sha256 mismatch: expected {expected_hash}, actual {actual_hash}",
                actual_sha256=actual_hash,
            )
        return actual_hash

    def _start_patch_downloads(self) -> None:
        if self.download_queue is None or self.patch_bundle is None:
            return
        missing_hash = self._patch_assets_missing_hash()
        if missing_hash:
            names = "、".join(asset.name for asset in missing_hash)
            self._record_patch_problem(
                code=ProblemCode.PATCH_MISSING_HASH,
                stage="prepare",
                summary="补丁目录缺少可信 SHA-256，已拒绝开始",
                suggestion="请刷新静态目录或切换下载源后重试。",
                technical_details=f"缺少或非法 SHA-256：{names}",
                asset=missing_hash[0],
            )
            self._on_patch_workflow_failed(
                "补丁资源缺少有效 SHA-256，已拒绝下载和应用。"
                "请刷新目录或切换下载源后重试。"
            )
            return
        self.patch_workflow_state = "downloading"
        self._set_batch_download_state("patch_downloading")
        specs = self._patch_download_specs()
        snapshots = self._patch_snapshots_by_task()
        active_states = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        task_ids: list[str] = []
        for spec in specs:
            task_ids.append(spec.task_id)
            snapshot = snapshots.get(spec.task_id)
            if snapshot is not None and snapshot.state is DownloadState.READY:
                if snapshot.result_path is not None and snapshot.result_path.is_file():
                    continue
                # A persisted READY record can outlive a file quarantined by
                # security software.  Forget it once so enqueue performs a
                # real re-download instead of waiting forever on stale state.
                self.download_queue.forget((spec.task_id,))
                snapshot = None
            try:
                if snapshot is not None and snapshot.state in active_states:
                    continue
                if snapshot is not None and snapshot.state in {
                    DownloadState.PAUSED, DownloadState.FAILED,
                }:
                    future = self.download_queue.resume(spec.task_id)
                else:
                    future = self.download_queue.enqueue(spec)
                future.add_done_callback(self._download_finished)
            except Exception as error:
                self.context.logger.exception(
                    "Unable to enqueue patch asset: task=%s", spec.task_id
                )
                self._on_patch_workflow_failed(str(error))
                return
        self.patch_task_ids = tuple(task_ids)
        self.catalog_preview.configure(text="正在下载补丁资源（3 个文件）……")
        # If everything came from the cache we may need to advance immediately.
        self.window.after(50, self._maybe_advance_patch_workflow)

    def _maybe_advance_patch_workflow(self) -> None:
        if self.patch_workflow_state != "downloading":
            return
        ready = self._patch_ready_paths()
        if ready is None:
            missing_ready = self._missing_ready_patch_asset()
            if missing_ready is not None:
                self._on_patch_workflow_failed(
                    self._patch_security_software_message(
                        missing_ready.spec.filename
                    )
                )
                return
            snapshots = self._patch_snapshots_by_task()
            failed_states = {
                DownloadState.FAILED, DownloadState.CANCELLED, DownloadState.CORRUPT,
            }
            for task_id in self.patch_task_ids:
                snapshot = snapshots.get(task_id)
                if snapshot is not None and snapshot.state in failed_states:
                    detail = f"：{snapshot.error}" if snapshot.error else ""
                    self._on_patch_workflow_failed(
                        f"补丁资源下载失败（{snapshot.spec.filename}）{detail}，"
                        "请刷新目录后重试"
                    )
                    return
            return
        self._apply_patch_after_download(ready)

    def _apply_patch_after_download(self, ready_paths: dict[str, Path]) -> None:
        if self.current_installation is None:
            self._on_patch_workflow_failed("未选择游戏目录")
            return
        self.patch_workflow_state = "applying"
        self._set_batch_download_state("patch_applying")
        self.catalog_preview.configure(text="补丁资源已就绪，正在应用补丁……")
        game_root = self.current_installation.root
        engine = self.patch_engine
        game_id = self.current_installation.game_id
        bundle = self.patch_bundle
        assets_by_role = {
            "unlocker_dll": bundle.unlocker_dll,
            "appinfo_json": bundle.appinfo_json,
        }
        task_by_role = {role: task_id for task_id, role in self.patch_task_roles.items()}

        def fail_with_problem(
            *, code: ProblemCode, stage: str, message: str, asset=None,
            actual_sha256: str | None = None, task_id: str | None = None,
        ) -> None:
            self._record_patch_problem(
                code=code,
                stage=stage,
                summary=(
                    "补丁文件疑似被安全软件拦截"
                    if code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED
                    else message
                ),
                suggestion=(
                    "请在系统安全软件界面核对文件来源和 SHA-256；确认误报后仅处理该次检测，"
                    "再返回程序重试。不要关闭整机防护，也不要添加整目录排除项。"
                    if code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED
                    else "请刷新静态目录或切换下载源后重新下载。"
                ),
                technical_details=message,
                asset=asset,
                actual_sha256=actual_sha256,
                task_id=task_id,
            )
            self._on_patch_workflow_failed(message)

        def worker() -> None:
            try:
                for role, path in ready_paths.items():
                    asset = assets_by_role[role]
                    try:
                        self._verify_patch_asset(path, asset)
                    except _PatchAssetVerificationError as error:
                        message = (
                            f"补丁资源完整性校验失败（{asset.name}）：{error}"
                        )
                        self._post_ui(
                            lambda error=error, message=message, asset=asset,
                            task_id=task_by_role.get(role): fail_with_problem(
                                code=error.code,
                                stage="verify",
                                message=message,
                                asset=asset,
                                actual_sha256=error.actual_sha256,
                                task_id=task_id,
                            )
                        )
                        return
                    except OSError as error:
                        self.context.logger.exception("Patch asset became unavailable")
                        if self.download_queue is not None:
                            try:
                                self.download_queue.cancel_many(self.patch_task_ids)
                            except Exception:
                                self.context.logger.exception(
                                    "Unable to stop patch downloads after file disappearance"
                                )
                        message = self._patch_security_software_message(asset.name)
                        details = f"{message}\n{type(error).__name__}: {error}"
                        task_id = task_by_role.get(role)

                        def finish_security_failure(
                            message=message,
                            details=details,
                            asset=asset,
                            task_id=task_id,
                        ) -> None:
                            self._record_patch_problem(
                                code=(
                                    ProblemCode
                                    .PATCH_SECURITY_INTERFERENCE_SUSPECTED
                                ),
                                stage="verify",
                                summary="补丁文件疑似被安全软件拦截",
                                suggestion=(
                                    "请在系统安全软件界面核对文件来源和 SHA-256；"
                                    "不要关闭整机防护，也不要添加整目录排除项。"
                                ),
                                technical_details=details,
                                asset=asset,
                                task_id=task_id,
                            )
                            self._on_patch_workflow_failed(message)

                        self._post_ui(finish_security_failure)
                        return
                patch_operation = (
                    engine.repair_patch if self.repair_workflow_active else engine.apply
                )
                result = patch_operation(
                    game_root,
                    unlocker_dll_source=ready_paths["unlocker_dll"],
                    original_dll_source=ready_paths["original_dll"],
                    appinfo_json_source=ready_paths["appinfo_json"],
                    game_id=game_id,
                )
                self._post_ui(lambda result=result: self._on_patch_applied(result))
            except PatchError as error:
                self.context.logger.exception("Patch apply failed")
                message = str(error) or "补丁应用失败"
                self._post_ui(
                    lambda message=message: fail_with_problem(
                        code=ProblemCode.PATCH_APPLY_FAILED,
                        stage="apply",
                        message=message,
                    )
                )
            except (FileNotFoundError, PermissionError) as error:
                self.context.logger.exception("Patch asset became unavailable")
                filename = getattr(error, "filename", None) or "补丁资源"
                message = self._patch_security_software_message(Path(filename).name)
                self._post_ui(
                    lambda message=message: fail_with_problem(
                        code=ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED,
                        stage="apply",
                        message=message,
                    )
                )
            except Exception as error:
                self.context.logger.exception("Patch apply crashed")
                message = str(error) or "补丁应用失败"
                self._post_ui(
                    lambda message=message: fail_with_problem(
                        code=ProblemCode.PATCH_APPLY_FAILED,
                        stage="apply",
                        message=message,
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_patch_applied(self, result) -> None:
        # Re-check on the UI hand-off boundary as antivirus quarantine is often
        # asynchronous and may happen just after PatchEngine.apply returns.
        if self.current_installation is None:
            self._on_patch_workflow_failed("补丁应用后游戏目录不可用")
            return
        audit = None
        audit_error: Exception | None = None
        try:
            audit = self.patch_engine.audit_recorded(
                self.current_installation.root
            )
            incomplete = audit.health is not PatchHealth.HEALTHY
        except (OSError, PatchError) as error:
            self.context.logger.exception("Post-apply patch audit failed")
            audit_error = error
            incomplete = True
        if incomplete:
            # Best-effort restoration prevents a quarantined loader DLL from
            # leaving the game in a half-patched state. Failure is included in
            # the same structured event without obscuring the audit failure.
            restore_error: Exception | None = None
            try:
                self.patch_engine.restore_original(self.current_installation.root)
            except Exception as error:
                restore_error = error
                self.context.logger.exception(
                    "Unable to restore original files after patch quarantine"
                )
            security_suspected = (
                isinstance(audit_error, (FileNotFoundError, PermissionError))
                or (audit_error is None and bool(getattr(audit, "missing", ())))
            )
            code = (
                ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED
                if security_suspected
                else ProblemCode.PATCH_AUDIT_FAILED
            )
            details = []
            if audit_error is not None:
                details.append(f"audit: {type(audit_error).__name__}: {audit_error}")
            elif audit is not None:
                details.append(
                    f"missing={audit.missing!r}; modified={audit.modified!r}"
                )
            if restore_error is not None:
                details.append(
                    f"restore: {type(restore_error).__name__}: {restore_error}"
                )
            message = self._patch_security_software_message(
                self.patch_profile.unlocker_dll_name
            )
            self._record_patch_problem(
                code=code,
                stage="audit",
                summary=(
                    "补丁应用后文件疑似被安全软件移除"
                    if security_suspected
                    else "补丁应用后审计未通过"
                ),
                suggestion=(
                    "请核对安全软件保护历史记录和文件 SHA-256 后重新下载；"
                    "不要关闭整机防护，也不要添加整目录排除项。"
                    if security_suspected
                    else "请导出诊断信息并重新执行补丁流程。"
                ),
                technical_details="\n".join(details),
            )
            self._on_patch_workflow_failed(message)
            return
        try:
            for task_id in tuple(self.patch_task_roles):
                self.problem_store.resolve_matching(task_id=task_id)
            for code in (
                ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED,
                ProblemCode.PATCH_APPLY_FAILED,
                ProblemCode.PATCH_AUDIT_FAILED,
            ):
                self.problem_store.resolve_matching(code=code)
        except Exception:
            self.context.logger.exception(
                "Unable to resolve patch problems after successful apply"
            )
        self._update_problem_badge()
        self.patch_workflow_state = "idle"
        self.patch_task_ids = ()
        detail_parts = []
        if result.backup_created:
            detail_parts.append("已建立原版备份")
        if result.backup_replaced:
            detail_parts.append("已替换异常备份 DLL")
        if result.unlocker_replaced:
            detail_parts.append("已更新补丁 DLL")
        if result.ini_written:
            detail_parts.append(
                f"已生成 {self.patch_profile.template.ini_target_name}"
            )
        summary = "补丁已应用；" + ("；".join(detail_parts) or "文件与目标一致，无需变更")
        self.catalog_preview.configure(text=summary)
        self._notify("补丁已应用")
        # Continue into the DLC batch that was queued on unlock.
        if self.repair_workflow_active:
            # The repair flow handles its own follow-up (re-download DLC list).
            self._continue_repair_after_patch()
            return
        pending_ids = self.pending_dlc_batch_task_ids
        selected_entries = [
            entry for entry in self.catalog_entries
            if self._dlc_task_id(entry.dlc_id) in pending_ids
        ]
        if not selected_entries:
            self._set_batch_download_state("idle")
            self._maybe_finish_unlock_workflow()
            return
        self._start_dlc_batch(selected_entries)

    def _on_patch_workflow_failed(self, message: str) -> None:
        if self.repair_workflow_active:
            self._on_repair_failed(message)
            return
        self.patch_workflow_state = "idle"
        self.patch_task_ids = ()
        self.pending_dlc_batch_task_ids = ()
        self._set_batch_download_state("idle")
        self.unlock_workflow_active = False
        self.unlock_requested_dlc_ids = ()
        self.unlock_failed_dlc_ids.clear()
        self.catalog_preview.configure(text=f"一键解锁工具执行失败：{message}")
        self._notify(f"一键解锁工具执行失败：{message}", error=True)
        messagebox.showerror("一键解锁工具执行失败", message, parent=self.window)

    def _restore_original_state(self) -> None:
        """Remove only receipt-backed DLC and the patch managed by this app."""
        if self.current_installation is None:
            messagebox.showwarning(
                "尚未检测游戏",
                "请先选择或识别当前游戏的有效目录。",
                parent=self.window,
            )
            return
        if self.batch_download_state != "idle":
            messagebox.showwarning(
                "当前操作尚未结束",
                "请先等待当前操作完成，或取消全部下载后再移除本程序安装内容。",
                parent=self.window,
            )
            return
        if self.auto_install_worker_running:
            messagebox.showwarning(
                "正在安装 DLC",
                "请等待当前 DLC 安装完成后再移除本程序安装内容。",
                parent=self.window,
            )
            return
        if not self._require_game_stopped("移除本程序安装内容"):
            return
        if self.install_service is None or self.install_repository is None:
            messagebox.showerror(
                "移除功能不可用",
                "安装记录服务尚未初始化，请重启程序后重试。",
                parent=self.window,
            )
            return
        unfinished_states = {
            DownloadState.QUEUED,
            DownloadState.DOWNLOADING,
            DownloadState.PAUSING,
            DownloadState.PAUSED,
            DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        if self.download_queue is not None and any(
            item.state in unfinished_states for item in self.download_queue.snapshots()
        ):
            messagebox.showwarning(
                "仍有下载任务",
                "移除前请先取消全部下载任务。暂停的任务也需要取消，避免移除后又自动安装。",
                parent=self.window,
            )
            return

        game_root = self.current_installation.root
        service = OriginalStateRestoreService(
            self.cartridge,
            self.patch_engine,
            self.install_service,
            self.install_repository,
        )
        try:
            preview = service.preview(game_root)
        except Exception as error:
            self.context.logger.exception("Unable to preview original-state restore")
            messagebox.showerror(
                "移除检查失败", str(error) or "无法检查当前游戏文件", parent=self.window,
            )
            return
        if not preview.patch_ready:
            messagebox.showerror(
                "无法安全移除补丁",
                preview.patch_reason
                or "未找到可信的原版备份。请先通过游戏平台验证游戏文件完整性。",
                parent=self.window,
            )
            return

        if not messagebox.askyesno(
            "移除本程序安装内容",
            "本操作只撤销由本程序管理的内容：\n\n"
            f"· 撤销本程序记录的 {preview.dlc_count} 个 DLC 安装；\n"
            "· 恢复安装前被替换的同名 DLC 内容；\n"
            "· 移除本程序补丁并还原可信的原版 DLL。\n\n"
            "游戏原有 DLC、其他来源的内容和下载缓存都不会被删除。是否继续？",
            parent=self.window,
        ):
            return
        self.auto_install_requested_task_ids.clear()
        self._set_batch_download_state("restoring")
        self.catalog_preview.configure(text="正在移除本程序安装内容，请勿启动游戏……")

        def worker() -> None:
            try:
                result = service.restore(game_root)
                self._post_ui(
                    lambda result=result: self._on_original_state_restored(result)
                )
            except RestoreOriginalError as error:
                self._post_ui(
                    lambda message=str(error): self._on_original_restore_failed(message)
                )
            except Exception as error:
                self.context.logger.exception("Original-state restore failed")
                message = str(error) or "移除本程序安装内容失败"
                self._post_ui(
                    lambda message=message: self._on_original_restore_failed(message)
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_original_state_restored(self, result) -> None:
        self._set_batch_download_state("idle")
        self._refresh_installed_dlc_paths()
        self._render_catalog_rows()
        mode = "安全移除"
        failures = list(result.failures)
        cache_detail = "下载缓存已保留"
        self.catalog_preview.configure(
            text=(
                f"{mode}完成：处理 {len(result.restored_dlc_ids)} 个 DLC，"
                f"{cache_detail}，失败 {len(failures)} 项"
            )
        )
        detail = (
            f"恢复方式：{mode}\n"
            f"已处理 DLC：{len(result.restored_dlc_ids)} 个\n"
            f"补丁文件处理：{len(result.patch_files)} 项\n"
            f"缓存：{cache_detail}"
        )
        if failures:
            detail += "\n\n未完成项目：\n" + "\n".join(failures[:8])
            if len(failures) > 8:
                detail += f"\n……另有 {len(failures) - 8} 项"
            self._notify("移除本程序安装内容时有部分项目未完成", error=True)
            messagebox.showwarning(
                "恢复完成，但有未完成项目", detail, parent=self.window
            )
            return
        self._notify("本程序安装内容已移除")
        messagebox.showinfo("移除完成", detail, parent=self.window)

    def _on_original_restore_failed(self, message: str) -> None:
        self._set_batch_download_state("idle")
        self.catalog_preview.configure(text=f"移除本程序安装内容失败：{message}")
        self._notify(f"移除本程序安装内容失败：{message}", error=True)
        messagebox.showerror(
            "移除本程序安装内容失败", message, parent=self.window
        )

    def _remove_patch(self) -> None:
        if self.current_installation is None:
            messagebox.showwarning(
                "尚未检测游戏", "请先选择或识别当前游戏的有效目录。", parent=self.window,
            )
            return
        if not self._require_game_stopped("移除补丁"):
            return
        patch_paths = self.patch_profile.patch_file_paths
        restore_target = self.patch_profile.relative_file_path(
            self.patch_profile.unlocker_dll_name
        )
        if not messagebox.askyesno(
            "确认移除补丁",
            f"将清理以下补丁文件，并把原版备份还原为 {restore_target}：\n"
            + "\n".join(f"· {path}" for path in patch_paths)
            + "\n"
            "请先关闭游戏。是否继续？",
            parent=self.window,
        ):
            return
        game_root = self.current_installation.root
        engine = self.patch_engine
        self._set_batch_download_state("restoring")

        def worker() -> None:
            try:
                touched = engine.restore_original(game_root)
                self._post_ui(
                    lambda touched=touched: self._on_patch_removed(touched)
                )
            except Exception as error:
                self.context.logger.exception("Patch removal failed")
                message = str(error) or "补丁移除失败"
                self._post_ui(
                    lambda message=message: self._on_patch_remove_failed(message)
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_patch_removed(self, touched: tuple[str, ...]) -> None:
        self._set_batch_download_state("idle")
        if not touched:
            self.catalog_preview.configure(text="游戏目录中未检测到补丁文件")
            messagebox.showinfo(
                "补丁移除", "游戏目录中未检测到需要清理的补丁文件。",
                parent=self.window,
            )
            return
        detail = "、".join(touched)
        self.catalog_preview.configure(text=f"补丁已移除：{detail}")
        self._notify("补丁已移除")
        messagebox.showinfo(
            "补丁移除完成",
            f"已恢复原版并清理以下文件：\n{detail}",
            parent=self.window,
        )

    def _on_patch_remove_failed(self, message: str) -> None:
        self._set_batch_download_state("idle")
        self.catalog_preview.configure(text=f"补丁移除失败：{message}")
        self._notify(f"补丁移除失败：{message}", error=True)
        messagebox.showerror(
            "补丁移除失败", message, parent=self.window,
        )

    def _update_repair_journal(
        self, phase: str, *, status: str = "active", message: str = ""
    ) -> None:
        if self.repair_game_root is None or not self.repair_cartridge_id:
            return
        completed: list[str] = []
        try:
            self._refresh_installed_dlc_paths()
            completed = [
                dlc_id for dlc_id in self.repair_requested_dlc_ids
                if self._installed_dlc_path(dlc_id) is not None
            ]
            self.repair_journal.update(
                self.repair_cartridge_id,
                self.repair_game_root,
                phase=phase,
                requested_dlc_ids=self.repair_requested_dlc_ids,
                completed_dlc_ids=completed,
                status=status,
                message=message,
            )
        except Exception:
            self.context.logger.exception("Unable to persist repair journal")

    def _one_click_repair(self) -> None:
        if self.current_installation is None:
            messagebox.showwarning(
                "尚未检测游戏", "请先选择或识别当前游戏的有效目录。", parent=self.window,
            )
            return
        if not self._require_game_stopped("一键修复"):
            return
        if self.patch_bundle is None:
            self._show_catalog_error(
                "补丁资源缺失，暂时无法执行一键修复；请稍后刷新目录"
            )
            return
        if self.download_queue is None:
            self._show_catalog_error("下载队列初始化失败，请查看日志")
            return
        catalog_error = self._repair_catalog_error()
        if catalog_error:
            self._show_catalog_error(catalog_error)
            return
        patch_paths = "、".join(self.patch_profile.patch_file_paths)
        prior_repair = self.repair_journal.load(
            self.cartridge.cartridge_id, self.current_installation.root
        )
        resume_note = (
            "\n检测到上次未完成的修复日志，本次将从安全预检阶段继续。\n"
            if prior_repair is not None else ""
        )
        if not messagebox.askyesno(
            "确认一键修复",
            "一键修复会执行以下操作：\n\n"
            "1. 先准备并校验补丁与全部 DLC，缓存缺失时才下载；\n"
            "2. 固化并校验当前安装的原生库保险库，不预先删除任何文件；\n"
            f"3. 原地事务修复补丁文件（{patch_paths}）；\n"
            "4. 从已校验缓存逐项事务重装 DLC，不批量预卸载；\n"
            "5. 最后复检 DLC、补丁和原生库状态。\n\n"
            "准备阶段失败不会改动当前游戏文件。此过程可能下载大量数据，是否继续？"
            + resume_note,
            parent=self.window,
        ):
            return
        self.auto_install_requested_task_ids.clear()
        self.unlock_workflow_active = False
        self.unlock_requested_dlc_ids = ()
        self.unlock_failed_dlc_ids.clear()
        self.repair_workflow_active = True
        self.repair_phase = "preparing"
        self.repair_requested_dlc_ids = tuple(
            entry.dlc_id for entry in self.catalog_entries
        )
        self.repair_cleanup_errors = ()
        self.repair_game_selection_generation = self.game_selection_generation
        self.repair_cartridge_id = self.cartridge.cartridge_id
        self.repair_game_root = self.current_installation.root
        self._update_repair_journal("preparing")
        self._set_game_selector_state("disabled")
        self._start_repair_preparation()

    def _repair_catalog_error(self) -> str | None:
        if self._uses_built_in_dlc_delivery():
            return None
        if not self.catalog_entries:
            return "当前资源目录没有 DLC，无法执行一键修复；尚未改动游戏文件"
        normalized = [entry.dlc_id.casefold() for entry in self.catalog_entries]
        if len(normalized) != len(set(normalized)):
            return "当前资源目录包含重复 DLC 编号，无法安全修复；尚未改动游戏文件"
        try:
            missing = [
                entry.display_name for entry in self.catalog_entries
                if not entry.download_assets
            ]
        except Exception as error:
            return f"无法读取完整 DLC 资源列表：{error}；尚未改动游戏文件"
        if missing:
            return (
                "以下 DLC 缺少下载资源，无法安全修复："
                + "、".join(missing[:5])
                + "；尚未改动游戏文件"
            )
        return None

    def _start_repair_preparation(self) -> None:
        if self.download_queue is None:
            self._on_repair_failed("下载队列不可用；尚未改动游戏文件")
            return
        specs = list(self._patch_download_specs())
        specs.extend(
            self._download_spec_for_entry(entry) for entry in self.catalog_entries
        )
        self.patch_task_ids = tuple(self.patch_task_roles)
        self.repair_prepare_task_ids = tuple(spec.task_id for spec in specs)
        active_task_ids: list[str] = []
        active_states = {
            DownloadState.QUEUED,
            DownloadState.DOWNLOADING,
            DownloadState.PAUSING,
            DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        }
        try:
            for spec in specs:
                snapshot = snapshots.get(spec.task_id)
                ready = (
                    snapshot is not None
                    and snapshot.state is DownloadState.READY
                    and snapshot.result_path is not None
                    and snapshot.result_path.is_file()
                    and snapshot.sha256 is not None
                )
                if ready:
                    continue
                self.auto_install_requested_task_ids.discard(spec.task_id)
                if snapshot is not None and snapshot.state in active_states:
                    active_task_ids.append(spec.task_id)
                    continue
                if snapshot is not None and snapshot.state in {
                    DownloadState.PAUSED, DownloadState.FAILED,
                }:
                    future = self.download_queue.resume(spec.task_id)
                else:
                    future = self.download_queue.enqueue(spec)
                future.add_done_callback(self._download_finished)
                active_task_ids.append(spec.task_id)
        except Exception as error:
            self.context.logger.exception("Unable to prepare repair resources")
            self._on_repair_failed(
                f"资源准备任务创建失败：{error}；尚未改动游戏文件"
            )
            return
        self.batch_download_task_ids = tuple(dict.fromkeys(active_task_ids))
        if self.batch_download_task_ids:
            self._set_batch_download_state("running")
        else:
            self._set_batch_download_state("repairing")
        self.catalog_preview.configure(
            text=f"一键修复：正在准备并校验 {len(specs)} 个资源，尚未改动游戏文件"
        )
        self.window.after(100, self._poll_repair_preparation)

    def _repair_context_is_current(self) -> bool:
        installation = self.current_installation
        return (
            installation is not None
            and self.game_selection_generation
            == self.repair_game_selection_generation
            and self.cartridge.cartridge_id == self.repair_cartridge_id
            and installation.root == self.repair_game_root
        )

    def _poll_repair_preparation(self) -> None:
        if not self.repair_workflow_active or self.repair_phase != "preparing":
            return
        if not self._repair_context_is_current():
            self._on_repair_failed(
                "修复期间游戏或目录发生切换；尚未改动游戏文件"
            )
            return
        if self.download_queue is None:
            self._on_repair_failed("下载队列不可用；尚未改动游戏文件")
            return
        snapshots = {
            item.spec.task_id: item for item in self.download_queue.snapshots()
        }
        failed_states = {
            DownloadState.FAILED,
            DownloadState.CANCELLED,
            DownloadState.CORRUPT,
        }
        for task_id in self.repair_prepare_task_ids:
            snapshot = snapshots.get(task_id)
            if snapshot is not None and snapshot.state in failed_states:
                detail = f"：{snapshot.error}" if snapshot.error else ""
                self._on_repair_failed(
                    f"资源 {snapshot.spec.filename} 准备失败{detail}；尚未改动游戏文件"
                )
                return
        ready = [
            snapshots.get(task_id) for task_id in self.repair_prepare_task_ids
        ]
        complete = all(
            snapshot is not None
            and snapshot.state is DownloadState.READY
            and snapshot.result_path is not None
            and snapshot.result_path.is_file()
            and snapshot.sha256 is not None
            for snapshot in ready
        )
        if not complete:
            ready_count = sum(
                snapshot is not None and snapshot.state is DownloadState.READY
                for snapshot in ready
            )
            self.catalog_preview.configure(
                text=(
                    f"一键修复：资源准备 {ready_count}/{len(ready)}，"
                    "尚未改动游戏文件"
                )
            )
            self.window.after(250, self._poll_repair_preparation)
            return
        self.repair_phase = "preflight"
        self.batch_download_task_ids = ()
        self._set_batch_download_state("repairing")
        self.catalog_preview.configure(
            text="一键修复：资源已下载，正在做最终校验和磁盘空间检查……"
        )
        threading.Thread(
            target=self._preflight_and_clean_repair,
            daemon=True,
            name="repair-preflight",
        ).start()

    def _preflight_and_clean_repair(self) -> None:
        installation = self.current_installation
        queue = self.download_queue
        service = self.install_service
        if installation is None or queue is None or service is None:
            self._post_ui(
                lambda: self._on_repair_failed(
                    "安装环境在资源准备期间失效；尚未改动游戏文件"
                )
            )
            return
        game_root = installation.root
        entries = tuple(self.catalog_entries)
        snapshots = {
            item.spec.task_id: item for item in queue.snapshots()
        }
        try:
            game_state = self.cartridge.adapter.inspect(installation)
            if game_state.running:
                raise RuntimeError("游戏在资源准备期间被启动，请关闭游戏后重试")
            total = len(entries)
            for index, entry in enumerate(entries, start=1):
                snapshot = snapshots[self._dlc_task_id(entry.dlc_id)]
                self._post_ui(
                    lambda index=index, total=total, entry=entry:
                    self.catalog_preview.configure(
                        text=(
                            f"一键修复：预检 {index}/{total}："
                            f"{entry.display_name}，尚未改动游戏文件"
                        )
                    )
                )
                plan = service.engine.plan(
                    snapshot.result_path,
                    game_root,
                    expected_sha256=snapshot.sha256,
                )
                service.engine.ensure_disk_space(plan, replaced_existing=False)
        except Exception as error:
            self.context.logger.exception("Repair resource preflight failed")
            message = str(error) or "资源预检失败"
            self._post_ui(
                lambda message=message: self._on_repair_failed(
                    f"{message}；尚未改动游戏文件"
                )
            )
            return

        if not self._repair_context_is_current():
            self._post_ui(
                lambda: self._on_repair_failed(
                    "修复期间游戏或目录发生切换；尚未改动游戏文件"
                )
            )
            return
        # All resources are ready and the original library will be solidified
        # by PatchEngine before any game file changes. Never pre-delete DLC or
        # patch files: repair is an in-place, fail-closed transaction.
        self._post_ui(lambda: self._update_repair_journal("preflight_complete"))
        self._post_ui(lambda: self._start_repair_reinstall([]))

    def _start_repair_reinstall(self, cleanup_errors: list[str]) -> None:
        if not self._repair_context_is_current():
            self._on_repair_failed("游戏目录已不可用")
            return
        self._refresh_installed_dlc_paths()
        self._render_catalog_rows()
        self.repair_cleanup_errors = tuple(cleanup_errors)
        if cleanup_errors:
            self.catalog_preview.configure(
                text=(
                    "一键修复：清理阶段发生 "
                    f"{len(cleanup_errors)} 个问题，将继续从已校验缓存尝试恢复……"
                )
            )
        # A prior successful unlock marks each task as already installed. The
        # game files have just been removed, so allow the installer pipeline to
        # consume the still-valid READY packages again.
        for entry in self.catalog_entries:
            self.auto_install_attempted.discard(self._dlc_task_id(entry.dlc_id))
            self.auto_install_redownload_attempted.discard(
                self._dlc_task_id(entry.dlc_id)
            )
        # Queue every DLC as the pending batch so the patch flow will hand off
        # into a full-catalog batch after the patch is applied.
        self.pending_dlc_batch_task_ids = tuple(
            self._dlc_task_id(entry.dlc_id) for entry in self.catalog_entries
        )
        self.repair_phase = "patching"
        self._update_repair_journal("patching")
        self._start_patch_downloads()

    def _continue_repair_after_patch(self) -> None:
        # Runs on the UI thread after _on_patch_applied handed off the repair.
        pending_ids = self.pending_dlc_batch_task_ids
        selected_entries = [
            entry for entry in self.catalog_entries
            if self._dlc_task_id(entry.dlc_id) in pending_ids
        ]
        self.pending_dlc_batch_task_ids = ()
        if not selected_entries:
            self._set_batch_download_state("idle")
            self.catalog_preview.configure(
                text="一键修复：补丁已就绪，没有需要下载或重新安装的 DLC"
            )
            self.repair_phase = "installing"
            self._update_repair_journal("installing")
            self._maybe_finish_repair_workflow()
            return
        # Start the DLC batch; auto-install is already wired into the queue's
        # completion callback, so nothing more to do here.
        self.repair_phase = "installing"
        self._update_repair_journal("installing")
        self._start_dlc_batch(selected_entries)
        self.catalog_preview.configure(
            text=f"一键修复：补丁已应用，正在复用缓存或下载并安装 {len(selected_entries)} 个 DLC"
        )

    def _maybe_finish_repair_workflow(self) -> None:
        if (
            not self.repair_workflow_active
            or self.repair_phase != "installing"
            or self.patch_workflow_state != "idle"
            or self.batch_download_state != "idle"
            or self.auto_install_worker_running
        ):
            return
        installation = self.current_installation
        requested = self.repair_requested_dlc_ids
        self._refresh_installed_dlc_paths()
        missing = tuple(
            dlc_id for dlc_id in requested
            if self._installed_dlc_path(dlc_id) is None
        )
        patch_healthy = False
        if installation is not None:
            try:
                audit = self.patch_engine.audit_recorded(installation.root)
                patch_healthy = audit.health is PatchHealth.HEALTHY
            except Exception:
                self.context.logger.exception("Final repair patch audit failed")
        repair_game_root = self.repair_game_root
        repair_cartridge_id = self.repair_cartridge_id
        self.repair_workflow_active = False
        self.repair_phase = "idle"
        self.repair_prepare_task_ids = ()
        self.repair_requested_dlc_ids = ()
        cleanup_errors = self.repair_cleanup_errors
        self.repair_cleanup_errors = ()
        self.repair_game_selection_generation = -1
        self.repair_cartridge_id = ""
        self.repair_game_root = None
        self._set_game_selector_state("normal")
        if missing or not patch_healthy or cleanup_errors:
            problems = []
            if missing:
                problems.append(f"仍缺少 {len(missing)} 个 DLC")
            if not patch_healthy:
                problems.append("补丁复检未通过")
            if cleanup_errors:
                problems.append(f"清理阶段有 {len(cleanup_errors)} 项未完成")
            detail = "；".join(problems)
            self.catalog_preview.configure(text=f"一键修复未完整完成：{detail}")
            if repair_game_root is not None and repair_cartridge_id:
                try:
                    self.repair_journal.update(
                        repair_cartridge_id, repair_game_root, phase="verification_failed",
                        requested_dlc_ids=requested,
                        completed_dlc_ids=(dlc_id for dlc_id in requested if dlc_id not in missing),
                        status="failed", message=detail,
                    )
                except Exception:
                    self.context.logger.exception("Unable to persist failed repair journal")
            self._notify("一键修复未完整完成", error=True)
            messagebox.showwarning(
                "一键修复未完整完成",
                detail + "。请查看下载任务和运行日志后重试。",
                parent=self.window,
            )
            return
        detail = f"补丁健康，{len(requested)} 个 DLC 均已安装并通过最终识别。"
        if repair_game_root is not None and repair_cartridge_id:
            try:
                self.repair_journal.complete(repair_cartridge_id, repair_game_root)
            except Exception:
                self.context.logger.exception("Unable to clear completed repair journal")
        self.catalog_preview.configure(text=f"一键修复完成：{detail}")
        self._notify("一键修复完成")
        messagebox.showinfo("一键修复完成", detail, parent=self.window)

    def _on_repair_failed(self, message: str) -> None:
        self._update_repair_journal(
            self.repair_phase or "failed", status="failed", message=message
        )
        if self.download_queue is not None and self.repair_prepare_task_ids:
            try:
                self.download_queue.cancel_many(self.repair_prepare_task_ids)
            except Exception:
                self.context.logger.exception("Unable to cancel failed repair preparation")
        self.repair_workflow_active = False
        self.repair_phase = "idle"
        self.repair_prepare_task_ids = ()
        self.repair_requested_dlc_ids = ()
        self.repair_cleanup_errors = ()
        self.repair_game_selection_generation = -1
        self.repair_cartridge_id = ""
        self.repair_game_root = None
        self._set_game_selector_state("normal")
        self.patch_workflow_state = "idle"
        self.patch_task_ids = ()
        self.pending_dlc_batch_task_ids = ()
        self.batch_download_task_ids = ()
        self._set_batch_download_state("idle")
        self.catalog_preview.configure(text=f"一键修复失败：{message}")
        self._notify(f"一键修复失败：{message}", error=True)
        messagebox.showerror("一键修复失败", message, parent=self.window)

    # ---- End of patch workflow ---------------------------------------------

    def _run_install_action(self, operation, entry, success_text: str) -> None:
        token = self._begin_manual_file_operation(success_text)
        if token is None:
            return

        def worker() -> None:
            try:
                operation()
                self._post_ui(
                    lambda: self._finish_install_action(
                        token, entry, success_text
                    )
                )
            except Exception as error:
                self.context.logger.exception("DLC install action failed")
                message = str(error)
                self._post_ui(
                    lambda message=message:
                    self._finish_manual_file_error(
                        token, "操作失败", message
                    )
                )
        threading.Thread(target=worker, daemon=True).start()

    def _finish_install_action(self, token, entry, text: str) -> None:
        if self.manual_file_operation_token != token:
            return
        current = self._manual_file_operation_is_current(token)
        self.manual_file_operation_token = None
        if not current:
            return
        self._refresh_installed_dlc_paths()
        self._refresh_active_receipt_dlc_ids()
        self._render_catalog_rows()
        self._notify(f"{entry.display_name}：{text}")
        messagebox.showinfo(text, f"{entry.display_name}：{text}", parent=self.window)

    def _close(self) -> None:
        if self._content_work_is_active() or self.cache_cleanup_running:
            messagebox.showwarning(
                "任务仍在进行",
                "当前仍有下载、安装、补丁恢复或缓存维护任务。\n"
                "请等待完成，或先取消全部下载，再关闭程序。",
                parent=self.window,
            )
            return
        self._hide_game_picker()
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
        speed_text = f" · {_format_speed(speed)}" if speed else ""
        eta = snapshot.eta_seconds
        eta_text = f" · 约 {eta:.0f} 秒" if eta is not None and eta > 0 else ""
        task_id = snapshot.spec.task_id
        entry = next(
            (item for item in self.catalog_entries if self._dlc_task_id(item.dlc_id) == task_id),
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
            f"{label} · {_format_size(snapshot.bytes_downloaded)}"
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
        if entry is not None and snapshot.state in terminal:
            self._show_install_state(entry)

    def _scan_games(self) -> None:
        if self.current_installation is not None and self._content_work_is_active():
            self._notify("请先取消或结束当前下载/安装任务，再重新扫描游戏", error=True)
            return
        generation = self.game_selection_generation
        cartridge_id = self.cartridge.cartridge_id
        game_name = self.cartridge.adapter.descriptor.display_name
        if self.discovery is None:
            self.game_status.configure(text=f"{game_name} · 初始化失败")
            self.game_path.configure(text="游戏发现服务不可用，请查看日志")
            return
        self._set_game_buttons("disabled")
        self.game_status.configure(text=f"{game_name} · 正在扫描游戏库……")
        self.top_health.configure(text=f"{game_name} · 正在扫描路径")

        def worker() -> None:
            try:
                report = self.discovery.scan()
                self._post_ui(
                    lambda report=report: self._on_game_scanned(
                        report, generation=generation, cartridge_id=cartridge_id
                    )
                )
            except Exception as error:
                self.context.logger.exception("Game discovery failed")
                message = str(error)
                self._post_ui(
                    lambda message=message: self._show_game_error(
                        message, popup=False, generation=generation,
                        cartridge_id=cartridge_id,
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_game_scanned(
        self, report, *, generation: int | None = None,
        cartridge_id: str | None = None,
    ) -> None:
        if generation is not None and generation != self.game_selection_generation:
            return
        if cartridge_id is not None and cartridge_id != self.cartridge.cartridge_id:
            return
        game_name = self.cartridge.adapter.descriptor.display_name
        self._set_game_buttons("normal")
        installations = [
            installation
            for installation in report.available
            if installation.game_id == self.cartridge.adapter.descriptor.game_id
        ]
        if not installations:
            self.current_installation = None
            self.installed_dlc_paths = {}
            self.active_receipt_dlc_ids = frozenset()
            self.install_recovery_running = False
            self.install_recovery_failed = False
            self.install_recovery_key = None
            self.install_recovery_pending = None
            self.game_status.configure(text="未检测到有效安装")
            suffix = f"（扫描产生 {len(report.issues)} 条诊断信息）" if report.issues else ""
            self.game_path.configure(
                text=f"可使用“选择目录”手动指定 {game_name} 根目录{suffix}"
            )
            self.open_game_button.configure(state="disabled")
            self.launch_game_button.configure(state="disabled")
            self.top_health.configure(text=f"{game_name} · 未检测到有效路径")
            self._render_catalog_rows()
            return

        installation = next(
            (item for item in installations if item.selected),
            installations[0],
        )
        self._show_installation(installation)

    def _choose_game_path(self) -> None:
        if self.discovery is None:
            return
        if self.current_installation is not None and self._content_work_is_active():
            self._notify("请先取消或结束当前下载/安装任务，再更改游戏目录", error=True)
            return
        selected = filedialog.askdirectory(
            title=f"选择 {self.cartridge.adapter.descriptor.display_name} 游戏根目录",
            parent=self.window,
            mustexist=True,
        )
        if not selected:
            return
        generation = self.game_selection_generation
        cartridge_id = self.cartridge.cartridge_id
        adapter_id = self.cartridge.adapter.descriptor.adapter_id
        self._set_game_buttons("disabled")
        self.game_status.configure(
            text=f"{self.cartridge.adapter.descriptor.display_name} · 正在验证所选目录……"
        )

        def worker() -> None:
            try:
                installation = self.discovery.add_manual(
                    adapter_id,
                    Path(selected),
                    select=True,
                )
                self._post_ui(
                    lambda installation=installation: self._show_installation(
                        installation, generation=generation,
                        cartridge_id=cartridge_id,
                    ),
                )
            except Exception as error:
                self.context.logger.exception("Manual game path validation failed")
                message = str(error)
                self._post_ui(
                    lambda message=message: self._show_game_error(
                        message, generation=generation,
                        cartridge_id=cartridge_id,
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_installation(
        self, installation, *, generation: int | None = None,
        cartridge_id: str | None = None,
    ) -> None:
        if generation is not None and generation != self.game_selection_generation:
            return
        if cartridge_id is not None and cartridge_id != self.cartridge.cartridge_id:
            return
        self.current_installation = installation
        self._refresh_installed_dlc_paths()
        self.auto_install_attempted.clear()
        self._set_game_buttons("normal")
        self.game_status.configure(text="路径已验证")
        self.game_path.configure(text=str(installation.root))
        self.open_game_button.configure(state="normal")
        self.launch_game_button.configure(state="normal")
        self.top_health.configure(
            text=f"{self.cartridge.adapter.descriptor.display_name} · 路径正常"
        )
        self.selected_dlc_ids = {
            dlc_id for dlc_id in self.selected_dlc_ids
            if not any(
                entry.dlc_id == dlc_id and self._is_entry_installed(entry)
                for entry in self.catalog_entries
            )
        }
        self._render_catalog_rows()
        self._recover_incomplete_installs(
            installation.root,
            generation=(
                self.game_selection_generation if generation is None else generation
            ),
            cartridge_id=self.cartridge.cartridge_id,
        )

    def _recover_incomplete_installs(
        self, game_root: Path, *, generation: int, cartridge_id: str
    ) -> None:
        service = self.install_service
        if service is None:
            self._schedule_ready_installs()
            return
        installation = self.current_installation
        try:
            game_state = (
                self.cartridge.adapter.inspect(installation)
                if installation is not None else None
            )
        except Exception:
            self.install_recovery_failed = True
            self.context.logger.exception(
                "Unable to verify game state before transaction recovery"
            )
            self.catalog_preview.configure(
                text="无法确认游戏是否运行；已暂停安装恢复"
            )
            self._set_batch_download_state(self.batch_download_state)
            return
        if game_state is None or game_state.running:
            self.install_recovery_failed = True
            self.catalog_preview.configure(
                text="游戏正在运行；请关闭游戏并重新扫描后再安装"
            )
            self._set_batch_download_state(self.batch_download_state)
            return
        key = (generation, cartridge_id, str(Path(game_root).resolve(strict=False)))
        if self.install_recovery_running:
            if key != self.install_recovery_key:
                self.install_recovery_pending = (game_root, generation, cartridge_id)
            return
        self.install_recovery_failed = False
        self.install_recovery_running = True
        self.install_recovery_key = key
        self._set_batch_download_state(self.batch_download_state)

        def worker() -> None:
            try:
                recovered = service.recover_incomplete((game_root,))
                self._post_ui(
                    lambda key=key, recovered=recovered:
                    self._finish_install_recovery(key, recovered, None)
                )
            except Exception as error:
                self.context.logger.exception("Interrupted install recovery failed")
                message = str(error)
                self._post_ui(
                    lambda key=key, message=message:
                    self._finish_install_recovery(key, (), message)
                )

        threading.Thread(
            target=worker, daemon=True, name="install-transaction-recovery"
        ).start()

    def _finish_install_recovery(self, key, recovered, error: str | None) -> None:
        if key != self.install_recovery_key:
            return
        self.install_recovery_running = False
        self.install_recovery_key = None
        pending = self.install_recovery_pending
        self.install_recovery_pending = None
        generation, cartridge_id, game_root = key
        stale = (
            generation != self.game_selection_generation
            or cartridge_id != self.cartridge.cartridge_id
            or self.current_installation is None
            or str(self.current_installation.root.resolve(strict=False)) != game_root
        )
        if not stale and error is not None:
            self.install_recovery_failed = True
            self.catalog_preview.configure(text="检测到未完成安装，但自动恢复失败")
            self._notify("未完成安装恢复失败，请查看日志后重新扫描", error=True)
            messagebox.showwarning(
                "安装恢复失败",
                f"程序没有继续自动安装，以免覆盖尚未恢复的文件。\n\n{error}",
                parent=self.window,
            )
        elif not stale and recovered:
            self.install_recovery_failed = False
            self._refresh_installed_dlc_paths()
            self._refresh_active_receipt_dlc_ids()
            self._render_catalog_rows()
            self._notify(f"已安全恢复 {len(recovered)} 个中断安装事务")
        if not stale and error is None:
            self.install_recovery_failed = False
            self._set_batch_download_state(self.batch_download_state)
            self._schedule_ready_installs()
        if pending is not None:
            pending_root, pending_generation, pending_cartridge_id = pending
            self._recover_incomplete_installs(
                pending_root,
                generation=pending_generation,
                cartridge_id=pending_cartridge_id,
            )

    def _show_game_error(
        self, message: str, *, popup: bool = True,
        generation: int | None = None, cartridge_id: str | None = None,
    ) -> None:
        if generation is not None and generation != self.game_selection_generation:
            return
        if cartridge_id is not None and cartridge_id != self.cartridge.cartridge_id:
            return
        self._set_game_buttons("normal")
        self.game_status.configure(
            text=f"{self.cartridge.adapter.descriptor.display_name} · 路径验证失败"
        )
        self.game_path.configure(text=message)
        self.top_health.configure(
            text=f"{self.cartridge.adapter.descriptor.display_name} · 路径异常"
        )
        if popup:
            messagebox.showerror("游戏路径无效", message, parent=self.window)

    def _open_game_directory(self) -> None:
        if self.current_installation is None:
            return
        try:
            open_directory(self.current_installation.root)
        except Exception as error:
            self._show_game_error(str(error))

    def _require_game_stopped(self, action: str) -> bool:
        """Fail closed before changing files that may be locked by the game."""
        if (
            self.auto_install_worker_running
            or self.cache_cleanup_running
            or self.batch_download_state != "idle"
            or self.patch_workflow_state != "idle"
        ):
            messagebox.showwarning(
                "当前任务尚未结束",
                f"请等待下载、自动安装、补丁或缓存维护完成后再执行“{action}”。",
                parent=self.window,
            )
            return False
        if self.install_recovery_running:
            messagebox.showwarning(
                "正在检查安装事务",
                f"请等待中断安装恢复完成后再执行“{action}”。",
                parent=self.window,
            )
            return False
        if self.install_recovery_failed:
            messagebox.showwarning(
                "安装恢复尚未完成",
                f"为避免覆盖未恢复文件，暂不执行“{action}”。\n"
                "请关闭游戏后点击“重新扫描”，确认恢复成功再重试。",
                parent=self.window,
            )
            return False
        if self.manual_file_operation_token is not None:
            messagebox.showwarning(
                "文件操作尚未结束",
                "请等待当前 DLC 检查、安装或卸载操作结束。",
                parent=self.window,
            )
            return False
        installation = self.current_installation
        if installation is None:
            return False
        try:
            state = self.cartridge.adapter.inspect(installation)
        except Exception as error:
            self.context.logger.exception("Unable to verify game process state")
            messagebox.showwarning(
                "无法确认游戏状态",
                f"执行“{action}”前无法确认游戏是否正在运行：\n{error}\n\n"
                "请关闭游戏后重新扫描，再重试。",
                parent=self.window,
            )
            return False
        if not state.running:
            return True
        messagebox.showwarning(
            "游戏正在运行",
            f"检测到 {self.cartridge.adapter.descriptor.display_name} 正在运行。\n"
            f"为避免文件占用或安装损坏，请关闭游戏后再执行“{action}”。",
            parent=self.window,
        )
        return False

    def _launch_game(self) -> None:
        webbrowser.open(f"steam://rungameid/{self.cartridge.store_app_id}")

    def _auto_check_update(self) -> None:
        """Startup update check with quiet retries so a mandatory update is
        surfaced even when the network is slow on first launch."""
        delays = (15_000, 45_000)

        def run(remaining: tuple[int, ...]) -> None:
            try:
                release = self.context.updates.check()
                self._post_ui(lambda release=release: self._on_checked(release))
            except Exception as error:
                self.context.logger.warning(
                    "Startup update check failed: %s", error
                )
                if remaining:
                    self.window.after(remaining[0], lambda: run(remaining[1:]))

        run(delays)

    def _set_update_activity_visible(self, visible: bool, *, checking: bool = False) -> None:
        if visible:
            self.progress.grid()
            self.update_cancel_button.grid()
            if checking:
                self.progress.configure(mode="indeterminate")
                self.progress.start()
            else:
                self.progress.stop()
                self.progress.configure(mode="determinate")
        else:
            self.progress.stop()
            self.progress.grid_remove()
            self.update_cancel_button.grid_remove()

    def _check_update(self) -> None:
        if not self.context.updates.enabled:
            messagebox.showinfo(
                "更新尚未配置",
                "当前下载源没有配置对应的程序更新清单。",
                parent=self.window,
            )
            return
        self.update_button.configure(state="disabled")
        self.status.configure(text="正在检查更新……")
        self._set_update_activity_visible(True, checking=True)

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
            self._set_update_activity_visible(False)
            return
        if release.mandatory:
            messagebox.showinfo(
                "发现新版本",
                (
                    f"\u68c0\u6d4b\u5230\u65b0\u7248\u672c v{release.version}"
                    f"\uff08\u91cd\u8981\u66f4\u65b0\uff09\n\n"
                    f"{release.notes or ''}\n\n"
                    "\u672c\u6b21\u66f4\u65b0\u9700\u5b8c\u6210\u540e\u624d\u80fd"
                    "\u7ee7\u7eed\u4f7f\u7528\uff0c\u6b63\u5728\u51c6\u5907\u5b89\u88c5"
                    "\uff0c\u8bf7\u7a0d\u5019\u2026\u2026"
                ),
                parent=self.window,
            )
            self.status.configure(
                text=(
                    f"\u6b63\u5728\u51c6\u5907\u5b89\u88c5 v{release.version}"
                    f"\uff08\u91cd\u8981\u66f4\u65b0\uff09\u2026\u2026"
                )
            )
        else:
            answer = messagebox.askyesno(
                "发现新版本",
                f"发现 v{release.version}\n\n{release.notes or '是否立即安装？'}",
                parent=self.window,
            )
            if not answer:
                self.status.configure(text=f"已发现 v{release.version}，暂未安装")
                self.update_button.configure(state="normal")
                self._set_update_activity_visible(False)
                return
        cancel_event = threading.Event()
        self.update_download_active = True
        self.update_download_cancelling = False
        self.update_download_preparing = False
        self.update_download_version = release.version
        self.update_download_current = 0
        self.update_download_total = release.size
        self.update_download_speed = 0.0
        self.update_download_started_at = time.monotonic()
        self.update_download_cancel_event = cancel_event
        self.progress.set(0)
        self._set_update_activity_visible(True)
        self.update_cancel_button.configure(state="normal")
        self.status.configure(text=f"正在下载 v{release.version}……")
        self._refresh_update_download_task()

        def progress(current: int, total: int | None) -> None:
            self._post_ui(
                lambda: self._record_update_download_progress(current, total)
            )

        def worker() -> None:
            try:
                if release.kind == "full":
                    self.context.updates.start_full_update(
                        release, progress, cancel_event.is_set
                    )
                    self._post_ui(lambda: self._full_update_prepared(release.version))
                else:
                    self.context.updates.install(
                        release, progress, cancel_event.is_set
                    )
                    self._post_ui(lambda: self._installed(release.version))
            except Exception as error:
                self.context.logger.exception("Update installation failed")
                message = str(error)
                if cancel_event.is_set():
                    self._post_ui(self._update_download_cancelled)
                else:
                    self._post_ui(
                        lambda message=message: self._update_download_failed(message)
                    )

        threading.Thread(target=worker, daemon=True).start()

    def _record_update_download_progress(
        self, current: int, total: int | None,
    ) -> None:
        if not self.update_download_active:
            return
        self.update_download_current = current
        self.update_download_total = total
        elapsed = max(time.monotonic() - self.update_download_started_at, 0.001)
        self.update_download_speed = current / elapsed
        if total:
            self.progress.set(min(current / total, 1))
            self.status.configure(
                text=(
                    f"正在下载 v{self.update_download_version}…… "
                    f"{_format_size(current)}/{_format_size(total)} · "
                    f"{_format_speed(self.update_download_speed)}"
                )
            )
            if current >= total:
                self.update_download_preparing = True
                self.update_cancel_button.configure(state="disabled")
        else:
            self.status.configure(
                text=(
                    f"正在下载 v{self.update_download_version}…… "
                    f"{_format_size(current)} · "
                    f"{_format_speed(self.update_download_speed)}"
                )
            )
        self._refresh_update_download_task()

    def _cancel_update_download(self) -> None:
        event = self.update_download_cancel_event
        if (
            event is None
            or not self.update_download_active
            or self.update_download_cancelling
            or self.update_download_preparing
        ):
            return
        self.update_download_cancelling = True
        event.set()
        self.update_cancel_button.configure(state="disabled")
        self.status.configure(text="正在取消程序更新下载……")
        self._refresh_update_download_task()

    def _clear_update_download(self) -> None:
        self.update_download_active = False
        self.update_download_cancelling = False
        self.update_download_preparing = False
        self.update_download_speed = 0.0
        self.update_download_cancel_event = None
        self._set_update_activity_visible(False)
        self.update_cancel_button.configure(state="disabled")
        if getattr(self, "current_page", None) == "下载任务":
            self._refresh_task_page()

    def _update_download_cancelled(self) -> None:
        self._clear_update_download()
        self.status.configure(text="程序更新下载已取消")
        self.update_button.configure(state="normal")
        self._notify("程序更新下载已取消")

    def _update_download_failed(self, message: str) -> None:
        self._clear_update_download()
        self._show_error(message)

    def _full_update_prepared(self, version: str) -> None:
        self.progress.set(1)
        self.update_download_preparing = True
        self.update_cancel_button.configure(state="disabled")
        self._refresh_update_download_task()
        self.status.configure(text=f"v{version} 已准备，正在退出以替换启动器……")
        self.window.after(700, self.context.exit_for_full_update)

    def _installed(self, version: str) -> None:
        self.progress.set(1)
        self._clear_update_download()
        self.status.configure(text=f"v{version} 已安装，重启后生效")
        if messagebox.askyesno("更新完成", "模块更新已安全安装，是否立即重启？", parent=self.window):
            self.context.restart()
        self.update_button.configure(state="normal")

    def _show_error(self, message: str) -> None:
        self._set_update_activity_visible(False)
        self.status.configure(text="更新失败")
        self.update_button.configure(state="normal")
        messagebox.showerror("更新失败", message, parent=self.window)

    def run(self) -> None:
        # Show the window inside the event loop: a bare deiconify() before
        # mainloop() can leave the window hidden on some Windows Tk builds.
        self.window.after(0, self._show_main_window)
        self.window.mainloop()

    def _show_main_window(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()


def create_application(context) -> DlcHubApplication:
    return DlcHubApplication(context)
