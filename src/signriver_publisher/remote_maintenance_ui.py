from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .github import GitHubPublisherError, GitHubReleaseClient, GitHubRepository
from .gitlink import GitLinkAttachmentClient, GitLinkError, GitLinkRepository
from .models import GameProfile
from .remote import (
    RemoteAsset,
    RemoteBulkDeleteResult,
    RemoteRelease,
    RemoteResourceManager,
)
from .workspace import WorkspaceError

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
CARD = "#FFFFFF"
TEXT = "#212121"
MUTED = "#757575"
RED = "#E53935"


def _is_immutable_dlc_filename(name: str) -> bool:
    value = name.casefold()
    return value.startswith("dlc") and (value.endswith(".zip") or ".zip.part" in value)


class RemoteMaintenanceUiMixin:
    """Advanced remote-resource maintenance and repository controls."""

    def _build_remote_tab(self) -> None:
        self.remote_tab.grid_rowconfigure(2, weight=1)
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
        self.remote_status.grid(row=0, column=0, padx=18, pady=(13, 5), sticky="ew")
        self.remote_refresh_button = ctk.CTkButton(
            toolbar,
            text="刷新远程",
            width=110,
            fg_color=LIGHT_BLUE,
            command=self.refresh_remote_resources,
        )
        self.remote_refresh_button.grid(row=0, column=1, padx=4, pady=(10, 5))
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
        self.remote_delete_all_button.grid(row=0, column=3, padx=(4, 14), pady=(10, 5))
        ctk.CTkButton(
            toolbar,
            text="选择文件上传",
            width=130,
            fg_color=BLUE,
            command=self.choose_remote_upload,
        ).grid(row=0, column=2, padx=4, pady=(10, 5))
        ctk.CTkButton(
            toolbar,
            text="← 返回资源入口",
            width=142,
            height=34,
            fg_color="transparent",
            text_color=BLUE,
            border_width=1,
            border_color="#90CAF9",
            hover_color="#EAF4FD",
            command=lambda: self.content_tabs.set("DLC / 补丁发布"),
        ).grid(row=1, column=3, padx=(4, 14), pady=(4, 11), sticky="e")

        summary_card = ctk.CTkFrame(
            self.remote_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        summary_card.grid(row=1, column=0, columnspan=2, padx=8, pady=4, sticky="ew")
        summary_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            summary_card,
            text="发布差异摘要",
            font=("Microsoft YaHei UI", 15, "bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, padx=18, pady=(10, 2), sticky="w")
        self.remote_diff_summary = ctk.CTkLabel(
            summary_card,
            text="刷新远程后会显示新增、更新、复用和云端多余文件的数量。",
            text_color=MUTED,
            anchor="w",
        )
        self.remote_diff_summary.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")

        self.remote_detail_container = ctk.CTkFrame(
            self.remote_tab,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        self.remote_detail_container.grid(
            row=2, column=0, columnspan=2, padx=8, pady=(4, 8), sticky="nsew"
        )
        self.remote_detail_container.grid_columnconfigure(1, weight=1)
        self.remote_detail_container.grid_rowconfigure(0, weight=1)
        self.remote_detail_sidebar = ctk.CTkFrame(
            self.remote_detail_container,
            width=154,
            fg_color="#F5F8FC",
            corner_radius=10,
        )
        self.remote_detail_sidebar.grid(
            row=0, column=0, padx=(12, 8), pady=12, sticky="ns"
        )
        self.remote_detail_sidebar.grid_propagate(False)
        ctk.CTkLabel(
            self.remote_detail_sidebar,
            text="查看内容",
            font=("Microsoft YaHei UI", 13, "bold"),
            text_color=MUTED,
        ).pack(anchor="w", padx=14, pady=(14, 8))
        self.remote_changes_nav_button = ctk.CTkButton(
            self.remote_detail_sidebar,
            text="变更清单",
            anchor="w",
            height=36,
            command=lambda: self._select_remote_detail_page("changes"),
        )
        self.remote_changes_nav_button.pack(fill="x", padx=10, pady=3)
        self.remote_details_nav_button = ctk.CTkButton(
            self.remote_detail_sidebar,
            text="云端详情",
            anchor="w",
            height=36,
            fg_color="transparent",
            text_color=BLUE,
            hover_color="#EAF4FD",
            command=lambda: self._select_remote_detail_page("details"),
        )
        self.remote_details_nav_button.pack(fill="x", padx=10, pady=3)
        self.remote_detail_pages = ctk.CTkFrame(
            self.remote_detail_container, fg_color="transparent"
        )
        self.remote_detail_pages.grid(
            row=0, column=1, padx=(0, 12), pady=12, sticky="nsew"
        )
        self.remote_detail_pages.grid_columnconfigure(0, weight=1)
        self.remote_detail_pages.grid_rowconfigure(0, weight=1)
        self.remote_changes_page = ctk.CTkFrame(
            self.remote_detail_pages, fg_color="transparent"
        )
        self.remote_details_page = ctk.CTkFrame(
            self.remote_detail_pages, fg_color="transparent"
        )
        for page in (self.remote_changes_page, self.remote_details_page):
            page.grid_columnconfigure(0, weight=1)
            page.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            self.remote_changes_page,
            text="仅显示本次发布需要关注的文件；缓存一致的 DLC 收进“可复用 DLC”分组。",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, padx=18, pady=(14, 6), sticky="w")
        self.remote_asset_title = ctk.CTkLabel(
            self.remote_details_page,
            text="GitLink Release 附件",
            font=("Microsoft YaHei UI", 19, "bold"),
            text_color=BLUE,
        )
        self.remote_asset_title.grid(row=0, column=0, padx=18, pady=(14, 6), sticky="w")
        self.local_output_list = ctk.CTkScrollableFrame(
            self.remote_changes_page,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
        )
        self.local_output_list.grid(
            row=1, column=0, padx=14, pady=(4, 14), sticky="nsew"
        )
        self.remote_asset_list = ctk.CTkScrollableFrame(
            self.remote_details_page,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
        )
        self.remote_asset_list.grid(
            row=1, column=0, padx=14, pady=(4, 14), sticky="nsew"
        )
        self._select_remote_detail_page("changes")

    def _select_remote_detail_page(self, page: str) -> None:
        """Switch the remote-maintenance content pane from the compact sidebar."""
        selected = page == "changes"
        self.remote_changes_page.grid_forget()
        self.remote_details_page.grid_forget()
        visible_page = self.remote_changes_page if selected else self.remote_details_page
        visible_page.grid(row=0, column=0, sticky="nsew")
        self.remote_changes_nav_button.configure(
            fg_color=BLUE if selected else "transparent",
            text_color="#FFFFFF" if selected else BLUE,
            hover_color="#1565C0" if selected else "#EAF4FD",
        )
        self.remote_details_nav_button.configure(
            fg_color="transparent" if selected else BLUE,
            text_color=BLUE if selected else "#FFFFFF",
            hover_color="#EAF4FD" if selected else "#1565C0",
        )

    def _show_remote_message(self, message: str) -> None:
        for child in self.remote_asset_list.winfo_children():
            child.destroy()
        ctk.CTkLabel(self.remote_asset_list, text=message, text_color=MUTED).pack(
            pady=24
        )
        self._schedule_scrollable_reset(self.remote_asset_list)

    def _fill_remote_diff(
        self, profile: GameProfile, assets: tuple[RemoteAsset, ...]
    ) -> None:
        """Render the metadata-only DLC / patch publish preview.

        Only immutable DLC ZIPs may be reused from the trusted cache. Patches,
        DLLs and other mutable files always replace their same-name attachment.
        No remote attachment is downloaded for this preview.
        """
        local_assets = self.workspace.publish_assets(profile)
        local_files = tuple(asset.path for asset in local_assets)
        # Release attachment names are effectively case-insensitive on the
        # Windows publishing workflow.  Compare normalized keys here as the
        # actual upload pipeline does; otherwise a legacy attachment whose
        # capitalization differs is misleadingly shown as "新增" instead of
        # "需要更新".
        remote_names = {asset.name.casefold() for asset in assets}
        target = (
            {"owner": self.settings.github_owner, "repository": self.settings.github_repository}
            if self._publish_target() == "github"
            else {"owner": self.settings.owner, "repository": self.settings.repository}
        )
        # GitLink can retain a historical attachment title that differs from
        # the logical filename recorded by an earlier publisher version.  An
        # attachment ID that is still present is authoritative evidence that
        # the corresponding logical asset exists remotely, so use it as a
        # comparison alias.  This only affects the preview label: mutable
        # same-name assets continue through the normal replacement path.
        publish_state = self.workspace.load_publish_state(
            profile, target["owner"], target["repository"]
        )
        tracked_assets = publish_state.get("assets", {})
        if isinstance(tracked_assets, dict):
            live_attachment_ids = {asset.asset_id for asset in assets}
            remote_names.update(
                str(name).casefold()
                for name, value in tracked_assets.items()
                if isinstance(value, dict)
                and str(value.get("attachment_id") or "") in live_attachment_ids
            )
        cache = self.workspace.load_content_reuse_cache(profile)
        cache.update(self.release_service.latest_game_content_reuse_cache(
            game_id=profile.game_id, release_tag=profile.release_tag
        ))
        if not cache and self._publish_target() == "gitlink":
            legacy = self.workspace.load_publish_state(
                profile, self.settings.owner, self.settings.repository
            )
            legacy_assets = legacy.get("assets")
            if isinstance(legacy_assets, dict):
                cache = {"gitlink": {"target": target, "assets": legacy_assets}}
        source_cache = cache.get(self._publish_target(), {}) if isinstance(cache, dict) else {}
        cached_assets = source_cache.get("assets", {}) if isinstance(source_cache, dict) and source_cache.get("target") == target else {}
        cached_by_name = {
            str(name).casefold(): value
            for name, value in cached_assets.items()
        } if isinstance(cached_assets, dict) else {}
        local_by_name = {asset.name.casefold(): asset for asset in local_assets}
        for child in self.local_output_list.winfo_children():
            child.destroy()
        if not local_files:
            self.remote_diff_summary.configure(text="尚未生成可检测的本地发布文件。")
            ctk.CTkLabel(
                self.local_output_list,
                text="尚未生成可检测的本地发布文件",
                text_color=MUTED,
            ).pack(pady=24)
        else:
            changes: list[tuple[Path, str, str]] = []
            reusable_rows: list[tuple[Path, str, str]] = []
            for path in local_files:
                name_key = path.name.casefold()
                asset = local_by_name[name_key]
                cached = cached_by_name.get(name_key)
                reuse_match = (
                    _is_immutable_dlc_filename(path.name)
                    and name_key in remote_names
                    and isinstance(cached, dict)
                    and cached.get("sha256") == asset.sha256
                    and int(cached.get("size", cached.get("size_bytes", -1))) == asset.size_bytes
                )
                action = (
                    "云端缓存命中：DLC 一致，将跳过上传"
                    if reuse_match
                    else (
                        "每次更新，将替换云端同名文件"
                        if name_key in remote_names
                        else "将新增到云端"
                    )
                )
                category = "DLC" if _is_immutable_dlc_filename(path.name) else "可变文件"
                (reusable_rows if reuse_match else changes).append((path, category, action))

            remote_only = remote_names - set(local_by_name)
            preserve_remote_only_files = self.workspace.load_preserve_remote_only_files()
            remote_only_label = "云端保留" if preserve_remote_only_files else "云端多余"
            self.remote_diff_summary.configure(
                text=(
                    f"跳过上传 {len(reusable_rows)} · 需要更新 {sum(path.name.casefold() in remote_names for path, _, _ in changes)} "
                    f"· 新增 {sum(path.name.casefold() not in remote_names for path, _, _ in changes)} "
                    f"· {remote_only_label} {len(remote_only)}"
                )
            )

            def render_group(
                title: str, rows: list[tuple[Path, str, str]], color: str
            ) -> None:
                if not rows:
                    return
                ctk.CTkLabel(
                    self.local_output_list,
                    text=f"{title} · {len(rows)}",
                    font=("Microsoft YaHei UI", 13, "bold"),
                    text_color=color,
                    anchor="w",
                ).pack(fill="x", padx=10, pady=(12, 4))
                for path, category, action in rows:
                    row = ctk.CTkFrame(
                        self.local_output_list,
                        fg_color=CARD,
                        border_width=1,
                        border_color="#E0E0E0",
                        corner_radius=8,
                    )
                    row.pack(fill="x", padx=4, pady=3)
                    ctk.CTkLabel(
                        row, text=path.name, anchor="w", text_color=TEXT
                    ).pack(side="left", fill="x", expand=True, padx=(10, 6), pady=8)
                    ctk.CTkLabel(
                        row, text=category, text_color=MUTED, width=64
                    ).pack(side="left", padx=4, pady=8)
                    ctk.CTkLabel(row, text=action, text_color=color).pack(
                        side="right", padx=10, pady=8
                    )
            render_group("需要发布", changes, BLUE)
            render_group("云端缓存命中（可复用 DLC）", reusable_rows, "#2E7D32")
        self._schedule_scrollable_reset(self.local_output_list)
        reusable_names = {
            path.name
            for path in local_files
            if _is_immutable_dlc_filename(path.name)
            and (cached := cached_by_name.get(path.name.casefold())) is not None
            and isinstance(cached, dict)
            and cached.get("sha256") == local_by_name[path.name].sha256
            and int(cached.get("size", cached.get("size_bytes", -1))) == local_by_name[path.name].size_bytes
            and path.name.casefold() in remote_names
        }
        self._fill_remote_assets(
            assets,
            local_names={path.name for path in local_files},
            reusable_names=reusable_names,
            preserve_remote_only_files=self.workspace.load_preserve_remote_only_files(),
        )
        # A refresh is primarily a publish-diff operation.  Always return to
        # that page after rendering so the result cannot remain hidden behind
        # the raw cloud-attachment detail page.
        self._select_remote_detail_page("changes")

    def _fill_remote_assets(
        self,
        assets: tuple[RemoteAsset, ...],
        *,
        local_names: set[str] | None = None,
        reusable_names: set[str] | None = None,
        preserve_remote_only_files: bool = False,
    ) -> None:
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
            action = "云端缓存命中：DLC 一致，将保留" if reusable_names and asset.name in reusable_names else (
                "将被同名文件替换"
                if local_names is not None and asset.name in local_names
                else (
                    "云端保留（兼容发布时不会删除）"
                    if preserve_remote_only_files
                    else "云端保留（批量镜像发布时将删除）"
                )
            )
            ctk.CTkLabel(row, text=action, text_color=MUTED).pack(
                side="left", padx=6, pady=9
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

    def refresh_remote_resources(self) -> None:
        if not self._begin_remote_operation("正在读取远程资源…", mutating=False):
            return
        self._log(f"用户操作：刷新“{self.profile.display_name}”的远程 Release 资源。")
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
        approval = self._confirm_maintenance_authorization(
            "删除单个远端附件",
            f"{self._publish_target()} / {self.profile.release_tag} 将永久删除 {asset.name}",
        )
        if approval is None:
            return
        self._activate_maintenance(approval)
        if not self._begin_remote_operation(f"正在删除 {asset.name}…"):
            self._fail_active_maintenance("远程删除操作未能启动")
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
        approval = self._confirm_maintenance_authorization(
            "删除全部远端附件",
            f"{self._publish_target()} / {self.profile.release_tag} 将永久删除 {len(release.assets)} 个附件",
        )
        if approval is None:
            return
        self._activate_maintenance(approval)
        if not self._begin_remote_operation("正在删除全部远程附件…"):
            self._fail_active_maintenance("批量远程删除操作未能启动")
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
        token = self.settings.token.strip() or None
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

    def _begin_remote_operation(self, message: str, *, mutating: bool = True) -> bool:
        if self._remote_operation_active:
            messagebox.showinfo("远程操作进行中", "请等待当前远程操作完成")
            return False
        if mutating and not self._begin_background_mutation(
            "remote", "正在处理远程资源"
        ):
            return False
        self._remote_operation_active = True
        self._remote_operation_locks_close = mutating
        self.remote_refresh_button.configure(state="disabled")
        self.remote_delete_all_button.configure(state="disabled")
        self.remote_status.configure(text=message)
        return True

    def _remote_loaded(
        self, profile: GameProfile, release: RemoteRelease | None
    ) -> None:
        self._remote_operation_active = False
        if getattr(self, "_remote_operation_locks_close", False):
            self._end_background_mutation("remote")
        self._remote_operation_locks_close = False
        self.remote_refresh_button.configure(state="normal")
        if profile.game_id != self.profile.game_id:
            return
        if release is None:
            self._current_remote_release = None
            self.remote_delete_all_button.configure(state="disabled")
            self.remote_status.configure(
                text=f"{profile.release_tag} · Release 尚未创建"
            )
            self._fill_remote_diff(profile, ())
            return
        self._current_remote_release = release
        self.remote_delete_all_button.configure(
            state="normal" if release.assets else "disabled"
        )
        self.remote_status.configure(
            text=f"{release.tag} · {len(release.assets)} 个远程附件"
        )
        self._fill_remote_diff(profile, release.assets)

    def _remote_mutation_done(
        self,
        profile: GameProfile,
        action: str,
        name: str,
        warnings: tuple[str, ...],
        release: RemoteRelease | None,
    ) -> None:
        self._remote_operation_active = False
        if getattr(self, "_remote_operation_locks_close", False):
            self._end_background_mutation("remote")
        self._remote_operation_locks_close = False
        self.remote_refresh_button.configure(state="normal")
        self._log(f"远程资源{action}完成：{name}")
        self._complete_active_maintenance(action=action, asset=name)
        if profile.game_id == self.profile.game_id:
            if release is None:
                self._current_remote_release = None
                self.remote_delete_all_button.configure(state="disabled")
                self.remote_status.configure(
                    text=f"{profile.release_tag} · Release 尚未创建"
                )
                self._fill_remote_diff(profile, ())
            else:
                self._current_remote_release = release
                self.remote_delete_all_button.configure(
                    state="normal" if release.assets else "disabled"
                )
                self.remote_status.configure(
                    text=f"{release.tag} · {len(release.assets)} 个远程附件"
                )
                self._fill_remote_diff(profile, release.assets)
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
            self._fill_remote_diff(profile, assets)
        summary = f"远程附件删除完成：成功 {len(result.deleted)} 个，失败 {len(result.failures)} 个。"
        self._log(summary)
        if result.failures:
            self._fail_active_maintenance(summary + " " + "；".join(result.failures))
            messagebox.showwarning(
                "部分附件删除失败", summary + "\n\n" + "\n".join(result.failures)
            )
        else:
            self._complete_active_maintenance(deleted=len(result.deleted))
            messagebox.showinfo("全部删除完成", summary)

    def _remote_failed(self, message: str) -> None:
        self._remote_operation_active = False
        if getattr(self, "_remote_operation_locks_close", False):
            self._end_background_mutation("remote")
        self._remote_operation_locks_close = False
        self.remote_refresh_button.configure(state="normal")
        release = self._current_remote_release
        self.remote_delete_all_button.configure(
            state="normal" if release and release.assets else "disabled"
        )
        self.remote_status.configure(text="远程操作失败")
        self._log(f"远程操作失败：{message}")
        self._fail_active_maintenance(message)
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
        owner = self.settings.github_owner.strip()
        name = self.settings.github_repository.strip()
        token = self.settings.github_token.strip()
        if not owner or not name:
            raise GitHubPublisherError("请先在“账户与测试 → 发布目标”填写 GitHub 所有者和仓库名")
        if not token:
            raise GitHubPublisherError("请先在“账户与测试 → 发布目标”保存 GitHub token")
        return GitHubReleaseClient(GitHubRepository(owner, name), token)

    def _repository(self) -> GitLinkRepository:
        owner = self.settings.owner.strip()
        name = self.settings.repository.strip()
        if not owner or not name:
            raise GitLinkError("请先在“账户与测试 → 发布目标”填写 GitLink 所有者和仓库名")
        return GitLinkRepository(owner, name)

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
        approval = self._confirm_maintenance_authorization(
            "采用远端附件作为本地发布状态",
            f"gitlink / {profile.release_tag} 将按名称和大小写入本地发布记录",
        )
        if approval is None:
            return
        self._activate_maintenance(approval)
        if not self._begin_remote_operation("正在核对远程 DLC 附件…"):
            self._fail_active_maintenance("采用远端附件操作未能启动")
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
        self._complete_active_maintenance(
            adopted=len(result.adopted), skipped=len(result.skipped)
        )
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
        self._fail_active_maintenance(message)
        messagebox.showerror("采用远程附件失败", message)
