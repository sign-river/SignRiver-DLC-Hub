from __future__ import annotations

from tkinter import messagebox

from .acceptance_ui import AcceptanceUiMixin
from .announcement_ui import AnnouncementUiMixin
from .cartridge_management_ui import CartridgeManagementUiMixin
from .build_queue import ContentBuildQueue
from .content_management_ui import ContentManagementUiMixin
from .legacy_ui import PublisherApplication as _LegacyPublisherApplication
from .publisher_targets_ui import PublisherTargetsUiMixin
from .release_actions_ui import ReleaseActionsUiMixin
from .release_center_ui import ReleaseCenterUiMixin
from .release_service import ReleaseService
from .remote_maintenance_ui import RemoteMaintenanceUiMixin
from .upload_queue import ContentUploadQueue
from .upload_queue_ui import UploadQueueUiMixin
from .ui_runtime import PublisherUiRuntimeMixin


class _WorkspaceSidebar:
    """Small navigation adapter preserving the old ``add`` / ``set`` API.

    Several workspaces already navigate with ``self.tabs.set(name)``.  Keeping
    that surface lets the outer navigation become a true sidebar without
    coupling resource, cartridge and account workflows to a tab-widget.
    """

    def __init__(self, master) -> None:
        import customtkinter as ctk

        self._frame = ctk.CTkFrame(master, fg_color="#F5F7FA", corner_radius=0)
        self._frame.grid_columnconfigure(1, weight=1)
        self._frame.grid_rowconfigure(0, weight=1)
        self._sidebar = ctk.CTkFrame(self._frame, width=210, corner_radius=0, fg_color="#FFFFFF")
        self._sidebar.grid(row=0, column=0, sticky="ns")
        self._sidebar.grid_propagate(False)
        self._content = ctk.CTkFrame(self._frame, fg_color="transparent", corner_radius=0)
        self._content.grid(row=0, column=1, padx=(14, 18), pady=14, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(
            self._sidebar,
            text="工作区",
            font=("Microsoft YaHei UI", 14, "bold"),
            text_color="#1769C2",
        ).pack(anchor="w", padx=22, pady=(24, 6))
        ctk.CTkLabel(
            self._sidebar,
            text="按工作内容切换",
            text_color="#8291A3",
        ).pack(anchor="w", padx=22, pady=(0, 18))
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None

    def grid(self, **kwargs) -> None:
        self._frame.grid(**kwargs)

    def add(self, name: str):
        import customtkinter as ctk

        if name in self._pages:
            raise ValueError(f"工作区已存在：{name}")
        button = ctk.CTkButton(
            self._sidebar,
            text=name,
            anchor="w",
            height=44,
            corner_radius=9,
            fg_color="transparent",
            text_color="#334155",
            hover_color="#EAF4FD",
            command=lambda value=name: self.set(value),
        )
        button.pack(fill="x", padx=12, pady=3)
        page = ctk.CTkFrame(self._content, fg_color="#FFFFFF", corner_radius=14)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._buttons[name] = button
        self._pages[name] = page
        if self._current is None:
            self.set(name)
        return page

    def set(self, name: str) -> None:
        if name not in self._pages:
            raise ValueError(f"未知工作区：{name}")
        for page_name, page in self._pages.items():
            page.grid_remove()
            selected = page_name == name
            self._buttons[page_name].configure(
                fg_color="#1976D2" if selected else "transparent",
                hover_color="#1565C0" if selected else "#EAF4FD",
                text_color="white" if selected else "#334155",
            )
        self._pages[name].grid()
        self._current = name


class _PageRouter:
    """Non-visual page router for in-workspace action buttons.

    Resource management has prominent purpose-built buttons inside its pages;
    adding another segmented tab bar above them only duplicates navigation.
    """

    def __init__(self, parent) -> None:
        import customtkinter as ctk

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self._host = ctk.CTkFrame(parent, fg_color="transparent")
        self._host.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        self._host.grid_columnconfigure(0, weight=1)
        self._host.grid_rowconfigure(0, weight=1)
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None

    def add(self, name: str, *, scrollable: bool = False):
        import customtkinter as ctk

        if name in self._pages:
            raise ValueError(f"页面已存在：{name}")
        page = (
            ctk.CTkScrollableFrame(
                self._host,
                fg_color="transparent",
                corner_radius=0,
                scrollbar_button_color="#90A4AE",
                scrollbar_button_hover_color="#607D8B",
            )
            if scrollable
            else ctk.CTkFrame(self._host, fg_color="transparent")
        )
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages[name] = page
        if self._current is None:
            self.set(name)
        return page

    def set(self, name: str) -> None:
        if name not in self._pages:
            raise ValueError(f"未知页面：{name}")
        for page in self._pages.values():
            page.grid_remove()
        self._pages[name].grid()
        self._current = name


class _SectionSidebar:
    """Contextual secondary navigation without stacked tab bars.

    The main shell already has a workspace sidebar.  This smaller rail only
    appears inside workspaces that contain several independent tools, keeping
    the active page obvious while leaving the content area free of segmented
    controls and their extra grey container.
    """

    def __init__(self, parent) -> None:
        import customtkinter as ctk

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self._frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._frame.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        self._frame.grid_columnconfigure(1, weight=1)
        self._frame.grid_rowconfigure(0, weight=1)
        self._sidebar = ctk.CTkFrame(
            self._frame,
            width=176,
            fg_color="#F7F9FC",
            corner_radius=12,
        )
        self._sidebar.grid(row=0, column=0, padx=(0, 12), sticky="ns")
        self._sidebar.grid_propagate(False)
        ctk.CTkLabel(
            self._sidebar,
            text="功能页面",
            font=("Microsoft YaHei UI", 13, "bold"),
            text_color="#1769C2",
        ).pack(anchor="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            self._sidebar,
            text="选择要管理的内容",
            font=("Microsoft YaHei UI", 12),
            text_color="#8291A3",
        ).pack(anchor="w", padx=18, pady=(0, 12))
        self._host = ctk.CTkFrame(self._frame, fg_color="transparent")
        self._host.grid(row=0, column=1, sticky="nsew")
        self._host.grid_columnconfigure(0, weight=1)
        self._host.grid_rowconfigure(0, weight=1)
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._current: str | None = None

    def add(self, name: str):
        import customtkinter as ctk

        if name in self._pages:
            raise ValueError(f"页面已存在：{name}")
        button = ctk.CTkButton(
            self._sidebar,
            text=name,
            anchor="w",
            height=40,
            corner_radius=8,
            fg_color="transparent",
            text_color="#334155",
            hover_color="#EAF4FD",
            command=lambda value=name: self.set(value),
        )
        button.pack(fill="x", padx=10, pady=3)
        page = ctk.CTkFrame(self._host, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._buttons[name] = button
        self._pages[name] = page
        if self._current is None:
            self.set(name)
        return page

    def hide(self, name: str) -> None:
        """Keep an internal page available without exposing a sidebar entry."""
        button = self._buttons.get(name)
        if button is not None:
            button.pack_forget()

    def set(self, name: str) -> None:
        if name not in self._pages:
            raise ValueError(f"未知页面：{name}")
        for page_name, page in self._pages.items():
            page.grid_remove()
            selected = page_name == name
            button = self._buttons.get(page_name)
            if button is not None:
                button.configure(
                    fg_color="#1976D2" if selected else "transparent",
                    hover_color="#1565C0" if selected else "#EAF4FD",
                    text_color="white" if selected else "#334155",
                )
        self._pages[name].grid()
        self._current = name


class PublisherApplication(
    PublisherUiRuntimeMixin,
    ReleaseActionsUiMixin,
    ReleaseCenterUiMixin,
    PublisherTargetsUiMixin,
    ContentManagementUiMixin,
    AcceptanceUiMixin,
    AnnouncementUiMixin,
    CartridgeManagementUiMixin,
    RemoteMaintenanceUiMixin,
    UploadQueueUiMixin,
    _LegacyPublisherApplication,
):
    """Refactored publisher shell composed from task-oriented UI workspaces."""

    def _publish_target(self) -> str:
        """Return the active target without depending on the removed legacy menu.

        The old compatibility workspace owned ``publish_target_menu``.  The
        refactored application stores the choice in ``PublisherSettings`` and
        exposes it through the dedicated "发布目标" page instead, so startup
        callbacks must not attempt to read that removed widget.
        """

        return getattr(self.settings, "publish_target", "gitlink")

    def _sync_publish_target_controls(self) -> None:
        """Compatibility no-op for legacy startup callbacks.

        The legacy implementation updated controls that belonged exclusively
        to the removed single-target/compatibility page.  Current target pages
        rebuild their own controls after saving settings.
        """

        return

    def __init__(self, workspace, *, settings=None, settings_path=None) -> None:
        # These runtime flags are read by callbacks scheduled during the inherited
        # initializer, which builds the UI and starts background refresh work.
        self._is_closing = False
        self._ui_pump_running = True
        # The batch service must exist before the inherited initializer calls
        # the dynamic task-workspace builder below.
        self.release_service = ReleaseService(workspace.root)
        self.content_build_queue = ContentBuildQueue(workspace.root)
        self.content_upload_queue = ContentUploadQueue(workspace.root)
        super().__init__(workspace, settings=settings, settings_path=settings_path)

    def _build_ui(self) -> None:
        import customtkinter as ctk
        from .legacy_ui import BRAND

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        # 旧发布器把品牌横幅做成了近两百像素高的“标题页”。发布时真正
        # 需要的是工作区与当前状态，因此改成紧凑的工作台顶栏。
        header = ctk.CTkFrame(self, fg_color=BRAND, corner_radius=0, height=82)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="SignRiver 发布工作台",
            font=("Microsoft YaHei UI", 22, "bold"),
            text_color="white",
        ).grid(row=0, column=0, padx=28, pady=(13, 0), sticky="w")
        ctk.CTkLabel(
            header,
            text="发布包、资源上传、游戏支持数据与账户测试",
            text_color="#E6F2FF",
            anchor="w",
        ).grid(row=1, column=0, padx=30, pady=(0, 13), sticky="w")
        ctk.CTkLabel(
            header,
            text="发布过程会自动保留可恢复记录",
            text_color="#D7ECFF",
            fg_color="#2E76B8",
            corner_radius=12,
            height=30,
        ).grid(row=0, column=1, rowspan=2, padx=28, pady=18, sticky="e")

        self.tabs = _WorkspaceSidebar(self)
        self.tabs.grid(row=1, column=0, sticky="nsew")

        self.release_center_tab = self.tabs.add("发布包与归档")
        self.content_tab = self.tabs.add("资源管理")
        self.game_support_tab = self.tabs.add("游戏支持数据")
        self.account_tab = self.tabs.add("账户与测试")

        self._build_release_center_tab()
        self._build_content_workspace()
        self._build_game_support_workspace()
        self._build_account_test_workspace()

    def _close_publisher(self) -> None:
        """Close only after active release work reaches a safe terminal state."""
        active_preparations = self.acceptance.active_preparations()
        if active_preparations:
            games = ", ".join(
                str(value.get("game_id", "未知游戏")) for value in active_preparations
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

        self._is_closing = True
        self._ui_pump_running = False
        self.withdraw()
        self.destroy()

    def _nested_tabs(self, parent):
        return _SectionSidebar(parent)

    def _build_content_workspace(self) -> None:
        self.content_tabs = _PageRouter(self.content_tab)
        self.sources_tab = self.content_tabs.add("本地资源")
        self.content_release_tab = self.content_tabs.add("DLC / 补丁发布", scrollable=True)
        self.build_queue_tab = self.content_tabs.add("构建队列")
        self.upload_queue_tab = self.content_tabs.add("上传队列")
        self.remote_tab = self.content_tabs.add("远端维护")
        self._build_sources_tab()
        self._build_content_release_tab()
        self._build_build_queue_tab()
        self._build_upload_queue_tab()
        self._build_remote_tab()
        self.content_tabs.set("DLC / 补丁发布")

    def _build_game_support_workspace(self) -> None:
        # 当前工作区只有一个对外页面，直接使用无侧栏的页面路由。
        self.game_support_tabs = _PageRouter(self.game_support_tab)
        self.cartridges_tab = self.game_support_tabs.add("卡带与公告")
        # 游戏配置仍保留为内部页面，供“编辑卡带”跳转；不再占用侧栏入口。
        self.games_tab = self.game_support_tabs.add("游戏配置")
        self._build_games_tab()
        self._build_cartridge_management_tab()

    def _build_account_test_workspace(self) -> None:
        self.account_tabs = self._nested_tabs(self.account_tab)
        self.publisher_targets_tab = self.account_tabs.add("发布目标")
        self.acceptance_tab = self.account_tabs.add("人工验收")
        self._build_publisher_targets_tab()
        self._build_acceptance_tab()

    def _open_cartridge_management(self) -> None:
        """Open the current cartridge and Hub workspace from a legacy entry point."""
        self.tabs.set("游戏支持数据")
        self.game_support_tabs.set("卡带与公告")
        self.refresh_cartridge_management()
