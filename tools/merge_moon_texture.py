"""Merge the detailed LRO WAC mosaic with NASA's polar-filled LROC texture.

The WAC equirectangular mosaic has far more mid-latitude detail but a no-data
band near the poles, which projects into black streaks at the top of the globe.
The SVS "LROC colour poles" texture has full polar coverage but is blurred above
about 80 degrees. This merges them: WAC everywhere below 78 degrees, SVS above
88 degrees, and a smooth ramp between, so the pole is covered and the equatorial
terrain keeps its detail.

Usage: python tools/merge_moon_texture.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
TEX = ROOT / "assets" / "textures"

DETAIL = TEX / "moon_base.jpg"          # LRO WAC mosaic, high detail
POLES = TEX / "moon_lroc_poles.jpg"     # SVS texture with polar fill
OUT = TEX / "moon_surface.jpg"

SOFT_LO, SOFT_HI = 66.0, 80.0


def main() -> int:
    detail = Image.open(DETAIL).convert("RGB")
    poles = Image.open(POLES).convert("RGB").resize(detail.size, Image.LANCZOS)

    a = np.asarray(detail, dtype=np.float32)
    b = np.asarray(poles, dtype=np.float32)
    rows, cols = a.shape[:2]

    lat = 90.0 - (np.arange(rows) + 0.5) * (180.0 / rows)
    t = np.clip((np.abs(lat) - SOFT_LO) / (SOFT_HI - SOFT_LO), 0.0, 1.0)
    # Smoothstep so the seam is invisible.
    t = t * t * (3.0 - 2.0 * t)
    w = t[:, None, None]

    merged = a * (1.0 - w) + b * w

    # The cap rows are stretched radially when wrapped onto the sphere, which
    # reads as a pinwheel. A latitude-graded blur removes the streaks without
    # touching the detailed mid-latitude mosaic.
    image = Image.fromarray(np.clip(merged, 0, 255).astype(np.uint8), mode="RGB")

    # Radial "spokes" at the poles come from compressing polar orbits into an
    # equirectangular grid. They run along longitude, so a horizontal-only blur
    # that strengthens toward the pole removes them without softening the
    # mid-latitudes.
    def smooth_band(band: Image.Image, strength: float) -> Image.Image:
        width, height = band.size
        factor = max(1, int(round(2 + strength * 14)))
        small = band.resize((max(8, width // factor), height), Image.BILINEAR)
        return small.resize((width, height), Image.BILINEAR)

    cap = int(rows * (90.0 - SOFT_LO) / 180.0)
    for top in (True, False):
        box = (0, 0, cols, cap) if top else (0, rows - cap, cols, rows)
        band = image.crop(box)
        # Split the cap in two so the outer (more distorted) ring is smoothed more.
        half = cap // 2
        pieces = [
            (band.crop((0, 0, cols, half)), 1.0 if top else 0.35),
            (band.crop((0, half, cols, cap)), 0.35 if top else 1.0),
        ]
        for index, (piece, strength) in enumerate(pieces):
            out = smooth_band(piece, strength)
            image.paste(out, (box[0], box[1] + index * half))
    image.save(OUT, quality=90, optimize=True)

    grey = np.asarray(image.convert("L"), dtype=np.float32)
    print(f"wrote {OUT.name} {OUT.stat().st_size // 1024} KB")
    for label, sl in (("north cap", grey[:6]), ("north 80-88", grey[24:68]), ("equator", grey[1000:1060]), ("south cap", grey[-6:])):
        print(f"  {label:12s} mean={sl.mean():6.1f} std={sl.std():6.1f} dark%={(sl < 12).mean() * 100:5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
