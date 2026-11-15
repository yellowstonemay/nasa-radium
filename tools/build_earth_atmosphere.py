"""Extra Earth layers that are modelled rather than measured raster products.

  * sunlight - NASA POWER measured 20-year means at the 79 catalogued sites,
               blended with a clear-sky latitude term and interpolated. The
               WorldClim radiation product is not reachable from this network,
               so the measured anchors are the honest alternative.
  * pressure - barometric, from the shipped elevation raster.

Snow/ice, barren ground and green cover come from the MODIS land-cover shares
that tools/build_land_use.py already bins, so they are written there.

Run: python tools/build_earth_atmosphere.py
"""

from __future__ import annotations

import json
import math
import re
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GRIDS = ROOT / "assets" / "grids"
DATA = ROOT / "assets" / "data"
CACHE = ROOT / "tools" / ".gridcache" / "atmos"

MERC_PX = 1440
W, H = 720, 360               # 0.25 degree working grid, converted on the way out
MERC_LAT = 85.0511287798

GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/{layer}/default/{time}/{matrix}/{z}/{row}/{col}.png"
COLORMAP = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/{name}.xml"
TILE_Z = 1                    # 3 x 2 tiles of 512 px: 0.23 deg per pixel
TILE_COLS, TILE_ROWS = 3, 2

# One mid-month composite each, so a full annual cycle is covered.
MONTHS = [f"{year}-{month:02d}-15"
          for year in (2023, 2024) for month in range(1, 13)]


def fetch(url: str, name: str, tries: int = 3) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists():
        return path.read_bytes()
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RADIUM-hackathon/1.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            path.write_bytes(data)
            return data
        except Exception as err:
            last = err
    raise RuntimeError(f"could not fetch {url}: {last}")


def grid_lat_lon() -> tuple[np.ndarray, np.ndarray]:
    lat = 90.0 - (np.arange(H) + 0.5) * (180.0 / H)
    lon = -180.0 + (np.arange(W) + 0.5) * (360.0 / W)
    return np.meshgrid(lat, lon, indexing="ij")


def load_elevation_grid() -> np.ndarray:
    """Shipped elevation raster, resampled onto the 0.25 degree working grid."""
    meta = json.loads((GRIDS / "earth-elev-meta.js").read_text(encoding="utf-8")
                      .split("window.RADIUM_GRID_EARTH_ELEV = ", 1)[1].rstrip().rstrip(";"))
    image = np.asarray(Image.open(ROOT / meta["file"]).convert("L"), dtype=np.float32)
    merc = np.full(image.shape, np.nan, dtype=np.float64)
    valid = image > 0
    merc[valid] = meta["min"] + ((image[valid] - 1) / 254.0) * (meta["max"] - meta["min"])

    # The shipped raster is mercator-rowed, so unproject before working in degrees.
    rows = (np.arange(H) + 0.5) * (image.shape[0] / H)
    cols = (np.arange(W) + 0.5) * (image.shape[1] / W)
    grid = merc[np.ix_(rows.astype(int), cols.astype(int))]
    return grid


def pressure_from_elevation(elev_merc: np.ndarray) -> np.ndarray:
    """Barometric pressure in kPa: the standard atmosphere, from elevation."""
    with np.errstate(invalid="ignore"):
        return 101.325 * np.power(1.0 - 2.25577e-5 * np.maximum(elev_merc, 0.0), 5.25588)


def solar_field() -> np.ndarray:
    """POWER-measured solar at the catalogued sites, blended with latitude."""
    metrics = json.loads((ROOT / "assets" / "earth-metrics.js").read_text(encoding="utf-8")
                         .split("=", 1)[1].strip().rstrip(";"))
    prospect = json.loads((DATA / "prospect-sites.js").read_text(encoding="utf-8")
                          .split("=", 1)[1].strip().rstrip(";"))
    anchors = [(v["lat"], v["lon"], v["solarKwhM2Day"]) for v in metrics.values()]
    anchors += [(p["lat"], p["lon"], p["solarKwhM2Day"]) for p in prospect
                if isinstance(p.get("solarKwhM2Day"), (int, float))]

    lat, lon = grid_lat_lon()
    clear_sky = 7.4 * np.maximum(np.cos(np.deg2rad(lat)), 0.30)
    weight_sum = np.full((H, W), 0.5)
    acc = clear_sky * 0.5
    for a_lat, a_lon, value in anchors:
        d_lon = np.abs(((lon - a_lon + 180.0) % 360.0) - 180.0)
        km = np.hypot(lat - a_lat, d_lon * np.cos(np.deg2rad(lat))) * 111.0
        w = 1.0 / (1.0 + (km / 1500.0) ** 2)
        acc += w * value
        weight_sum += w
    return acc / weight_sum


