from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path

import customtkinter as ctk
from tkinter import BooleanVar, filedialog, messagebox

from .signriver_app.adapters import AdapterRegistry
from .signriver_app.adapters.builtin import create_builtin_adapters
from .signriver_app.application import DownloadQueue, GameDiscoveryService, StellarisCatalogService
from .signriver_app.domain import DownloadSpec, DownloadState
from .signriver_app.infrastructure.catalog import GitLinkReleaseSource, GitLinkSourceConfig
from .signriver_app.infrastructure.catalog import inspect_stellaris_package
from .signriver_app.infrastructure.downloads import DownloadManager
from .signriver_app.infrastructure.persistence import (
    Database,
    DownloadTaskRepository,
    GameInstallationRepository,
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
        self.catalog = StellarisCatalogService(
            GitLinkReleaseSource(GitLinkSourceConfig("signriver", "file-warehouse"))
        )
        self.download_manager = DownloadManager(self.context.paths.cache)
        self.catalog_entries = ()
        self.catalog_rows = {}
        self.selected_dlc_ids = set()
        self.dlc_selection_vars = {}
        self.download_repository = None
        self.download_queue = None
        self.current_installation = None
        try:
            registry = AdapterRegistry(create_builtin_adapters())
            database = Database(self.context.paths.data / "hub.db")
            repository = GameInstallationRepository(database)
            self.download_repository = DownloadTaskRepository(database)
            self.discovery = GameDiscoveryService(registry, repository)
            self.download_queue = DownloadQueue(
                self.download_manager,
                repository=self.download_repository,
                max_concurrent=2,
                on_change=self._queue_download_event,
                verifier_for=lambda _spec: inspect_stellaris_package,
            )
        except Exception:
            self.context.logger.exception("Unable to initialize game discovery")
        self._build_ui()
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self._show_recovered_downloads()
        self.window.after(350, self._scan_games)
        self.window.after(500, self._refresh_catalog)
        if self.context.updates.enabled and self.context.updates.check_on_startup:
            self.window.after(800, self._check_update)

    def _build_ui(self) -> None:
        container = ctk.CTkFrame(self.window, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=36, pady=30)

        ctk.CTkLabel(
            container,
            text="SignRiver DLC Hub",
            font=ctk.CTkFont(size=30, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            container,
            text="多游戏 DLC 管理中心",
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=15),
        ).pack(anchor="w", pady=(4, 30))

        game_card = ctk.CTkFrame(container)
        game_card.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(
            game_card,
            text="游戏检测",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(18, 4))
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

        ctk.CTkLabel(
            container,
            text="Stellaris Steam 样例已接入；DLC 目录和下载模块将在后续阶段启用。",
            text_color=("gray45", "gray65"),
        ).pack(anchor="w", pady=(24, 0))

    def _set_game_buttons(self, state: str) -> None:
        self.game_scan_button.configure(state=state)
        self.game_path_button.configure(state=state)

    def _refresh_catalog(self) -> None:
        self.catalog_refresh_button.configure(state="disabled")
        self.catalog_status.configure(text="正在读取 GitLink · ste Release……")

        def worker() -> None:
            try:
                entries = self.catalog.refresh()
                self.window.after(0, lambda entries=entries: self._show_catalog(entries))
            except Exception as error:
                self.context.logger.exception("DLC catalog refresh failed")
                message = str(error)
                self.window.after(0, lambda message=message: self._show_catalog_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _show_catalog(self, entries) -> None:
        self.catalog_entries = entries
        self.catalog_refresh_button.configure(state="normal")
        self.catalog_status.configure(text=f"Stellaris · 已读取 {len(entries)} 个 DLC 资源")
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
        self.catalog_refresh_button.configure(state="normal")
        self.catalog_status.configure(text="DLC 目录读取失败")
        self.catalog_preview.configure(text=message)

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
            row.grid(row=index, column=0, columnspan=6, sticky="ew", pady=3)
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
            task_id = f"stellaris-{entry.dlc_id}"
            self.catalog_rows[task_id] = (status, action, pause, cancel)
            if task_id in snapshots:
                self._show_download_state(snapshots[task_id])
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
        spec = DownloadSpec(
            task_id=f"stellaris-{entry.dlc_id}",
            url=entry.asset.download_url,
            filename=entry.asset.name,
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
        except Exception:
            self.context.logger.exception("DLC queue task crashed")

    def _queue_download_event(self, snapshot) -> None:
        self.window.after(
            0, lambda snapshot=snapshot: self._show_download_state(snapshot)
        )

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
        status, action, pause, cancel = row
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

    def _scan_games(self) -> None:
        if self.discovery is None:
            self.game_status.configure(text="Stellaris · 初始化失败")
            self.game_path.configure(text="游戏发现服务不可用，请查看日志")
            return
        self._set_game_buttons("disabled")
        self.game_status.configure(text="Stellaris · 正在扫描 Steam 游戏库……")

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

    def _show_game_error(self, message: str, *, popup: bool = True) -> None:
        self._set_game_buttons("normal")
        self.game_status.configure(text="Stellaris · 路径验证失败")
        self.game_path.configure(text=message)
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
