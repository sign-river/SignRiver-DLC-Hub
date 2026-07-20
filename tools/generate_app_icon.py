"""Generate the Windows app icon shipped under config/app.ico."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ICO = ROOT / "config" / "app.ico"
OUTPUT_PNG = ROOT / "config" / "app.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BRAND = (58, 126, 191, 255)       # #3A7EBF
PRIMARY = (25, 118, 210, 255)    # #1976D2
LIGHT = (234, 243, 251, 255)     # #EAF3FB
WHITE = (255, 255, 255, 255)


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _draw_mark(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, size // 16)
    radius = max(2, size // 5)
    _rounded_rect(
        draw,
        (margin, margin, size - margin - 1, size - margin - 1),
        radius,
        BRAND,
    )
    # Soft inner highlight for depth at larger sizes.
    if size >= 48:
        inset = max(2, size // 12)
        _rounded_rect(
            draw,
            (inset, inset, size - inset - 1, size - inset - 1),
            max(2, radius - inset // 2),
            PRIMARY,
        )

    # River wave — SignRiver cue.
    mid = size / 2
    amp = size * 0.08
    wave_y = mid + size * 0.08
    points: list[tuple[float, float]] = []
    for index in range(0, 33):
        x = size * (0.18 + 0.64 * index / 32)
        y = wave_y + amp * math.sin(index / 32 * math.pi * 2.2)
        points.append((x, y))
    width = max(2, size // 14)
    draw.line(points, fill=WHITE, width=width, joint="curve")

    # Second quieter wave.
    points2: list[tuple[float, float]] = []
    for index in range(0, 33):
        x = size * (0.18 + 0.64 * index / 32)
        y = wave_y + size * 0.12 + amp * 0.7 * math.sin(
            index / 32 * math.pi * 2.2 + 0.8
        )
        points2.append((x, y))
    draw.line(points2, fill=LIGHT, width=max(1, width - 1), joint="curve")

    # Unlock keyhole above the river.
    cx = mid
    cy = size * 0.32
    ring = max(2, int(size * 0.10))
    stroke = max(1, size // 16)
    draw.ellipse(
        (cx - ring, cy - ring, cx + ring, cy + ring),
        outline=WHITE,
        width=stroke,
    )
    inner = max(1, int(size * 0.035))
    draw.ellipse(
        (cx - inner, cy - inner, cx + inner, cy + inner),
        fill=WHITE,
    )
    stem_w = max(2, int(size * 0.07))
    stem_top = cy + ring * 0.55
    stem_bottom = cy + ring + max(2, int(size * 0.10))
    draw.rounded_rectangle(
        (cx - stem_w / 2, stem_top, cx + stem_w / 2, stem_bottom),
        radius=max(1, stem_w // 3),
        fill=WHITE,
    )
    # Key bit — small side notch so it reads as an unlock mark, not a power glyph.
    bit_w = max(2, int(size * 0.06))
    bit_h = max(1, int(size * 0.035))
    draw.rectangle(
        (
            cx + stem_w / 2 - 1,
            stem_bottom - bit_h * 2,
            cx + stem_w / 2 + bit_w,
            stem_bottom - bit_h,
        ),
        fill=WHITE,
    )
    return image


def main() -> int:
    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    # Hand-draw every size so 16px strokes stay readable, then pack into one ICO.
    frames = [_draw_mark(size) for size in SIZES]
    frames[-1].save(OUTPUT_PNG)
    frames[0].save(
        OUTPUT_ICO,
        format="ICO",
        sizes=[(image.width, image.height) for image in frames],
        append_images=frames[1:],
    )
    from PIL import Image as _Image

    with _Image.open(OUTPUT_ICO) as probe:
        embedded = sorted(probe.ico.sizes()) if probe.ico is not None else []
    if len(embedded) < len(SIZES):
        # Older Pillow builds ignore append_images; fall back to resampled pack.
        frames[-1].save(
            OUTPUT_ICO,
            format="ICO",
            sizes=[(size, size) for size in SIZES],
        )
    print(f"Wrote {OUTPUT_ICO}")
    print(f"Wrote {OUTPUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
