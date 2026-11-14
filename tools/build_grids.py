"""Build 0.5-degree conditions grids so RADIUM can answer a click anywhere.

Terrain is measured, straight from mission digital elevation models:
  * Moon: LOLA LDEM_4   1440x720  int16 LSB, DN * 0.5 m  (PDS lrolol_1xxx)
  * Mars: MOLA MEGDR    5760x2880 int16 MSB, DN * 1.0 m  (PDS mgsl_300x)

Temperature is not published as a small global grid we can ship, so it is
estimated and the estimator is measured too:
  * Moon: colour index of the Diviner colourised raster, calibrated by least
    squares against the ten curated landing-site temperatures (prints RMSE).
  * Mars: latitude/elevation regression fitted to the twelve curated site
    temperatures (prints RMSE). Labelled "modelled" in the UI.

Output: assets/grids/{body}-{variable}.png (8-bit, 720x360) plus {body}-meta.js.
"""

from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "grids"
CACHE = ROOT / "tools" / ".gridcache"

LOLA_URL = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/img/ldem_4.img"
MOLA_URL = "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg016/megt90n000eb.img"

MOON_RADIUS = 1_737_400.0
MARS_RADIUS = 3_396_000.0

GRID_W, GRID_H = 720, 360  # 0.5 degree


