from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .github import (
    GitHubPublisherError,
    GitHubReleaseClient,
    GitHubRepository,
    GitHubUploadPaused,
)
from .gitlink import (
    GitLinkAttachmentClient,
    GitLinkError,
    GitLinkRepository,
    UploadControl,
    UploadPaused,
)
from .models import GameProfile, PublishAsset
from .remote import RemoteResourceManager
from .settings import PublisherSettingsError
from .updates import (
    MODULE_ARCHIVE_RELEASE_TAG,
    UPDATE_MANIFEST_ASSET,
    UPDATE_RELEASE_TAG,
    UpdateReleaseDraft,
    inspect_module_archive,
    inspect_update_package,
    release_asset_url,
    write_update_manifest,
)
from .workspace import WorkspaceError

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
TEXT = "#212121"
MUTED = "#757575"


class CompatibilityPublishUiMixin:
    """Legacy build-and-publish workflow retained as an explicit fallback path."""

    def _build_publish_tab(self) -> None:
        self.build_tab.grid_rowconfigure(1, weight=1)
        build_card = self._card(self.build_tab, 0, "兼容发布（回退 / 修复）")
        ctk.CTkLabel(
            build_card,
            text="仅用于标准批次流程不可用时的受控回退或修复；不要与同一批次的标准发布并行执行。",
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(0, 4), sticky="ew")
        actions = ctk.CTkFrame(build_card, fg_color="transparent")
        actions.grid(row=2, column=0, padx=18, pady=(2, 16), sticky="ew")
        self.build_button = ctk.CTkButton(
            actions,
            text="生成全部发布文件",
            width=180,
            fg_color=BLUE,
            command=self.build_all,
        )
        self.build_button.pack(side="left", padx=4)
        self.steam_button = ctk.CTkButton(
            actions,
            text="刷新 Steam 数据",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.refresh_steam_data,
        )
        self.steam_button.pack(side="left", padx=4)
        ctk.CTkButton(
            actions,
            text="打开输出目录",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.open_output_folder,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            actions,
            text="打开卡带管理",
            width=180,
            fg_color=LIGHT_BLUE,
            command=self._open_cartridge_management,
        ).pack(side="left", padx=4)
        self.build_summary = ctk.CTkLabel(actions, text="尚未构建", text_color=MUTED)
        self.build_summary.pack(side="left", padx=18)
        self.freshness_summary = ctk.CTkLabel(
            build_card,
            text="资源提交时间：切换卡带或构建后自动读取本地包修改时间",
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=980,
        )
        self.freshness_summary.grid(row=3, column=0, padx=22, pady=(0, 14), sticky="ew")

        remote = self._card(self.build_tab, 1, "发布控制台")
        remote.grid_rowconfigure(6, weight=1)
        settings = ctk.CTkFrame(remote, fg_color="transparent")
        settings.grid(row=1, column=0, padx=20, sticky="ew")
        settings.grid_columnconfigure((1, 3, 5), weight=1)
        ctk.CTkLabel(settings, text="发布目标").grid(row=0, column=0, padx=(0, 8))
        self.publish_target_menu = ctk.CTkOptionMenu(
            settings,
            values=["GitLink", "GitHub"],
            fg_color=LIGHT_BLUE,
            button_color=BLUE,
            command=self._on_publish_target_changed,
        )
        self.publish_target_menu.set(
            "GitHub" if self.settings.publish_target == "github" else "GitLink"
        )
        self.publish_target_menu.grid(row=0, column=1, padx=(0, 18), sticky="ew")
        ctk.CTkLabel(settings, text="所有者").grid(row=0, column=2, padx=(0, 8))
        self.owner_entry = ctk.CTkEntry(settings, border_color="#BDBDBD")
        self.owner_entry.insert(0, self.settings.active_owner)
        self.owner_entry.grid(row=0, column=3, padx=(0, 18), sticky="ew")
        ctk.CTkLabel(settings, text="仓库").grid(row=0, column=4, padx=(0, 8))
        self.repo_entry = ctk.CTkEntry(settings, border_color="#BDBDBD")
        self.repo_entry.insert(0, self.settings.active_repository)
        self.repo_entry.grid(row=0, column=5, padx=(0, 10), sticky="ew")
        regions = ctk.CTkFrame(remote, fg_color="transparent")
        regions.grid(row=2, column=0, padx=18, pady=12, sticky="ew")
        regions.grid_columnconfigure((0, 1, 2), weight=1, uniform="publish")
        region_specs = (
            (
                "DLC / 补丁流水线",
                "常规双源发布请进入批次工作台；此处仅保留兼容维护能力",
            ),
            (
                "发布客户端",
                "完整程序更新包与双源更新清单",
            ),
            (
                "维护基础设施",
                "历史模块归档，以及卡带与公告入口",
            ),
        )
        region_frames = []
        for column, (title, hint) in enumerate(region_specs):
            frame = ctk.CTkFrame(
                regions, fg_color="#F7F9FC", border_width=1,
                border_color="#D8DEE6", corner_radius=10,
            )
            frame.grid(
                row=0, column=column, padx=5, pady=0, sticky="nsew"
            )
            ctk.CTkLabel(
                frame, text=title, font=("Microsoft YaHei UI", 16, "bold"),
                text_color=BLUE, anchor="w",
            ).pack(fill="x", padx=14, pady=(12, 2))
            ctk.CTkLabel(
                frame, text=hint, text_color=MUTED, anchor="w",
                justify="left", wraplength=300,
            ).pack(fill="x", padx=14, pady=(0, 8))
            region_frames.append(frame)

        game_region, client_region, infrastructure_region = region_frames
        advanced = ctk.CTkFrame(
            remote, fg_color="#F7F9FC", border_width=1,
            border_color="#D8DEE6", corner_radius=10,
        )
        self.publish_advanced_frame = advanced
        self.check_gitlink_button = ctk.CTkButton(
            advanced,
            text="检查仓库",
            width=160,
            fg_color=LIGHT_BLUE,
            command=self.check_gitlink,
        )
        self.create_repository_button = ctk.CTkButton(
            advanced,
            text="创建新仓库",
            width=140,
            fg_color=LIGHT_BLUE,
            command=self.create_repository,
        )
        self.adopt_remote_button = ctk.CTkButton(
            advanced,
            text="采用远程附件",
            width=145,
            fg_color=LIGHT_BLUE,
            command=self.adopt_remote_assets,
        )
        self.publish_button = ctk.CTkButton(
            game_region,
            text="进入 DLC / 补丁发布批次",
            width=210,
            fg_color=BLUE,
            command=self.create_game_content_release_batch,
        )
        self.publish_button.pack(fill="x", padx=14, pady=(4, 14))
        self.publish_update_button = ctk.CTkButton(
            advanced,
            text="单源发布程序更新",
            width=150,
            fg_color=BLUE,
            command=self.publish_update_release,
        )
        self.publish_update_mirror_button = ctk.CTkButton(
            client_region,
            text="双源镜像发布更新",
            width=170,
            fg_color=LIGHT_BLUE,
            command=lambda: self.publish_update_release(mirror=True),
        )
        self.publish_update_mirror_button.pack(fill="x", padx=14, pady=(4, 14))
        self.publish_module_archive_button = ctk.CTkButton(
            advanced,
            text="单源发布模块归档",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.publish_module_archive,
        )
        self.publish_hub_single_button = ctk.CTkButton(
            advanced,
            text="单源发布卡带中心",
            width=150,
            fg_color=LIGHT_BLUE,
            command=self.publish_cartridge_hub,
        )
        self.publish_module_archive_mirror_button = ctk.CTkButton(
            infrastructure_region,
            text="双源镜像归档",
            width=150,
            fg_color=LIGHT_BLUE,
            command=lambda: self.publish_module_archive(mirror=True),
        )
        self.publish_module_archive_mirror_button.pack(
            fill="x", padx=14, pady=(4, 6)
        )
        ctk.CTkButton(
            infrastructure_region, text="打开卡带管理",
            fg_color=LIGHT_BLUE,
            command=self._open_cartridge_management,
        ).pack(fill="x", padx=14, pady=(0, 14))

        self.publish_advanced_button = ctk.CTkButton(
            remote, text="展开高级操作 ▾", width=160,
            fg_color="transparent", border_width=1,
            border_color="#B8C5D1", text_color=TEXT,
            command=self._toggle_publish_advanced,
        )
        self.publish_advanced_button.grid(
            row=3, column=0, padx=22, pady=(0, 8), sticky="w"
        )
        ctk.CTkLabel(
            advanced,
            text="单源与仓库维护",
            font=("Microsoft YaHei UI", 14, "bold"),
            text_color=TEXT,
        ).pack(side="left", padx=(12, 8), pady=10)
        for button in (
            self.check_gitlink_button,
            self.create_repository_button,
            self.adopt_remote_button,
            self.publish_update_button,
            self.publish_module_archive_button,
            self.publish_hub_single_button,
        ):
            button.pack(side="left", padx=4, pady=10)
        self.token_entry = ctk.CTkEntry(
            advanced,
            width=230,
            show="●",
            placeholder_text="发布令牌",
            border_color="#BDBDBD",
        )
        self.token_entry.pack(side="right", padx=4)
        if self.settings.active_token:
            self.token_entry.insert(0, self.settings.active_token)
        for entry in (self.owner_entry, self.repo_entry, self.token_entry):
            entry.bind("<FocusOut>", lambda _event: self._save_active_settings())
        transfer = ctk.CTkFrame(remote, fg_color="transparent")
        transfer.grid(row=5, column=0, padx=22, pady=(0, 10), sticky="ew")
        transfer.grid_columnconfigure(1, weight=1)
        self.upload_status = ctk.CTkLabel(
            transfer, text="等待发布", width=250, anchor="w", text_color=MUTED
        )
        self.upload_status.grid(row=0, column=0, padx=(0, 12), sticky="w")
        self.upload_progress = ctk.CTkProgressBar(
            transfer, height=14, progress_color=BLUE
        )
        self.upload_progress.grid(row=0, column=1, padx=8, sticky="ew")
        self.upload_progress.set(0)
        self.publish_pause_button = ctk.CTkButton(
            transfer,
            text="暂停发布",
            width=110,
            fg_color=LIGHT_BLUE,
            state="disabled",
            command=self.toggle_publish_pause,
        )
        self.publish_pause_button.grid(row=0, column=2, padx=(12, 0))
        self.log = ctk.CTkTextbox(
            remote,
            fg_color="#FAFAFA",
            border_width=1,
            border_color="#E0E0E0",
            text_color=TEXT,
        )
        self.log.grid(row=6, column=0, padx=20, pady=(0, 18), sticky="nsew")
        self._log("令牌从本地私密配置或输入框读取，不会输出到日志。")

    def _toggle_publish_advanced(self) -> None:
        self._publish_advanced_visible = not self._publish_advanced_visible
        if self._publish_advanced_visible:
            self.publish_advanced_frame.grid(
                row=4, column=0, padx=22, pady=(0, 10), sticky="ew"
            )
            self.publish_advanced_button.configure(text="收起高级操作 ▴")
        else:
            self.publish_advanced_frame.grid_remove()
            self.publish_advanced_button.configure(text="展开高级操作 ▾")

    def publish_release(self) -> None:
        if not self._save_active_settings():
            return
        self._active_publish_scope = "game"
        if self._publish_target() == "github":
            self._publish_release_github()
            return
        try:
            assets = self.workspace.publish_assets(self.profile)
            repo = self._repository()
            previous_state = self.workspace.load_publish_state(
                self.profile, repo.owner, repo.name
            )
        except (WorkspaceError, GitLinkError, OSError) as error:
            messagebox.showerror("无法发布", str(error))
            return
        if not messagebox.askyesno(
            "确认增量发布",
            f"同步 {len(assets)} 个文件到\n{repo.owner}/{repo.name} · {self.profile.release_tag}\n\n未变化文件将复用远程附件；AppInfo 每次强制更新。是否继续？",
        ):
            return
        approval = self._confirm_maintenance_authorization(
            "单源发布游戏内容",
            f"gitlink / {repo.owner}/{repo.name} / {self.profile.release_tag} 将同步 {len(assets)} 个文件",
        )
        if approval is None:
            return
        self._activate_maintenance(approval)
        token = self.token_entry.get().strip() or None
        self._publish_resume_context = (repo, self.profile, assets, token)
        if not self._start_publish(repo, self.profile, assets, previous_state, token):
            self._fail_active_maintenance("单源游戏发布未能启动")

    def publish_update_release(self, *, mirror: bool = False) -> None:
        """Publish a built module/full ZIP and its client update manifest."""
        if not self._save_active_settings():
            return
        package_names = filedialog.askopenfilenames(
            title="选择程序更新包",
            initialdir=self._update_package_dir(),
            filetypes=[("ZIP 文件", "*.zip")],
        )
        if not package_names:
            return
        packages = tuple(Path(name) for name in package_names)
        try:
            inspected = tuple(
                (candidate, inspect_update_package(candidate))
                for candidate in packages
            )
            identities = {(info.version, info.kind) for _path, info in inspected}
            if len(identities) != 1:
                raise ValueError("所选更新包的版本和类型必须一致")
            version, kind = identities.pop()
            platform_packages: dict[str, Path] = {}
            if len(inspected) > 1:
                if kind != "full":
                    raise ValueError("只有全量更新可以同时选择多个平台包")
                for candidate, info in inspected:
                    if not info.target_platform or not info.target_arch:
                        raise ValueError(f"包内缺少目标平台/架构：{candidate.name}")
                    key = f"{info.target_platform}-{info.target_arch}"
                    if key in platform_packages:
                        raise ValueError(f"重复的平台包：{key}")
                    platform_packages[key] = candidate
                missing = {
                    "windows-x64", "steamos-x64", "macos-x64"
                } - platform_packages.keys()
                if missing:
                    raise ValueError(f"缺少平台包：{', '.join(sorted(missing))}")
            package = platform_packages.get("windows-x64", inspected[0][0])
        except ValueError as error:
            messagebox.showerror("程序更新", str(error), parent=self)
            return
        asked = self._ask_update_notes(version, kind)
        if asked is None:
            return
        notes, mandatory = asked
        if not mirror:
            approval = self._confirm_maintenance_authorization(
                "单源发布程序更新",
                f"{self._publish_target()} / {version} / {kind} 将上传 {len(packages)} 个包并切换清单",
            )
            if approval is None:
                return
            self._activate_maintenance(approval)
        operation = "正在镜像发布程序更新" if mirror else "正在发布程序更新"
        if not self._begin_background_mutation("update-publish", operation):
            self._fail_active_maintenance("程序更新发布未能启动")
            return
        owner, repository, token = (
            self.owner_entry.get().strip(),
            self.repo_entry.get().strip(),
            self.token_entry.get().strip(),
        )
        target = self._publish_target()
        self.publish_update_button.configure(state="disabled", text="正在发布…")
        self.publish_update_mirror_button.configure(state="disabled")
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_sample = None
        self._upload_speed = 0.0
        self._active_publish_scope = "game"
        self._upload_control = UploadControl()
        self.upload_progress.set(0)
        self.upload_status.configure(text="正在准备程序更新发布…")

        def worker() -> None:
            try:
                draft = UpdateReleaseDraft(
                    version=version.strip(), kind=kind, package=package,
                    notes=notes, mandatory=mandatory,
                    platform_packages=platform_packages or None,
                )
                self._update_publish_resume = (draft, mirror, target, owner, repository, token)
                if mirror:
                    self._publish_update_mirror(draft)
                    published_target = "GitLink + GitHub"
                else:
                    platform_urls = {
                        key: release_asset_url(target, owner, repository, path.name)
                        for key, path in (draft.platform_packages or {}).items()
                    }
                    manifest = write_update_manifest(
                        self.workspace.output_dir / "updates" / UPDATE_MANIFEST_ASSET,
                        channel="stable",
                        releases=[draft.release_dict(
                            release_asset_url(target, owner, repository, package.name),
                            platform_urls,
                        )],
                    )
                    publish_packages = tuple(
                        (draft.platform_packages or {"windows-x64": package}).values()
                    )
                    total = len(publish_packages) + 1
                    for index, item in enumerate(publish_packages):
                        self._publish_update_target(
                            target, owner, repository, token, item, None,
                            progress_start=index, progress_total=total,
                        )
                    self._publish_update_target(
                        target, owner, repository, token, None, manifest,
                        progress_start=len(publish_packages), progress_total=total,
                    )
                    published_target = target
                self._post_ui(
                    lambda: self._publish_update_done(version.strip(), published_target)
                )
            except (UploadPaused, GitHubUploadPaused) as error:
                self._post_ui(
                    lambda value=str(error): self._publish_update_paused(value)
                )
            except Exception as error:
                self._post_ui(lambda message=str(error): self._publish_update_failed(message))

        threading.Thread(
            target=worker, daemon=True, name="update-release-publish"
        ).start()

    def _publish_update_mirror(self, draft: UpdateReleaseDraft) -> None:
        """Upload the identical package to both hosts before either manifest."""
        targets = (
            ("gitlink", self.settings.owner, self.settings.repository, self.settings.token),
            ("github", self.settings.github_owner, self.settings.github_repository, self.settings.github_token),
        )
        if not all(owner and repository and token for _target, owner, repository, token in targets):
            raise ValueError("双源镜像发布需要在本地配置中填写 GitLink 和 GitHub 的完整凭据")
        manifests = []
        for target, owner, repository, _token in targets:
            platform_urls = {
                key: release_asset_url(target, owner, repository, path.name)
                for key, path in (draft.platform_packages or {}).items()
            }
            manifests.append((target, owner, repository, _token, write_update_manifest(
                self.workspace.output_dir / "updates" / target / UPDATE_MANIFEST_ASSET,
                channel="stable",
                releases=[draft.release_dict(
                    release_asset_url(target, owner, repository, draft.package.name),
                    platform_urls,
                )],
            )))
        # Package first: a newly visible manifest can never reference an asset
        # that has not reached its source Release yet.
        publish_packages = tuple(
            (draft.platform_packages or {"windows-x64": draft.package}).values()
        )
        total = len(targets) * (len(publish_packages) + 1)
        completed = 0
        for target, owner, repository, token, _manifest in manifests:
            for package in publish_packages:
                self._publish_update_target(
                    target, owner, repository, token, package, None,
                    progress_start=completed, progress_total=total,
                )
                completed += 1
        for target, owner, repository, token, manifest in manifests:
            self._publish_update_target(
                target,
                owner,
                repository,
                token,
                None,
                manifest,
                progress_start=completed,
                progress_total=total,
            )
            completed += 1

    def publish_module_archive(self, *, mirror: bool = False) -> None:
        """Publish every verified module snapshot from the standard archive directory."""
        if not self._save_active_settings():
            return
        archive_dir = self._module_archive_dir()
        packages = tuple(sorted(archive_dir.glob("SignRiver-DLC-Hub-module-v*.zip")))
        if not packages:
            messagebox.showerror(
                "模块归档",
                f"归档目录中没有模块 ZIP：\n{archive_dir}\n\n"
                "请先执行 tools\\build_module.py --all-versions app\\versions。",
                parent=self,
            )
            return
        try:
            archives = tuple((package, inspect_module_archive(package)) for package in packages)
        except ValueError as error:
            messagebox.showerror("模块归档", f"归档校验失败：{error}", parent=self)
            return
        target = self._publish_target()
        destination = "GitLink + GitHub" if mirror else target
        versions = ", ".join(archive.version for _package, archive in archives)
        if not messagebox.askyesno(
            "确认发布模块归档",
            f"归档目录：{archive_dir}\n已识别 {len(archives)} 个版本：{versions}\n\n"
            f"将上传到 {destination} 的 {MODULE_ARCHIVE_RELEASE_TAG} Release。"
            "此操作不会发布客户端更新。是否继续？",
            parent=self,
        ):
            return
        if not mirror:
            approval = self._confirm_maintenance_authorization(
                "单源发布模块归档",
                f"{target} / {MODULE_ARCHIVE_RELEASE_TAG} 将上传 {len(archives)} 个模块归档：{versions}",
            )
            if approval is None:
                return
            self._activate_maintenance(approval)
        if not self._begin_background_mutation("module-archive", "正在发布模块归档"):
            self._fail_active_maintenance("模块归档发布未能启动")
            return
        selected_owner = self.owner_entry.get().strip()
        selected_repository = self.repo_entry.get().strip()
        selected_token = self.token_entry.get().strip()
        self.publish_module_archive_button.configure(state="disabled", text="正在归档…")
        self.publish_module_archive_mirror_button.configure(state="disabled")
        self.upload_progress.set(0)
        self.upload_status.configure(text=f"正在归档 {len(archives)} 个模块版本…")

        def worker() -> None:
            try:
                targets: tuple[tuple[str, str, str, str], ...]
                if mirror:
                    targets = (
                        ("gitlink", self.settings.owner, self.settings.repository, self.settings.token),
                        ("github", self.settings.github_owner, self.settings.github_repository, self.settings.github_token),
                    )
                    if not all(owner and repository and token for _target, owner, repository, token in targets):
                        raise ValueError("双源镜像归档需要在本地配置中填写 GitLink 和 GitHub 的完整凭据")
                else:
                    targets = ((target, selected_owner, selected_repository, selected_token),)
                total = len(archives) * len(targets)
                for target_index, (host, owner, repository, token) in enumerate(targets):
                    for archive_index, (package, _archive) in enumerate(archives):
                        self._publish_update_target(
                            host, owner, repository, token, package, None,
                            progress_start=target_index * len(archives) + archive_index,
                            progress_total=total,
                            release_tag=MODULE_ARCHIVE_RELEASE_TAG,
                            release_name="SignRiver Module Archives",
                        )
                self._post_ui(lambda: self._publish_module_archive_done(versions, destination))
            except Exception as error:
                self._post_ui(lambda message=str(error): self._publish_module_archive_failed(message))

        threading.Thread(
            target=worker, daemon=True, name="module-archive-publish"
        ).start()

    def _module_archive_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent.parent / "modules"
        return Path(__file__).resolve().parents[2] / "dist" / "modules"

    def _update_package_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent.parent / "updates"
        return Path(__file__).resolve().parents[2] / "dist" / "updates"

    def _update_paths(package: Path | None, manifest: Path | None) -> tuple[Path, ...]:
        return tuple(path for path in (package, manifest) if path is not None)

    def _publish_update_target(
        self, target: str, owner: str, repository: str, token: str,
        package: Path | None, manifest: Path | None,
        *,
        progress_start: int = 0,
        progress_total: int | None = None,
        release_tag: str = UPDATE_RELEASE_TAG,
        release_name: str = "SignRiver Updates",
    ) -> None:
        paths = self._update_paths(package, manifest)
        total = progress_total or len(paths)
        target_label = "GitHub" if target == "github" else "GitLink"

        def progress_callback(index: int, path: Path):
            name = f"{target_label} · {path.name}"
            size = path.stat().st_size
            self._queue_upload_progress(index, total, name, 0, size)
            return lambda sent, upload_size: self._queue_upload_progress(
                index, total, name, sent, upload_size
            )

        if target == "github":
                    client = GitHubReleaseClient(
                        GitHubRepository(owner, repository), token
                    )
                    if paths:
                        progress_callback(progress_start + 1, paths[0])
                    release = client.ensure_release(
                        release_tag, name=release_name
                    )
                    for offset, path in enumerate(paths, start=1):
                        callback = progress_callback(progress_start + offset, path)
                        client.upload_asset(
                            release,
                            path,
                            replace_existing=True,
                            progress=callback,
                            should_pause=lambda: bool(
                                self._upload_control
                                and self._upload_control.pause_requested
                            ),
                        )
                        callback(path.stat().st_size, path.stat().st_size)
        elif target == "gitlink":
                    manager = RemoteResourceManager(
                        GitLinkAttachmentClient(token or None),
                        GitLinkRepository(owner, repository),
                    )
                    for offset, path in enumerate(paths, start=1):
                        callback = progress_callback(progress_start + offset, path)
                        manager.upload_file_to_release(
                            release_tag,
                            release_name,
                            path,
                            progress=callback,
                            control=getattr(self, "_upload_control", None),
                        )
                        callback(path.stat().st_size, path.stat().st_size)
        else:
            raise ValueError(f"unsupported update target: {target}")

    def _publish_update_done(self, version: str, target: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self.upload_progress.set(1)
        self.upload_status.configure(
            text=f"程序更新 {version} 已发布完成 · {target}"
        )
        self._end_background_mutation("update-publish")
        self._upload_control = None
        self._update_publish_resume = None
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        pause_button.configure(state="disabled", text="\u6682\u505c\u53d1\u5e03")
        self.publish_update_button.configure(state="normal", text="单源发布程序更新")
        self.publish_update_mirror_button.configure(state="normal")
        message = f"程序更新 {version} 已发布到 {target} 的 {UPDATE_RELEASE_TAG} Release"
        self._log(message)
        self._complete_active_maintenance(version=version, target=target)
        messagebox.showinfo("程序更新发布完成", message, parent=self)

    def _default_update_notes(self, version: str, kind: str) -> str:
        """Default release notes: prefer the per-version draft kept in
        ``publisher-workspace/update-notes.json`` (maintained by the release
        helper/AI each build), falling back to a generic template."""
        try:
            payload = json.loads(
                (self.workspace.root / "update-notes.json").read_text(
                    encoding="utf-8"
                )
            )
            notes = payload.get(version)
            if isinstance(notes, str) and notes.strip():
                return notes.strip()
        except (OSError, ValueError, TypeError):
            pass
        if kind == "module":
            return f"\u300c{version}\u300d\u6a21\u5757\u66f4\u65b0\uff1a\u4fee\u590d\u95ee\u9898\u5e76\u4f18\u5316\u4f7f\u7528\u4f53\u9a8c\uff0c\u5efa\u8bae\u5c3d\u5feb\u66f4\u65b0\u3002"
        return f"\u300c{version}\u300d\u7248\u672c\u66f4\u65b0\uff1a\u4fee\u590d\u95ee\u9898\u5e76\u4f18\u5316\u4f7f\u7528\u4f53\u9a8c\uff0c\u5efa\u8bae\u5c3d\u5feb\u66f4\u65b0\u3002"

    def _ask_update_notes(self, version: str, kind: str) -> tuple[str, bool] | None:
        """Custom styled dialog: editable default notes + mandatory checkbox."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("\u7a0b\u5e8f\u66f4\u65b0\u53d1\u5e03")
        dialog.geometry("660x480")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        result: dict[str, object] = {}

        ctk.CTkLabel(
            dialog,
            text=f"\u5df2\u8bc6\u522b\uff1a\u7248\u672c {version} \u00b7 \u7c7b\u578b {kind}",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(22, 2))
        ctk.CTkLabel(
            dialog,
            text="\u66f4\u65b0\u8bf4\u660e\uff08\u9ed8\u8ba4\u5df2\u751f\u6210\uff0c\u53ef\u76f4\u63a5\u4fee\u6539\uff09\uff1a",
            anchor="w",
        ).pack(anchor="w", padx=28, pady=(6, 4))

        textbox = ctk.CTkTextbox(
            dialog, width=600, height=230, font=ctk.CTkFont(size=14)
        )
        textbox.pack(padx=28, pady=(4, 12))
        textbox.insert("1.0", self._default_update_notes(version, kind))

        mandatory_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            dialog,
            text="\u5f3a\u5236\u6b64\u7248\u672c\u66f4\u65b0\uff08\u7528\u6237\u65e0\u6cd5\u8df3\u8fc7\uff09",
            variable=mandatory_var,
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", padx=28, pady=(0, 16))

        button_row = ctk.CTkFrame(dialog, fg_color="transparent")
        button_row.pack(fill="x", padx=28, pady=(0, 22))

        def confirm() -> None:
            notes_text = textbox.get("1.0", "end").strip()
            result["value"] = (notes_text, bool(mandatory_var.get()))
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        ctk.CTkButton(
            button_row, text="\u53d6\u6d88", width=110, fg_color="#9E9E9E",
            command=cancel,
        ).pack(side="right", padx=(10, 0))
        ctk.CTkButton(
            button_row, text="\u786e\u8ba4\u53d1\u5e03", width=140,
            command=confirm,
        ).pack(side="right")
        dialog.wait_window()
        value = result.get("value")
        return value if isinstance(value, tuple) else None

    def _publish_update_paused(self, message: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_control = None
        self._end_background_mutation("update-publish")
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="\u53d1\u5e03\u5df2\u6682\u505c")
        self.publish_update_button.configure(state="disabled", text="\u53d1\u5e03\u5df2\u6682\u505c")
        self.publish_update_mirror_button.configure(state="disabled")
        pause_button.configure(state="normal", text="\u7ee7\u7eed\u53d1\u5e03")
        status_label.configure(text="\u5df2\u6682\u505c\uff1b\u7ee7\u7eed\u65f6\u4f1a\u4ece\u5934\u91cd\u65b0\u4e0a\u4f20")
        self._log(f"{message}\u3002\u5df2\u6682\u505c\uff1b\u70b9\u51fb\u7ee7\u7eed\u53d1\u5e03\u5c06\u91cd\u65b0\u4e0a\u4f20\u3002")

    def _resume_update_publish(self) -> None:
        resume = getattr(self, "_update_publish_resume", None)
        if resume is None:
            return
        draft, mirror, target, owner, repository, token = resume
        if not self._begin_background_mutation(
            "update-publish", "\u6b63\u5728\u7ee7\u7eed\u53d1\u5e03\u7a0b\u5e8f\u66f4\u65b0"
        ):
            return
        self._upload_control = UploadControl()
        self.upload_progress.set(0)
        self.upload_status.configure(text="\u6b63\u5728\u7ee7\u7eed\u53d1\u5e03\u7a0b\u5e8f\u66f4\u65b0\u2026")
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        pause_button.configure(state="normal", text="\u6682\u505c\u53d1\u5e03")
        self._log("\u7ee7\u7eed\u53d1\u5e03\uff1a\u91cd\u65b0\u4e0a\u4f20\uff08GitHub \u8986\u76d6\u3001GitLink \u590d\u7528\uff09\u3002")

        def worker() -> None:
            try:
                if mirror:
                    self._publish_update_mirror(draft)
                    published_target = "GitLink + GitHub"
                else:
                    platform_urls = {
                        key: release_asset_url(target, owner, repository, path.name)
                        for key, path in (draft.platform_packages or {}).items()
                    }
                    manifest = write_update_manifest(
                        self.workspace.output_dir / "updates" / UPDATE_MANIFEST_ASSET,
                        channel="stable",
                        releases=[draft.release_dict(
                            release_asset_url(target, owner, repository, draft.package.name),
                            platform_urls,
                        )],
                    )
                    publish_packages = tuple(
                        (draft.platform_packages or {"windows-x64": draft.package}).values()
                    )
                    total = len(publish_packages) + 1
                    for index, package in enumerate(publish_packages):
                        self._publish_update_target(
                            target, owner, repository, token, package, None,
                            progress_start=index, progress_total=total,
                        )
                    self._publish_update_target(
                        target, owner, repository, token, None, manifest,
                        progress_start=len(publish_packages), progress_total=total,
                    )
                    published_target = target
                self._post_ui(
                    lambda: self._publish_update_done(draft.version, published_target)
                )
            except (UploadPaused, GitHubUploadPaused) as error:
                self._post_ui(
                    lambda value=str(error): self._publish_update_paused(value)
                )
            except Exception as error:
                self._post_ui(
                    lambda message=str(error): self._publish_update_failed(message)
                )

        threading.Thread(
            target=worker, daemon=True, name="resume-update-publish"
        ).start()

    def _publish_update_failed(self, message: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self.upload_status.configure(text="程序更新发布失败，请查看下方日志")
        self._end_background_mutation("update-publish")
        self._upload_control = None
        self._update_publish_resume = None
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        pause_button.configure(state="disabled", text="\u6682\u505c\u53d1\u5e03")
        self.publish_update_button.configure(state="normal", text="单源发布程序更新")
        self.publish_update_mirror_button.configure(state="normal")
        self._log(f"程序更新发布失败：{message}")
        self._fail_active_maintenance(message)
        messagebox.showerror("程序更新发布失败", message, parent=self)

    def _publish_module_archive_done(self, version: str, target: str) -> None:
        self.upload_progress.set(1)
        self.upload_status.configure(text=f"模块归档 {version} 已发布完成 · {target}")
        self._end_background_mutation("module-archive")
        self.publish_module_archive_button.configure(
            state="normal", text="单源发布模块归档"
        )
        self.publish_module_archive_mirror_button.configure(state="normal")
        message = f"模块归档 {version} 已发布到 {target} 的 {MODULE_ARCHIVE_RELEASE_TAG} Release"
        self._log(message)
        self._complete_active_maintenance(versions=version, target=target)
        messagebox.showinfo("模块归档发布完成", message, parent=self)

    def _publish_module_archive_failed(self, message: str) -> None:
        self.upload_status.configure(text="模块归档发布失败，请查看下方日志")
        self._end_background_mutation("module-archive")
        self.publish_module_archive_button.configure(
            state="normal", text="单源发布模块归档"
        )
        self.publish_module_archive_mirror_button.configure(state="normal")
        self._log(f"模块归档发布失败：{message}")
        self._fail_active_maintenance(message)
        messagebox.showerror("模块归档发布失败", message, parent=self)

    def _publish_scope_controls(self):
        if self._active_publish_scope == "hub":
            return (
                self.hub_publish_button,
                self.hub_publish_pause_button,
                self.hub_upload_status,
                self.hub_upload_progress,
            )
        return (
            self.publish_button,
            self.publish_pause_button,
            self.upload_status,
            self.upload_progress,
        )

    def _set_publish_buttons_available(self, available: bool) -> None:
        state = "normal" if available else "disabled"
        self.publish_button.configure(state=state, text="发布当前游戏到所选源")
        self.publish_update_button.configure(state=state, text="单源发布程序更新")
        self.publish_update_mirror_button.configure(state=state)
        self.publish_module_archive_button.configure(
            state=state, text="单源发布模块归档"
        )
        self.publish_module_archive_mirror_button.configure(state=state)
        self.hub_publish_button.configure(state=state, text="一键双端发布卡带")
        self.publish_hub_single_button.configure(state=state)

    def _publish_target(self) -> str:
        return "github" if self.publish_target_menu.get() == "GitHub" else "gitlink"

    def _save_active_settings(self) -> bool:
        if self.settings_path is None:
            return True
        self.settings = self.settings.with_active_values(
            self.owner_entry.get().strip(),
            self.repo_entry.get().strip(),
            self.token_entry.get().strip(),
        )
        try:
            self.settings.save(self.settings_path)
        except PublisherSettingsError as error:
            self._log(f"无法保存本地发布配置：{error}")
            messagebox.showerror("保存本地配置失败", str(error))
            return False
        return True

    def _on_publish_target_changed(self, display_name: str) -> None:
        if not self._save_active_settings():
            return
        target = "github" if display_name == "GitHub" else "gitlink"
        self.settings = self.settings.with_publish_target(target)
        self.owner_entry.delete(0, "end")
        self.repo_entry.delete(0, "end")
        self.token_entry.delete(0, "end")
        self.owner_entry.insert(0, self.settings.active_owner)
        self.repo_entry.insert(0, self.settings.active_repository)
        if self.settings.active_token:
            self.token_entry.insert(0, self.settings.active_token)
        self.repository = GitLinkRepository(
            self.settings.active_owner, self.settings.active_repository
        )
        self._sync_publish_target_controls()
        self._save_active_settings()
        self._log(
            f"发布目标已切换为 {display_name}："
            f"{self.settings.active_owner}/{self.settings.active_repository}"
        )
        if hasattr(self, "cartridge_list"):
            self.refresh_cartridge_management()

    def _sync_publish_target_controls(self) -> None:
        is_github = self._publish_target() == "github"
        self.check_gitlink_button.configure(text="检查仓库")
        self.create_repository_button.configure(text="创建新仓库")
        self.token_entry.configure(
            placeholder_text="GitHub token" if is_github else "GitLink 私有令牌"
        )
        self.adopt_remote_button.configure(
            state="disabled" if is_github else "normal",
            text="GitHub 暂不支持采用" if is_github else "采用远程附件",
        )
        if hasattr(self, "remote_asset_title"):
            self.remote_asset_title.configure(
                text="GitHub Release 附件" if is_github else "GitLink Release 附件"
            )

    def _publish_release_github(self) -> None:
        try:
            assets = self.workspace.publish_assets(self.profile)
        except (WorkspaceError, OSError) as error:
            messagebox.showerror("无法发布", str(error))
            return
        owner = self.owner_entry.get().strip()
        name = self.repo_entry.get().strip()
        token = self.token_entry.get().strip()
        if not owner or not name:
            messagebox.showerror("无法发布", "GitHub owner 和仓库名不能为空")
            return
        if not token:
            messagebox.showerror("无法发布", "请填写 GitHub token")
            return
        if not messagebox.askyesno(
            "确认发布到 GitHub",
            f"上传 {len(assets)} 个文件到\n"
            f"{owner}/{name} · {self.profile.release_tag}\n\n"
            "同名附件会被替换。是否继续？",
        ):
            return
        approval = self._confirm_maintenance_authorization(
            "单源发布游戏内容",
            f"github / {owner}/{name} / {self.profile.release_tag} 将上传 {len(assets)} 个文件",
        )
        if approval is None:
            return
        self._activate_maintenance(approval)
        if not self._start_github_publish(owner, name, token, self.profile, assets):
            self._fail_active_maintenance("GitHub 游戏发布未能启动")

    def _start_github_publish(
        self,
        owner: str,
        name: str,
        token: str,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        completed: frozenset[str] = frozenset(),
    ) -> bool:
        if not self._begin_background_mutation(
            "publish", "正在上传 GitHub Release"
        ):
            return False
        publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="正在发布…")
        self.adopt_remote_button.configure(state="disabled")
        self._upload_control = UploadControl()
        self._github_publish_resume_context = (
            owner, name, token, profile, assets, completed,
        )
        pause_button.configure(state="normal", text="暂停发布")
        status_label.configure(text="正在准备 GitHub 上传…")
        progress_bar.set(0)

        def worker() -> None:
            try:
                client = GitHubReleaseClient(
                    GitHubRepository(owner, name), token
                )
                release = client.ensure_release(profile.release_tag)
                total = len(assets)
                completed_names = set(completed)
                changed_names = {
                    asset.name
                    for asset in self.workspace.changed_publish_assets(
                        profile, owner, name, assets, state_channel="github"
                    )
                }
                for index, asset in enumerate(assets, start=1):
                    if (
                        asset.name in completed_names
                        or asset.name not in changed_names
                    ):
                        completed_names.add(asset.name)
                        self._queue_upload_progress(
                            index, total, asset.name, asset.size_bytes, asset.size_bytes
                        )
                        self._post_ui(
                            lambda i=index, value=asset.name: self._log(
                                f"[{i}/{total}] 复用 GitHub 附件 {value}"
                            )
                        )
                        continue
                    self._queue_upload_progress(
                        index, total, asset.name, 0, asset.size_bytes
                    )
                    client.upload_asset(
                        release,
                        asset.path,
                        replace_existing=True,
                        progress=lambda sent, size, i=index, value=asset.name: (
                            self._queue_upload_progress(i, total, value, sent, size)
                        ),
                        should_pause=lambda: bool(
                            self._upload_control and self._upload_control.pause_requested
                        ),
                    )
                    completed_names.add(asset.name)
                    self._queue_upload_progress(
                        index, total, asset.name, asset.size_bytes, asset.size_bytes
                    )
                self.workspace.save_publish_state(
                    profile,
                    self.workspace.publish_state_for_assets(
                        profile, owner, name, assets
                    ),
                    state_channel="github",
                )
                self._post_ui(
                    lambda: self._github_publish_done(owner, name, profile, total)
                )
            except GitHubUploadPaused as error:
                self._post_ui(
                    lambda value=str(error), done=frozenset(completed_names): (
                        self._github_publish_paused(value, done)
                    )
                )
            except (GitHubPublisherError, OSError) as error:
                message = str(error)
                self._post_ui(
                    lambda message=message: self._github_publish_failed(message)
                )

        try:
            threading.Thread(target=worker, daemon=True).start()
        except RuntimeError:
            self._upload_control = None
            self._github_publish_resume_context = None
            self._end_background_mutation("publish")
            self._set_publish_buttons_available(True)
            self._sync_publish_target_controls()
            pause_button.configure(state="disabled", text="暂停发布")
            status_label.configure(text="GitHub 发布未能启动")
            return False
        return True

    def _github_publish_done(
        self, owner: str, name: str, profile: GameProfile, total: int
    ) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("publish")
        _publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self._sync_publish_target_controls()
        pause_button.configure(state="disabled", text="暂停发布")
        status_label.configure(text=f"GitHub 发布完成 · {total} 个文件")
        progress_bar.set(1)
        self._upload_control = None
        self._github_publish_resume_context = None
        summary = f"已发布到 GitHub {owner}/{name} · {profile.release_tag}"
        self._log(summary)
        self._complete_active_maintenance(
            target="github", uploaded=total, release_tag=profile.release_tag
        )
        if self._active_publish_scope == "hub":
            self.refresh_cartridge_management()
        messagebox.showinfo("发布完成", summary)

    def _github_publish_failed(self, message: str) -> None:
        self._remote_operation_active = False
        self._end_background_mutation("publish")
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self._sync_publish_target_controls()
        pause_button.configure(state="disabled", text="暂停发布")
        status_label.configure(text="GitHub 发布失败")
        self._upload_control = None
        self._github_publish_resume_context = None
        self._log(f"GitHub 发布失败：{message}")
        self._fail_active_maintenance(message)
        messagebox.showerror("GitHub 发布失败", message)

    def _start_publish(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        previous_state: dict[str, object],
        token: str | None,
    ) -> bool:
        if not self._begin_background_mutation(
            "publish",
            "正在上传 Release",
            resume=self._upload_control is None,
        ):
            return False
        self._upload_control = UploadControl()
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_sample = None
        self._upload_speed = 0.0
        publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="正在发布…")
        self.adopt_remote_button.configure(state="disabled")
        pause_button.configure(state="normal", text="暂停发布")
        status_label.configure(text="正在准备上传…")
        progress_bar.set(0)
        self._log(
            f"开始单文件确认发布 {profile.display_name}：共 {len(assets)} 个文件。"
        )
        try:
            threading.Thread(
                target=self._publish_worker,
                args=(repo, profile, assets, previous_state, token),
                daemon=True,
            ).start()
        except RuntimeError:
            self._upload_control = None
            self._publish_resume_context = None
            self._end_background_mutation("publish")
            self._set_publish_buttons_available(True)
            self.adopt_remote_button.configure(state="normal")
            pause_button.configure(state="disabled", text="暂停发布")
            status_label.configure(text="发布未能启动")
            return False
        return True

    def _publish_worker(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        previous_state: dict[str, object],
        token: str | None,
    ) -> None:
        try:
            client = GitLinkAttachmentClient(token)
            manager = RemoteResourceManager(client, repo)

            def progress(index: int, total: int, name: str, stage: str) -> None:
                self._post_ui(
                    lambda i=index, count=total, value=name, action=stage: self._log(
                        f"[{i}/{count}] {action} {value}"
                    )
                )

            def upload_progress(
                index: int, total: int, name: str, sent: int, size: int
            ) -> None:
                self._queue_upload_progress(index, total, name, sent, size)

            def checkpoint(state: dict[str, object]) -> None:
                self.workspace.save_publish_state(profile, state)

            result = manager.sync_release(
                profile,
                assets,
                previous_state,
                force_upload=frozenset({profile.appinfo_name}),
                progress=progress,
                upload_progress=upload_progress,
                upload_control=self._upload_control,
                checkpoint=checkpoint,
            )
            warnings = result.warnings
            try:
                self.workspace.save_publish_state(profile, result.state)
            except OSError as error:
                warnings = (
                    *warnings,
                    f"Release 已更新，但本地发布状态保存失败；下次可能重新上传：{error}",
                )
            self._post_ui(
                lambda value=result, notes=warnings: self._publish_done(
                    repo,
                    profile,
                    value.action,
                    value.uploaded,
                    value.reused,
                    value.removed,
                    notes,
                )
            )
        except UploadPaused as error:
            self._post_ui(lambda value=str(error): self._publish_paused(value))
        except Exception as error:
            message = str(error)
            self._post_ui(lambda value=message: self._publish_failed(value))

    def _publish_done(
        self,
        repo: GitLinkRepository,
        profile: GameProfile,
        action: str,
        uploaded: int,
        reused: int,
        removed: int,
        warnings: tuple[str, ...],
    ) -> None:
        self._end_background_mutation("publish")
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        _publish_button, pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self.adopt_remote_button.configure(state="normal")
        pause_button.configure(state="disabled", text="暂停发布")
        progress_bar.set(1)
        status_label.configure(text="发布完成")
        self._publish_resume_context = None
        self._upload_control = None
        if not self.settings.token:
            self.token_entry.delete(0, "end")
        summary = f"Release {action}完成：上传 {uploaded}，复用 {reused}，清理旧附件 {removed}。"
        self._log(summary)
        self._complete_active_maintenance(
            target="gitlink", uploaded=uploaded, reused=reused, removed=removed
        )
        if self._active_publish_scope == "hub":
            self.refresh_cartridge_management()
        if warnings:
            messagebox.showwarning(
                "发布完成但有警告", f"{summary}\n\n" + "\n".join(warnings)
            )
        else:
            messagebox.showinfo(
                "发布完成",
                f"资源已发布到 {repo.owner}/{repo.name} 的 {profile.release_tag} Release。\n\n{summary}",
            )

    def _publish_failed(self, message: str) -> None:
        self._end_background_mutation("publish")
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(True)
        self.adopt_remote_button.configure(state="normal")
        pause_button.configure(state="disabled", text="暂停发布")
        status_label.configure(text="发布中断；已确认文件已保留")
        self._publish_resume_context = None
        self._upload_control = None
        self._log(
            f"发布中断：{message}。已确认的文件不会重新上传，可再次点击发布继续。"
        )
        self._fail_active_maintenance(message)
        messagebox.showerror(
            "发布中断",
            f"{message}\n\n此前已确认到 Release 的文件已保留，再次发布会从未完成文件继续。",
        )

    def toggle_publish_pause(self) -> None:
        control = self._upload_control
        _publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        if control is not None:
            control.request_pause()
            pause_button.configure(state="disabled", text="正在暂停…")
            status_label.configure(text="正在中止当前文件上传…")
            return
        if getattr(self, "_update_publish_resume", None) is not None:
            self._resume_update_publish()
            return
        github_context = self._github_publish_resume_context
        if github_context is not None:
            owner, name, token, profile, assets, completed = github_context
            self._log("继续 GitHub 发布：当前文件将从头上传，已完成文件会跳过。")
            self._start_github_publish(
                owner, name, token, profile, assets, completed,
            )
            return
        context = self._publish_resume_context
        if context is None:
            return
        repo, profile, assets, token = context
        try:
            previous_state = self.workspace.load_publish_state(
                profile, repo.owner, repo.name
            )
        except OSError as error:
            messagebox.showerror("无法继续发布", str(error))
            return
        self._log("继续发布：当前未完成文件将从头上传，已确认文件直接复用。")
        self._start_publish(repo, profile, assets, previous_state, token)

    def _publish_paused(self, message: str) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        self._upload_control = None
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="发布已暂停")
        self.adopt_remote_button.configure(state="disabled")
        pause_button.configure(state="normal", text="继续发布")
        status_label.configure(text="已暂停；继续时当前文件从头上传")
        self._log(f"{message}。已确认文件已保存；继续时当前文件会从头上传。")

    def _github_publish_paused(
        self, message: str, completed: frozenset[str]
    ) -> None:
        with self._pending_upload_progress_lock:
            self._pending_upload_progress = None
        context = self._github_publish_resume_context
        if context is None:
            return
        owner, name, token, profile, assets, _previous_completed = context
        self._github_publish_resume_context = (
            owner, name, token, profile, assets, completed,
        )
        self._upload_control = None
        self._end_background_mutation("publish")
        publish_button, pause_button, status_label, _progress_bar = (
            self._publish_scope_controls()
        )
        self._set_publish_buttons_available(False)
        publish_button.configure(state="disabled", text="发布已暂停")
        pause_button.configure(state="normal", text="继续发布")
        status_label.configure(text="已暂停；继续时当前文件会从头上传")
        self._log(f"{message}。已完成的 GitHub 文件将保留，继续时会跳过。")

    def _show_upload_progress(
        self, index: int, total: int, name: str, sent: int, size: int
    ) -> None:
        now = time.monotonic()
        if self._upload_sample is None or self._upload_sample[0] != name:
            self._upload_sample = (name, sent, now)
            self._upload_speed = 0.0
        else:
            _, previous_sent, previous_time = self._upload_sample
            elapsed = now - previous_time
            if elapsed > 0:
                current_speed = max(0.0, sent - previous_sent) / elapsed
                self._upload_speed = (
                    current_speed
                    if self._upload_speed <= 0
                    else self._upload_speed * 0.65 + current_speed * 0.35
                )
            self._upload_sample = (name, sent, now)
        ratio = min(1.0, sent / size) if size else 0.0
        _publish_button, _pause_button, status_label, progress_bar = (
            self._publish_scope_controls()
        )
        progress_bar.set(ratio)
        status_label.configure(
            text=(
                f"[{index}/{total}] {name} · {ratio * 100:.1f}% · "
                f"{self._format_transfer_size(sent)}/{self._format_transfer_size(size)} · "
                f"{self._format_transfer_size(self._upload_speed)}/s"
            )
        )
