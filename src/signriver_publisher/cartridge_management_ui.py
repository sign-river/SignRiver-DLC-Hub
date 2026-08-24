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
        self.cartridge_home_page.grid_rowconfigure(1, weight=1)
        self.cartridge_detail_page = ctk.CTkFrame(self.cartridges_tab, fg_color="transparent")
        self.cartridge_detail_page.grid(row=0, column=0, sticky="nsew")
        self.cartridge_detail_page.grid_remove()
        self.cartridge_detail_page.grid_columnconfigure(0, weight=1)
        self.cartridge_detail_page.grid_rowconfigure(2, weight=1)
        ctk.CTkButton(
            self.cartridge_detail_page, text="← 返回卡带与公告", width=150,
            fg_color="transparent", text_color=BLUE, hover_color="#EAF4FD",
            command=self._show_cartridge_home,
        ).grid(row=0, column=0, padx=8, pady=(4, 0), sticky="w")

        toolbar = self._card(self.cartridge_home_page, 0, "卡带统一管理")
        toolbar.grid_columnconfigure(0, weight=2)
        toolbar.grid_columnconfigure(1, weight=3)
        toolbar.grid_rowconfigure(3, weight=0)
        self.hub_summary = ctk.CTkLabel(
            toolbar,
            text="正在读取卡带…",
            text_color=TEXT,
            anchor="w",
            justify="left",
        )
        self.hub_summary.grid(
            row=1, column=0, padx=(22, 14), pady=(0, 4), sticky="ew"
        )
        self.hub_hint = ctk.CTkLabel(
            toolbar,
            text=(
                "完整主表会统一生成；GitLink 发布时按卡带逐项比较，"
                "只上传新增或发生变化的文档。"
            ),
            text_color=MUTED,
            anchor="w",
        )
        self.hub_hint.grid(
            row=2, column=0, padx=(22, 14), pady=(0, 10), sticky="new"
        )

        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.grid(
            row=1, column=1, rowspan=2, padx=(8, 18), pady=(0, 10), sticky="nsew"
        )
        for column in range(4):
            actions.grid_columnconfigure(column, weight=1, uniform="hub_actions")
        for row in range(2):
            actions.grid_rowconfigure(row, weight=1, uniform="hub_action_rows")
        self.hub_refresh_button = ctk.CTkButton(
            actions,
            text="刷新卡带",
            fg_color=LIGHT_BLUE,
            command=self.refresh_cartridge_management,
        )
        self.hub_refresh_button.grid(row=0, column=0, padx=4, pady=3, sticky="nsew")
        self.announcement_manage_button = ctk.CTkButton(
            actions,
            text="管理公告",
            fg_color=LIGHT_BLUE,
            command=self.open_announcement_manager,
        )
        self.announcement_manage_button.grid(row=0, column=1, padx=4, pady=3, sticky="nsew")
        self.hub_generate_button = ctk.CTkButton(
            actions,
            text="重新生成全部",
            fg_color=LIGHT_BLUE,
            command=self.generate_client_hub,
        )
        self.hub_generate_button.grid(row=0, column=2, padx=4, pady=3, sticky="nsew")
        ctk.CTkButton(
            actions,
            text="打开 hub 目录",
            fg_color=LIGHT_BLUE,
            command=self.open_hub_output_folder,
        ).grid(row=0, column=3, padx=4, pady=3, sticky="nsew")
        ctk.CTkButton(
            actions,
            text="打开指南目录",
            fg_color=LIGHT_BLUE,
            command=self.open_guides_source_folder,
        ).grid(row=1, column=0, padx=4, pady=3, sticky="nsew")
        self.hub_publish_button = ctk.CTkButton(
            actions,
            text="一键双端发布卡带",
            fg_color=BLUE,
            command=self.publish_cartridge_hub_mirror,
        )
        self.hub_publish_button.grid(row=1, column=1, padx=4, pady=3, sticky="nsew")
        self.guides_publish_button = ctk.CTkButton(
            actions,
            text="双端发布指南",
            fg_color=BLUE,
            command=self.publish_guides_mirror,
        )
        self.guides_publish_button.grid(row=1, column=2, padx=4, pady=3, sticky="nsew")
        ctk.CTkButton(
            actions,
            text="全部游戏卡带",
            fg_color=LIGHT_BLUE,
            command=self._show_cartridge_detail,
        ).grid(row=1, column=3, padx=4, pady=3, sticky="nsew")

        transfer = ctk.CTkFrame(toolbar, fg_color="transparent")
        transfer.grid(
            row=4, column=0, columnspan=2, padx=22, pady=(0, 14), sticky="ew"
        )
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

        workflow = self._card(self.cartridge_home_page, 1, "发布流程")
        workflow.grid_rowconfigure(1, weight=1)
        workflow.grid_columnconfigure((0, 1, 2), weight=1, uniform="hub_workflow")
        workflow_steps = (
            ("1  刷新卡带", "读取当前游戏卡带与本地生成状态。"),
            ("2  生成主表", "将卡带、公告和指南整理为可发布文件。"),
            ("3  双端发布", "确认内容后同步到 GitLink 与 GitHub。"),
        )
        for column, (title, description) in enumerate(workflow_steps):
            step = ctk.CTkFrame(
                workflow,
                fg_color="#F5F9FE",
                border_width=1,
                border_color="#D8E8F7",
                corner_radius=10,
            )
            step.grid(row=1, column=column, padx=10, pady=(4, 18), sticky="nsew")
            step.grid_rowconfigure(1, weight=1)
            ctk.CTkLabel(
                step,
                text=title,
                font=("Microsoft YaHei UI", 15, "bold"),
                text_color=BLUE,
                anchor="w",
            ).grid(row=0, column=0, padx=16, pady=(16, 6), sticky="nw")
            ctk.CTkLabel(
                step,
                text=description,
                text_color=MUTED,
                justify="left",
                anchor="nw",
                wraplength=260,
            ).grid(row=1, column=0, padx=16, pady=(0, 16), sticky="new")

        list_card = self._card(self.cartridge_detail_page, 1, "全部游戏卡带")
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
        guide_status = self.workspace.guide_resource_summary().status_text
        self.hub_summary.configure(
            text=(
                f"共 {len(profiles)} 张卡带 · 本地已生成 {generated} 张 · "
                f"公告 {self.workspace.announcement_status()} · 报错指南 {guide_status} · "
                f"发布目标 {target} / hub"
            )
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
        """Publish only the optional guide assets to the dedicated guides Release."""
        if not self.workspace.guide_resource_summary().configured:
            messagebox.showinfo("没有可发布的指南", "请先在指南目录配置 guides_index.json。")
            return
        if not self._save_active_settings():
            return
        targets = (
            ("GitLink", self.settings.owner, self.settings.repository, self.settings.token),
            ("GitHub", self.settings.github_owner, self.settings.github_repository, self.settings.github_token),
        )
        if not all(owner and repository and token for _, owner, repository, token in targets):
            messagebox.showerror("无法双端发布指南", "请先填写并保存 GitLink 和 GitHub 的仓库及令牌。")
            return
        if not messagebox.askyesno(
            "确认双端发布指南",
            f"将指南索引、详情和 hub 普通附件同步到：\n\n"
            f"GitLink · {targets[0][1]}/{targets[0][2]} · guides\n"
            f"GitHub · {targets[1][1]}/{targets[1][2]} · guides\n\n是否继续？",
        ):
            return
        if not self._begin_background_mutation("publish", "正在双端发布报错指南"):
            return
        self._active_publish_scope = "guides"
        self._set_publish_buttons_available(False)
        self.hub_generate_button.configure(state="disabled")
        self.hub_publish_button.configure(state="disabled")
        self.guides_publish_button.configure(state="disabled", text="正在发布指南…")
        self.hub_upload_status.configure(text="正在生成指南 Release…")
        self.hub_upload_progress.set(0)
        self._upload_control = UploadControl()

        def worker() -> None:
            stage = "GitLink"
            try:
                assets = self.workspace.guides_publish_assets()
                if not assets:
                    raise RuntimeError("指南目录未生成任何可发布文件")
                total = len(assets) * 2
                profile = self.workspace.guides_release_profile()
                repo = GitLinkRepository(targets[0][1], targets[0][2])
                manager = RemoteResourceManager(GitLinkAttachmentClient(targets[0][3]), repo)
                previous = self.workspace.load_publish_state(profile, repo.owner, repo.name)
                result = manager.sync_release(
                    profile, assets, previous,
                    upload_control=self._upload_control,
                    progress=lambda index, count, name, action: self._post_ui(
                        lambda value=name, step=action: self._log(f"[GitLink guides] {step} {value}")
                    ),
                    upload_progress=lambda index, count, name, sent, size: self._queue_upload_progress(index, total, name, sent, size),
                    checkpoint=lambda state: self.workspace.save_publish_state(profile, state),
                )
                self.workspace.save_publish_state(profile, result.state)
                stage = "GitHub"
                github = GitHubReleaseClient(
                    GitHubRepository(targets[1][1], targets[1][2]), targets[1][3]
                )
                release = github.ensure_release(profile.release_tag, name="SignRiver Guides")
                for index, asset in enumerate(assets, start=1):
                    overall = len(assets) + index
                    github.upload_asset(
                        release, asset.path, replace_existing=True,
                        progress=lambda sent, size, i=overall, value=asset.name: self._queue_upload_progress(i, total, value, sent, size),
                        should_pause=lambda: bool(self._upload_control and self._upload_control.pause_requested),
                    )
                self._post_ui(lambda count=len(assets): self._guides_mirror_publish_done(count))
            except (UploadPaused, GitHubUploadPaused) as error:
                self._post_ui(lambda value=f"{stage}：{error}": self._guides_mirror_publish_failed(value, paused=True))
            except Exception as error:
                self._post_ui(lambda value=f"{stage}：{error}": self._guides_mirror_publish_failed(value))

        threading.Thread(target=worker, daemon=True, name="guides-mirror-publish").start()

    def _guides_mirror_publish_done(self, count: int) -> None:
        self._end_background_mutation("publish")
        self._upload_control = None
        self._set_publish_buttons_available(True)
        self.hub_generate_button.configure(state="normal")
        self.hub_publish_button.configure(state="normal")
        self.guides_publish_button.configure(state="normal", text="双端发布指南")
        self.hub_upload_progress.set(1)
        self.hub_upload_status.configure(text="指南双端发布完成")
        self._log(f"报错指南双端发布完成：每端 {count} 个附件。")
        messagebox.showinfo("指南发布完成", "guides Release 已同步到 GitLink 和 GitHub。")

    def _guides_mirror_publish_failed(self, message: str, *, paused: bool = False) -> None:
        self._end_background_mutation("publish")
        self._upload_control = None
        self._set_publish_buttons_available(True)
        self.hub_generate_button.configure(state="normal")
        self.hub_publish_button.configure(state="normal")
        self.guides_publish_button.configure(state="normal", text="双端发布指南")
        self.hub_publish_pause_button.configure(state="disabled", text="暂停发布")
        self.hub_upload_status.configure(text="指南发布已暂停" if paused else "指南发布失败")
        self._log(f"报错指南双端发布未完成：{message}")
        if paused:
            messagebox.showinfo("指南发布已暂停", message)
        else:
            messagebox.showerror("指南双端发布失败", message)

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