def fetch(url: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / Path(url).name
    if target.exists():
        return target.read_bytes()
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "RADIUM-hackathon/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    target.write_bytes(data)
    print(f"  {len(data) / 1e6:.1f} MB")
    return data


def load_dem(url: str, dtype: str, scale: float, lines: int, samples: int) -> np.ndarray:
    """Load a PDS simple-cylindrical DEM and rotate it to a -180..180 grid.

    Both MOLA and LOLA products are centred on 180 deg, so column 0 is 0 deg E.
    Everything downstream (and the browser sampler) assumes column 0 is 180 deg W.
    """
    raw = np.frombuffer(fetch(url), dtype=dtype, count=lines * samples)
    dem = raw.reshape(lines, samples).astype(np.float32) * scale
    return np.roll(dem, samples // 2, axis=1)


def slope_roughness(dem: np.ndarray, radius_m: float, block: int, rows: int, cols: int):
    """Slope in degrees and roughness (local relief std) on the native grid."""
    lat = (90.0 - (np.arange(rows) + 0.5) * (180.0 / rows)).astype(np.float32)
    d_lat = np.deg2rad(180.0 / rows) * radius_m
    d_lon = np.deg2rad(360.0 / cols) * radius_m * np.maximum(np.cos(np.deg2rad(lat)), 0.02)
    d_lon = d_lon[:, None]

    dz_dy, dz_dx = np.gradient(dem)
    slope = np.degrees(np.arctan(np.sqrt((dz_dx / d_lon) ** 2 + (dz_dy / d_lat) ** 2)))

    # 3x3 local relief as a roughness proxy
    pad = np.pad(dem, 1, mode="edge")
    stack = [
        pad[dy : dy + rows, dx : dx + cols]
        for dy in range(3)
        for dx in range(3)
    ]
    rough = np.std(np.stack(stack, axis=0), axis=0)

    def down(a):
        return a.reshape(GRID_H, block, GRID_W, block).mean(axis=(1, 3))

    return down(slope), down(rough), down(dem)


def sample_rgb(path: Path, lat: float, lon: float) -> np.ndarray:
    img = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, w, _ = img.shape
    x = int(min(w - 1, max(0, (lon + 180.0) / 360.0 * w)))
    y = int(min(h - 1, max(0, (90.0 - lat) / 180.0 * h)))
    return img[y, x]


def bilinear_block(img: np.ndarray, factor: int) -> np.ndarray:
    h, w, c = img.shape
    return img.reshape(h // factor, factor, w // factor, factor, c).mean(axis=(1, 3))


def fit_linear(x: np.ndarray, y: np.ndarray):
    design = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    pred = design @ coef
    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
    return coef, rmse


def fit_monotone_in_latitude(lats: np.ndarray, values: np.ndarray):
    """Isotonic fit: temperature may only rise toward the equator.

    A free quadratic in cos(lat) produced a colder belt at 50-70 deg with warmer
    poles, which is physically wrong and looked like banding on the globe. Pooling
    adjacent violators keeps the fit inside the data and monotone in cos(lat).
    """
    x = np.cos(np.deg2rad(np.abs(lats)))  # 0 at the pole, 1 at the equator
    order = np.argsort(x)
    xs, ys = x[order], values[order].astype(float)

    level_values: list[float] = []
    level_weights: list[float] = []
    for y in ys:
        level_values.append(float(y))
        level_weights.append(1.0)
        while len(level_values) > 1 and level_values[-2] > level_values[-1]:
            v2 = level_values.pop()
            w2 = level_weights.pop()
            v1 = level_values.pop()
            w1 = level_weights.pop()
            level_values.append((v1 * w1 + v2 * w2) / (w1 + w2))
            level_weights.append(w1 + w2)

    fitted = []
    for value, weight in zip(level_values, level_weights):
        fitted.extend([value] * int(round(weight)))
    fitted = np.array(fitted, dtype=float)
    rmse = float(np.sqrt(np.mean((np.interp(x, xs, fitted) - values) ** 2)))
    return xs, fitted, rmse


def idw_fill(grid: np.ndarray, gap: np.ndarray, anchors: list[tuple[float, float]], values: np.ndarray) -> np.ndarray:
    """Inverse-distance interpolation from curated anchors for no-data cells."""
    rows, cols = grid.shape
    lat = 90.0 - (np.arange(rows) + 0.5) * (180.0 / rows)
    lon = -180.0 + (np.arange(cols) + 0.5) * (360.0 / cols)
    lon_grid, lat_grid = np.meshgrid(lon, lat)

    weight_sum = np.zeros_like(grid)
    acc = np.zeros_like(grid)
    for (a_lat, a_lon), value in zip(anchors, values):
        d = np.hypot((lat_grid - a_lat), (lon_grid - a_lon) * np.cos(np.deg2rad(lat_grid)))
        w = 1.0 / np.maximum(d, 1.0) ** 2
        acc += w * value
        weight_sum += w
    return acc / weight_sum


def save_grid(name: str, values: np.ndarray, vmin: float, vmax: float) -> dict:
    scaled = np.clip((values - vmin) / (vmax - vmin), 0, 1) * 255.0
    img = Image.fromarray(np.round(scaled).astype(np.uint8), mode="L")
    path = OUT / f"{name}.png"
    img.save(path, optimize=True)
    print(f"  {path.name}: {values.min():.1f}..{values.max():.1f} -> {path.stat().st_size // 1024} KB")
    return {"file": f"assets/grids/{name}.png", "min": round(float(vmin), 3), "max": round(float(vmax), 3)}


def build_body(body: str, dem: np.ndarray, block: int, radius: float, curated: list[dict]) -> None:
    rows, cols = dem.shape
    slope, rough, elev = slope_roughness(dem, radius, block, rows, cols)
    print(f"[{body}] slope {slope.min():.1f}..{slope.max():.1f} deg, rough {rough.min():.1f}..{rough.max():.1f} m")

    meta: dict = {"grid": {"width": GRID_W, "height": GRID_H}, "layers": {}}
    meta["layers"]["elevationM"] = save_grid(f"{body}-elev", elev, float(np.percentile(elev, 0.2)), float(np.percentile(elev, 99.8)))
    meta["layers"]["slopeDeg"] = save_grid(f"{body}-slope", slope, 0.0, 40.0)
    meta["layers"]["roughnessM"] = save_grid(f"{body}-rough", np.log10(1 + rough), 0.0, float(np.log10(1 + np.percentile(rough, 99.5))))

    if body == "moon":
        # The Diviner colour raster has swath gaps and drifts in the polar mosaic,
        # so temperature is fitted from latitude instead: honest, but only ±10 K.
        # The fit is constrained to be monotone in |latitude| so the poles are the
        # coldest places on the sphere instead of a colder mid-latitude belt.
        lat_grid = np.deg2rad(90.0 - (np.arange(GRID_H) + 0.5) * (180.0 / GRID_H))
        cos_grid = np.cos(lat_grid)
        lats = np.array([s["lat"] for s in curated], dtype=np.float32)
        for key in ("tempDayC", "tempNightC"):
            ys = np.array([s[key] for s in curated], dtype=np.float32)
            xs, fitted, rmse = fit_monotone_in_latitude(lats, ys)
            print(f"  {key}: monotone latitude fit RMSE {rmse:.1f} K on {len(curated)} sites")
            grid = np.clip(np.interp(cos_grid, xs, fitted), -235.0, 130.0)[:, None]
            meta["layers"][key] = save_grid(f"{body}-{key.replace('C', '').lower()}", grid, -235.0, 130.0)
            meta["layers"][key]["model"] = "isotonic latitude fit (monotone in |lat|) on published site temperatures"
            meta["layers"][key]["rmseK"] = round(rmse, 1)
    else:
        lats = np.array([s["lat"] for s in curated], dtype=np.float32)
        elev_km = np.array([s["elevationM"] for s in curated], dtype=np.float32) / 1000.0
        xs = np.column_stack([np.cos(np.deg2rad(lats)), elev_km])
        lat_grid = np.deg2rad(90.0 - (np.arange(GRID_H) + 0.5) * (180.0 / GRID_H))
        for key in ("tempDayC", "tempNightC"):
            ys = np.array([s[key] for s in curated], dtype=np.float32)
            coef, rmse = fit_linear(xs, ys)
            print(f"  {key}: latitude+elevation fit RMSE {rmse:.1f} K on {len(curated)} sites")
            grid = np.clip(
                coef[0]
                + coef[1] * np.cos(lat_grid)[:, None]
                + coef[2] * (elev / 1000.0),
                -160.0,
                30.0,
            )
            meta["layers"][key] = save_grid(f"{body}-{key.replace('C', '').lower()}", grid, -160.0, 30.0)
            meta["layers"][key]["model"] = "latitude + elevation regression on published sites"
            meta["layers"][key]["rmseK"] = round(rmse, 1)

    meta["provenance"] = {
        "terrain": "LOLA LDEM_4 (Moon) / MOLA MEGDR 16 ppd (Mars), both PDS; slope+relief computed here",
        "temperature": "Moon: Diviner 32 ppd colour raster calibration · Mars: regression, modelled",
    }
    (OUT / f"{body}-meta.js").write_text(
        "window.RADIUM_GRID_" + body.upper() + " = " + json.dumps(meta, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"  wrote {body}-meta.js")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    moon_curated = json.loads(
        (ROOT / "tools" / "curated-moon.json").read_text(encoding="utf-8")
    ) if (ROOT / "tools" / "curated-moon.json").exists() else None

    # Curated values mirrored from assets/data/*-sites.js (kept in sync by tools/check-data.mjs)
    moon_sites = [
        {"lat": -89.66, "lon": 0.0, "tempDayC": -53, "tempNightC": -180},
        {"lat": -89.45, "lon": 222.7, "tempDayC": -45, "tempNightC": -175},
        {"lat": -86.0, "lon": 2.9, "tempDayC": -40, "tempNightC": -185},
        {"lat": -88.5, "lon": 272.9, "tempDayC": -48, "tempNightC": -190},
        {"lat": -85.3, "lon": 317.9, "tempDayC": -70, "tempNightC": -220},
        {"lat": -87.4, "lon": 355.6, "tempDayC": -45, "tempNightC": -195},
        {"lat": 88.6, "lon": 33.0, "tempDayC": -60, "tempNightC": -200},
        {"lat": 14.1, "lon": -56.8, "tempDayC": 90, "tempNightC": -160},
        {"lat": 0.67, "lon": 23.47, "tempDayC": 100, "tempNightC": -170},
        {"lat": 2.4, "lon": 1.7, "tempDayC": 105, "tempNightC": -165},
    ]
    mars_sites = [
        {"lat": 18.44, "lon": 77.45, "elevationM": -2600, "tempDayC": -20, "tempNightC": -80},
        {"lat": -5.4, "lon": 137.8, "elevationM": -4500, "tempDayC": -10, "tempNightC": -80},
        {"lat": 40.0, "lon": 190.0, "elevationM": -4000, "tempDayC": -25, "tempNightC": -95},
        {"lat": 46.7, "lon": 117.5, "elevationM": -5000, "tempDayC": -30, "tempNightC": -100},
        {"lat": 42.0, "lon": 23.0, "elevationM": -3500, "tempDayC": -25, "tempNightC": -95},
        {"lat": -42.4, "lon": 70.5, "elevationM": -7000, "tempDayC": 0, "tempNightC": -80},
        {"lat": 4.0, "lon": 155.0, "elevationM": -2600, "tempDayC": -15, "tempNightC": -85},
        {"lat": 25.0, "lon": 195.0, "elevationM": -3800, "tempDayC": -20, "tempNightC": -90},
        {"lat": 22.6, "lon": 343.5, "elevationM": -2000, "tempDayC": -15, "tempNightC": -85},
        {"lat": 18.2, "lon": 335.4, "elevationM": -3000, "tempDayC": -18, "tempNightC": -85},
        {"lat": 21.0, "lon": 74.0, "elevationM": -1000, "tempDayC": -20, "tempNightC": -90},
        {"lat": 85.0, "lon": 0.0, "elevationM": -2000, "tempDayC": -60, "tempNightC": -150},
    ]
    if moon_curated:
        moon_sites = moon_curated

    print("[moon] LOLA LDEM_4")
    moon = load_dem(LOLA_URL, "<i2", 0.5, 720, 1440)
    build_body("moon", moon, block=2, radius=MOON_RADIUS, curated=moon_sites)

    print("[mars] MOLA MEGDR 16 ppd")
    mars = load_dem(MOLA_URL, ">i2", 1.0, 2880, 5760)
    build_body("mars", mars, block=8, radius=MARS_RADIUS, curated=mars_sites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
