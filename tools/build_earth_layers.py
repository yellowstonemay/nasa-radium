"""Build the analytical Earth layers used by the RADIUM Earth view.

Two layers are produced:

1. Night lights (raster)  - real VIIRS Black Marble tiles stitched and composited
   additively over a near-black base, so city lights read as lights rather than as
   a faint dusting of pixels.

2. Surface temperature field - inverse-distance interpolation of the 40 measured
   NASA POWER station climatologies, masked to 2,500 km around a real site so we
   never invent a temperature for the middle of an ocean with no measurements.

Usage: python tools/build_earth_layers.py
"""

from __future__ import annotations

import io
import json
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
TEXTURES = ROOT / "assets" / "textures"
GRIDS = ROOT / "assets" / "grids"
CACHE = ROOT / "tools" / ".tilecache"
METRICS = ROOT / "assets" / "earth-metrics.js"

LIGHTS = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Night_Lights/default/"
    "2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png"
)
TILE = 256
GRID_W, GRID_H = 720, 360
MASK_KM = 2500.0
EARTH_R_KM = 6371.0


def download(url: str) -> bytes | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / (str(abs(hash(url))) + ".png")
    if target.exists():
        return target.read_bytes()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RADIUM-hackathon/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except Exception:
        return None
    target.write_bytes(data)
    return data


def stitch_lights(zoom: int = 3) -> Image.Image:
    cols = rows = 2 ** zoom
    canvas = Image.new("RGB", (cols * TILE, rows * TILE), (2, 4, 9))

    def grab(xy):
        x, y = xy
        return x, y, download(LIGHTS.format(z=zoom, y=y, x=x))

    for x, y, data in ThreadPoolExecutor(max_workers=10).map(
        grab, [(x, y) for y in range(rows) for x in range(cols)]
    ):
        if not data:
            continue
        try:
            tile = Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception:
            continue
        base = canvas.crop((x * TILE, y * TILE, (x + 1) * TILE, (y + 1) * TILE)).convert("RGBA")
        canvas.paste(Image.alpha_composite(base, tile).convert("RGB"), (x * TILE, y * TILE))
    return ImageEnhance.Brightness(canvas).enhance(1.75)


def load_sites() -> list[dict]:
    src = METRICS.read_text(encoding="utf-8")
    body = src[src.index("{") : src.rindex(";")]
    data = json.loads(body)
    out = []
    for site in data.values():
        if site.get("tempMeanC") is None:
            continue
        out.append({"lat": site["lat"], "lon": site["lon"], "t": float(site["tempMeanC"])})
    return out


def haversine_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


HEAT_RAMP = [
    (0.00, (9, 22, 66)),
    (0.30, (24, 96, 158)),
    (0.52, (58, 186, 168)),
    (0.74, (233, 178, 68)),
    (1.00, (247, 219, 172)),
]


def ramp_color(t: float) -> tuple[int, int, int]:
    t = min(1.0, max(0.0, t))
    for i in range(len(HEAT_RAMP) - 1):
        p0, c0 = HEAT_RAMP[i]
        p1, c1 = HEAT_RAMP[i + 1]
        if t <= p1:
            f = (t - p0) / max(1e-6, p1 - p0)
            return tuple(round(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))
    return HEAT_RAMP[-1][1]


def build_temp_field(sites: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    lats = 90.0 - (np.arange(GRID_H) + 0.5) * (180.0 / GRID_H)
    lons = -180.0 + (np.arange(GRID_W) + 0.5) * (360.0 / GRID_W)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    weight_sum = np.zeros((GRID_H, GRID_W))
    value_sum = np.zeros((GRID_H, GRID_W))
    nearest = np.full((GRID_H, GRID_W), 1e9)

    for site in sites:
        coslat = np.cos(np.deg2rad(lat_grid))
        dx = (lon_grid - site["lon"]) * coslat
        dy = lat_grid - site["lat"]
        dist = np.sqrt(dx * dx + dy * dy) * 111.0  # km, good enough for weighting
        # Gaussian kernel keeps the field smooth instead of producing hard blobs.
        w = np.exp(-(dist ** 2) / (2.0 * 1150.0 ** 2)) + 0.02 / np.maximum(dist, 200.0)
        weight_sum += w
        value_sum += w * site["t"]
        nearest = np.minimum(nearest, dist)

    field = value_sum / np.maximum(weight_sum, 1e-12)
    return field, nearest


def main() -> int:
    TEXTURES.mkdir(parents=True, exist_ok=True)
    GRIDS.mkdir(parents=True, exist_ok=True)

    print("[earth] VIIRS night lights")
    lights = stitch_lights(3)
    lit = np.asarray(lights.convert("L"), dtype=np.float32)
    coverage = float((lit > 12).mean() * 100)
    print(f"  lit-pixel coverage {coverage:.2f}%")
    if coverage < 1.0:
        print("  ! sparse product at this zoom; skipping night-lights layer", flush=True)
    else:
        lights.save(TEXTURES / "earth_lights.jpg", quality=86, optimize=True)
        print(f"  earth_lights.jpg {lights.size} {(TEXTURES / 'earth_lights.jpg').stat().st_size // 1024} KB")

    sites = load_sites()
    print(f"[earth] temperature field from {len(sites)} measured site climatologies")
    field, nearest = build_temp_field(sites)
    masked = nearest <= MASK_KM
    print(f"  interpolated coverage {masked.mean() * 100:.1f}% of the globe")
    lo, hi = float(field[masked].min()), float(field[masked].max())
    print(f"  range {lo:.1f} C .. {hi:.1f} C")

    scaled = np.clip((field - lo) / max(1e-6, hi - lo), 0, 1)
    lut = np.array([ramp_color(v / 255.0) for v in range(256)], dtype=np.uint8)
    rgba = np.zeros((GRID_H, GRID_W, 4), dtype=np.uint8)
    rgba[..., :3] = lut[np.round(scaled * 255).astype(np.uint8)]
    # Fade the alpha out near the mask edge so the field does not end in a hard line.
    fade = np.clip((MASK_KM - nearest) / 600.0, 0, 1)
    rgba[..., 3] = np.round(fade * 225).astype(np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(GRIDS / "earth-temp.png", optimize=True)
    print(f"  earth-temp.png {(GRIDS / 'earth-temp.png').stat().st_size // 1024} KB")

    meta = {
        "layer": {
            "file": "assets/grids/earth-temp.png",
            "min": round(lo, 2),
            "max": round(hi, 2),
            "maskKm": MASK_KM,
            "sites": len(sites),
        },
        "provenance": "Inverse-distance interpolation of 40 NASA POWER 2001-2020 climatologies",
    }
    (GRIDS / "earth-meta.js").write_text(
        "window.RADIUM_GRID_EARTH = " + json.dumps(meta, indent=2) + ";\n", encoding="utf-8"
    )
    print("  wrote earth-meta.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
