"""Collect real imagery for every Earth analog site.

Two things are fetched per site, both from public, keyless, licensed sources:

1. Satellite mosaic - Sentinel-2 cloudless 2020 (EOX, CC BY 4.0) WMTS tiles,
   stitched into a 768x512 top-down view of the site.

2. Ground photos - Wikimedia Commons geosearch around the coordinates, so the
   photos are genuinely of that place, with author + licence recorded.

Nothing is generated. Every downloaded image is kept under assets/photos/ with
its attribution so the page works offline and can always cite the source.

Usage: python tools/fetch_site_photos.py
"""

from __future__ import annotations

import io
import json
import math
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "photos"
META = ROOT / "assets" / "photos.js"
SITES_JS = ROOT / "assets" / "data" / "earth-sites.js"
METRICS_JS = ROOT / "assets" / "earth-metrics.js"

UA = {"User-Agent": "RADIUM-hackathon/1.0 (educational; contact: team@example.com)"}

SAT_TMPL = (
    "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg"
)
SAT_Z = 12
SAT_COLS, SAT_ROWS = 3, 2
TILE = 256

SAT_CREDIT = "Sentinel-2 cloudless 2020 - EOX IT Services GmbH (CC BY 4.0)"
SAT_LINK = "https://s2maps.eu"

MAX_PHOTOS = 6

# Sites whose geotagged photos sit further away than the default radius.
RADIUS_KM = {
    "dasht-e-kavir": 100,
    "dash-e-kavir": 100,
    "aral-sea-bed": 100,
    "kati-thanda": 100,
    "sechura": 90,
    "bunger-hills": 100,
    "don-juan-pond": 60,
    "mistastin": 60,
    "tolbachik": 60,
    "qaidam": 100,
    "strelley-pool": 100,
    "sossusvlei": 100,
    "lakagigar": 60,
    "lunar-crater-nv": 60,
    "gypsum-hill": 60,
}

# Better Commons search terms for sites whose display name finds nothing.
SEARCH_OVERRIDE = {
    "lut": "Dasht-e Lut desert",
    "strelley-pool": "Pilbara stromatolite",
    "bunger-hills": "Bunger Hills Antarctica",
    "gypsum-hill": "Axel Heiberg Island",
    "mistastin": "Mistastin Lake",
    "dash-e-kavir": "Dasht-e Kavir",
    "kati-thanda": "Lake Eyre",
    "aral-sea-bed": "Aral Sea",
    "sechura": "Sechura desert",
    "ojos-del-salado": "Nevado Ojos del Salado",
    "mdrs": "San Rafael Swell",
    "lunar-crater-nv": "Lunar Crater Nevada",
}

# Photos of infrastructure and signage are geotagged nearby but say nothing
# about the landscape.
TITLE_BLOCKLIST = (
    "train", "railway", "locomotive", "museum", "hotel", "restaurant", "hostel",
    "building", "station", "village", "church", "chapel", "mosque", "cemetery",
    "grave", "sign", "signpost", "plaque", "memorial", "monument", "shop",
    "street", "road", "highway", "bus", "car", "truck", "vehicle", "airport",
    "school", "hospital", "painting", "drawing", "map", "diagram", "logo",
    "flag", "stamp", "coin", "portrait", "poster", "book", "document", "camp",
    "shelter", "dome", "solar panel", "antenna", "telescope", "visitor",
    "parking", "bridge", "dam", "pipeline", "mine", "quarry",
    # Accommodation and facilities: geotagged near these sites but demonstrate
    # nothing about the terrain.
    "housing", "quarters", "lodge", "residence", "cabin", "bunkhouse", "motel",
    "apartment", "barracks", "headquarters", "kiosk", "toilet", "restroom",
    "picnic", "bench", "fence", "gate", "exhibit", "display", "interior",
    "room", "kitchen", "office", "warehouse", "hangar", "garage",
)

# Close-ups of plants or animals show the biosphere, not the terrain analog.
SUBJECT_PENALTIES = (
    "flower", "wildflower", "blossom", "inflorescence", "botany", "flora",
    "plant", "shrub", "lichen", "moss", "fungus", "insect", "butterfly",
    "beetle", "bird", "lizard", "mammal", "skeleton", "bone", "skull",
    "seed", "leaf", "leaves", "petal", "pollen", "herbarium",
)

