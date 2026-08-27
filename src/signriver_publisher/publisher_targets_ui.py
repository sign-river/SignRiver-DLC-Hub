from __future__ import annotations

import webbrowser
import threading
from tkinter import messagebox

import customtkinter as ctk

from .github import GitHubReleaseClient, GitHubRepository
from .gitlink import GitLinkAttachmentClient, GitLinkRepository
from .settings import PublisherSettings, PublisherSettingsError


class PublisherTargetsUiMixin:
    """Independent account and frozen-publication-target workspace.

    The workspace only exposes repository coordinates and credential presence.
    Stored tokens are never rendered.  Repository configuration lives here
    rather than redirecting operators into a legacy maintenance screen.
    """

    def _save_active_settings(self) -> bool:
        """Persist current settings without touching removed legacy entries.

        The refactored publisher stores GitLink and GitHub targets directly in
        ``self.settings``.  Some retained compatibility actions still call the
        historical save hook, whose old implementation tried to read the
        removed single-target ``owner_entry`` / ``repo_entry`` / ``token_entry``
        widgets and crashed before the operation could start.
        """
        if self.settings_path is None:
            return True
        try:
            self.settings.save(self.settings_path)
        except PublisherSettingsError as error:
            self._log(f"无法保存本地发布配置：{error}")
            messagebox.showerror("保存本地配置失败", str(error), parent=self)
            return False
        return True

    def _set_publish_buttons_available(self, available: bool) -> None:
        """Refresh only controls that exist in the modular publisher shell."""
        button = getattr(self, "hub_publish_button", None)
        if button is not None:
            button.configure(
                state="normal" if available else "disabled",
                text="一键双端发布卡带",
            )
        extensions_button = getattr(self, "extensions_publish_button", None)
        if extensions_button is not None:
            extensions_button.configure(
                state="normal" if available else "disabled",
                text="双端上传工具文件",
            )
        build_button = getattr(self, "extensions_build_button", None)
        if build_button is not None:
            build_button.configure(state="normal" if available else "disabled")
        local_button = getattr(self, "extensions_local_publish_button", None)
        if local_button is not None:
            local_button.configure(
                state="normal" if available else "disabled",
                text="本地发布指南与工具项",
            )

    def _removed_single_source_action(self) -> None:
        """Prevent a retained legacy method from reviving a removed workflow."""
        messagebox.showinfo(
            "入口已移除",
            "新版发布器只保留发布工作台、上传队列和卡带双端发布；"
            "旧的单源发布与手动采用远端附件入口已移除。",
            parent=self,
        )

    def publish_release(self) -> None:
        self._removed_single_source_action()

    def publish_module_archive(self, *, mirror: bool = False) -> None:
        del mirror
        self._removed_single_source_action()

    def publish_cartridge_hub(self) -> None:
        self._removed_single_source_action()

    def adopt_remote_assets(self) -> None:
        self._removed_single_source_action()

    def _publish_scope_controls(self):
        """Return progress controls for the active mirror-publish scope."""
        if self._active_publish_scope == "hub":
            return (
                self.hub_publish_button,
                self.hub_publish_pause_button,
                self.hub_upload_status,
                self.hub_upload_progress,
            )
        if self._active_publish_scope == "extensions":
            return (
                self.extensions_publish_button,
                self.extensions_publish_pause_button,
                self.extensions_upload_status,
                self.extensions_upload_progress,
            )
        raise RuntimeError("旧单源发布范围已移除")

    def _build_publisher_targets_tab(self) -> None:
        for child in self.publisher_targets_tab.winfo_children():
            child.destroy()
        self.publisher_targets_tab.grid_columnconfigure(0, weight=1)
        self.publisher_targets_tab.grid_rowconfigure(1, weight=1)

        targets = ctk.CTkFrame(self.publisher_targets_tab, fg_color="transparent")
        targets.grid(row=0, column=0, padx=8, pady=(8, 5), sticky="ew")
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

        guide = ctk.CTkFrame(
            self.publisher_targets_tab,
            fg_color="#F7FAFD",
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        guide.grid(row=1, column=0, padx=8, pady=(5, 8), sticky="new")
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
                "• 测试演练前，两端都必须显示测试仓库；若显示正式资产库，请不要开始上传或发布。\n"
                "• 本页不会显示令牌，也不会验证令牌实际登录的是谁；“配置的所有者”仅表示将写入的仓库命名空间。\n"
                "• 修改配置后，请重新加入上传队列或创建新的发布任务，避免新配置与历史记录混用。"
            ),
            anchor="w",
            justify="left",
            wraplength=960,
            text_color="#4F5B66",
        ).grid(row=1, column=0, padx=18, pady=(0, 14), sticky="ew")

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
            f"{provider_name} 后续发布目标：{clean_owner}/{clean_repository}\n\n"
            "已有上传和发布记录的目标不会变化。",
            parent=self,
        )

    def _test_publisher_target_connection(
        self,
        provider: str,
        owner: str,
        repository: str,
        button: ctk.CTkButton,
        status_label: ctk.CTkLabel,
    ) -> None:
        """Perform a read-only repository request without saving the form."""
        clean_owner = owner.strip()
        clean_repository = repository.strip()
        provider_name = "GitHub" if provider == "github" else "GitLink"
        if not clean_owner or not clean_repository:
            status_label.configure(text="请先填写所有者和仓库名。", text_color="#C62828")
            return
        token = self.settings.github_token if provider == "github" else self.settings.token
        if not token:
            status_label.configure(
                text=f"未配置 {provider_name} 令牌，无法测试。",
                text_color="#C62828",
            )
            return

        button.configure(state="disabled", text="正在测试…")
        status_label.configure(text="正在连接并验证访问权限…", text_color="#64748B")

        def worker() -> None:
            try:
                if provider == "github":
                    info = GitHubReleaseClient(
                        GitHubRepository(clean_owner, clean_repository), token
                    ).repository_info()
                    display_name = str(info.get("full_name") or "").strip()
                else:
                    GitLinkAttachmentClient(token).list_releases(
                        GitLinkRepository(clean_owner, clean_repository)
                    )
                    display_name = f"{clean_owner}/{clean_repository}"
            except Exception as error:
                detail = str(error).strip() or error.__class__.__name__
                self._post_ui(
                    lambda value=detail: self._finish_publisher_target_connection_test(
                        button,
                        status_label,
                        provider_name,
                        success=False,
                        detail=value,
                    )
                )
                return
            self._post_ui(
                lambda value=display_name: self._finish_publisher_target_connection_test(
                    button,
                    status_label,
                    provider_name,
                    success=True,
                    detail=value,
                )
            )

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"publisher-target-check-{provider}",
        ).start()

    @staticmethod
    def _finish_publisher_target_connection_test(
        button: ctk.CTkButton,
        status_label: ctk.CTkLabel,
        provider_name: str,
        *,
        success: bool,
        detail: str,
    ) -> None:
        button.configure(state="normal", text="测试连通性")
        if success:
            status_label.configure(
                text=f"✓ 已连接：{detail}", text_color="#2E7D32"
            )
            return
        status_label.configure(
            text=f"连接失败：{detail}", text_color="#C62828"
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
            text=f"{provider} 发布目标",
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
            repository_link = ctk.CTkLabel(
                card,
                text=url,
                anchor="w",
                text_color="#1976D2",
                font=("Consolas", 13, "underline"),
                cursor="hand2",
            )
            repository_link.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")
            repository_link.bind("<Button-1>", lambda _event, value=url: webbrowser.open(value))
            settings_row = 3
        else:
            settings_row = 2

        ctk.CTkFrame(card, height=1, fg_color="#D8DEE6").grid(
            row=settings_row, column=0, padx=16, pady=(2, 12), sticky="ew"
        )
        ctk.CTkLabel(
            card,
            text="账号配置",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color="#3E4A56",
        ).grid(row=settings_row + 1, column=0, padx=16, pady=(0, 4), sticky="w")
        ctk.CTkLabel(card, text="所有者", text_color="#4F5B66").grid(
            row=settings_row + 2, column=0, padx=16, pady=(2, 0), sticky="w"
        )
        owner_entry = ctk.CTkEntry(card, border_color="#BDBDBD")
        owner_entry.insert(0, owner)
        owner_entry.grid(
            row=settings_row + 3, column=0, padx=16, pady=(0, 8), sticky="ew"
        )
        ctk.CTkLabel(card, text="仓库", text_color="#4F5B66").grid(
            row=settings_row + 4, column=0, padx=16, pady=(0, 0), sticky="w"
        )
        repository_entry = ctk.CTkEntry(card, border_color="#BDBDBD")
        repository_entry.insert(0, repository)
        repository_entry.grid(
            row=settings_row + 5, column=0, padx=16, pady=(0, 10), sticky="ew"
        )
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(
            row=settings_row + 6, column=0, padx=16, pady=(0, 6), sticky="w"
        )
        ctk.CTkButton(
            actions,
            text=f"保存 {provider} 目标",
            width=166,
            height=38,
            command=lambda source=provider.lower(), owner_field=owner_entry, repository_field=repository_entry: self._save_publisher_target_settings(
                source, owner_field.get(), repository_field.get()
            ),
        ).pack(side="left")
        connection_button = ctk.CTkButton(
            actions,
            text="测试连通性",
            width=126,
            height=38,
            fg_color="#FFFFFF",
            text_color="#1976D2",
            border_width=1,
            border_color="#90CAF9",
        )
        connection_button.pack(side="left", padx=(8, 0))
        connection_status = ctk.CTkLabel(
            card,
            text="尚未测试（不会保存当前修改）",
            anchor="w",
            text_color="#8291A3",
        )
        connection_status.grid(
            row=settings_row + 7, column=0, padx=16, pady=(0, 16), sticky="ew"
        )
        connection_button.configure(
            command=lambda source=provider.lower(), owner_field=owner_entry, repository_field=repository_entry, test_button=connection_button, status=connection_status: self._test_publisher_target_connection(
                source,
                owner_field.get(),
                repository_field.get(),
                test_button,
                status,
            )
        )
