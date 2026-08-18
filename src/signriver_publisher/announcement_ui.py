from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from .announcements import AnnouncementDraft, AnnouncementValidationError

BLUE = "#1976D2"
LIGHT_BLUE = "#42A5F5"
BRAND = "#3A7EBF"
PAGE = "#F5F7FA"
CARD = "#FFFFFF"
TEXT = "#212121"
MUTED = "#757575"


class AnnouncementUiMixin:
    """Announcement editor dialog and draft persistence controls."""

    def open_announcement_manager(self) -> None:
        existing = getattr(self, "announcement_manager_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        try:
            draft = self.workspace.load_announcement_draft()
        except AnnouncementValidationError as error:
            messagebox.showerror("公告配置异常", str(error))
            return

        window = ctk.CTkToplevel(self)
        self.announcement_manager_window = window
        window.title("管理启动公告")
        window.geometry("720x610")
        window.minsize(620, 540)
        window.configure(fg_color=PAGE)
        window.transient(self)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(
            window,
            fg_color=CARD,
            border_width=1,
            border_color="#D8DEE6",
            corner_radius=14,
        )
        card.grid(row=0, column=0, padx=18, pady=18, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(6, weight=1)
        ctk.CTkLabel(
            card,
            text="客户端启动公告",
            font=("Microsoft YaHei UI", 22, "bold"),
            text_color=BLUE,
        ).grid(row=0, column=0, columnspan=2, padx=22, pady=(20, 4), sticky="w")
        ctk.CTkLabel(
            card,
            text="保存后会在下一次生成或发布 hub 时生效；停用会保留草稿并停止远端发布。",
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="ew")

        self.announcement_enabled = ctk.CTkCheckBox(
            card,
            text="启用并随 hub 发布",
            fg_color=BLUE,
            hover_color=BRAND,
        )
        self.announcement_enabled.grid(
            row=2, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="w"
        )
        if draft.enabled:
            self.announcement_enabled.select()

        ctk.CTkLabel(card, text="公告版本 ID", text_color=TEXT).grid(
            row=3, column=0, padx=(22, 12), pady=6, sticky="w"
        )
        self.announcement_id_entry = ctk.CTkEntry(
            card, border_width=2, border_color="#BDBDBD"
        )
        self.announcement_id_entry.grid(
            row=3, column=1, padx=(0, 22), pady=6, sticky="ew"
        )
        self.announcement_id_entry.insert(0, draft.announcement_id)

        ctk.CTkLabel(card, text="公告标题", text_color=TEXT).grid(
            row=4, column=0, padx=(22, 12), pady=6, sticky="w"
        )
        self.announcement_title_entry = ctk.CTkEntry(
            card, border_width=2, border_color="#BDBDBD"
        )
        self.announcement_title_entry.grid(
            row=4, column=1, padx=(0, 22), pady=6, sticky="ew"
        )
        self.announcement_title_entry.insert(0, draft.title)

        date_row = ctk.CTkFrame(card, fg_color="transparent")
        date_row.grid(row=5, column=0, columnspan=2, padx=22, pady=6, sticky="ew")
        date_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(date_row, text="更新日期", text_color=TEXT).grid(
            row=0, column=0, padx=(0, 12), sticky="w"
        )
        self.announcement_date_entry = ctk.CTkEntry(
            date_row, width=170, border_width=2, border_color="#BDBDBD"
        )
        self.announcement_date_entry.grid(row=0, column=1, sticky="w")
        self.announcement_date_entry.insert(0, draft.updated_at)
        ctk.CTkLabel(
            date_row,
            text="版本 ID 改变后，已选择“不再提示”的客户端也会重新显示公告。",
            text_color=MUTED,
            anchor="e",
        ).grid(row=0, column=2, padx=(14, 0), sticky="e")

        body_frame = ctk.CTkFrame(card, fg_color="transparent")
        body_frame.grid(
            row=6, column=0, columnspan=2, padx=22, pady=(8, 10), sticky="nsew"
        )
        body_frame.grid_columnconfigure(0, weight=1)
        body_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(body_frame, text="公告正文", text_color=TEXT).grid(
            row=0, column=0, pady=(0, 6), sticky="w"
        )
        self.announcement_body = ctk.CTkTextbox(
            body_frame,
            fg_color="#FAFAFA",
            border_width=2,
            border_color="#BDBDBD",
            wrap="word",
        )
        self.announcement_body.grid(row=1, column=0, sticky="nsew")
        self.announcement_body.insert("1.0", draft.body)

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(
            row=7, column=0, columnspan=2, padx=22, pady=(4, 20), sticky="ew"
        )
        for column in range(3):
            actions.grid_columnconfigure(column, weight=1, uniform="announcement")
        ctk.CTkButton(
            actions,
            text="预览公告",
            fg_color=LIGHT_BLUE,
            command=self.preview_announcement,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(
            actions,
            text="保存公告",
            fg_color=BLUE,
            command=self.save_announcement,
        ).grid(row=0, column=1, padx=5, sticky="ew")
        ctk.CTkButton(
            actions,
            text="关闭",
            fg_color="#9E9E9E",
            command=window.destroy,
        ).grid(row=0, column=2, padx=(5, 0), sticky="ew")
        window.grab_set()
        window.focus_force()

    def _announcement_editor_value(self) -> AnnouncementDraft:
        return AnnouncementDraft(
            announcement_id=self.announcement_id_entry.get(),
            title=self.announcement_title_entry.get(),
            updated_at=self.announcement_date_entry.get(),
            body=self.announcement_body.get("1.0", "end"),
            enabled=bool(self.announcement_enabled.get()),
        )

    def preview_announcement(self) -> None:
        try:
            draft = self._announcement_editor_value().validate()
        except AnnouncementValidationError as error:
            messagebox.showerror("无法预览公告", str(error))
            return
        messagebox.showinfo(
            "公告预览",
            f"{draft.title}\n{draft.updated_at}\n\n{draft.body}",
            parent=self.announcement_manager_window,
        )

    def save_announcement(self) -> None:
        draft = self._announcement_editor_value()
        if draft.enabled:
            try:
                draft = draft.validate()
            except AnnouncementValidationError as error:
                messagebox.showerror("无法启用公告", str(error))
                return
        elif self.workspace.announcement_path.is_file() and not messagebox.askyesno(
            "确认停用公告",
            "停用后会保留当前草稿；下一次发布 hub 时将从 Release 移除 announcement.json。是否继续？",
            parent=self.announcement_manager_window,
        ):
            return
        if not self._begin_background_mutation(
            "announcement-save", "正在保存客户端启动公告"
        ):
            return
        try:
            self.workspace.save_announcement_draft(draft)
            self.refresh_cartridge_management()
            state = "已启用" if draft.enabled else "已保存为停用草稿"
            self._log(f"客户端启动公告{state}：{draft.announcement_id or '未填写版本 ID'}")
            messagebox.showinfo(
                "公告已保存",
                f"公告{state}。下一次生成或发布 hub 时会自动同步。",
                parent=self.announcement_manager_window,
            )
        except (AnnouncementValidationError, OSError) as error:
            messagebox.showerror("公告保存失败", str(error))
        finally:
            self._end_background_mutation("announcement-save")
