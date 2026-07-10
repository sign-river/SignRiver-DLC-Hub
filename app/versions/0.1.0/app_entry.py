from __future__ import annotations

import threading
import webbrowser

import customtkinter as ctk
from tkinter import messagebox


class DlcHubApplication:
    def __init__(self, context) -> None:
        self.context = context
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        self.window = ctk.CTk()
        self.window.title("SignRiver DLC Hub")
        self.window.geometry("760x480")
        self.window.minsize(640, 400)
        self._build_ui()
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
            text="游戏管理模块将在下一阶段接入。",
            text_color=("gray45", "gray65"),
        ).pack(anchor="w", pady=(24, 0))

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
                self.window.after(0, lambda: self._show_error(str(error)))

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
                    self.status.configure(text=f"正在下载…… {current / 1048576:.1f}/{total / 1048576:.1f} MB")
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
                    self.window.after(0, lambda: self._open_full_update(error))
                    return
                self.context.logger.exception("Update installation failed")
                self.window.after(0, lambda: self._show_error(str(error)))

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