# Titles that suggest a scanned archive photo rather than a landscape view today.
ARCHIVE_HINTS = ("historic", "historical", "archive", "photograph collection", "nara -")

# Titles that are actually looking down from orbit, not standing on the ground.
ORBITAL_HINTS = (
    "sentinel", "landsat", "satellite", "from space", "from orbit", "aerial view",
    "astronaut photograph", "earth observatory", "iss0", "modis", "spot ",
)


def load_sites() -> list[dict]:
    src = SITES_JS.read_text(encoding="utf-8")
    meta_src = METRICS_JS.read_text(encoding="utf-8")
    metrics = json.loads(meta_src[meta_src.index("{") : meta_src.rindex(";")])

    sites = []
    for match in re.finditer(r'id:\s*"([^"]+)",\s*\n\s*name:\s*"([^"]+)"', src):
        site_id, name = match.group(1), match.group(2)
        if site_id in metrics:
            sites.append(
                {
                    "id": site_id,
                    "name": name,
                    "lat": metrics[site_id]["lat"],
                    "lon": metrics[site_id]["lon"],
                }
            )
    return sites


def get(url: str, timeout: int = 45) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def get_json(url: str):
    data = get(url)
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def build_satellite(site: dict) -> bool:
    cx, cy = lat_lon_to_tile(site["lat"], site["lon"], SAT_Z)
    canvas = Image.new("RGB", (SAT_COLS * TILE, SAT_ROWS * TILE), (10, 14, 24))

    jobs = [
        (dx, dy)
        for dy in range(-(SAT_ROWS // 2), SAT_ROWS - SAT_ROWS // 2)
        for dx in range(-(SAT_COLS // 2), SAT_COLS - SAT_COLS // 2)
    ]

    def grab(job):
        dx, dy = job
        x, y = cx + dx, cy + dy
        return dx, dy, get(SAT_TMPL.format(z=SAT_Z, y=y, x=x))

    ok = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(grab, jobs))
    for (dx, dy), (_, _, data) in zip(jobs, results):
        if not data:
            continue
        try:
            tile = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            continue
        canvas.paste(tile, ((dx + SAT_COLS // 2) * TILE, (dy + SAT_ROWS // 2) * TILE))
        ok += 1

    if ok < 3:
        return False
    canvas.save(OUT / f"{site['id']}-sat.jpg", quality=88, optimize=True)
    return True


def safe_image(data: bytes) -> Image.Image | None:
    try:
        image = Image.open(io.BytesIO(data))
        if image.mode in ("P", "LA"):
            image = image.convert("RGBA")
        return image.convert("RGB")
    except Exception:
        return None


def commons_geosearch(site: dict, radius_km: float, limit: int = 6) -> list[dict]:
    """Photos geotagged near the site. The API caps the radius at 10 km."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "geosearch",
        "ggsnamespace": "6",
        "ggscoord": f"{site['lat']}|{site['lon']}",
        "ggsradius": str(int(min(radius_km, 10.0) * 1000)),
        "ggslimit": str(limit * 3),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime|size",
        "iiurlwidth": "900",
    }
    data = get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    return collect_images(data)


def commons_textsearch(site: dict, limit: int = 8) -> list[dict]:
    """Fallback for remote sites with no geotagged photos nearby."""
    query = SEARCH_OVERRIDE.get(site["id"]) or site["name"].split(",")[0]
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": query,
        "gsrlimit": str(limit * 3),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime|size",
        "iiurlwidth": "1200",
    }
    data = get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    if not data:
        return []
    tokens = [t.lower() for t in query.replace("-", " ").split() if len(t) > 3]
    return [
        photo
        for photo in collect_images(data)
        if any(token in photo["title"].lower() for token in tokens)
    ]


CATEGORY_BLOCKLIST = (
    "flora", "fauna", "plants", "plant", "insects", "birds", "animals",
    "wildlife", "botany", "flowers", "lichens", "mosses", "fungi", "trees",
    "people", "maps", "diagrams", "history of", "vehicles", "buildings",
    "signs", "aerial photographs", "satellite images", "maps and diagrams",
)


def commons_categories(site: dict, limit: int = 8) -> list[dict]:
    """Photos from the Commons categories that match the site.

    Curated categories are the best source of landscape photography for a named
    place, and they reach well beyond the 10 km geosearch radius.
    """
    name = SEARCH_OVERRIDE.get(site["id"]) or site["name"].split(",")[0]
    found = get_json(
        "https://commons.wikimedia.org/w/api.php?"
        + urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": name,
                "srnamespace": "14",
                "srlimit": "6",
            }
        )
    )
    if not found or "query" not in found:
        return []

    categories = [row["title"] for row in found["query"]["search"]]
    tokens = [t.lower() for t in name.replace("-", " ").split() if len(t) > 3]
    categories = [
        c
        for c in categories
        if any(t in c.lower() for t in tokens)
        and not any(bad in c.lower() for bad in CATEGORY_BLOCKLIST)
    ]
    if not categories:
        return []

    photos: list[dict] = []
    for category in categories[:3]:
        data = get_json(
            "https://commons.wikimedia.org/w/api.php?"
            + urllib.parse.urlencode(
                {
                    "action": "query",
                    "format": "json",
                    "generator": "categorymembers",
                    "gcmtitle": category,
                    "gcmtype": "file",
                    "gcmlimit": str(limit * 2),
                    "prop": "imageinfo",
                    "iiprop": "url|extmetadata|mime|size",
                    "iiurlwidth": "1200",
                }
            )
        )
        photos.extend(collect_images(data))
    return photos


TITLE_KEYWORDS = (
    "view", "panorama", "panoramic", "landscape", "aerial", "from above",
    "formation", "rock", "cliff", "canyon", "valley", "dune", "sand", "desert",
    "crater", "lava", "ice", "glacier", "permafrost", "salt", "playa", "plain",
    "ridge", "peak", "summit", "terrain", "basin", "caldera", "volcano",
    "field", "plateau", "escarpment", "coast", "shore", "lake", "spring",
    "mountain", "hills", "expanse", "horizon", "sky",
)


def relevance(title: str, site_name: str) -> int:
    """Rank candidate photos by how much they look like a landscape of the site."""
    low = title.lower()
    score = 2 * sum(1 for word in TITLE_KEYWORDS if word in low)
    for token in site_name.replace(",", " ").replace("-", " ").lower().split():
        if len(token) > 3 and token in low:
            score += 2
    if any(bad in low for bad in ("portrait", "people", "person", "tourist", "selfie", "crowd")):
        score -= 5
    if any(bad in low for bad in SUBJECT_PENALTIES):
        score -= 5
    if any(hint in low for hint in ARCHIVE_HINTS):
        score -= 6
    # Four-digit 19xx years usually mark a scanned historical photograph.
    if re.search(r"\b19\d{2}\b", low):
        score -= 5
    if is_orbital(title):
        score -= 3
    return score


def is_orbital(title: str) -> bool:
    low = title.lower()
    return any(hint in low for hint in ORBITAL_HINTS)


def blocked(title: str) -> bool:
    low = title.lower()
    return any(word in low for word in TITLE_BLOCKLIST)


def collect_images(data) -> list[dict]:
    if not data or "query" not in data:
        return []
    picked = []
    for page in data["query"]["pages"].values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("mime", "").startswith("image/"):
            continue
        width, height = info.get("width") or 0, info.get("height") or 0
        if width < 1000 or height < 500:
            continue
        ratio = width / max(1, height)
        if ratio < 1.15 or ratio > 2.8:
            continue
        if blocked(page["title"]):
            continue
        meta = info.get("extmetadata") or {}
        title = page["title"].replace("File:", "")
        picked.append(
            {
                "title": title,
                "thumb": info.get("thumburl"),
                "page": info.get("descriptionurl"),
                "author": re.sub("<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip(),
                "license": (meta.get("LicenseShortName") or {}).get("value", "unknown"),
                "licenseUrl": (meta.get("LicenseUrl") or {}).get("value", ""),
                "order": len(picked),
            }
        )
    return picked


def pick_best(photos: list[dict], site_name: str, count: int = 2) -> list[dict]:
    ranked = sorted(
        photos,
        key=lambda p: (-relevance(p["title"], site_name), p.get("order", 0)),
    )
    # Split into photos that describe terrain and photos that merely happen to be
    # near the site. If there is enough terrain imagery, ignore the rest, so a
    # gallery never leads with a wildflower or a building.
    strong = [p for p in ranked if has_terrain_word(p["title"])]
    weak = [p for p in ranked if not has_terrain_word(p["title"])]
    ordered = strong + weak if len(strong) < 3 else strong
    return ordered[:count]


def has_terrain_word(title: str) -> bool:
    low = title.lower()
    return any(word in low for word in TITLE_KEYWORDS)


def title_key(title: str) -> str:
    """Collapse titles that describe the same subject, e.g. a numbered series."""
    base = re.sub(r"\([^)]*\)", "", title.lower())
    base = re.sub(r"[^a-z ]+", " ", base)
    words = [w for w in base.split() if len(w) > 2]
    return " ".join(words[:5])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sites = load_sites()
    print(f"{len(sites)} sites")

    manifest: dict[str, dict] = {}

    def handle(site):
        radius = RADIUS_KM.get(site["id"], 10)
        entry = {"photos": [], "satellite": None}
        if build_satellite(site):
            entry["satellite"] = {
                "file": f"assets/photos/{site['id']}-sat.jpg",
                "credit": SAT_CREDIT,
                "url": SAT_LINK,
            }

        # Curated categories give the best landscape photography for a named
        # place; geosearch adds anything else photographed on the ground there.
        geo = commons_geosearch(site, radius)
        cats = commons_categories(site)
        text = commons_textsearch(site) if len(geo) < 3 else []
        sources = []
        if geo:
            sources.append("geo")
        if cats:
            sources.append("category")
        if text:
            sources.append("text")

        merged: list[dict] = []
        seen: set[str] = set()
        for group in (geo, cats, text):
            for photo in group:
                key = photo["title"].lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(photo)

        ranked = pick_best(merged, site["name"], 30)

        def download(passes: int) -> None:
            """Download candidates, one image per subject first; allow repeats on
            the second pass so sparse sites still get a gallery."""
            used_subjects: set[str] = set()
            for photo in ranked:
                if len(entry["photos"]) >= MAX_PHOTOS:
                    return
                if not photo.get("thumb"):
                    continue
                subject = title_key(photo["title"])
                if passes == 1 and subject in used_subjects:
                    continue
                if photo["title"] in {p["title"] for p in entry["photos"]}:
                    continue
                data = get(photo["thumb"], timeout=60)
                if not data:
                    continue
                image = safe_image(data)
                if image is None:
                    continue
                used_subjects.add(subject)
                image.thumbnail((1200, 1200), Image.LANCZOS)
                index = len(entry["photos"]) + 1
                name = f"{site['id']}-{index}.jpg"
                image.save(OUT / name, quality=84, optimize=True)
                entry["photos"].append(
                    {
                        "file": f"assets/photos/{name}",
                        "title": photo["title"],
                        "author": photo["author"] or "Wikimedia Commons contributor",
                        "license": photo["license"],
                        "licenseUrl": photo["licenseUrl"],
                        "page": photo["page"],
                        "kind": "Orbital view" if is_orbital(photo["title"]) else "Ground view",
                    }
                )

        download(1)
        if len(entry["photos"]) < 3:
            download(2)
        entry["photoSource"] = "+".join(sources) if entry["photos"] else None
        status = f"sat={'y' if entry['satellite'] else 'n'} photos={len(entry['photos'])}"
        print(f"  {site['id']:20s} {status}", flush=True)
        return site["id"], entry

    with ThreadPoolExecutor(max_workers=5) as pool:
        for site_id, entry in pool.map(handle, sites):
            manifest[site_id] = entry

    payload = "window.RADIUM_PHOTOS = " + json.dumps(manifest, indent=1) + ";\n"
    META.write_text(payload, encoding="utf-8")

    total_sat = sum(1 for v in manifest.values() if v["satellite"])
    total_photos = sum(len(v["photos"]) for v in manifest.values())
    print(f"\n{total_sat} satellite mosaics, {total_photos} ground photos -> {META.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
