"""Render the Moon day/night temperature layers as clean globe textures.

The Diviner colour product on Moon Trek only has data over the southern hemisphere
at the zoom levels it publishes (z3 is the deepest tile set, 24 of 32 tiles present),
so stitching it produced a black northern cap, a seam at the equator and vertical
no-data streaks. This script instead renders the temperature grid that
tools/build_grids.py already derives (latitude regression calibrated against
published Diviner site temperatures, +/-8 K day, +/-10 K night), which is complete
and seamless, and modulates it with the real LRO WAC mosaic so the terrain still
reads as terrain.

Output: assets/textures/moon_day.jpg and moon_night.jpg at 2048x1024.

Run: python tools/build_moon_temp_textures.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
GRIDS = ROOT / "assets" / "grids"
OUT = ROOT / "assets" / "textures"
BASE = OUT / "moon_surface.jpg"

WIDTH, HEIGHT = 2048, 1024

# Display ranges (degrees C): padded around what the model actually produces so
# each layer uses its whole ramp, with the legend stating the exact span.
RANGES = {"moon_day": (-65.0, 110.0), "moon_night": (-200.0, -150.0)}

# Day is a warm ramp, night a cold one, both in the same family as the computed
# Earth fields so every heat layer in the app reads alike.
RAMPS = {
    "moon_day": [
        (0.00, (16, 26, 61)),
        (0.32, (33, 102, 168)),
        (0.55, (56, 168, 154)),
        (0.76, (224, 168, 60)),
        (1.00, (253, 240, 204)),
    ],
    "moon_night": [
        (0.00, (5, 9, 20)),
        (0.30, (22, 34, 74)),
        (0.55, (51, 72, 143)),
        (0.78, (127, 168, 217)),
        (1.00, (232, 245, 255)),
    ],
}


def load_meta() -> dict:
    text = (GRIDS / "moon-meta.js").read_text(encoding="utf-8")
    body = text.split("=", 1)[1].strip().rstrip(";")
    return json.loads(body)


def read_profile(path: Path, lo: float, hi: float) -> np.ndarray:
    """The grid is stored as a one-pixel-wide latitude profile, so read the rows
    directly and interpolate vertically: resizing a 1 px image leaves stripes."""
    image = Image.open(path).convert("L")
    values = np.asarray(image, dtype=np.float32)[:, 0] / 255.0
    centres = (np.arange(values.size) + 0.5) / values.size
    rows = (np.arange(HEIGHT) + 0.5) / HEIGHT
    profile = np.interp(rows, centres, lo + values * (hi - lo))
    kernel = np.ones(9, dtype=np.float32) / 9.0
    padded = np.pad(profile, 4, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def colourise(normalised: np.ndarray, ramp) -> np.ndarray:
    t = np.clip(normalised, 0.0, 1.0)
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    for i in range(len(ramp) - 1):
        p0, c0 = ramp[i]
        p1, c1 = ramp[i + 1]
        band = (t >= p0) & (t <= p1)
        if not band.any():
            continue
        f = ((t[band] - p0) / max(1e-6, p1 - p0))[:, None]
        out[band] = np.array(c0, dtype=np.float32) * (1 - f) + np.array(c1, dtype=np.float32) * f
    out[t > ramp[-1][0]] = ramp[-1][1]
    return out


def relief_luminance() -> np.ndarray:
    """LRO WAC mosaic brightness, used to modulate the colour so craters show."""
    base = Image.open(BASE).convert("L").resize((WIDTH, HEIGHT), Image.LANCZOS)
    # The stitched mosaic has hairline tile seams; a light blur removes them
    # without touching the crater relief.
    base = base.filter(ImageFilter.GaussianBlur(1.1))
    base = base.filter(ImageFilter.UnsharpMask(radius=2, percent=65, threshold=3))
    lum = np.asarray(base, dtype=np.float32) / 255.0
    lo, hi = np.percentile(lum, [2, 98])
    return np.clip((lum - lo) / max(1e-6, hi - lo), 0.0, 1.0)


def render(key: str, grid_file: str, out_name: str, lum: np.ndarray) -> dict:
    lo, hi = RANGES[key]
    profile = read_profile(GRIDS / grid_file, -235.0, 130.0)
    t = np.clip((profile - lo) / max(1e-6, hi - lo), 0.0, 1.0)
    plane = np.repeat(t[:, None], WIDTH, axis=1)
    rgb = colourise(plane, RAMPS[key])

    # Relief modulation keeps hue but lets the terrain read through.
    shade = 0.74 + 0.60 * lum
    rgb = np.clip(rgb * shade[:, :, None], 0, 255)

    image = Image.fromarray(np.round(rgb).astype(np.uint8), mode="RGB")
    path = OUT / out_name
    image.save(path, quality=86, optimize=True, progressive=True)
    return {
        "key": key,
        "file": f"assets/textures/{out_name}",
        "bytes": path.stat().st_size,
        "rangeC": [lo, hi],
        "modelRangeC": [round(float(profile.min()), 1), round(float(profile.max()), 1)],
    }


def main() -> int:
    meta = load_meta()
    lum = relief_luminance()
    OUT.mkdir(parents=True, exist_ok=True)

    day = meta["layers"]["tempDayC"]
    night = meta["layers"]["tempNightC"]
    report = [
        render("moon_day", "moon-tempday.png", "moon_day.jpg", lum),
        render("moon_night", "moon-tempnight.png", "moon_night.jpg", lum),
    ]
    for item in report:
        print(f"{item['key']}: {item['bytes'] / 1024:.0f} KB, ramp {item['rangeC']} C, "
              f"model occupies {item['modelRangeC']} C")

    legend = {
        "generated": "tools/build_moon_temp_textures.py",
        "resolution": [WIDTH, HEIGHT],
        "method": "latitude regression calibrated on published Diviner site temperatures, "
                  "rendered over the LRO WAC mosaic for relief",
        "error": {"moon_day": "±8 K", "moon_night": "±10 K"},
        "layers": {item["key"]: item for item in report},
    }
    (GRIDS / "moon-temp-textures.json").write_text(json.dumps(legend, indent=2) + "\n", encoding="utf-8")
    print("wrote assets/grids/moon-temp-textures.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
