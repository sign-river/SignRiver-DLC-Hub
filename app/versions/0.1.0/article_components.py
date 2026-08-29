"""通用文章与指南页面组件（CustomTkinter 5.2）。

组件只负责展示与回调，不耦合业务服务，适合嵌入任意 CTkScrollableFrame。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re

import customtkinter as ctk
from PIL import Image


# 统一的浅色/深色主题调色板。
PALETTE = {
    "Bg": ("#F7F9FC", "#151A22"),
    "Surface": ("#FFFFFF", "#202733"),
    "Border": ("#DCE3EC", "#374151"),
    "Text": ("#1F2937", "#F3F4F6"),
    "MutedText": ("#667085", "#AAB4C3"),
    "Accent": ("#2563EB", "#60A5FA"),
    "Warning": ("#B45309", "#F59E0B"),
    "WarningSurface": ("#FFF7E6", "#3A2B16"),
    "Info": ("#1D4ED8", "#60A5FA"),
    "InfoSurface": ("#EFF6FF", "#172B4D"),
    "Success": ("#15803D", "#4ADE80"),
    "SuccessSurface": ("#ECFDF3", "#163524"),
}


def _font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(size=size, weight=weight)


class AlertBanner(ctk.CTkFrame):
    """带状态色、图标、标题和自适应说明的横幅。"""

    _STYLES = {
        "warning": ("⚠", "Warning", "WarningSurface", "Warning"),
        "info": ("ⓘ", "Info", "InfoSurface", "Info"),
        "success": ("✓", "Success", "SuccessSurface", "Success"),
    }

    def __init__(self, master, title: str, message: str, *, kind: str = "info", **kwargs):
        if kind not in self._STYLES:
            raise ValueError(f"未知横幅类型: {kind}")
        icon, _, surface, accent = self._STYLES[kind]
        kwargs.setdefault("height", 72)
        super().__init__(master, fg_color=PALETTE[surface], border_color=PALETTE[accent],
                         border_width=1, corner_radius=10, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text=icon, text_color=PALETTE[accent], font=_font(20, "bold"),
                     width=28).grid(row=0, column=0, padx=(14, 8), pady=14, sticky="n")
        body = ctk.CTkFrame(self, fg_color="transparent", height=1)
        body.grid(row=0, column=1, padx=(0, 14), pady=12, sticky="ew")
        body.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(body, text=title, text_color=PALETTE["Text"],
                                        font=_font(14, "bold"), anchor="w", wraplength=760)
        self.title_label.grid(row=0, column=0, sticky="ew")
        self.message_label = ctk.CTkLabel(body, text=message, text_color=PALETTE["MutedText"],
                                          justify="left", anchor="w", wraplength=760)
        self.message_label.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        self.bind("<Configure>", self._resize)

    def _resize(self, event) -> None:
        self.title_label.configure(wraplength=max(240, event.width - 72))
        self.message_label.configure(wraplength=max(240, event.width - 72))


class PillBadge(ctk.CTkLabel):
    """用于路径、DLL、状态等关键短文本的轻量标签。"""

    def __init__(self, master, text: str, *, tone: str = "neutral", **kwargs):
        colors = {
            "accent": (PALETTE["Accent"], PALETTE["InfoSurface"]),
            "success": (PALETTE["Success"], PALETTE["SuccessSurface"]),
            "warning": (PALETTE["Warning"], PALETTE["WarningSurface"]),
            "neutral": (PALETTE["MutedText"], PALETTE["Bg"]),
        }
        if tone not in colors:
            raise ValueError(f"未知标签色调: {tone}")
        text_color, fg_color = colors[tone]
        super().__init__(master, text=text, text_color=text_color, fg_color=fg_color,
                         corner_radius=999, padx=9, pady=3, font=_font(12, "bold"), **kwargs)


def extract_inline_badges(text: str) -> list[tuple[str, str]]:
    """提取正文中适合标签化的 DLL 名称和 Windows 路径。"""
    values: list[tuple[str, str]] = []
    for value in re.findall(r"[\w.-]+\.dll", text, flags=re.IGNORECASE):
        item = (value, "accent")
        if item not in values:
            values.append(item)
    for value in re.findall(r"[A-Za-z]:\\[^，。；\n]{2,80}", text):
        display = value.rstrip("\\")
        if len(display) > 42:
            display = display[:39].rstrip() + "..."
        item = (display, "neutral")
        if item not in values:
            values.append(item)
    return values[:4]


class ArticleParagraphCard(ctk.CTkFrame):
    """可复制、可自适应高度的文章正文卡片。"""

    def __init__(self, master, text: str, *, variant: str = "body", **kwargs):
        if variant not in {"body", "lead", "note"}:
            raise ValueError(f"未知正文样式: {variant}")
        surface = {"body": "transparent", "lead": PALETTE["InfoSurface"],
                   "note": PALETTE["WarningSurface"]}[variant]
        # CustomTkinter 禁止 border_color 使用透明色；正文边框宽度为 0，
        # 这里使用页面背景色作为安全的占位颜色。
        border = {"body": PALETTE["Bg"], "lead": PALETTE["Accent"],
                  "note": PALETTE["Warning"]}[variant]
        accent = {"body": PALETTE["Border"], "lead": PALETTE["Accent"],
                  "note": PALETTE["Warning"]}[variant]
        kwargs.setdefault("height", 1)
        super().__init__(master, fg_color=surface, border_color=border,
                         border_width=0 if variant == "body" else 1,
                         corner_radius=0 if variant == "body" else 10, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(self, width=3, height=1, fg_color=accent,
                     corner_radius=2).grid(row=0, column=0, sticky="ns", padx=(4, 10), pady=8)
        font_size = 15 if variant == "lead" else 14
        self.text_widget = ctk.CTkTextbox(
            self, height=34, border_spacing=0, activate_scrollbars=False, wrap="char",
            fg_color="transparent", border_width=0, corner_radius=0,
            text_color=PALETTE["Text"] if variant == "lead" else PALETTE["MutedText"],
            font=_font(font_size),
        )
        self.text_widget.insert("1.0", text)
        self.text_widget.configure(state="disabled")
        self.text_widget.grid(row=0, column=1, sticky="ew", padx=(0, 14),
                              pady=10 if variant == "body" else 12)
        badges = extract_inline_badges(text)
        if badges:
            badge_row = ctk.CTkFrame(self, fg_color="transparent", height=1)
            badge_row.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=(0, 10))
            for value, tone in badges:
                PillBadge(badge_row, value, tone=tone).pack(side="left", padx=(0, 6))


class StepWorkflowCard(ctk.CTkFrame):
    """带圆形序号、分层文本和右侧动作按钮的步骤卡片。"""

    def __init__(self, master, step: int, title: str, body: str, *,
                 action_text: str | None = None, command: Callable[[], None] | None = None,
                 **kwargs):
        kwargs.setdefault("height", 72)
        super().__init__(master, fg_color=PALETTE["Surface"], border_color=PALETTE["Border"],
                         border_width=1, corner_radius=10, **kwargs)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(self, text=str(step), width=34, height=34, corner_radius=17,
                             fg_color=PALETTE["Accent"], text_color="#FFFFFF",
                             font=_font(14, "bold"))
        badge.grid(row=0, column=0, padx=(14, 12), pady=14, sticky="")
        content = ctk.CTkFrame(self, fg_color="transparent", height=1)
        content.grid(row=0, column=1, padx=(0, 12), pady=12, sticky="ew")
        content.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(content, text=title, text_color=PALETTE["Text"],
                                        anchor="w", wraplength=620, font=_font(14, "bold"))
        self.title_label.grid(row=0, column=0, sticky="ew")
        self.body_label = None
        if body:
            self.body_label = ctk.CTkLabel(content, text=body, text_color=PALETTE["MutedText"],
                                           justify="left", anchor="w", wraplength=620)
            self.body_label.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        else:
            self.title_label.grid_configure(pady=17)
        if action_text:
            ctk.CTkButton(self, text=action_text, command=command, width=132, height=36,
                          fg_color=PALETTE["Accent"], hover_color="#1D4ED8").grid(
                              row=0, column=2, padx=(4, 14), pady=14, sticky="e")
        self.bind("<Configure>", self._resize)

    def _resize(self, event) -> None:
        self.title_label.configure(wraplength=max(220, event.width - 220))
        if self.body_label is not None:
            self.body_label.configure(wraplength=max(220, event.width - 220))


class FramedImageContainer(ctk.CTkFrame):
    """带边框、等比缩放和图注的图片预览容器。"""

    def __init__(self, master, image: Image.Image | str | Path, *, caption: str = "",
                 max_size: tuple[int, int] = (760, 420), **kwargs):
        super().__init__(master, fg_color=PALETTE["Bg"], border_color=PALETTE["Border"],
                         border_width=1, corner_radius=10, **kwargs)
        self._source = Image.open(image) if isinstance(image, (str, Path)) else image
        self._source = self._source.convert("RGBA")
        self._max_size = max_size
        self._image_label = ctk.CTkLabel(self, text="")
        self._image_label.pack(padx=12, pady=(12, 8))
        if caption:
            self._caption = ctk.CTkLabel(self, text=caption, text_color=PALETTE["MutedText"],
                                         justify="center", wraplength=max_size[0] - 24)
            self._caption.pack(padx=12, pady=(0, 12), fill="x")
        self.bind("<Configure>", self._resize)
        self._resize_image(max_size[0])

    def _resize(self, event) -> None:
        self._resize_image(min(self._max_size[0], max(240, event.width - 24)))

    def _resize_image(self, width: int) -> None:
        ratio = min(width / self._source.width, self._max_size[1] / self._source.height, 1)
        size = (max(1, int(self._source.width * ratio)), max(1, int(self._source.height * ratio)))
        self._photo = ctk.CTkImage(light_image=self._source, dark_image=self._source, size=size)
        self._image_label.configure(image=self._photo)
        if hasattr(self, "_caption"):
            self._caption.configure(wraplength=max(180, width - 24))

    def bind_click(self, callback: Callable[[object], object]) -> None:
        """将同一点击回调绑定到容器和实际图片，保持预览可点击。"""
        self.bind("<Button-1>", callback, add="+")
        self._image_label.bind("<Button-1>", callback, add="+")


def demo_patch_troubleshooting(master=None) -> ctk.CTkToplevel | ctk.CTk:
    """组合组件渲染一个可运行的“补丁异常排查指引”示例。"""
    root = master or ctk.CTk()
    if master is None:
        root.geometry("1120x840")
        root.minsize(1000, 700)
    page = ctk.CTkScrollableFrame(root, fg_color=PALETTE["Bg"])
    page.pack(fill="both", expand=True, padx=24, pady=24)
    ctk.CTkLabel(page, text="补丁异常排查指引", text_color=PALETTE["Text"],
                 font=_font(24, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
    ctk.CTkLabel(page, text="按以下步骤检查文件完整性与安装状态。", text_color=PALETTE["MutedText"],
                 anchor="w", wraplength=900).pack(fill="x", pady=(0, 16))
    AlertBanner(page, "先确认游戏已完全退出", "请关闭 Steam 游戏进程，再执行下面的修复步骤。", kind="warning").pack(fill="x", pady=(0, 12))
    for step, title, body in ((1, "检查补丁文件", "确认以下文件存在且未被杀毒软件隔离："),
                               (2, "重新应用补丁", "返回主页点击“一键修复”，完成后重新启动游戏。"),
                               (3, "仍然失败？", "导出诊断信息并联系支持团队。")):
        card = StepWorkflowCard(page, step, title, body,
                                 action_text="执行" if step < 3 else "导出诊断",
                                 command=lambda s=step: print(f"执行步骤 {s}"))
        card.pack(fill="x", pady=6)
    tags = ctk.CTkFrame(page, fg_color="transparent")
    tags.pack(fill="x", pady=(10, 6))
    PillBadge(tags, "dinput8.dll", tone="accent").pack(side="left", padx=(0, 6))
    PillBadge(tags, "补丁正常", tone="success").pack(side="left", padx=6)
    PillBadge(tags, "C:\\Games\\HOI4", tone="neutral").pack(side="left", padx=6)
    return root


__all__ = [
    "PALETTE", "AlertBanner", "StepWorkflowCard", "PillBadge",
    "FramedImageContainer", "ArticleParagraphCard", "extract_inline_badges",
    "demo_patch_troubleshooting",
]
