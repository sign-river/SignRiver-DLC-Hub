from __future__ import annotations

from tkinter import messagebox

from .acceptance_ui import AcceptanceUiMixin
from .announcement_ui import AnnouncementUiMixin
from .cartridge_management_ui import CartridgeManagementUiMixin
from .compatibility_publish_ui import CompatibilityPublishUiMixin
from .content_management_ui import ContentManagementUiMixin
from .legacy_ui import PublisherApplication as _LegacyPublisherApplication
from .publisher_targets_ui import PublisherTargetsUiMixin
from .release_actions_ui import ReleaseActionsUiMixin
from .release_center_ui import ReleaseCenterUiMixin
from .release_service import ReleaseService
from .remote_maintenance_ui import RemoteMaintenanceUiMixin
from .ui_runtime import PublisherUiRuntimeMixin


class PublisherApplication(
    PublisherUiRuntimeMixin,
    ReleaseActionsUiMixin,
    ReleaseCenterUiMixin,
    PublisherTargetsUiMixin,
    ContentManagementUiMixin,
    AcceptanceUiMixin,
    AnnouncementUiMixin,
    CartridgeManagementUiMixin,
    CompatibilityPublishUiMixin,
    RemoteMaintenanceUiMixin,
    _LegacyPublisherApplication,
):
    """Refactored publisher shell composed from task-oriented UI workspaces."""

    def __init__(self, workspace, *, settings=None, settings_path=None) -> None:
        # The batch service must exist before the inherited initializer calls
        # the dynamic task-workspace builder below.
        self.release_service = ReleaseService(workspace.root)
        super().__init__(workspace, settings=settings, settings_path=settings_path)

    def _build_ui(self) -> None:
        import customtkinter as ctk
        from .legacy_ui import BRAND

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color=BRAND, corner_radius=0, height=92)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="SignRiver 发布管理器",
            font=("Microsoft YaHei UI", 26, "bold"),
            text_color="white",
        ).grid(row=0, column=0, padx=(28, 18), pady=(18, 4), sticky="w")
        ctk.CTkLabel(
            header,
            text="按任务完成准备、发布、维护与验收；每个批次都会冻结发布目标。",
            text_color="#E6F2FF",
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, padx=30, pady=(0, 16), sticky="ew")

        self.tabs = ctk.CTkTabview(self, segmented_button_selected_color="#1976D2")
        self.tabs.grid(row=1, column=0, padx=22, pady=18, sticky="nsew")

        self.release_center_tab = self.tabs.add("发布工作台")
        self.content_tab = self.tabs.add("内容准备")
        self.publisher_targets_tab = self.tabs.add("账号与发布目标")
        self.maintenance_tab = self.tabs.add("高级维护")
        self.review_tab = self.tabs.add("核对与验收")

        self._build_release_center_tab()
        self._build_content_workspace()
        self._build_publisher_targets_tab()
        self._build_maintenance_workspace()
        self._build_review_workspace()

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
        import customtkinter as ctk

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        tabs = ctk.CTkTabview(parent)
        tabs.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        return tabs

    def _build_content_workspace(self) -> None:
        self.content_tabs = self._nested_tabs(self.content_tab)
        self.sources_tab = self.content_tabs.add("本地资源")
        self.content_release_tab = self.content_tabs.add("DLC / 补丁发布")
        self.games_tab = self.content_tabs.add("游戏内容")
        self.cartridges_tab = self.content_tabs.add("卡带与 Hub")
        self._build_sources_tab()
        self._build_content_release_tab()
        self._build_games_tab()
        self._build_cartridge_management_tab()

    def _build_review_workspace(self) -> None:
        self.review_tabs = self._nested_tabs(self.review_tab)
        self.acceptance_tab = self.review_tabs.add("人工验收（参考）")
        self.announcement_tab = self.review_tabs.add("公告与说明")
        self._build_acceptance_tab()
        self._build_announcement_tab()

    def _build_maintenance_workspace(self) -> None:
        self.maintenance_tabs = self._nested_tabs(self.maintenance_tab)
        self.build_tab = self.maintenance_tabs.add("兼容发布（回退 / 修复）")
        self.remote_tab = self.maintenance_tabs.add("远端维护（高风险）")
        self._build_publish_tab()
        self._build_remote_tab()
