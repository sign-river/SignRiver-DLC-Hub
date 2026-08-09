"""Render a plain white-background black-text notice image (CJK aware)."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",  # Microsoft YaHei Bold
    r"C:\Windows\Fonts\msyh.ttc",    # Microsoft YaHei
    r"C:\Windows\Fonts\simhei.ttf",  # SimHei
    r"C:\Windows\Fonts\simsun.ttc",  # SimSun
)


def resolve_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise SystemExit("no usable CJK font found")


_BULLET = re.compile(r"^(?P<mark>[\u00b7\u2022\-\*\d]+[.\u3001?]?\s+)")


def wrap_paragraph(
    paragraph: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> tuple[list[str], int]:
    """Wrap one paragraph; returns (lines, continuation indent in px)."""
    indent_px = 0
    bullet = _BULLET.match(paragraph)
    if bullet:
        indent_px = int(draw.textlength(bullet.group("mark"), font=font))
    if not paragraph.strip():
        return [""], 0
    lines: list[str] = []
    current = ""
    for char in paragraph:
        candidate = current + char
        if draw.textlength(candidate, font=font) > max_width and current:
            lines.append(current)
            current = char
        else:
            current = candidate
    lines.append(current)
    return lines, indent_px


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[tuple[list[str], int]]:
    return [
        wrap_paragraph(paragraph, font, max_width, draw)
        for paragraph in text.splitlines()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", type=Path, default=Path("notice.txt"))
    parser.add_argument("--output", type=Path, default=Path("dist/notice.png"))
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--font-size", type=int, default=34)
    parser.add_argument("--title-size", type=int, default=48)
    parser.add_argument("--line-spacing", type=int, default=16)
    parser.add_argument("--paragraph-gap", type=int, default=24)
    parser.add_argument("--margin", type=int, default=64)
    args = parser.parse_args()

    text = args.text.read_text(encoding="utf-8")
    title, _, body = text.partition("\n")

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_font = resolve_font(args.title_size)
    body_font = resolve_font(args.font_size)
    content_width = args.width - args.margin * 2
    title_lines = wrap_text(title, title_font, content_width, probe)
    body_paragraphs = wrap_text(body, body_font, content_width, probe)
    body_line_count = sum(len(lines) for lines, _indent in body_paragraphs)
    blank_paragraphs = sum(1 for lines, _indent in body_paragraphs if not lines or not lines[0])

    title_line_h = args.title_size + args.line_spacing
    body_line_h = args.font_size + args.line_spacing
    height = (
        args.margin * 2
        + len(title_lines) * title_line_h
        + args.paragraph_gap
        + body_line_count * body_line_h
        + blank_paragraphs * (args.paragraph_gap - args.line_spacing)
    )

    image = Image.new("RGB", (args.width, height), "white")
    draw = ImageDraw.Draw(image)
    y = args.margin
    for lines, _indent in title_lines:
        for line in lines:
            draw.text((args.margin, y), line, font=title_font, fill="black")
            y += title_line_h
    y += args.paragraph_gap
    for lines, indent_px in body_paragraphs:
        if not lines or not lines[0]:
            y += args.paragraph_gap - args.line_spacing
            continue
        for index, line in enumerate(lines):
            x = args.margin + (indent_px if index > 0 else 0)
            draw.text((x, y), line, font=body_font, fill="black")
            y += body_line_h

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)
    print(f"saved: {args.output} ({image.width}x{image.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
