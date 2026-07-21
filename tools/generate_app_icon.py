"""Build Windows app icons from config/app-icon-source.png."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config" / "app-icon-source.png"
OUTPUT_ICO = ROOT / "config" / "app.ico"
OUTPUT_PNG = ROOT / "config" / "app.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _square_cover(image: Image.Image, size: int) -> Image.Image:
    """Center-crop to square, then resize with high-quality filter."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = rgba.crop((left, top, left + side, top + side))
    return cropped.resize((size, size), Image.Resampling.LANCZOS)


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
    if len(embedded) < len(SIZES):
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
