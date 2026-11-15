"""Grade how open - and how available - the land under an Earth pin really is.

Every other number in the Earth dossier answers "is this place a good analog".
None of them noticed that a click in Manhattan was being graded as a base site.
This tool adds the missing constraint from MODIS land cover:

  * source: NASA GIBS serves the MODIS Combined IGBP Land Cover Type product
    (500 m, annual, Aqua+Terra) as colourised WMTS tiles with a published
    colormap, so no Earthdata login is needed and the classes are exact;
  * each 0.25 degree cell records the area share of all 17 classes, the
    openness of those shares (area-weighted) and the dominant class;
  * water and no-data stay empty rather than being scored, because a lake is
    not a bad base site - it is not a site.

Outputs:
  assets/grids/earth-open.png        openness 0-100, mercator square (0 = no data)
  assets/grids/earth-landcover.png   dominant IGBP class index, 0 = water/no data
  assets/data/earth-landuse.js       per-site openness + dominant class

Run: python tools/build_land_use.py
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
CACHE = ROOT / "tools" / ".gridcache" / "landuse"

COLORMAP = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_IGBP_Land_Cover_Type.xml"
TILE = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/"
    "MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual/default/500m/{z}/{row}/{col}.png"
)
TILE_Z = 4          # 20 x 10 tiles of 512 px: 0.035 deg per pixel
TILE_COLS, TILE_ROWS = 20, 10
TILE_PX = 512

W, H = 1440, 720    # 0.25 degree screening grid
MERC_PX = 1440
MERC_LAT = 85.0511287798

# How usable each IGBP class is as base ground. Barren and ice are wide open;
# forest costs clearing and blocks vehicle movement; cropland costs a land-use
# argument; a city is not a candidate at all. Water is not scored.
OPENNESS = {
    16: 100,  # barren
    15: 96,   # permanent snow and ice
    10: 92,   # grasslands
    7: 88,    # open shrublands
    9: 82,    # savannas
    8: 72,    # woody savannas
    6: 66,    # closed shrublands
    5: 58,    # mixed forest
    3: 56,    # deciduous needleleaf forest
    4: 52,    # deciduous broadleaf forest
    14: 50,   # cropland / natural vegetation mosaics
    1: 48,    # evergreen needleleaf forest
    11: 45,   # permanent wetlands
    2: 44,    # evergreen broadleaf forest
    12: 32,   # croplands
    13: 0,    # urban and built-up
}
NOT_LAND = {0, 17}     # water bodies


def fetch(url: str, name: str, tries: int = 4) -> bytes:
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
        except Exception as err:  # network hiccup: retry, then fail loudly
            last = err
    raise RuntimeError(f"could not fetch {url}: {last}")


def colormap() -> tuple[dict[tuple[int, int, int], int], dict[int, str]]:
    """RGB -> class index and class index -> label, straight from GIBS."""
    text = fetch(COLORMAP, "igbp-colormap.xml").decode("utf-8", "replace")
    by_ref = {
        int(m.group(2)): m.group(1)
        for m in re.finditer(r'<LegendEntry rgb="[^"]+" tooltip="([^"]*)" id="(\d+)"', text)
    }
    colours: dict[tuple[int, int, int], int] = {}
    labels: dict[int, str] = {}
    for match in re.finditer(
        r'<ColorMapEntry rgb="(\d+),(\d+),(\d+)"[^>]*?sourceValue="([\d,]+)"[^>]*?ref="(\d+)"', text
    ):
        r, g, b, values, ref = match.groups()
        rgb = (int(r), int(g), int(b))
        first = int(values.split(",")[0])
        colours[rgb] = first
        labels[first] = by_ref.get(int(ref), f"class {first}")
    labels[0] = labels.get(0, "Water bodies")
    labels[17] = labels.get(17, "Water bodies")
    return colours, labels


def palette_lut(colours: dict[tuple[int, int, int], int]) -> np.ndarray:
    """Map a 256-entry PNG palette onto class indices (-1 = no data)."""
    lut = np.full(256, -1, dtype=np.int16)
    # Palette indices are resolved per tile from the file's own palette, so this
    # helper only knows the RGB table; see class_map().
    del lut
    return np.full(256, -1, dtype=np.int16)


def class_map(path: Path, colours: dict[tuple[int, int, int], int]) -> np.ndarray:
    """Decode one palette PNG tile into IGBP class indices (-1 = no data)."""
    image = Image.open(path)
    indices = np.asarray(image, dtype=np.uint8)
    palette = np.array(image.getpalette(), dtype=np.uint8).reshape(-1, 3)
    lut = np.full(len(palette), -1, dtype=np.int16)
    for i, rgb in enumerate(palette):
        lut[i] = colours.get((int(rgb[0]), int(rgb[1]), int(rgb[2])), -1)
    cls = lut[indices]
    transparent = image.info.get("transparency")
    if isinstance(transparent, int) and transparent < len(lut):
        cls[indices == transparent] = -1
    return cls


def g(grid: np.ndarray, lat: float, lon: float) -> tuple[int, int]:
    row = min(H - 1, max(0, int((90.0 - lat) / 180.0 * H)))
    col = min(W - 1, max(0, int(((lon + 180.0) % 360.0) / 360.0 * W)))
    return row, col


def to_mercator(values: np.ndarray, valid: np.ndarray):
    rows = np.arange(MERC_PX) + 0.5
    merc_y = (1.0 - 2.0 * rows / MERC_PX) * math.pi
    lat = np.degrees(np.arctan(np.sinh(merc_y)))
    src_row = np.clip(((90.0 - lat) / 180.0 * H).astype(int), 0, H - 1)
    src_col = np.clip((np.arange(MERC_PX) * W // MERC_PX), 0, W - 1)
    return values[np.ix_(src_row, src_col)], valid[np.ix_(src_row, src_col)]


def encode(values: np.ndarray, valid: np.ndarray, lo: float, hi: float, name: str,
           meta_extra: dict) -> None:
    values, valid = to_mercator(values, valid)
    scaled = np.zeros(values.shape, dtype=np.uint8)
    scaled[valid] = np.clip(np.round((values[valid] - lo) / (hi - lo) * 254.0) + 1.0, 1, 255).astype(np.uint8)
    Image.fromarray(scaled, mode="L").save(GRIDS / f"{name}.png", optimize=True)
    meta = {
        "file": f"assets/grids/{name}.png",
        "width": MERC_PX,
        "height": MERC_PX,
        "bounds": [[-MERC_LAT, -180], [MERC_LAT, 180]],
        "projection": "Web Mercator, square",
        "min": lo,
        "max": hi,
        "cells": int(valid.sum()),
    }
    meta.update(meta_extra)
    body = "window." + meta_extra["global"] + " = " + json.dumps(meta, indent=2) + ";\n"
    (GRIDS / f"{name}-meta.js").write_text(body, encoding="utf-8")
    print(f"wrote {name}.png ({int(valid.sum())} cells)")


def build_grids(colours: dict[tuple[int, int, int], int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Area-share binning of the 500 m classes into 0.25 degree cells."""
    open_sum = np.zeros((H, W), dtype=np.float64)
    open_cnt = np.zeros((H, W), dtype=np.float64)
    class_area = np.zeros((len(OPENNESS) + 2, H, W), dtype=np.float32)
    class_ids = sorted(set(OPENNESS) | NOT_LAND)
    index_of = {cls: i for i, cls in enumerate(class_ids)}

    rows_per_strip = 72  # 18 degrees of tile row = 72 cells of 0.25 degrees
    for tile_row in range(TILE_ROWS):
        strip = np.full((TILE_PX, TILE_PX * TILE_COLS), -1, dtype=np.int16)
        for tile_col in range(TILE_COLS):
            path = CACHE / f"t{TILE_Z}_{tile_row}_{tile_col}.png"
            fetch(TILE.format(z=TILE_Z, row=tile_row, col=tile_col), path.name)
            strip[:, tile_col * TILE_PX:(tile_col + 1) * TILE_PX] = class_map(path, colours)

        # Openness: average of the per-pixel scores, water and no-data excluded.
        score = np.full(strip.shape, np.nan, dtype=np.float32)
        for cls, value in OPENNESS.items():
            score[strip == cls] = value
        land = ~np.isnan(score)
        strip_open = np.where(land, score, 0.0).astype(np.float32)
        strip_land = land.astype(np.float32)

        def shrink(arr):
            return np.asarray(
                Image.fromarray(arr, mode="F").resize((W, rows_per_strip), Image.BOX),
                dtype=np.float64,
            )

        band = slice(tile_row * rows_per_strip, (tile_row + 1) * rows_per_strip)
        open_sum[band] = shrink(strip_open)
        open_cnt[band] = shrink(strip_land)
        for cls in class_ids:
            class_area[index_of[cls], band] = shrink((strip == cls).astype(np.float32))
        print(f"  land-cover row {tile_row + 1}/{TILE_ROWS}", flush=True)

    land_frac = open_cnt
    openness = np.divide(open_sum, open_cnt, out=np.zeros_like(open_sum), where=open_cnt > 0)
    # The dominant class is picked among land classes only, so a coastal cell
    # reads "Barren" rather than "Water Bodies" while its openness comes from
    # the land pixels in it.
    land_rows = [index_of[cls] for cls in class_ids if cls not in NOT_LAND]
    dominant = np.asarray(land_rows, dtype=np.int16)[np.argmax(class_area[land_rows], axis=0)]
    shares = class_area.sum(axis=0)
    valid = (land_frac > 0.4) & (shares > 0)
    dominant = np.where(valid, dominant, -1)

    # Class shares the map layers need: permanent snow and ice, barren ground,
    # and everything green (the four forest classes plus shrub, savanna, grass,
    # cropland and mosaic).
    def share_of(classes: list[int]) -> np.ndarray:
        rows = [index_of[cls] for cls in classes if cls in index_of]
        return np.clip(class_area[rows].sum(axis=0) * 100.0, 0, 100)

    extras = {
        "snow": share_of([15]),
        "barren": share_of([16]),
        "veg": share_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14]),
    }
    return openness, dominant, valid, extras


