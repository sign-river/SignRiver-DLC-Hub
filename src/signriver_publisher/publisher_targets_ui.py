from __future__ import annotations

import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from .gitlink import GitLinkRepository
from .settings import PublisherSettings, PublisherSettingsError


class PublisherTargetsUiMixin:
    """Independent account and frozen-publication-target workspace.

    The workspace only exposes repository coordinates and credential presence.
    Stored tokens are never rendered.  Repository configuration lives here
    rather than redirecting operators into a legacy maintenance screen.
    """

    def _build_publisher_targets_tab(self) -> None:
        for child in self.publisher_targets_tab.winfo_children():
            child.destroy()
        self.publisher_targets_tab.grid_columnconfigure(0, weight=1)
        self.publisher_targets_tab.grid_rowconfigure(3, weight=1)

        heading = ctk.CTkFrame(
            self.publisher_targets_tab,
            fg_color="#FFF8E1",
            border_width=1,
            border_color="#F3C969",
            corner_radius=14,
        )
        heading.grid(row=0, column=0, padx=8, pady=(8, 5), sticky="ew")
        heading.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            heading,
            text="账号与发布目标（独立界面）",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color="#9A5B00",
        ).grid(row=0, column=0, padx=18, pady=(14, 3), sticky="w")
        ctk.CTkLabel(
            heading,
            text=(
                "这里集中查看和修改 GitLink、GitHub 的发布账号与目标仓库。"
                "程序更新、DLC 和补丁都会同时写入两端；创建批次后，目标仓库会冻结到批次中。"
            ),
            anchor="w",
            justify="left",
            wraplength=900,
            text_color="#6D5A37",
        ).grid(row=1, column=0, padx=18, pady=(0, 14), sticky="ew")

        targets = ctk.CTkFrame(self.publisher_targets_tab, fg_color="transparent")
        targets.grid(row=1, column=0, padx=8, pady=5, sticky="ew")
        targets.grid_columnconfigure(0, weight=1, uniform="publisher_targets")
        targets.grid_columnconfigure(1, weight=1, uniform="publisher_targets")
        self._build_publisher_target_card(
            targets,
            column=0,
            provider="GitLink",
            owner=self.settings.owner,
            repository=self.settings.repository,
            credential_configured=bool(self.settings.token),
            url_template="https://gitlink.org.cn/{owner}/{repository}",
        )
        self._build_publisher_target_card(
            targets,
            column=1,
            provider="GitHub",
            owner=self.settings.github_owner,
            repository=self.settings.github_repository,
            credential_configured=bool(self.settings.github_token),
            url_template="https://github.com/{owner}/{repository}",
        )

        settings = ctk.CTkFrame(
            self.publisher_targets_tab,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        settings.grid(row=2, column=0, padx=8, pady=(5, 8), sticky="ew")
        settings.grid_columnconfigure(0, weight=1)
        settings.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            settings,
            text="账号配置",
            font=("Microsoft YaHei UI", 17, "bold"),
            text_color="#1976D2",
        ).grid(row=0, column=0, columnspan=2, padx=18, pady=(14, 3), sticky="w")
        ctk.CTkLabel(
            settings,
            text=(
                "直接在本页修改两端的所有者和仓库。令牌不会显示；保存仓库坐标不会改动已保存的令牌。"
                "修改后只影响新建批次，已有批次仍以冻结目标执行。"
            ),
            anchor="w",
            justify="left",
            wraplength=960,
            text_color="#4F5B66",
        ).grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 10), sticky="ew")
        self._build_publisher_target_settings(
            settings,
            column=0,
            provider="GitLink",
            owner=self.settings.owner,
            repository=self.settings.repository,
        )
        self._build_publisher_target_settings(
            settings,
            column=1,
            provider="GitHub",
            owner=self.settings.github_owner,
            repository=self.settings.github_repository,
        )

        guide = ctk.CTkFrame(
            self.publisher_targets_tab,
            fg_color="#F7FAFD",
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        guide.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")
        guide.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            guide,
            text="发布前核对",
            font=("Microsoft YaHei UI", 17, "bold"),
            text_color="#1976D2",
        ).grid(row=0, column=0, padx=18, pady=(14, 3), sticky="w")
        ctk.CTkLabel(
            guide,
            text=(
                "• 测试演练前，两端都必须显示测试仓库；若显示正式资产库，请不要创建或执行发布批次。\n"
                "• 本页不会显示令牌，也不会验证令牌实际登录的是谁；“配置的所有者”仅表示将写入的仓库命名空间。\n"
                "• 修改配置后，请重新创建批次，避免新配置与旧批次混用。"
            ),
            anchor="w",
            justify="left",
            wraplength=960,
            text_color="#4F5B66",
        ).grid(row=1, column=0, padx=18, pady=(0, 14), sticky="ew")

    def _build_publisher_target_settings(
        self,
        parent: ctk.CTkFrame,
        *,
        column: int,
        provider: str,
        owner: str,
        repository: str,
    ) -> None:
        panel = ctk.CTkFrame(parent, fg_color="#F7FAFD", corner_radius=10)
        panel.grid(row=2, column=column, padx=8, pady=(0, 14), sticky="ew")
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            panel,
            text=f"{provider} 账号",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color="#3E4A56",
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        ctk.CTkLabel(panel, text="所有者", text_color="#4F5B66").grid(
            row=1, column=0, padx=14, pady=(2, 0), sticky="w"
        )
        owner_entry = ctk.CTkEntry(panel, border_color="#BDBDBD")
        owner_entry.insert(0, owner)
        owner_entry.grid(row=2, column=0, padx=14, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(panel, text="仓库", text_color="#4F5B66").grid(
            row=3, column=0, padx=14, pady=(0, 0), sticky="w"
        )
        repository_entry = ctk.CTkEntry(panel, border_color="#BDBDBD")
        repository_entry.insert(0, repository)
        repository_entry.grid(row=4, column=0, padx=14, pady=(0, 10), sticky="ew")
        ctk.CTkButton(
            panel,
            text=f"保存 {provider} 目标",
            width=166,
            height=38,
            command=lambda source=provider.lower(), owner_field=owner_entry, repository_field=repository_entry: self._save_publisher_target_settings(
                source, owner_field.get(), repository_field.get()
            ),
        ).grid(row=5, column=0, padx=14, pady=(0, 14), sticky="w")

    def _save_publisher_target_settings(
        self, provider: str, owner: str, repository: str
    ) -> None:
        clean_owner = owner.strip()
        clean_repository = repository.strip()
        if not clean_owner or not clean_repository:
            messagebox.showerror("无法保存账号配置", "所有者和仓库名都不能为空。", parent=self)
            return
        if provider == "github":
            updated = PublisherSettings(
                owner=self.settings.owner,
                repository=self.settings.repository,
                token=self.settings.token,
                github_owner=clean_owner,
                github_repository=clean_repository,
                github_token=self.settings.github_token,
                publish_target=self.settings.publish_target,
            )
            provider_name = "GitHub"
        else:
            updated = PublisherSettings(
                owner=clean_owner,
                repository=clean_repository,
                token=self.settings.token,
                github_owner=self.settings.github_owner,
                github_repository=self.settings.github_repository,
                github_token=self.settings.github_token,
                publish_target=self.settings.publish_target,
            )
            provider_name = "GitLink"
        if self.settings_path is not None:
            try:
                updated.save(self.settings_path)
            except PublisherSettingsError as error:
                messagebox.showerror("保存本地配置失败", str(error), parent=self)
                return
        self.settings = updated
        self.repository = GitLinkRepository(
            self.settings.active_owner, self.settings.active_repository
        )
        self._sync_publish_target_controls()
        if hasattr(self, "cartridge_list"):
            self.refresh_cartridge_management()
        self._build_publisher_targets_tab()
        messagebox.showinfo(
            "账号配置已保存",
            f"{provider_name} 新建批次目标：{clean_owner}/{clean_repository}\n\n"
            "已有批次的发布目标不会变化。",
            parent=self,
        )

    def _build_publisher_target_card(
        self,
        parent: ctk.CTkFrame,
        *,
        column: int,
        provider: str,
        owner: str,
        repository: str,
        credential_configured: bool,
        url_template: str,
    ) -> None:
        card = ctk.CTkFrame(
            parent,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        card.grid(row=0, column=column, padx=4, pady=4, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        clean_owner = owner.strip()
        clean_repository = repository.strip()
        repository_name = (
            f"{clean_owner}/{clean_repository}"
            if clean_owner and clean_repository
            else "未完整配置"
        )
        credential_text = "已配置（已隐藏）" if credential_configured else "未配置"
        ctk.CTkLabel(
            card,
            text=f"{provider} 实际发布目标",
            font=("Microsoft YaHei UI", 18, "bold"),
            text_color="#1976D2",
        ).grid(row=0, column=0, padx=16, pady=(14, 5), sticky="w")
        ctk.CTkLabel(
            card,
            text=(
                f"配置的所有者：{clean_owner or '未配置'}\n"
                f"目标仓库：{repository_name}\n"
                f"凭据状态：{credential_text}"
            ),
            justify="left",
            anchor="w",
            text_color="#3E4A56",
        ).grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        if clean_owner and clean_repository:
            url = url_template.format(owner=clean_owner, repository=clean_repository)
            ctk.CTkLabel(
                card,
                text=url,
                anchor="w",
                text_color="#5D6D7E",
                font=("Consolas", 11),
            ).grid(row=2, column=0, padx=16, pady=(0, 8), sticky="ew")
            ctk.CTkButton(
                card,
                text=f"在浏览器打开 {provider} 仓库",
                width=206,
                height=40,
                command=lambda value=url: webbrowser.open(value),
            ).grid(row=3, column=0, padx=16, pady=(0, 14), sticky="w")
