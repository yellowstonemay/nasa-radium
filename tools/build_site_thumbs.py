"""Crop a real surface view around every curated Moon and Mars site.

The source is the same NASA mosaic already used as the globe texture
(LRO WAC for the Moon, Viking MDIM for Mars), so each dossier image is the
actual terrain at that coordinate rather than an illustration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TEXTURES = ROOT / "assets" / "textures"
OUT = ROOT / "assets" / "photos"
MANIFEST = ROOT / "assets" / "pin-thumbs.js"

# body -> (texture, site data file, globe variable)
BODIES = {
    "moon": ("moon_base.jpg", "assets/data/moon-sites.js", "RADIUM_MOON"),
    "mars": ("mars_base.jpg", "assets/data/mars-sites.js", "RADIUM_MARS"),
}

CROP = 460


def parse_sites(path: Path) -> list[dict]:
    src = path.read_text(encoding="utf-8")
    sites = []
    pattern = re.compile(
        r'id:\s*"([^"]+)"[\s\S]*?lat:\s*(-?[\d.]+),\s*lon:\s*(-?[\d.]+)'
    )
    for match in pattern.finditer(src):
        sites.append(
            {
                "id": match.group(1),
                "lat": float(match.group(2)),
                "lon": float(match.group(3)),
            }
        )
    return sites


def crop_at(texture: Image.Image, lat: float, lon: float, size: int) -> Image.Image:
    width, height = texture.size
    lon_n = ((lon + 180.0) % 360) - 180.0
    x = int(((lon_n + 180.0) / 360.0) * width)
    y = int(((90.0 - lat) / 180.0) * height)
    half = size // 2
    left = max(0, min(width - size, x - half))
    top = max(0, min(height - size, y - half))
    return texture.crop((left, top, left + size, top + size))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}

    for body, (texture_name, data_file, _) in BODIES.items():
        texture = Image.open(TEXTURES / texture_name).convert("RGB")
        sites = parse_sites(ROOT / data_file)
        print(f"[{body}] {len(sites)} sites from {texture_name} {texture.size}")
        for site in sites:
            crop = crop_at(texture, site["lat"], site["lon"], CROP)
            crop = crop.resize((320, 320), Image.LANCZOS)
            name = f"{body}-{site['id']}.jpg"
            crop.save(OUT / name, quality=86, optimize=True)
            manifest[f"{body}:{site['id']}"] = f"assets/photos/{name}"
        print(f"  wrote {len(sites)} crops")

    MANIFEST.write_text(
        "window.RADIUM_PIN_THUMBS = " + json.dumps(manifest, indent=1) + ";\n",
        encoding="utf-8",
    )
    print(f"total {len(manifest)} thumbnails -> {MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