def site_values(openness: np.ndarray, dominant: np.ndarray, valid: np.ndarray,
                lat: float, lon: float) -> dict | None:
    """Nearest graded cell within ~1 degree of a site centre."""
    row, col = g(np.zeros((1, 1)), lat, lon)
    if valid[row, col]:
        return {"open": int(round(openness[row, col])), "class": int(dominant[row, col])}
    best = None
    radius = int(1.0 / (180.0 / H))
    for d_row in range(-radius, radius + 1):
        for d_col in range(-radius, radius + 1):
            r = min(H - 1, max(0, row + d_row))
            c = (col + d_col) % W
            if not valid[r, c]:
                continue
            distance = d_row * d_row + d_col * d_col
            if best is None or distance < best[0]:
                best = (distance, r, c)
    if best is None:
        return None
    return {"open": int(round(openness[best[1], best[2]])), "class": int(dominant[best[1], best[2]])}


def main() -> int:
    GRIDS.mkdir(parents=True, exist_ok=True)
    colours, labels = colormap()
    print(f"colormap: {len(colours)} colours -> {len(labels)} classes")
    openness, dominant, valid, extras = build_grids(colours)

    encode(openness, valid, 0.0, 100.0, "earth-open", {
        "global": "RADIUM_GRID_EARTH_OPEN",
        "units": "open-land score 0-100",
        "source": "MODIS Combined IGBP Land Cover Type (annual, 500 m) via NASA GIBS, area-share binned to 0.25 degrees",
        "url": "https://earthdata.nasa.gov/gibs",
    })
    encode(extras["snow"], valid, 0.0, 100.0, "earth-snow", {
        "global": "RADIUM_GRID_EARTH_SNOW",
        "units": "percent of cell",
        "source": "MODIS IGBP class 15 (permanent snow and ice) area share via NASA GIBS",
        "url": "https://earthdata.nasa.gov/gibs",
    })
    encode(extras["barren"], valid, 0.0, 100.0, "earth-barren", {
        "global": "RADIUM_GRID_EARTH_BARREN",
        "units": "percent of cell",
        "source": "MODIS IGBP class 16 (barren) area share via NASA GIBS",
        "url": "https://earthdata.nasa.gov/gibs",
    })
    encode(extras["veg"], valid, 0.0, 100.0, "earth-green", {
        "global": "RADIUM_GRID_EARTH_GREEN",
        "units": "percent of cell",
        "source": "MODIS IGBP forest, shrub, savanna, grass and cropland classes summed via NASA GIBS",
        "url": "https://earthdata.nasa.gov/gibs",
    })
    encode(dominant.astype(np.float64), valid, 0.0, 17.0, "earth-landcover", {
        "global": "RADIUM_GRID_EARTH_LANDCOVER",
        "units": "dominant IGBP class index",
        "classes": {str(k): labels.get(k, f"class {k}") for k in sorted(labels)},
        "openness": {str(k): v for k, v in sorted(OPENNESS.items())},
        "source": "MODIS Combined IGBP Land Cover Type (annual, 500 m) via NASA GIBS",
        "url": "https://earthdata.nasa.gov/gibs",
    })

    # Per-site values: the dossiers are static, so they are baked here.
    metrics = json.loads(
        (ROOT / "assets" / "earth-metrics.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";")
    )
    prospect = json.loads(
        (DATA / "prospect-sites.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";")
    )
    entries: dict[str, dict] = {}
    for key, value in metrics.items():
        found = site_values(openness, dominant, valid, value["lat"], value["lon"])
        if found:
            entries[key] = found
    for value in prospect:
        found = site_values(openness, dominant, valid, value["lat"], value["lon"])
        if found:
            entries[value["id"]] = found

    body = (
        "/* RADIUM - land cover at every Earth site.\n"
        " * Generated by tools/build_land_use.py from MODIS IGBP land cover (NASA GIBS).\n"
        " * open  = 0-100 usability of the ground (barren 100, urban 0), area-weighted.\n"
        " * class = dominant IGBP class index for the 0.25 degree cell.\n"
        " */\n"
        "window.RADIUM_EARTH_LANDUSE = " + json.dumps(entries, indent=1, sort_keys=True) + ";\n"
    )
    (DATA / "earth-landuse.js").write_text(body, encoding="utf-8")
    missing = [k for k in metrics if k not in entries]
    print(f"wrote earth-landuse.js ({len(entries)} sites, {len(missing)} without land data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
