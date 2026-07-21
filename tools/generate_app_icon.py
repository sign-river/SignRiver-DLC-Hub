"""Build Windows app icons from the user-maintained config/app.png."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config" / "app.png"
SOURCE_BACKUP = ROOT / "config" / "app-icon-source.png"
OUTPUT_ICO = ROOT / "config" / "app.ico"
# Include Win10/11 taskbar sizes (20/40) so DPI scaling stays sharp.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _square_cover(image: Image.Image, size: int) -> Image.Image:
    """Center-pad to square, then resize without trimming the artwork."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    side = max(width, height)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(rgba, ((side - width) // 2, (side - height) // 2))
    # Downscale in steps so 16–48px taskbar glyphs stay crisp.
    current = square
    while current.width > size * 2:
        nxt = max(size, current.width // 2)
        current = current.resize((nxt, nxt), Image.Resampling.LANCZOS)
    resized = current.resize((size, size), Image.Resampling.LANCZOS)
    if size <= 48:
        resized = resized.filter(ImageFilter.UnsharpMask(radius=0.6, percent=120, threshold=2))
    return resized


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"Missing icon source: {SOURCE}")
    OUTPUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, SOURCE_BACKUP)
    with Image.open(SOURCE) as source:
        frames = [_square_cover(source, size) for size in SIZES]
    frames[0].save(
        OUTPUT_ICO,
        format="ICO",
        sizes=[(image.width, image.height) for image in frames],
        append_images=frames[1:],
    )
    with Image.open(OUTPUT_ICO) as probe:
        embedded = sorted(probe.ico.sizes()) if probe.ico is not None else []
    missing = [size for size in SIZES if (size, size) not in embedded]
    if missing:
        frames[-1].save(
            OUTPUT_ICO,
            format="ICO",
            sizes=[(size, size) for size in SIZES],
        )
        with Image.open(OUTPUT_ICO) as probe:
            embedded = sorted(probe.ico.sizes()) if probe.ico is not None else []
    print(f"Wrote {OUTPUT_ICO} sizes={embedded}")
    print(f"Synced {SOURCE_BACKUP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
