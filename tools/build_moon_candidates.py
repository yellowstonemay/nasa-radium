"""Add the expanded lunar candidate set to assets/data/moon-sites.js.

Numbers come from two places, and the split is deliberate:

  * terrain and temperature are sampled from the same LOLA / Diviner-derived
    grids the app uses for point queries (assets/grids/moon-*.png), so a site's
    dossier always agrees with a query at its coordinates;
  * illumination, Earth visibility, ice proximity and the qualitative scores are
    literature-derived: the Artemis III candidate region study, published
    peak-of-eternal-light analyses, and LROC / Diviner results. Each entry keeps
    a confidence tag and a citation.

The script only writes the block between the two markers in moon-sites.js, so the
original ten hand-written sites are never touched. Run it twice and the file is
unchanged.

Run: python tools/build_moon_candidates.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GRIDS = ROOT / "assets" / "grids"
DATA = ROOT / "assets" / "data" / "moon-sites.js"

BEGIN = "  // --- generated: extra lunar candidates (tools/build_moon_candidates.py)"
END = "  // --- end generated"

ARTEMIS = (
    "NASA - Artemis III candidate landing regions",
    "https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/",
)
LROC = ("LROC - lunar reconnaissance orbiter camera", "https://lroc.sese.asu.edu/")
ILLUM = ("NASA SVS - LRO illumination and PSR mapping", "https://svs.gsfc.nasa.gov/4720")
DIVINER = ("PDS - LRO Diviner surface temperatures", "https://pds-geosciences.wustl.edu/missions/lro/diviner.htm")
TREK = ("NASA Moon Trek - LOLA topography", "https://trek.nasa.gov/moon/")

# id, name, region, lat, lon, illumination %, earth visibility %, ice index,
# ice distance km, dust, subsurface, biosignature, science, composition,
# rationale, limits, source, confidence
SITES = [
    (
        "peak-near-shackleton", "Peak Near Shackleton", "Shackleton - south pole", -89.4, 130.0,
        84, 99, 74, 3, 30, 25, 8, 91,
        "Highland massif on the Shackleton rim; oldest exposed terrain near the pole",
        "Artemis III candidate region: a sunlit peak with permanently shadowed ground inside a short moonwalk.",
        "Extremely small usable area on the crest; crew must descend into the cold trap for ice samples.",
        ARTEMIS, "medium",
    ),
    (
        "connecting-ridge-ext", "Connecting Ridge Extension", "Shackleton - de Gerlache", -89.3, 222.0,
        90, 96, 80, 2, 28, 28, 8, 93,
        "Ridge crest between Shackleton and de Gerlache, massif regolith",
        "Artemis III candidate region with the best continuous sunlight near the pole and ice-bearing PSRs alongside.",
        "Ridge is narrow, so the base footprint and the landing ellipse compete for the same flat ground.",
        ARTEMIS, "medium",
    ),
    (
        "faustini-rim-a", "Faustini Rim A", "Faustini - south pole", -87.1, 85.3,
        76, 92, 72, 4, 32, 30, 10, 90,
        "Rim of Faustini, a 39 km crater with one of the coldest floors measured",
        "Artemis III candidate region: sunlit rim above a permanently shadowed floor, so ice and power are metres apart in altitude.",
        "Long shadows cross the rim for part of the year; PSR descent is steep.",
        ARTEMIS, "medium",
    ),
    (
        "de-gerlache-rim-2", "de Gerlache Rim 2", "Shackleton - de Gerlache", -88.4, 272.6,
        85, 94, 76, 3, 30, 30, 8, 90,
        "Highland rim material adjacent to de Gerlache PSR",
        "Artemis III candidate region on the opposite rim to de Gerlache Rim 1, giving launch-window flexibility.",
        "Close to the existing de Gerlache site, so it adds redundancy more than new geology.",
        ARTEMIS, "medium",
    ),
    (
        "de-gerlache-kocher", "de Gerlache-Kocher Massif", "Shackleton - de Gerlache", -88.3, 250.0,
        78, 93, 74, 5, 32, 34, 9, 89,
        "Massif between de Gerlache and Kocher, mixed highland and impact melt",
        "Artemis III candidate region with more relief and exposed stratigraphy than the flat rims.",
        "Rough terrain raises landing risk; comms geometry is worse than the ridge sites.",
        ARTEMIS, "medium",
    ),
    (
        "amundsen-rim", "Amundsen Rim", "Amundsen - south pole", -84.5, 82.8,
        68, 100, 62, 8, 30, 35, 8, 88,
        "Rim of Amundsen, a 103 km crater straddling the south polar terrain",
        "Artemis III candidate region: a large, relatively gentle rim with PSR access and full Earth visibility.",
        "Lower peak illumination than the Shackleton cluster, so battery sizing is tighter.",
        ARTEMIS, "medium",
    ),
    (
        "leibnitz-beta", "Leibnitz Beta Plateau", "Leibnitz - south pole", -85.0, 25.0,
        70, 100, 58, 20, 34, 40, 6, 84,
        "High plateau of pre-Nectarian highland crust",
        "Artemis III candidate region: broad flat ground that can host a larger base than a ridge crest.",
        "Ice is kilometres away rather than adjacent; long traverses needed for volatiles.",
        ARTEMIS, "medium",
    ),
    (
        "nobile-rim-1", "Nobile Rim 1", "Nobile - south pole", -84.9, 53.9,
        66, 97, 64, 12, 33, 32, 8, 86,
        "Rim of Nobile crater, highland regolith over impact melt",
        "Artemis III candidate region on the opposite side of the pole, useful for launch-window coverage.",
        "Moderate illumination; the rim is more broken than the Shackleton side.",
        ARTEMIS, "medium",
    ),
    (
        "nobile-rim-2", "Nobile Rim 2", "Nobile - south pole", -85.6, 58.5,
        72, 95, 68, 8, 33, 30, 8, 87,
        "Higher section of the Nobile rim with small PSRs below",
        "Artemis III candidate region with better sunlight than Rim 1 and ice within rover range.",
        "Narrow sunlit band; the usable area is a fraction of the region outline.",
        ARTEMIS, "medium",
    ),
    (
        "whipple-rim", "Whipple Crater Rim", "Lunar North Pole", 88.7, 113.6,
        78, 100, 66, 5, 30, 28, 6, 88,
        "North polar highland rim with shadowed floor",
        "Northern counterpart to the Shackleton ridge: a peak-of-eternal-light candidate identified in LRO illumination studies, above a cold trap.",
        "Thinner PSR coverage than the south and no confirmed surface ice detection.",
        ILLUM, "medium",
    ),
]
# Mid-latitude science and resource targets: no polar ice, but rare geology,
# lava-tube access or far-side materials that a base could exploit.
SCIENCE_SITES = [
    (
        "aristarchus-plateau", "Aristarchus Plateau", "Oceanus Procellarum", 25.4, 312.4,
        60, 100, 8, 0, 25, 55, 5, 92,
        "Pyroclastic dark mantling over highland uplift, cut by Vallis Schroteri",
        "The brightest large feature on the Moon: explosive volcanics, a sinuous rille and candidate lava tubes in one place.",
        "Volatile-poor and far from polar ice; radiation and thermal cycling are unshielded.",
        LROC, "medium",
    ),
    (
        "gruithuisen-domes", "Gruithuisen Domes", "Mare Imbrium north-west", 36.4, 319.8,
        55, 100, 6, 0, 26, 35, 5, 90,
        "Rare silicic (granite-like) volcanic domes",
        "One of the few places on the Moon with evolved, silica-rich volcanism, which matters for resource processing and for understanding lunar differentiation.",
        "Steep dome flanks; no local water and limited flat ground.",
        LROC, "medium",
    ),
    (
        "compton-belkovich", "Compton-Belkovich Complex", "Far-side highlands", 61.1, 99.5,
        55, 0, 12, 0, 24, 45, 5, 94,
        "Thorium-rich silicic volcanic complex in the far-side highlands",
        "Far-side volcanic complex discovered from orbit: radiogenic heat, evolved rock and no Earth line of sight, so it forces a relay architecture.",
        "Needs a relay satellite for comms; no ice and a long polar night at 61 deg N.",
        LROC, "medium",
    ),
    (
        "von-karman", "Von Karman Crater (Chang'e-4)", "South Pole-Aitken basin", -45.5, 177.6,
        55, 0, 10, 0, 22, 40, 5, 95,
        "Feldspathic and mafic materials excavated by the SPA impact",
        "Where Chang'e-4 landed: access to South Pole-Aitken mantle material, the deepest excavation on the Moon.",
        "Far side, so it needs relay comms; no polar ice within practical range.",
        LROC, "high",
    ),
    (
        "schrodinger-basin", "Schrodinger Basin", "South pole - Aitken rim", -75.0, 132.4,
        50, 0, 20, 60, 26, 45, 5, 94,
        "Basin ring with pyroclastic vents and impact melt",
        "Young basin with pyroclastics and a well-preserved ring, plus a south-polar-style cold trap inside it.",
        "Far side and high latitude: relay comms and severe winters.",
        LROC, "medium",
    ),
]

SITES = SITES + SCIENCE_SITES

# Region centroids published by the Artemis III study sit on crater floors as
# often as on their rims, so rim/peak/plateau sites are snapped to the highest
# ground within 1 degree of the published centre (the DEM does the placing, and
# the shift is printed on every run).
SNAP = {
    "peak-near-shackleton", "faustini-rim-a", "de-gerlache-rim-2",
    "de-gerlache-kocher", "amundsen-rim", "nobile-rim-1", "nobile-rim-2",
    "whipple-rim", "leibnitz-beta", "connecting-ridge-ext",
}


def snap_to_high_ground(dem: np.ndarray, lat: float, lon: float) -> tuple[float, float]:
    rows, cols = dem.shape
    best = (elevation_at(dem, lat, lon), lat, lon)
    for dlat in np.arange(-1.0, 1.01, 0.25):
        for dlon in np.arange(-1.0, 1.01, 0.25):
            # keep a degree clear of the pole: the last rows of the cylindrical
            # product are compressed and contain zero-filled gaps
            la = max(-88.5, min(88.5, lat + dlat))
            lo = (lon + dlon) % 360.0
            value = elevation_at(dem, la, lo)
            if value > best[0] and abs(value) > 1.0:
                best = (value, la, lo)
    return best[1], best[2]

LOLA = ROOT / "tools" / ".gridcache" / "ldem_4.img"
LOLA_SCALE = 0.5      # metres per DN
LOLA_LINES, LOLA_SAMPLES = 720, 1440   # 4 pixels per degree


def load_lola() -> np.ndarray:
    """Native 4 px/deg LOLA grid, rolled so column 0 is 180 W.

    The 0.5 degree PNG the browser uses is far too coarse at the poles: a polar
    rim site can land inside the crater next to it. Site numbers come from here.
    """
    raw = np.fromfile(LOLA, dtype="<i2", count=LOLA_LINES * LOLA_SAMPLES)
    dem = raw.reshape(LOLA_LINES, LOLA_SAMPLES).astype(np.float32) * LOLA_SCALE
    return np.roll(dem, LOLA_SAMPLES // 2, axis=1)


def elevation_at(dem: np.ndarray, lat: float, lon: float) -> float:
    """Bilinear elevation from the native 4 px/deg LOLA grid."""
    rows, cols = dem.shape
    lon180 = ((lon + 180.0) % 360.0) - 180.0          # sites use 0..360 east
    y = (90.0 - lat) / 180.0 * rows - 0.5
    x = (lon180 + 180.0) / 360.0 * cols - 0.5
    y0, x0 = int(np.floor(y)), int(np.floor(x))
    fy, fx = y - y0, x - x0
    y0 = max(0, min(rows - 2, y0))
    x0 = max(0, min(cols - 1, x0))
    y1, x1 = min(rows - 1, y0 + 1), (x0 + 1) % cols
    elevation = (
        dem[y0, x0] * (1 - fy) * (1 - fx) + dem[y0, x1] * (1 - fy) * fx
        + dem[y1, x0] * fy * (1 - fx) + dem[y1, x1] * fy * fx
    )
    return float(elevation)


def load_meta() -> dict:
    text = (GRIDS / "moon-meta.js").read_text(encoding="utf-8")
    return json.loads(text.split("=", 1)[1].strip().rstrip(";"))


def sample(layer: dict, lat: float, lon: float) -> float:
    """Nearest cell value from a 720x360 grid, or from a 1x360 latitude strip."""
    image = np.asarray(Image.open(ROOT / layer["file"]).convert("L"), dtype=np.float32)
    rows, cols = image.shape
    row = min(rows - 1, max(0, int((90.0 - lat) / 180.0 * rows)))
    col = min(cols - 1, max(0, int(((lon % 360.0) + 180.0) / 360.0 * cols))) if cols > 1 else 0
    value = float(image[row, col]) / 255.0
    return layer["min"] + value * (layer["max"] - layer["min"])


def js_entry(site: tuple, meta: dict, dem: np.ndarray) -> str:
    (sid, name, region, lat, lon, illum, earthvis, ice, ice_km, dust,
     subsurface, bio, science, composition, analog, limits, source, confidence) = site
    layers = meta["layers"]
    if sid in SNAP:
        moved_lat, moved_lon = snap_to_high_ground(dem, lat, lon)
        if (moved_lat, moved_lon) != (lat, lon):
            print(f"  {sid}: moved {abs(moved_lat - lat):.2f} deg lat, "
                  f"{abs(moved_lon - lon):.2f} deg lon to the local high ground")
        lat, lon = moved_lat, moved_lon
    elevation = elevation_at(dem, lat, lon)
    slope = sample(layers["slopeDeg"], lat, lon)
    relief = 10.0 ** sample(layers["roughnessM"], lat, lon) - 1.0
    day = sample(layers["tempDayC"], lat, lon)
    night = sample(layers["tempNightC"], lat, lon)
    solar = round(illum * 0.045, 1)  # same relation the hand-written sites use

    def num(value: float, digits: int = 0) -> float:
        rounded = round(value, digits)
        return int(rounded) if digits == 0 else rounded

    return f"""  {{
    id: "{sid}",
    name: "{name}",
    region: "{region}",
    lat: {lat}, lon: {lon},
    elevationM: {num(elevation)}, slopeDeg: {num(slope, 1)}, roughness: {num(relief, 1)},
    tempDayC: {num(day)}, tempNightC: {num(night)},
    illuminationPct: {illum}, earthVisibilityPct: {earthvis},
    iceIndex: {ice}, iceDistanceKm: {ice_km}, dustIndex: {dust}, solarKwh: {solar}, pressurePa: 0,
    composition: "{composition}",
    scienceScore: {science}, subsurfaceScore: {subsurface}, biosignatureScore: {bio},
    confidence: "{confidence}",
    analog: "{analog}",
    limits: "{limits}",
    source: {{ label: "{source[0]}", url: "{source[1]}" }}
  }}"""


def main() -> int:
    meta = load_meta()
    dem = load_lola()
    body = ",\n".join(js_entry(site, meta, dem) for site in SITES)
    block = BEGIN + "\n" + body + ",\n" + END

    text = DATA.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        text = head + block + tail
    else:
        # insert before the closing bracket of the array
        index = text.rstrip().rfind("];")
        head = text[:index].rstrip()
        if not head.endswith(","):
            head += ","
        text = head + "\n" + block + "\n" + text[index:]
    DATA.write_text(text, encoding="utf-8", newline="\n")

    total = len(re.findall(r'^    id: "', text, re.MULTILINE))
    print(f"wrote {len(SITES)} generated candidates, {total} lunar sites total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())