"""Build Windows app icons from config/app-icon-source.png."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config" / "app-icon-source.png"
OUTPUT_ICO = ROOT / "config" / "app.ico"
OUTPUT_PNG = ROOT / "config" / "app.png"
# Include Win10/11 taskbar sizes (20/40) so DPI scaling stays sharp.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _square_cover(image: Image.Image, size: int) -> Image.Image:
    """Center-crop to square, then resize with high-quality filter."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = rgba.crop((left, top, left + side, top + side))
    # Downscale in steps so 16–48px taskbar glyphs stay crisp.
    current = cropped
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
    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as source:
        frames = [_square_cover(source, size) for size in SIZES]
    frames[-1].save(OUTPUT_PNG)
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
    print(f"Wrote {OUTPUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
