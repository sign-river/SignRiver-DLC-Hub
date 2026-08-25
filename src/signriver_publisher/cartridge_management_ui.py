from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from .github import (
    GitHubReleaseClient,
    GitHubRepository,
    GitHubUploadPaused,
)
from .gitlink import (
    GitLinkAttachmentClient,
    GitLinkRepository,
    UploadControl,
    UploadPaused,
)
from .models import GameProfile, PublishAsset
from .remote import RemoteResourceManager

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
CARD = "#FFFFFF"
TEXT = "#212121"
MUTED = "#757575"


class CartridgeManagementUiMixin:
    """Cartridge hub generation, status display, and compatibility publishing."""

    def _build_cartridge_management_tab(self) -> None:
        self.cartridges_tab.grid_rowconfigure(0, weight=1)
        self.cartridges_tab.grid_columnconfigure(0, weight=1)

        self.cartridge_home_page = ctk.CTkFrame(self.cartridges_tab, fg_color="transparent")
        self.cartridge_home_page.grid(row=0, column=0, sticky="nsew")
        self.cartridge_home_page.grid_columnconfigure(0, weight=1)
        self.cartridge_detail_page = ctk.CTkFrame(self.cartridges_tab, fg_color="transparent")
        self.cartridge_detail_page.grid(row=0, column=0, sticky="nsew")
        self.cartridge_detail_page.grid_remove()
        self.cartridge_detail_page.grid_columnconfigure(0, weight=1)
        self.cartridge_detail_page.grid_rowconfigure(1, weight=1)
        ctk.CTkButton(
            self.cartridge_detail_page, text="← 返回发布资源管理", width=150,
            fg_color="transparent", text_color=BLUE, hover_color="#EAF4FD",
            command=self._show_cartridge_home,
        ).grid(row=0, column=0, padx=8, pady=(4, 0), sticky="w")

        toolbar = self._card(self.cartridge_home_page, 0, "发布资源统一管理")
        toolbar.grid_columnconfigure(0, weight=1)
        toolbar.grid_rowconfigure(2, weight=1)
        toolbar.grid_rowconfigure(3, weight=0)

        overview = ctk.CTkFrame(toolbar, fg_color="transparent")
        overview.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="ew")
        overview.grid_columnconfigure((0, 1), weight=1, uniform="resource_summary")

        cartridge_overview = ctk.CTkFrame(
            overview, fg_color="#F7FAFE", border_width=1,
            border_color="#D8E6F4", corner_radius=10,
        )
        cartridge_overview.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        cartridge_overview.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            cartridge_overview, text="卡带与公告", text_color=BLUE,
            font=("Microsoft YaHei UI", 14, "bold"), anchor="w",
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="ew")
        self.hub_summary = ctk.CTkLabel(
            cartridge_overview, text="正在读取卡带…", text_color=TEXT,
            anchor="w", justify="left",
        )
        self.hub_summary.grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")
        self.hub_target_summary = ctk.CTkLabel(
            cartridge_overview, text="公告与发布目标：正在读取…", text_color=MUTED,
            anchor="w", justify="left", wraplength=390,
        )
        self.hub_target_summary.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="ew")

        extension_overview = ctk.CTkFrame(
            overview, fg_color="#F7FAFE", border_width=1,
            border_color="#D8E6F4", corner_radius=10,
        )
        extension_overview.grid(row=0, column=1, padx=(6, 0), sticky="nsew")
        extension_overview.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            extension_overview, text="扩展指南与工具", text_color=BLUE,
            font=("Microsoft YaHei UI", 14, "bold"), anchor="w",
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="ew")
        self.hub_status_summary = ctk.CTkLabel(
            extension_overview, text="正在读取扩展资源…", text_color=MUTED,
            anchor="w", justify="left", wraplength=390,
        )
        self.hub_status_summary.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="ew")
        self.hub_refresh_button = ctk.CTkButton(
            overview, text="刷新资源概览", width=132, height=36,
            fg_color=LIGHT_BLUE, command=self.refresh_cartridge_management,
        )
        self.hub_refresh_button.grid(row=0, column=2, padx=(12, 0), sticky="ns")

        operations = ctk.CTkScrollableFrame(toolbar, fg_color="transparent")
        operations.grid(row=2, column=0, padx=18, pady=(0, 10), sticky="nsew")
        operations.grid_columnconfigure(0, weight=1)

        def resource_section(parent, row, title, description):
            section = ctk.CTkFrame(
                parent, fg_color="#F7FAFE", border_width=1,
                border_color="#D8E6F4", corner_radius=10,
            )
            section.grid(row=row, column=0, pady=(0, 10), sticky="ew")
            section.grid_columnconfigure((0, 1), weight=1, uniform="resource_columns")
            ctk.CTkLabel(
                section, text=title, text_color=BLUE,
                font=("Microsoft YaHei UI", 14, "bold"), anchor="w",
            ).grid(row=0, column=0, columnspan=2, padx=14, pady=(12, 2), sticky="ew")
            ctk.CTkLabel(
                section, text=description, text_color=MUTED,
                anchor="w", justify="left",
            ).grid(row=1, column=0, columnspan=2, padx=14, pady=(0, 8), sticky="ew")
            return section

        def operation_group(parent, column, title, description):
            group = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
            group.grid(row=2, column=column, padx=(0, 6) if column == 0 else (6, 0),
                       pady=(0, 12), sticky="nsew")
            group.grid_columnconfigure((0, 1), weight=1, uniform="operation_actions")
            ctk.CTkLabel(
                group, text=title, text_color=BLUE,
                font=("Microsoft YaHei UI", 13, "bold"), anchor="w",
            ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 2), sticky="ew")
            ctk.CTkLabel(
                group, text=description, text_color=MUTED,
                anchor="w", justify="left", wraplength=390,
            ).grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")
            return group

        def action_button(parent, text, command, row, column, *, primary=False, columnspan=1):
            button = ctk.CTkButton(
                parent, text=text, width=190, height=36,
                fg_color=BLUE if primary else LIGHT_BLUE,
                command=command,
            )
            button.grid(
                row=row, column=column, columnspan=columnspan,
                padx=6, pady=4, sticky="ew",
            )
            return button

        cartridge_section = resource_section(
            operations, 0, "卡带与公告",
            "管理游戏卡带、公告与 Hub 发布物。",
        )
        cartridge_browse = operation_group(
            cartridge_section, 0, "浏览与维护",
            "查看或维护已有卡带、公告和 Hub 文件，不会生成或上传。",
        )
        cartridge_publish = operation_group(
            cartridge_section, 1, "生成与发布",
            "先生成全部卡带，再将卡带资源发布到双端。",
        )
        action_button(cartridge_browse, "全部游戏卡带", self._show_cartridge_detail, 2, 0)
        self.announcement_manage_button = action_button(
            cartridge_browse, "管理公告", self.open_announcement_manager, 2, 1
        )
        action_button(
            cartridge_browse, "打开 hub 目录", self.open_hub_output_folder, 3, 0,
            columnspan=2,
        )
        self.hub_generate_button = action_button(
            cartridge_publish, "重新生成全部卡带", self.generate_client_hub, 2, 0
        )
        self.hub_publish_button = action_button(
            cartridge_publish, "一键双端发布卡带", self.publish_cartridge_hub_mirror,
            2, 1, primary=True,
        )

        extension_section = resource_section(
            operations, 1, "扩展指南与工具",
            "管理相互引用的指南、工具索引和工具包。",
        )
        extension_browse = operation_group(
            extension_section, 0, "浏览与维护",
            "查看或维护本地指南和工具源文件，不会生成或上传。",
        )
        extension_publish = operation_group(
            extension_section, 1, "生成与发布",
            "上传前统一校验指南、tools_index.json、工具包与 tool_id 引用。",
        )
        action_button(extension_browse, "打开指南目录", self.open_guides_source_folder, 2, 0)
        action_button(extension_browse, "打开工具目录", self.open_tools_source_folder, 2, 1)
        self.extensions_publish_button = action_button(
            extension_publish, "预检并双端发布扩展", self.publish_extensions_mirror,
            2, 0, primary=True, columnspan=2,
        )
        self.guides_publish_button = self.extensions_publish_button
        ctk.CTkLabel(
            extension_publish,
            text="未修改的扩展文件会由本地成功发布记录中的 SHA-256 跳过；同名新文件直接替换。",
            text_color=MUTED, anchor="w", justify="left", wraplength=390,
        ).grid(row=3, column=0, columnspan=2, padx=12, pady=(6, 10), sticky="ew")
        transfer = ctk.CTkFrame(
            toolbar, fg_color="#F7FAFE", border_width=1,
            border_color="#D8E6F4", corner_radius=10,
        )
        transfer.grid(row=3, column=0, padx=18, pady=(0, 14), sticky="ew")
        transfer.grid_columnconfigure(1, weight=1)
        self.hub_upload_status = ctk.CTkLabel(
            transfer, text="等待发布", width=235, anchor="w", text_color=MUTED,
        )
        self.hub_upload_status.grid(row=0, column=0, padx=(0, 12), sticky="w")
        self.hub_upload_progress = ctk.CTkProgressBar(
            transfer, height=14, progress_color=BLUE,
        )
        self.hub_upload_progress.grid(row=0, column=1, padx=8, sticky="ew")
        self.hub_upload_progress.set(0)
        self.hub_publish_pause_button = ctk.CTkButton(
            transfer, text="暂停发布", width=110, fg_color=LIGHT_BLUE,
            state="disabled", command=self.toggle_publish_pause,
        )
        self.hub_publish_pause_button.grid(row=0, column=2, padx=(12, 0))

        list_card = ctk.CTkFrame(self.cartridge_detail_page, fg_color="transparent")
        list_card.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        list_card.grid_columnconfigure(0, weight=1)
        list_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            list_card,
            text="全部游戏卡带",
            font=("Microsoft YaHei UI", 20, "bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, padx=12, pady=(8, 10), sticky="w")
        self.cartridge_list = ctk.CTkScrollableFrame(
            list_card,
            fg_color="transparent",
        )
        self.cartridge_list.grid(
            row=1, column=0, padx=4, pady=(0, 8), sticky="nsew"
        )

    def _show_cartridge_home(self) -> None:
        self.cartridge_detail_page.grid_remove()
        self.cartridge_home_page.grid()

    def _show_cartridge_detail(self) -> None:
        self.cartridge_home_page.grid_remove()
        self.cartridge_detail_page.grid()
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
        target = f"{self.settings.owner}/{self.settings.repository}"
        extension_status = self.workspace.extension_resource_summary().status_text
        self.hub_summary.configure(
            text=f"共 {len(profiles)} 张卡带 · 本地已生成 {generated} 张"
        )
        self.hub_target_summary.configure(
            text=(
                f"公告 {self.workspace.announcement_status()} · "
                f"发布目标 {target} / hub"
            )
        )
        self.hub_status_summary.configure(
            text=f"{extension_status} · 发布前将校验 tool_id 互相引用"
        )
        self._schedule_scrollable_reset(self.cartridge_list)

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
        self.tabs.set("游戏支持数据")
        self.game_support_tabs.set("游戏配置")

    def _return_to_cartridge_detail(self) -> None:
        """Return from editing a cartridge to its immediate list page."""
        self.tabs.set("游戏支持数据")
        self.game_support_tabs.set("卡带与公告")
        self._show_cartridge_detail()

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
        guide_status = self.workspace.guide_resource_summary().status_text
        self._log(
            f"客户端卡带中心已生成到 {hub_dir}（报错指南 {guide_status}）："
            + "、".join(asset.name for asset in assets)
        )
        messagebox.showinfo(
            "生成完成",
            f"已生成 {len(assets)} 个 hub 文件。\n报错指南：{guide_status}。\n\n"
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

    def publish_guides_mirror(self) -> None:
        """Keep compatibility with old callers while publishing all extensions."""
        self.publish_extensions_mirror()

    def publish_extensions_mirror(self) -> None:
        """Preflight and publish the linked guide and tool Releases together."""
        summary = self.workspace.extension_resource_summary()
        if not summary.guides.configured or summary.guides.error or summary.tools.error:
            messagebox.showerror(
                "扩展预检失败",
                "指南、工具包和相互引用必须完整后才能发布：\n\n"
                f"{summary.status_text}",
            )
            return
        if not self._save_active_settings():
            return
        targets = (
            ("GitLink", self.settings.owner, self.settings.repository, self.settings.token),
            ("GitHub", self.settings.github_owner, self.settings.github_repository, self.settings.github_token),
        )
        if not all(owner and repository and token for _, owner, repository, token in targets):
            messagebox.showerror(
                "无法双端发布扩展",
                "请先填写并保存 GitLink 和 GitHub 的仓库及令牌。",
            )
            return
        if not messagebox.askyesno(
            "确认双端发布扩展",
            "将先校验指南索引、指南正文、工具索引、工具包及 tool_id 引用，再依次同步到：\n\n"
            f"GitLink · {targets[0][1]}/{targets[0][2]} · guides\n"
            f"GitLink · {targets[0][1]}/{targets[0][2]} · tools\n"
            f"GitHub · {targets[1][1]}/{targets[1][2]} · guides\n"
            f"GitHub · {targets[1][1]}/{targets[1][2]} · tools\n\n"
            "本地成功发布记录中 SHA-256 未变化的文件将跳过；变更文件按同名覆盖。是否继续？",
        ):
            return
        if not self._begin_background_mutation("publish", "正在预检并双端发布扩展"):
            return
        self._active_publish_scope = "extensions"
        self._set_publish_buttons_available(False)
        self.hub_generate_button.configure(state="disabled")
        self.extensions_publish_button.configure(state="disabled", text="正在预检并发布扩展…")
        self.hub_upload_status.configure(text="正在校验并生成扩展 Release…")
        self.hub_upload_progress.set(0)
        self._upload_control = UploadControl()

        def worker() -> None:
            stage = "预检"
            try:
                plan = self.workspace.extension_publish_assets()
                release_sets = (
                    (self.workspace.guides_release_profile(), plan.guides, "SignRiver Guides"),
                    (self.workspace.tools_release_profile(), plan.tools, "SignRiver Tools"),
                )
                one_host_total = sum(len(assets) for _, assets, _ in release_sets)
                total = one_host_total * 2
                if not one_host_total:
                    raise RuntimeError("扩展目录未生成任何可发布文件")

                stage = "GitLink"
                gitlink_repo = GitLinkRepository(targets[0][1], targets[0][2])
                manager = RemoteResourceManager(GitLinkAttachmentClient(targets[0][3]), gitlink_repo)
                completed = 0
                for profile, assets, _ in release_sets:
                    previous = self.workspace.load_publish_state(profile, gitlink_repo.owner, gitlink_repo.name)
                    result = manager.sync_release(
                        profile, assets, previous,
                        upload_control=self._upload_control,
                        progress=lambda index, count, name, action, tag=profile.release_tag: self._post_ui(
                            lambda value=name, step=action, release_tag=tag: self._log(f"[GitLink {release_tag}] {step} {value}")
                        ),
                        upload_progress=lambda index, count, name, sent, size, offset=completed: self._queue_upload_progress(
                            offset + index, total, name, sent, size
                        ),
                        checkpoint=lambda state, current=profile: self.workspace.save_publish_state(current, state),
                    )
                    self.workspace.save_publish_state(profile, result.state)
                    completed += len(assets)

                stage = "GitHub"
                github_repo = GitHubRepository(targets[1][1], targets[1][2])
                github = GitHubReleaseClient(github_repo, targets[1][3])
                completed = one_host_total
                uploaded = 0
                skipped = 0
                for profile, assets, release_name in release_sets:
                    changed = self.workspace.changed_publish_assets(
                        profile, github_repo.owner, github_repo.name, assets,
                        state_channel="github",
                    )
                    skipped += len(assets) - len(changed)
                    if not changed:
                        self._post_ui(lambda tag=profile.release_tag, count=len(assets): self._log(
                            f"[GitHub {tag}] 本地哈希未变化，跳过 {count} 个附件"
                        ))
                    else:
                        release = github.ensure_release(profile.release_tag, name=release_name)
                        positions = {asset.name: index for index, asset in enumerate(assets, start=1)}
                        for asset in changed:
                            position = completed + positions[asset.name]
                            self._post_ui(lambda tag=profile.release_tag, name=asset.name: self._log(
                                f"[GitHub {tag}] 上传并覆盖 {name}"
                            ))
                            github.upload_asset(
                                release, asset.path, replace_existing=True,
                                progress=lambda sent, size, index=position, name=asset.name: self._queue_upload_progress(
                                    index, total, name, sent, size
                                ),
                                should_pause=lambda: bool(self._upload_control and self._upload_control.pause_requested),
                            )
                            uploaded += 1
                    self.workspace.save_publish_state(
                        profile, self.workspace.publish_state_for_assets(
                            profile, github_repo.owner, github_repo.name, assets
                        ),
                        state_channel="github",
                    )
                    completed += len(assets)
                self._post_ui(lambda guide_count=len(plan.guides), tool_count=len(plan.tools),
                              uploaded_count=uploaded, skipped_count=skipped: self._extensions_mirror_publish_done(
                                  guide_count, tool_count, uploaded_count, skipped_count
                              ))
            except (UploadPaused, GitHubUploadPaused) as error:
                self._post_ui(lambda value=f"{stage}：{error}": self._extensions_mirror_publish_failed(value, paused=True))
            except Exception as error:
                self._post_ui(lambda value=f"{stage}：{error}": self._extensions_mirror_publish_failed(value))

        threading.Thread(target=worker, daemon=True, name="extensions-mirror-publish").start()

    def _extensions_mirror_publish_done(
        self, guide_count: int, tool_count: int, uploaded: int, skipped: int
    ) -> None:
        self._end_background_mutation("publish")
        self._upload_control = None
        self._set_publish_buttons_available(True)
        self.hub_generate_button.configure(state="normal")
        self.hub_upload_progress.set(1)
        self.hub_upload_status.configure(text="指南与工具扩展双端发布完成")
        self._log(
            "指南与工具扩展双端发布完成："
            f"guides 每端 {guide_count} 个附件，tools 每端 {tool_count} 个附件；"
            f"GitHub 上传 {uploaded} 个，按本地哈希跳过 {skipped} 个。"
        )
        self.refresh_cartridge_management()
        messagebox.showinfo("扩展发布完成", "guides 与 tools Release 已同步到 GitLink 和 GitHub。")

    def _extensions_mirror_publish_failed(self, message: str, *, paused: bool = False) -> None:
        self._end_background_mutation("publish")
        self._upload_control = None
        self._set_publish_buttons_available(True)
        self.hub_generate_button.configure(state="normal")
        self.hub_publish_pause_button.configure(state="disabled", text="暂停发布")
        self.hub_upload_status.configure(text="扩展发布已暂停" if paused else "扩展发布失败")
        self._log(f"指南与工具扩展双端发布未完成：{message}")
        if paused:
            messagebox.showinfo("扩展发布已暂停", message)
        else:
            messagebox.showerror("扩展双端发布失败", message)

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
        approval = self._confirm_maintenance_authorization(
            "单源发布卡带中心",
            f"{self._publish_target()} / {owner}/{repository_name} / hub 将同步 {len(profiles)} 张卡带",
        )
        if approval is None:
            return
        self._activate_maintenance(approval)
        if not self._begin_background_mutation(
            "publish", "正在生成并上传 hub Release"
        ):
            self._fail_active_maintenance("卡带中心单源发布未能启动")
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
        self._fail_active_maintenance(message)
        messagebox.showerror("无法发布卡带中心", message)

    def export_client_hub(self) -> None:
        self.tabs.set("游戏支持数据")
        self.game_support_tabs.set("卡带与公告")
        self.generate_client_hub()

    def open_hub_output_folder(self) -> None:
        path = self.workspace.output_dir / "hub"
        path.mkdir(parents=True, exist_ok=True)
        self._open(path)

    def open_guides_source_folder(self) -> None:
        path = self.workspace.guides_source_dir
        path.mkdir(parents=True, exist_ok=True)
        self._open(path)

    def open_tools_source_folder(self) -> None:
        path = self.workspace.tools_source_dir
        path.mkdir(parents=True, exist_ok=True)
        self._open(path)