def to_mercator(values: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rows = np.arange(MERC_PX) + 0.5
    merc_y = (1.0 - 2.0 * rows / MERC_PX) * math.pi
    lat = np.degrees(np.arctan(np.sinh(merc_y)))
    src_row = np.clip(((90.0 - lat) / 180.0 * H).astype(int), 0, H - 1)
    src_col = np.clip((np.arange(MERC_PX) * W // MERC_PX), 0, W - 1)
    return values[np.ix_(src_row, src_col)], valid[np.ix_(src_row, src_col)]


def encode(values: np.ndarray, valid: np.ndarray, lo: float, hi: float, name: str,
           meta_extra: dict, already_mercator: bool = False) -> None:
    if not already_mercator:
        values, valid = to_mercator(values, valid)
    scaled = np.zeros(values.shape, dtype=np.uint8)
    good = valid & np.isfinite(values)
    scaled[good] = np.clip(np.round((values[good] - lo) / (hi - lo) * 254.0) + 1.0, 1, 255).astype(np.uint8)
    Image.fromarray(scaled, mode="L").save(GRIDS / f"{name}.png", optimize=True)
    meta = {
        "file": f"assets/grids/{name}.png",
        "width": MERC_PX,
        "height": MERC_PX,
        "bounds": [[-MERC_LAT, -180], [MERC_LAT, 180]],
        "projection": "Web Mercator, square",
        "min": lo,
        "max": hi,
        "cells": int(good.sum()),
    }
    meta.update(meta_extra)
    body = "window." + meta_extra["global"] + " = " + json.dumps(meta, indent=2) + ";\n"
    (GRIDS / f"{name}-meta.js").write_text(body, encoding="utf-8")
    print(f"wrote {name}.png ({int(good.sum())} cells)")


def main() -> int:
    GRIDS.mkdir(parents=True, exist_ok=True)

    # --- sunlight: modelled from measured anchors
    solar = solar_field()
    encode(solar, np.ones((H, W), dtype=bool), 0.5, 7.5, "earth-solar", {
        "global": "RADIUM_GRID_EARTH_SOLAR",
        "units": "kWh/m2/day",
        "source": "NASA POWER 2001-2020 means at the 79 catalogued sites, interpolated with a clear-sky latitude term",
        "url": "https://power.larc.nasa.gov/",
        "model": "inverse-distance blend (1500 km scale) of 79 POWER measurements with 7.4 cos(lat)",
    })

    # --- pressure: barometric from the shipped elevation raster, which is already
    # mercator-rowed, so it is written straight back out without a round trip.
    elev_meta = json.loads((GRIDS / "earth-elev-meta.js").read_text(encoding="utf-8")
                           .split("window.RADIUM_GRID_EARTH_ELEV = ", 1)[1].rstrip().rstrip(";"))
    elev_img = np.asarray(Image.open(ROOT / elev_meta["file"]).convert("L"), dtype=np.float32)
    elev_merc = np.full(elev_img.shape, np.nan, dtype=np.float64)
    land = elev_img > 0
    elev_merc[land] = elev_meta["min"] + ((elev_img[land] - 1) / 254.0) * (elev_meta["max"] - elev_meta["min"])
    pressure = pressure_from_elevation(elev_merc)
    encode(pressure, np.isfinite(pressure), 55.0, 105.0, "earth-pressure", {
        "global": "RADIUM_GRID_EARTH_PRESSURE",
        "units": "kPa",
        "source": "barometric conversion of the RADIUM elevation grid (AWS Terrain Tiles)",
        "url": "https://registry.opendata.aws/terrain-tiles/",
        "model": "101.325 x (1 - 2.25577e-5 h)^5.25588",
    }, already_mercator=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

