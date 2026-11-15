"""Global analog prospector.

Screens every 0.25 degree land cell on Earth against the measured envelope of the
40 catalogued analog sites, then refines the best new candidates with the same
NASA POWER / NOAA ETOPO1 pipeline used for the curated sites.

Global datasets (all keyless and public):

  * AWS Terrain Tiles (Mapzen terrarium, a SRTM / NED / GMTED / ETOPO blend)
    -> elevation, slope and roughness at 0.25 degrees
  * WorldClim 2.1 bio, 10 arc-minute -> mean / max / min temperature and rain
  * Natural Earth 50m land + countries + 10m populated places
    -> land mask, country label, nearest settlement for naming the candidate

Outputs:

  assets/grids/earth-prospect.png        global suitability raster (1440x720)
  assets/grids/earth-prospect-meta.js    bounds + method + dataset list
  assets/data/prospect-sites.js          ranked new candidate sites with metrics

Run: python tools/build_prospect_scan.py
"""

from __future__ import annotations

import io
import json
import math
import sys
import re
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "tools" / ".gridcache" / "prospect"
GRIDS = ROOT / "assets" / "grids"
DATA = ROOT / "assets" / "data"

W, H = 1440, 720          # 0.25 degree screening grid
MERC_LAT = 85.0511287798   # Leaflet draws image overlays linearly in Web Mercator
MERC_PX = 1440             # shipped rasters are square: one pixel per mercator step
DEM_Z = 5                 # 32x32 terrarium tiles -> 4.9 km pixels at the equator
TILE = 256

TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
WORLDCLIM = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_bio.zip"
NE_LAND = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson"
NE_COUNTRIES = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
NE_PLACES = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places_simple.geojson"
NE_GLACIATED = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_glaciated_areas.geojson"
NE_LAKES = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_lakes.geojson"

POWER = "https://power.larc.nasa.gov/api/temporal/climatology/point"
POWER_PARAMS = "T2M,T2M_MAX,T2M_MIN,PS,WS2M,RH2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN"
ETOPO = "https://api.opentopodata.org/v1/etopo1"

CANDIDATES = 40           # new sites to surface
MIN_FROM_KNOWN_KM = 200   # do not rediscover a catalogued analog
MIN_SPACING_KM = 700      # candidate to candidate separation
MAX_PER_COUNTRY = 3       # keep one country from dominating the shortlist
MIN_SCREEN_SCORE = 65     # below this a cell is not worth proposing


