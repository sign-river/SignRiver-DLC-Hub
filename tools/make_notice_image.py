"""Render a plain white-background black-text notice image (CJK aware).

Supports:
- first-line indent of 2 CJK characters for normal paragraphs
- bullet rows with hanging indent
- ``**bold**`` inline markers rendered with a bold font
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_REGULAR = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_FALLBACK = (
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)

_BULLET = re.compile(r"^(?P<mark>[·•\-*\d]+[.、]?\s+)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def resolve_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [FONT_BOLD if bold else FONT_REGULAR, *FONT_FALLBACK]
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise SystemExit("no usable CJK font found")


def parse_fragments(paragraph: str) -> list[tuple[str, bool]]:
    """Split a paragraph into (text, bold) fragments from **...** markers."""
    fragments: list[tuple[str, bool]] = []
    for index, part in enumerate(re.split(_BOLD, paragraph)):
        if not part:
            continue
        fragments.append((part, index % 2 == 1))
    return fragments


def expand_chars(
    fragments: list[tuple[str, bool]],
) -> list[tuple[str, bool]]:
    return [(char, bold) for text, bold in fragments for char in text]



def wrap_line(
    chars: list[tuple[str, bool]],
    font: ImageFont.FreeTypeFont,
    bold_font: ImageFont.FreeTypeFont,
    max_width: int,
    probe: ImageDraw.ImageDraw,
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Split chars into (first_line, rest) by pixel width."""
    line: list[tuple[str, bool]] = []
    width = 0
    rest = list(chars)
    for index, (char, bold) in enumerate(chars):
        w = int(probe.textlength(char, font=bold_font if bold else font))
        if width + w > max_width and line:
            rest = chars[index:]
            break
        line.append((char, bold))
        width += w
    else:
        rest = []
    return line, rest


def wrap_paragraph(
    fragments: list[tuple[str, bool]],
    font: ImageFont.FreeTypeFont,
    bold_font: ImageFont.FreeTypeFont,
    max_width: int,
    probe: ImageDraw.ImageDraw,
) -> tuple[list[list[tuple[str, bool]]], int]:
    chars = expand_chars(fragments)
    first_text = "".join(ch for ch, _b in chars)
    bullet = _BULLET.match(first_text)
    indent_px = int(probe.textlength(bullet.group("mark"), font=font)) if bullet else 0
    if not chars:
        return [[]], indent_px
    lines: list[list[tuple[str, bool]]] = []
    remaining = chars
    while remaining:
        line, remaining = wrap_line(remaining, font, bold_font, max_width, probe)
        lines.append(line)
    return lines, indent_px


def render_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    line: list[tuple[str, bool]],
    font: ImageFont.FreeTypeFont,
    bold_font: ImageFont.FreeTypeFont,
) -> None:
    for text, bold in group_by_style(line):
        draw.text((x, y), text, font=bold_font if bold else font, fill="black")
        x += int(draw.textlength(text, font=bold_font if bold else font))


def group_by_style(line: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    groups: list[tuple[str, bool]] = []
    for char, bold in line:
        if groups and groups[-1][1] == bold:
            groups[-1] = (groups[-1][0] + char, bold)
        else:
            groups.append((char, bold))
    return groups


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

    source = args.text.read_text(encoding="utf-8")
    title, _, body = source.partition("\n")

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_font = resolve_font(args.title_size, bold=True)
    body_font = resolve_font(args.font_size, bold=False)
    bold_font = resolve_font(args.font_size, bold=True)
    content_width = args.width - args.margin * 2

    title_lines = [expand_chars(parse_fragments(title))]
    paragraphs = [
        wrap_paragraph(parse_fragments(paragraph), body_font, bold_font, content_width, probe)
        for paragraph in body.splitlines()
    ]

    title_line_h = args.title_size + args.line_spacing
    body_line_h = args.font_size + args.line_spacing
    body_line_count = sum(len(lines) for lines, _indent in paragraphs)
    blank_paragraphs = sum(1 for lines, _indent in paragraphs if not lines or not lines[0])
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
    for line in title_lines:
        render_line(draw, args.margin, y, line, title_font, title_font)
        y += title_line_h
    y += args.paragraph_gap

    first_indent = int(args.font_size * 2)
    for lines, indent_px in paragraphs:
        if not lines or not lines[0]:
            y += args.paragraph_gap - args.line_spacing
            continue
        for index, line in enumerate(lines):
            if index == 0 and indent_px == 0:
                x = args.margin + first_indent
            else:
                x = args.margin + (indent_px if index > 0 else 0)
            render_line(draw, x, y, line, body_font, bold_font)
            y += body_line_h

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)
    print(f"saved: {args.output} ({image.width}x{image.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