def fetch(url: str, name: str, tries: int = 4) -> bytes:
    """Download once into the ignored cache directory."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RADIUM-hackathon/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            path.write_bytes(data)
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"download failed: {url} ({last})")


# --------------------------------------------------------------------- DEM
def mercator_y(lat: float, size: int) -> float:
    lat = max(-85.05112878, min(85.05112878, lat))
    rad = math.radians(lat)
    return (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * size


def y_to_lat(y: float, size: int) -> float:
    n = math.pi - 2.0 * math.pi * y / size
    return math.degrees(math.atan(math.sinh(n)))


def load_dem() -> np.ndarray:
    """Mosaic of terrarium tiles at DEM_Z, decoded to metres."""
    size = TILE * (2 ** DEM_Z)
    cache_file = CACHE / f"dem_z{DEM_Z}.npy"
    if cache_file.exists():
        return np.load(cache_file)

    CACHE.mkdir(parents=True, exist_ok=True)
    n = 2 ** DEM_Z
    mosaic = np.zeros((size, size), dtype=np.int16)
    jobs = [(x, y) for y in range(n) for x in range(n)]

    def grab(job):
        x, y = job
        data = fetch(TERRARIUM.format(z=DEM_Z, x=x, y=y), f"t_{DEM_Z}_{x}_{y}.png")
        rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float32)
        height = rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0
        return x, y, height

    done = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        for x, y, height in pool.map(grab, jobs):
            mosaic[y * TILE:(y + 1) * TILE, x * TILE:(x + 1) * TILE] = height.astype(np.int16)
            done += 1
            if done % 256 == 0:
                print(f"  dem tiles {done}/{len(jobs)}", flush=True)

    np.save(cache_file, mosaic)
    return mosaic


def bin_add(values: np.ndarray, target: np.ndarray, size: int, axis: int = 0):
    """Sum slices of `values` into `size` contiguous bins given by `target`.

    `target` holds one bin index per slice along `axis` and must be
    non-decreasing. Bins that receive nothing come back as zero with a zero
    count so callers can divide safely.
    """
    target = np.asarray(target, dtype=np.int64)
    counts = np.bincount(target, minlength=size).astype(np.float64)
    present = np.flatnonzero(counts > 0)
    if axis == 0:
        sums = np.zeros((size, values.shape[1]), dtype=np.float64)
        if present.size:
            sums[present] = np.add.reduceat(values, np.searchsorted(target, present, side="left"), axis=0)
    else:
        sums = np.zeros((values.shape[0], size), dtype=np.float64)
        if present.size:
            sums[:, present] = np.add.reduceat(values, np.searchsorted(target, present, side="left"), axis=1)
    return sums, counts


def safe_mean(sums: np.ndarray, counts: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)


def terrain_grids(dem: np.ndarray) -> dict[str, np.ndarray]:
    """Elevation mean, slope mean and within-cell relief standard deviation."""
    size = dem.shape[0]

    # Column bins are uniform in longitude; row bins follow Mercator, which is
    # why the row mapping has to be computed from latitude rather than assumed.
    col_target = np.minimum(W - 1, (np.arange(size) * W) // size)
    rows_lat_all = np.array([y_to_lat(y + 0.5, size) for y in range(size)], dtype=np.float64)
    row_target_all = np.clip(((90.0 - rows_lat_all) / (180.0 / H)).astype(int), 0, H - 1)

    acc_e = np.zeros((H, W), dtype=np.float64)
    acc_sq = np.zeros((H, W), dtype=np.float64)
    acc_slope = np.zeros((H, W), dtype=np.float64)
    acc_n = np.zeros((H, W), dtype=np.float64)

    band_rows = 512
    for y0 in range(0, size, band_rows):
        y1 = min(size, y0 + band_rows)
        pad0 = max(0, y0 - 1)
        pad1 = min(size, y1 + 1)
        band = dem[pad0:pad1].astype(np.float32)

        # Ground sampling distance per row (metres per pixel); Mercator pixels
        # shrink with the cosine of latitude.
        rows_lat = rows_lat_all[pad0:pad1]
        res = np.maximum(1.0, 156543.03392 * np.cos(np.radians(rows_lat)) / (2 ** DEM_Z))

        gy, gx = np.gradient(band)
        slope = np.degrees(np.arctan(np.hypot(gx / res[:, None], gy / res[:, None])))
        slope = np.nan_to_num(slope, nan=0.0, posinf=90.0, neginf=90.0)

        core = slice(y0 - pad0, y0 - pad0 + (y1 - y0))
        elev_core = band[core].astype(np.float64)
        slope_core = slope[core].astype(np.float64)

        col_e, col_counts = bin_add(elev_core, col_target, W, axis=1)
        col_sq, _ = bin_add(elev_core ** 2, col_target, W, axis=1)
        col_sl, _ = bin_add(slope_core, col_target, W, axis=1)

        row_target = row_target_all[y0:y1]
        e_sums, row_counts = bin_add(col_e, row_target, H)
        sq_sums, _ = bin_add(col_sq, row_target, H)
        sl_sums, _ = bin_add(col_sl, row_target, H)

        acc_e += e_sums
        acc_sq += sq_sums
        acc_slope += sl_sums
        # Every cell of col_e already sums several source pixels, so the weight
        # is rows x columns, not just rows.
        acc_n += row_counts[:, None] * col_counts[None, :]
        print(f"  terrain band {y1}/{size}", flush=True)

    elev = safe_mean(acc_e, acc_n)
    elev_sq = safe_mean(acc_sq, acc_n)
    slope = safe_mean(acc_slope, acc_n)
    relief = np.sqrt(np.maximum(0.0, elev_sq - elev ** 2))
    return {"elev": elev, "slope": slope, "relief": relief}


# ----------------------------------------------------------------- climate
BIO_FILES = {
    "tempMeanC": "wc2.1_10m_bio_1.tif",   # annual mean temperature, degrees C x10
    "tempMaxC": "wc2.1_10m_bio_5.tif",    # max temperature of the warmest month x10
    "tempMinC": "wc2.1_10m_bio_6.tif",    # min temperature of the coldest month x10
    "precipMmYear": "wc2.1_10m_bio_12.tif",
    "precipSeasonality": "wc2.1_10m_bio_15.tif",
}


def load_worldclim() -> dict[str, np.ndarray]:
    """WorldClim 2.1 bio at 10 arc-min, resampled to the screening grid.

    The GeoTIFFs are float32 in real units (degrees C, mm/year, percent) with a
    -3.4e38 nodata sentinel over ocean, so the resample is a validity-weighted
    mean rather than a plain interpolation.
    """
    cache_file = CACHE / "worldclim.npz"
    if cache_file.exists():
        stored = np.load(cache_file)
        return {k: stored[k] for k in stored.files}

    CACHE.mkdir(parents=True, exist_ok=True)
    blob = fetch(WORLDCLIM, "wc2.1_10m_bio.zip")
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = {Path(n).name: n for n in zf.namelist()}
    out: dict[str, np.ndarray] = {}
    for key, filename in BIO_FILES.items():
        with zf.open(names[filename]) as handle:
            arr = np.asarray(Image.open(io.BytesIO(handle.read())), dtype=np.float64)
        valid = np.isfinite(arr) & (arr > -1000.0)
        data = np.where(valid, arr, 0.0).astype(np.float32)
        weight = valid.astype(np.float32)
        sum_img = np.asarray(Image.fromarray(data, mode="F").resize((W, H), Image.BILINEAR))
        wgt_img = np.asarray(Image.fromarray(weight, mode="F").resize((W, H), Image.BILINEAR))
        with np.errstate(invalid="ignore", divide="ignore"):
            out[key] = np.where(wgt_img > 1e-3, sum_img / np.maximum(wgt_img, 1e-6), np.nan)
    out["precipMmDay"] = out["precipMmYear"] / 365.0
    np.savez_compressed(cache_file, **out)
    return out


# --------------------------------------------------------------- geography
def geojson(url: str, name: str):
    return json.loads(fetch(url, name).decode("utf-8"))


def rasterize(url: str, name: str) -> np.ndarray:
    """Paint a Natural Earth polygon layer onto the screening grid."""
    data = geojson(url, name)
    canvas = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(canvas)
    for feature in data["features"]:
        geom = feature["geometry"]
        polygons = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for polygon in polygons:
            ring = polygon[0]
            pts = [((lon + 180.0) * W / 360.0, (90.0 - lat) * H / 180.0) for lon, lat in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=255)
    return np.asarray(canvas, dtype=np.uint8) > 0


def land_mask() -> np.ndarray:
    return rasterize(NE_LAND, "ne_50m_land.geojson")


def rings_of(geometry):
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def in_ring(ring, lon: float, lat: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            if lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi:
                inside = not inside
        j = i
    return inside


def country_of(countries, lon: float, lat: float) -> str:
    for feature in countries["features"]:
        for ring in rings_of(feature["geometry"]):
            if in_ring(ring, lon, lat):
                props = feature["properties"]
                return props.get("NAME") or props.get("ADMIN") or ""
    return ""


def haversine(lat1, lon1, lat2, lon2):
    rad = np.radians
    dlat = rad(lat2 - lat1)
    dlon = rad(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(rad(lat1)) * np.cos(rad(lat2)) * np.sin(dlon / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def compass(bearing: float) -> str:
    points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return points[int((bearing % 360) / 22.5 + 0.5) % 16]


def bearing(lat1, lon1, lat2, lon2) -> float:
    rad = math.radians
    dlon = rad(lon2 - lon1)
    y = math.sin(dlon) * math.cos(rad(lat2))
    x = math.cos(rad(lat1)) * math.sin(rad(lat2)) - math.sin(rad(lat1)) * math.cos(rad(lat2)) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

# ---------------------------------------------------------------- envelope
def curated_metrics() -> dict[str, dict]:
    text = (ROOT / "assets" / "earth-metrics.js").read_text(encoding="utf-8")
    body = text.split("=", 1)[1].strip().rstrip(";")
    return json.loads(body)


def curated_sites() -> list[dict]:
    text = (ROOT / "assets" / "data" / "earth-sites.js").read_text(encoding="utf-8")
    body = text.split("=", 1)[1].strip().rstrip(";")
    return json.loads(body)


def robust_scale(values: np.ndarray) -> tuple[float, float]:
    """Median and a robust spread (IQR / 1.349, i.e. sigma of a normal)."""
    values = values[np.isfinite(values)]
    med = float(np.median(values))
    q1, q3 = np.percentile(values, [25, 75])
    spread = float((q3 - q1) / 1.349)
    if not np.isfinite(spread) or spread <= 0:
        spread = max(1e-3, float(np.std(values)) or 1.0)
    return med, spread


# Envelope dimensions: climate carries most of the weight because the terrain
# terms are only resolved at ~5 km in the global screen.
ENVELOPE = [
    ("tempMeanC", 2.2),
    ("tempMaxC", 1.1),
    ("tempMinC", 1.1),
    ("precipMmDay", 1.8),
    ("precipSeasonality", 0.7),
    ("elev", 0.5),
    ("slope", 0.7),
    ("relief", 0.5),
]


def sample_grid(grid: np.ndarray, lat: float, lon: float) -> float:
    col = int((lon + 180.0) * W / 360.0) % W
    row = int((90.0 - lat) * H / 180.0)
    row = max(0, min(H - 1, row))
    return float(grid[row, col])


def build_envelope(layers: dict[str, np.ndarray], curated: list[dict]) -> dict[str, dict]:
    """Learn the analog envelope from the measured values at the curated sites."""
    stats: dict[str, dict] = {}
    for key, weight in ENVELOPE:
        grid = layers.get(key)
        if grid is None:
            continue
        values = np.array([sample_grid(grid, site["lat"], site["lon"]) for site in curated])
        med, spread = robust_scale(values)
        stats[key] = {"weight": weight, "median": med, "spread": spread,
                      "min": float(np.nanmin(values)), "max": float(np.nanmax(values))}
    return stats


def membership(value, median: float, spread: float) -> np.ndarray:
    """Gaussian membership: 1 at the analog median, e^-2 at two spreads out."""
    return np.exp(-0.5 * ((value - median) / spread) ** 2)


def score_field(layers: dict[str, np.ndarray], envelope: dict[str, dict]) -> np.ndarray:
    """Weighted geometric mean of the per-dimension memberships.

    A geometric mean is used instead of an average so that a cell cannot buy a
    high score by matching most dimensions while failing one badly: an analog
    that is far too wet is not an analog regardless of its terrain.
    """
    log_sum = np.zeros((H, W), dtype=np.float64)
    total = 0.0
    for key, stat in envelope.items():
        grid = layers.get(key)
        if grid is None:
            continue
        m = np.clip(membership(grid, stat["median"], stat["spread"]), 1e-6, 1.0)
        log_sum += stat["weight"] * np.log(m)
        total += stat["weight"]
    return 100.0 * np.exp(log_sum / max(total, 1e-6))


# ------------------------------------------------------------- refinement
def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def rough_index(metres: float) -> float:
    return clamp((math.log10(1.0 + max(0.0, metres)) / math.log10(201.0)) * 10.0, 0.0, 10.0)


def estimators(metrics: dict) -> dict:
    """Derive the qualitative rubric fields from measured climate and terrain.

    These are transparent proxies, not field observations: the dossier labels
    every one of them as estimated.
    """
    temp = metrics["tempMeanC"] or 0.0
    tmax = metrics["tempMaxC"] or temp
    tmin = metrics["tempMinC"] or temp
    precip = metrics["precipMmDay"] or 0.0
    wind = metrics["windMs"] or 0.0
    slope = metrics["slopeDeg"] or 0.0
    rough = rough_index(metrics["roughnessM"] or 0.0)

    dryness = clamp(1.0 - precip / 2.0, 0.0, 1.0)
    cold = clamp((2.0 - temp) / 20.0, 0.0, 1.0)
    wetness = clamp(precip / 3.0, 0.0, 1.0)

    return {
        "iceIndex": round(100.0 * min(1.0, cold * 1.25) * min(1.0, precip / 1.2)),
        "dustIndex": round(100.0 * dryness * (0.45 + 0.55 * min(1.0, wind / 8.0))),
        "subsurfaceScore": round(clamp(rough * 7.0 + slope * 1.2)),
        "biosignatureScore": round(
            100.0 * wetness * (0.3 + 0.7 * clamp((temp + 15.0) / 30.0, 0.0, 1.0))
        ),
        "scienceScore": round(
            clamp(46.0 + rough * 4.0 + dryness * 24.0 + min(20.0, abs(tmax - tmin) * 0.45))
        ),
    }


def describe(metrics: dict, nearest_known: dict, rank: int, known_count: int,
             screen_score: float, screened_cells: int) -> tuple[str, str]:
    temp = metrics["tempMeanC"]
    precip = metrics["precipMmDay"]
    wind = metrics["windMs"] or 0.0
    relief = metrics["roughnessM"] or 0.0
    analog = (
        f"Screened candidate #{rank} of {screened_cells:,} land cells. The scan scores every cell "
        f"against the measured envelope of the {known_count} catalogued analogs; this one scored "
        f"{screen_score:.1f}/100 because its climate and terrain sit inside that envelope "
        f"({temp:.1f} C mean, {precip:.2f} mm/day rain, {wind:.1f} m/s wind, {relief:.0f} m local relief). "
        f"The nearest catalogued analog is {nearest_known['name']}, {nearest_known['km']:.0f} km away, "
        "so no published study describes this exact place as a Moon or Mars analog."
    )
    limits = (
        "Screening output, not a survey: climate and terrain are measured, but there is no field "
        "campaign, no published stratigraphy and no trafficability or land-status assessment here. "
        "Treat the ice, dust, subsurface and biosignature rows as proxies derived from those "
        "measurements, and ground-truth them before proposing a base."
    )
    return analog, limits


# -------------------------------------------------------------- candidate
def masks(layers: dict[str, np.ndarray]) -> np.ndarray:
    """Land, data-covered, not an ice sheet."""
    lat = 90.0 - (np.arange(H) + 0.5) * (180.0 / H)
    lon = -180.0 + (np.arange(W) + 0.5) * (360.0 / W)
    lat2 = lat[:, None]
    lon2 = lon[None, :]

    ok = np.ones((H, W), dtype=bool)
    ok &= layers["land"]
    ok &= np.isfinite(layers["elev"])
    ok &= np.isfinite(layers["tempMeanC"])
    ok &= layers["elev"] >= 0.0                      # open sea is not a base site
    ok &= ~((lat2 < -60.0))                          # Antarctic ice sheet
    ok &= ~((lat2 > 59.0) & (lon2 > -75.0) & (lon2 < -10.0))   # Greenland ice sheet
    ok &= ~layers["glacier"]                         # ice caps and valley glaciers
    ok &= ~layers["lake"]                            # standing water
    # Polar cells at sea level are ice shelves, sea ice or lagoon flats, none of
    # which are buildable; the terrarium DEM reports them as 0 m.
    ok &= ~((np.abs(lat2) > 66.0) & (layers["elev"] < 20.0))
    return ok


def climate_bucket(layers: dict[str, np.ndarray]) -> np.ndarray:
    """Coarse climate zone used to keep the shortlist diverse.

    Without this the top of the ranking is a single desert, so candidates are
    taken round-robin across 4 temperature x 3 precipitation zones.
    """
    tband = np.digitize(layers["tempMeanC"], [-5.0, 5.0, 15.0])
    pband = np.digitize(layers["precipMmDay"], [0.5, 2.0])
    return (tband * 3 + pband).astype(np.int16)


def pick_candidates(score, ok, layers, known, countries) -> list[tuple[int, int, float, int]]:
    masked = np.where(ok, score, -1.0)
    flat = masked.ravel()
    pool_size = min(250000, flat.size)
    pool = np.argpartition(flat, -pool_size)[-pool_size:]
    pool = pool[np.argsort(-flat[pool])]

    lat = 90.0 - (np.arange(H) + 0.5) * (180.0 / H)
    lon = -180.0 + (np.arange(W) + 0.5) * (360.0 / W)
    known_lat = np.array([k["lat"] for k in known])
    known_lon = np.array([k["lon"] for k in known])
    buckets = climate_bucket(layers).ravel()

    queues: dict[int, list[tuple[int, int, float]]] = {}
    for index in pool:
        value = float(flat[index])
        if value < MIN_SCREEN_SCORE:
            break
        row, col = divmod(int(index), W)
        clat, clon = float(lat[row]), float(lon[col])
        if haversine(clat, clon, known_lat, known_lon).min() < MIN_FROM_KNOWN_KM:
            continue
        queues.setdefault(int(buckets[index]), []).append((row, col, value))

    order = sorted(queues, key=lambda b: -queues[b][0][2])
    chosen: list[tuple[int, int, float, int]] = []
    country_count: dict[str, int] = {}
    cursor = {b: 0 for b in order}

    while len(chosen) < CANDIDATES and any(cursor[b] < len(queues[b]) for b in order):
        for bucket in order:
            if len(chosen) >= CANDIDATES:
                break
            queue = queues[bucket]
            while cursor[bucket] < len(queue):
                row, col, value = queue[cursor[bucket]]
                cursor[bucket] += 1
                clat, clon = float(lat[row]), float(lon[col])
                if chosen:
                    d = [haversine(clat, clon, lat[r], lon[c]) for r, c, _, _ in chosen]
                    if min(d) < MIN_SPACING_KM:
                        continue
                country = country_of(countries, clon, clat) or "unknown"
                if country_count.get(country, 0) >= MAX_PER_COUNTRY:
                    continue
                country_count[country] = country_count.get(country, 0) + 1
                chosen.append((row, col, value, bucket))
                break
    return chosen


def nearest_known(known: list[dict], lat: float, lon: float) -> dict:
    distances = haversine(lat, lon, np.array([k["lat"] for k in known]), np.array([k["lon"] for k in known]))
    index = int(np.argmin(distances))
    return {"id": known[index]["id"], "name": known[index]["name"], "km": round(float(distances[index]), 1)}


def nearest_settlement(places, lat: float, lon: float) -> dict:
    lats = places["lat"]
    lons = places["lon"]
    distances = haversine(lat, lon, lats, lons)
    order = np.argsort(distances)[:40]
    for index in order:
        if places["pop"][index] >= 5000:
            return {
                "name": places["name"][index],
                "country": places["adm0"][index],
                "km": round(float(distances[index]), 0),
                "bearing": compass(bearing(lat, lon, lats[index], lons[index])),
            }
    index = int(order[0])
    return {
        "name": places["name"][index],
        "country": places["adm0"][index],
        "km": round(float(distances[index]), 0),
        "bearing": compass(bearing(lat, lon, lats[index], lons[index])),
    }


def load_places():
    data = geojson(NE_PLACES, "ne_10m_populated_places_simple.geojson")
    names, adm0, lats, lons, pops = [], [], [], [], []
    for feature in data["features"]:
        props = feature["properties"]
        names.append(props.get("name") or props.get("NAME") or "")
        adm0.append(props.get("adm0name") or props.get("ADM0NAME") or "")
        lats.append(float(props.get("latitude") or props.get("LATITUDE")))
        lons.append(float(props.get("longitude") or props.get("LONGITUDE")))
        pops.append(float(props.get("pop_max") or props.get("POP_MAX") or 0))
    return {
        "name": names, "adm0": adm0,
        "lat": np.array(lats), "lon": np.array(lons), "pop": np.array(pops),
    }

# ------------------------------------------------------------------ output
def to_mercator(values: np.ndarray, valid: np.ndarray):
    """Resample the equirectangular grid onto square Web Mercator rows.

    Leaflet paints an image overlay as a single quad, so its rows are laid out
    linearly in projected space. Shipping equirectangular data would put the
    30 N row at 50 N on screen (a 20 degree shift) until it is reprojected here.
    """
    rows = np.arange(MERC_PX) + 0.5
    merc_y = (1.0 - 2.0 * rows / MERC_PX) * math.pi
    lat = np.degrees(np.arctan(np.sinh(merc_y)))
    src_row = np.clip(((90.0 - lat) / 180.0 * H).astype(int), 0, H - 1)
    src_col = np.clip((np.arange(MERC_PX) * W // MERC_PX), 0, W - 1)
    return values[np.ix_(src_row, src_col)], valid[np.ix_(src_row, src_col)]


def encode_raster(values: np.ndarray, valid: np.ndarray, lo: float, hi: float,
                  name: str, meta_extra: dict) -> None:
    """Write a masked 8-bit raster where 0 means 'no data' and 1..255 is the value."""
    cells = int(valid.sum())
    values, valid = to_mercator(values, valid)
    scaled = np.zeros(values.shape, dtype=np.uint8)
    normalised = np.clip((values[valid] - lo) / (hi - lo), 0.0, 1.0)
    scaled[valid] = np.clip(np.round(normalised * 254.0) + 1.0, 1, 255).astype(np.uint8)
    Image.fromarray(scaled, mode="L").save(GRIDS / f"{name}.png", optimize=True)
    meta = {
        "file": f"assets/grids/{name}.png",
        "width": MERC_PX,
        "height": MERC_PX,
        "bounds": [[-MERC_LAT, -180], [MERC_LAT, 180]],
        "projection": "Web Mercator, square",
        "min": lo,
        "max": hi,
        "cells": cells,
    }
    meta.update(meta_extra)
    body = "window." + meta_extra["global"] + " = " + json.dumps(meta, indent=2) + ";\n"
    (GRIDS / f"{name}-meta.js").write_text(body, encoding="utf-8")
    print(f"wrote {name}.png ({int(valid.sum())} cells)")


def write_elevation(layers: dict[str, np.ndarray], ok: np.ndarray) -> None:
    """Ship the DEM the screen uses as a colourisable elevation raster."""
    elev = layers["elev"]
    valid = ok & np.isfinite(elev)
    encode_raster(elev, valid, -400.0, 6000.0, "earth-elev", {
        "global": "RADIUM_GRID_EARTH_ELEV",
        "units": "metres",
        "source": "AWS Terrain Tiles (Mapzen terrarium, SRTM/NED/GMTED/ETOPO blend), 0.25 degree cell means",
        "url": "https://registry.opendata.aws/terrain-tiles/",
    })

    # WorldClim annual mean temperature is global and complete, so it makes a far
    # better heat map than interpolating blobs around 40 stations.
    heat = layers["tempMeanC"]
    heat_ok = ok & np.isfinite(heat)
    encode_raster(heat, heat_ok, -25.0, 32.0, "earth-heat", {
        "global": "RADIUM_GRID_EARTH_HEAT",
        "units": "degC",
        "source": "WorldClim 2.1 bio_1 (annual mean air temperature), 10 arc-minute, 1970-2000",
        "url": "https://www.worldclim.org/data/worldclim21.html",
    })


def write_site_analog(layers: dict[str, np.ndarray], envelope: dict[str, dict]) -> None:
    """Bake each site's analog fit so the browser can score sites synchronously.

    Same formula the screen uses (weighted geometric mean of Gaussian
    memberships), evaluated at the site's own cell, so a curated site, a
    discovered candidate and a clicked point are all on one scale.
    """
    metrics = curated_metrics()
    prospect = json.loads(
        (DATA / "prospect-sites.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";")
    )
    out: dict[str, float] = {}
    for site_id, value in metrics.items():
        out[site_id] = round(site_analog_fit(layers, envelope, value["lat"], value["lon"]), 1)
    for site in prospect:
        out[site["id"]] = round(site_analog_fit(layers, envelope, site["lat"], site["lon"]), 1)

    body = (
        "/* RADIUM - analog fit at each Earth site.\n"
        " * Generated by tools/build_prospect_scan.py --rasters-only.\n"
        " * 0-100: weighted geometric mean of the Gaussian memberships of the eight\n"
        " * measured envelope dimensions, i.e. the same score the global screen gives\n"
        " * a cell. The Discovered shortlist requires 65+.\n"
        " */\n"
        "window.RADIUM_EARTH_ANALOG = " + json.dumps(out, indent=1, sort_keys=True) + ";\n"
    )
    (DATA / "earth-analog.js").write_text(body, encoding="utf-8")
    print(f"wrote earth-analog.js ({len(out)} sites)")


def site_analog_fit(layers: dict[str, np.ndarray], envelope: dict[str, dict],
                    lat: float, lon: float) -> float:
    log_sum = 0.0
    total = 0.0
    for key, stat in envelope.items():
        grid = layers.get(key)
        if grid is None:
            continue
        value = sample_grid(grid, lat, lon)
        if not np.isfinite(value):
            continue
        m = float(np.clip(membership(np.array(value), stat["median"], stat["spread"]), 1e-6, 1.0))
        log_sum += stat["weight"] * math.log(m)
        total += stat["weight"]
    return 100.0 * math.exp(log_sum / max(total, 1e-6))


def write_field(score: np.ndarray, ok: np.ndarray, envelope: dict[str, dict]) -> None:
    """Encode the screening score as a grayscale raster: 0 means 'not screened'."""
    GRIDS.mkdir(parents=True, exist_ok=True)
    valid = ok & np.isfinite(score)
    cell_count = int(valid.sum())
    values, valid = to_mercator(score, valid)
    scaled = np.zeros(values.shape, dtype=np.uint8)
    scaled[valid] = np.clip(np.round(values[valid] / 100.0 * 254.0) + 1.0, 1, 255).astype(np.uint8)
    Image.fromarray(scaled, mode="L").save(GRIDS / "earth-prospect.png", optimize=True)

    meta = {
        "file": "assets/grids/earth-prospect.png",
        "width": MERC_PX,
        "height": MERC_PX,
        "bounds": [[-MERC_LAT, -180], [MERC_LAT, 180]],
        "projection": "Web Mercator, square",
        "screenedCells": cell_count,
        "threshold": MIN_SCREEN_SCORE,
        "envelope": {
            key: {
                "median": round(stat["median"], 3),
                "spread": round(stat["spread"], 3),
                "min": round(stat["min"], 3),
                "max": round(stat["max"], 3),
                "weight": stat["weight"],
            }
            for key, stat in envelope.items()
        },
        "datasets": [
            {"name": "AWS Terrain Tiles (Mapzen terrarium)", "detail": "SRTM / NED / GMTED / ETOPO blend, 0.25 degree means at zoom 5", "url": "https://registry.opendata.aws/terrain-tiles/"},
            {"name": "WorldClim 2.1 bio, 10 arc-minute", "detail": "mean/max/min temperature, precipitation and seasonality, 1970-2000", "url": "https://www.worldclim.org/data/worldclim21.html"},
            {"name": "Natural Earth 50m land, countries, 10m populated places", "detail": "land mask, country labels, nearest settlement", "url": "https://www.naturalearthdata.com/"},
            {"name": "NASA POWER climatology 2001-2020", "detail": "finalist refinement: temperature, pressure, wind, humidity, rain, solar", "url": "https://power.larc.nasa.gov/"},
            {"name": "NOAA ETOPO1", "detail": "finalist refinement: 1 arc-minute elevation and local slope", "url": "https://www.ngdc.noaa.gov/mgg/global/"}
        ]
    }
    body = "window.RADIUM_PROSPECT_META = " + json.dumps(meta, indent=2) + ";\n"
    (GRIDS / "earth-prospect-meta.js").write_text(body, encoding="utf-8")
    print(f"wrote earth-prospect.png ({int(valid.sum())} screened cells)")


def write_sites(sites: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    body = (
        "/* RADIUM - discovered candidates.\n"
        " * Generated by tools/build_prospect_scan.py. Climate and terrain are measured\n"
        " * (NASA POWER + NOAA ETOPO1); the qualitative rubric fields are documented\n"
        " * proxies, so every entry is labelled as a screening estimate, not a survey.\n"
        " */\n"
        "window.RADIUM_PROSPECT_SITES = " + json.dumps(sites, indent=1) + ";\n"
    )
    (DATA / "prospect-sites.js").write_text(body, encoding="utf-8")
    print(f"wrote {DATA / 'prospect-sites.js'} ({len(sites)} candidates)")

# ------------------------------------------------------------------- main
def load_refine_cache() -> dict[str, dict]:
    path = CACHE / "refined.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def refine(cells, places, countries, known, screened_cells) -> list[dict]:
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    import fetch_earth_data as fed  # reuse the curated-site measurement code

    cache = load_refine_cache()
    sites: list[dict] = []
    lat_axis = 90.0 - (np.arange(H) + 0.5) * (180.0 / H)
    lon_axis = -180.0 + (np.arange(W) + 0.5) * (360.0 / W)

    for rank, (row, col, screen_score, bucket) in enumerate(cells, start=1):
        lat = round(float(lat_axis[row]), 2)
        lon = round(float(lon_axis[col]), 2)
        print(f"[prospect {rank:02d}] {lat:.2f},{lon:.2f} screen={screen_score:.1f} zone={bucket}", flush=True)
        key = f"{lat:.2f},{lon:.2f}"
        cached = cache.get(key)
        if cached:
            metrics = cached
            climate = metrics
            elevs = metrics.get("elevSamplesM") or []
        else:
            try:
                climate = fed.power_climatology(lat, lon)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! POWER failed: {exc}")
                continue
            time.sleep(1.1)
            try:
                elevs = fed.elevation_grid(lat, lon)
                slope, roughness = fed.terrain_stats(elevs)
                elevation = round(elevs[0], 1)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! ETOPO failed: {exc}")
                elevs, slope, roughness, elevation = [], None, None, None
            time.sleep(1.1)

            metrics = {
            "lat": lat,
            "lon": lon,
            "elevationM": elevation,
            "slopeDeg": slope,
            "roughnessM": roughness,
            "tempMeanC": climate.get("T2M"),
            "tempMaxC": climate.get("T2M_MAX"),
            "tempMinC": climate.get("T2M_MIN"),
            "pressureKPa": climate.get("PS"),
            "windMs": climate.get("WS2M"),
            "humidityPct": climate.get("RH2M"),
            "precipMmDay": climate.get("PRECTOTCORR"),
            "solarKwhM2Day": climate.get("ALLSKY_SFC_SW_DWN"),
            "elevSamplesM": elevs,
            }
            cache[key] = metrics
            (CACHE / "refined.json").write_text(json.dumps(cache, indent=1), encoding="utf-8")

        if metrics["elevationM"] is not None and metrics["elevationM"] < 0.0:
            print("  ! below sea level, skipped")
            continue

        settlement = nearest_settlement(places, lat, lon)
        neighbour = nearest_known(known, lat, lon)
        country = country_of(countries, lon, lat) or settlement["country"] or "Unclaimed land"
        analog, limits = describe(metrics, neighbour, rank, len(known), screen_score, screened_cells)
        extra = estimators(metrics)

        label = (
            f"{settlement['km']:.0f} km {settlement['bearing']} of {settlement['name']}"
            if settlement["km"] < 1200
            else f"{lat:.1f}N {lon:.1f}E sector"
        )

        sites.append(
            {
                "id": f"prospect-{rank:02d}",
                "name": label,
                "region": country,
                "prospect": True,
                "prospectRank": rank,
                "screenScore": round(screen_score, 1),
                "confidence": "screening",
                "analog": analog,
                "limits": limits,
                "source": {
                    "label": f"Screen cell {round(screen_score,1)} / 100 - open map check",
                    "url": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
                },
                "settlement": settlement,
                "nearestAnalog": neighbour,
                "estimated": [
                    "iceIndex", "dustIndex", "subsurfaceScore",
                    "biosignatureScore", "scienceScore",
                ],
                **extra,
                **{k: metrics[k] for k in (
                    "lat", "lon", "elevationM", "slopeDeg", "roughnessM",
                    "tempMeanC", "tempMaxC", "tempMinC", "pressureKPa",
                    "windMs", "humidityPct", "precipMmDay", "solarKwhM2Day",
                )},
                "elevSamplesM": elevs,
                "provenance": {
                    "climate": "NASA POWER climatology 2001-2020 (MERRA-2 / CERES)",
                    "terrain": "NOAA ETOPO1 1 arc-minute via OpenTopoData (5-point sample)",
                    "screening": "0.25 deg global scan over AWS Terrain Tiles + WorldClim 2.1 bio",
                },
            }
        )
    return sites


def build_layers() -> dict[str, np.ndarray]:
    print("loading global datasets")
    dem = load_dem()
    terrain = terrain_grids(dem)
    climate = load_worldclim()
    return {
        "elev": terrain["elev"],
        "slope": terrain["slope"],
        "relief": terrain["relief"],
        "tempMeanC": climate["tempMeanC"],
        "tempMaxC": climate["tempMaxC"],
        "tempMinC": climate["tempMinC"],
        "precipMmDay": climate["precipMmDay"],
        "precipSeasonality": climate["precipSeasonality"],
        "land": land_mask(),
        "glacier": rasterize(NE_GLACIATED, "ne_50m_glaciated_areas.geojson"),
        "lake": rasterize(NE_LAKES, "ne_50m_lakes.geojson"),
    }


def write_point_fields(layers: dict[str, np.ndarray], ok: np.ndarray) -> None:
    """Rasters that let the browser grade any Earth point offline.

    The screening grid already computes these eight fields; shipping the five the
    point grader needs (plus elevation, written above) means a click anywhere is
    graded from measurements instead of interpolated blobs. Slope and relief in
    particular come from the native DEM, which a client cannot recover from the
    0.25 degree elevation raster.
    """
    fields = [
        ("earth-tmax", "RADIUM_GRID_EARTH_TMAX", layers["tempMaxC"], -40.0, 55.0, "degC",
         "WorldClim 2.1 bio_5 (max temperature of the warmest month), 10 arc-minute"),
        ("earth-tmin", "RADIUM_GRID_EARTH_TMIN", layers["tempMinC"], -60.0, 30.0, "degC",
         "WorldClim 2.1 bio_6 (min temperature of the coldest month), 10 arc-minute"),
        ("earth-precip", "RADIUM_GRID_EARTH_PRECIP", layers["precipMmDay"], 0.0, 12.0, "mm/day",
         "WorldClim 2.1 bio_12 (annual precipitation) / 365, 10 arc-minute"),
        ("earth-slope", "RADIUM_GRID_EARTH_SLOPE", layers["slope"], 0.0, 40.0, "deg",
         "computed from AWS Terrain Tiles at native resolution, mean per 0.25 degree cell"),
        ("earth-relief", "RADIUM_GRID_EARTH_RELIEF", layers["relief"], 0.0, 1200.0, "m",
         "within-cell elevation standard deviation from AWS Terrain Tiles"),
        ("earth-season", "RADIUM_GRID_EARTH_SEASON", layers["precipSeasonality"], 0.0, 200.0, "%",
         "WorldClim 2.1 bio_15 (precipitation seasonality, coefficient of variation)"),
    ]
    for name, global_name, values, lo, hi, units, source in fields:
        valid = ok & np.isfinite(values)
        encode_raster(values, valid, lo, hi, name, {
            "global": global_name,
            "units": units,
            "source": source,
            "url": "https://www.worldclim.org/data/worldclim21.html"
            if "WorldClim" in source
            else "https://registry.opendata.aws/terrain-tiles/",
        })


def main(argv: list[str]) -> int:
    layers = build_layers()
    ok = masks(layers)
    if "--rasters-only" in argv:
        write_elevation(layers, ok)
        write_point_fields(layers, ok)
        metrics = curated_metrics()
        known = [
            {"id": key, "lat": value["lat"], "lon": value["lon"], "name": key}
            for key, value in metrics.items()
        ]
        envelope = build_envelope(layers, known)
        write_field(score_field(layers, envelope), ok, envelope)
        write_site_analog(layers, envelope)
        return 0

    metrics = curated_metrics()
    # earth-sites.js is hand-written JavaScript, so read the display names with a
    # small regex instead of a JSON parser.
    text = (ROOT / "assets" / "data" / "earth-sites.js").read_text(encoding="utf-8")
    names = {m.group(1): m.group(2) for m in re.finditer(r'id:\s*"([^"]+)",\s*\n\s*name:\s*"([^"]+)"', text)}
    known = [
        {"id": key, "lat": value["lat"], "lon": value["lon"], "name": names.get(key, key)}
        for key, value in metrics.items()
    ]

    envelope = build_envelope(layers, known)
    score = score_field(layers, envelope)
    print(f"  screened {int((ok & np.isfinite(score)).sum())} land cells")

    countries = geojson(NE_COUNTRIES, "ne_50m_admin_0_countries.geojson")
    cells = pick_candidates(score, ok, layers, known, countries)
    print(f"  {len(cells)} candidates pass the spacing rules")

    write_field(score, ok, envelope)
    write_elevation(layers, ok)
    places = load_places()
    sites = refine(cells, places, countries, known, int((ok & np.isfinite(score)).sum()))
    write_sites(sites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))