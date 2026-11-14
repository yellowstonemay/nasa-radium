"""Stitch NASA Trek / GIBS map tiles into equirectangular textures.

Usage:  python tools/fetch_textures.py [--zoom-base 4] [--zoom-layer 3]

Everything here is keyless public data:
  Moon  -> NASA Moon Trek (LRO WAC / LOLA / Diviner)
  Mars  -> NASA Mars Trek (MGS MOLA / TES, MOLA roughness)
  Earth -> NASA GIBS Blue Marble (base texture only; live layers are streamed)

The output is written to assets/textures/ so the demo still renders offline.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps, ImageStat

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "textures"
CACHE = ROOT / "tools" / ".tilecache"

TREK = "https://trek.nasa.gov/tiles/{body}/EQ/{layer}/1.0.0/default/default028mm/{z}/{y}/{x}.{ext}"

# layer key -> (body, Trek layer id, label)
TREK_LAYERS = {
    "moon_base": ("Moon", "LRO_WAC_Mosaic_Global_303ppd_v02", "LRO WAC global mosaic"),    "moon_day": ("Moon", "LRO_Diviner_ST_Avg_Clr_Global_32ppd", "Diviner average daytime surface temperature"),
    "moon_night": ("Moon", "LRO_Diviner_STN_Avg_Clr_Global_32ppd", "Diviner average nighttime surface temperature"),
    "moon_slope": ("Moon", "LRO_LOLA_ClrSlope_Global_16ppd", "LOLA slope"),
    "moon_rough": ("Moon", "LRO_LOLA_ClrRoughness_Global_16ppd", "LOLA roughness"),
    "mars_base": ("Mars", "Mars_MGS_MOLA_ClrShade_merge_global_463m", "MOLA color shaded relief"),
    "mars_visible": ("Mars", "Mars_Viking_MDIM21_ClrMosaic_global_232m", "Viking MDIM color mosaic"),
    "mars_ir": ("Mars", "THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018", "THEMIS daytime infrared mosaic"),
    "mars_inertia": ("Mars", "TES_Thermal_Inertia", "TES thermal inertia"),
    "mars_albedo": ("Mars", "Mars_MGS_TES_Albedo_mosaic_global_7410m", "TES albedo"),
    "mars_dust": ("Mars", "TES_Dust", "TES dust coverage"),
    "mars_rough": ("Mars", "mola_roughness", "MOLA roughness"),
}

GIBS = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry"
    "/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg"
)

EXTENSIONS = ("jpg", "png", "jpeg")


def download(url: str) -> bytes | None:
    cache_key = CACHE / (str(abs(hash(url))) + Path(url).suffix)
    if cache_key.exists():
        return cache_key.read_bytes()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RADIUM-hackathon/1.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
    except Exception:
        return None
    cache_key.parent.mkdir(parents=True, exist_ok=True)
    cache_key.write_bytes(data)
    return data


def resolve_extension(body: str, layer: str) -> str | None:
    for ext in EXTENSIONS:
        if download(TREK.format(body=body, layer=layer, z=1, y=0, x=0, ext=ext)):
            return ext
    return None


def tile_grid(zoom: int) -> tuple[int, int]:
    return 2 ** zoom, 2 ** (zoom - 1)


def stitch(body: str, layer: str, zoom: int) -> Image.Image | None:
    ext = resolve_extension(body, layer)
    if not ext:
        print(f"  ! could not resolve tiles for {layer}", file=sys.stderr)
        return None
    cols, rows = tile_grid(zoom)
    canvas = Image.new("RGBA", (cols * 256, rows * 256), (0, 0, 0, 255))

    def grab(args):
        x, y = args
        data = download(TREK.format(body=body, layer=layer, z=zoom, y=y, x=x, ext=ext))
        return x, y, data

    jobs = [(x, y) for y in range(rows) for x in range(cols)]
    done = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        for x, y, data in pool.map(grab, jobs):
            done += 1
            if not data:
                continue
            try:
                tile = Image.open(io.BytesIO(data)).convert("RGBA")
            except Exception:
                continue
            canvas.paste(tile, (x * 256, y * 256))
            if done % 32 == 0:
                print(f"  {layer}: {done}/{len(jobs)} tiles", flush=True)
    return canvas


def stitch_earth_base(zoom: int = 3) -> Image.Image | None:
    cols, rows = 2 ** zoom, 2 ** zoom

    def grab(args):
        x, y = args
        return x, y, download(GIBS.format(z=zoom, y=y, x=x))

    canvas = Image.new("RGBA", (cols * 256, rows * 256), (0, 0, 0, 255))
    for x, y, data in ThreadPoolExecutor(max_workers=12).map(
        grab, [(x, y) for y in range(rows) for x in range(cols)]
    ):
        if data:
            canvas.paste(Image.open(io.BytesIO(data)).convert("RGBA"), (x * 256, y * 256))
    return canvas


HEAT_RAMP = ("#0b1030", "#2f4bd6", "#1fd6c1", "#f2c14e", "#f7f4ea")


def percentile_from_hist(hist: list[int], pct: float) -> int:
    total = sum(hist)
    if total == 0:
        return 0
    target = total * pct / 100.0
    seen = 0
    for value, count in enumerate(hist):
        seen += count
        if seen >= target:
            return value
    return 255


def composite_overlay(base: Image.Image, overlay: Image.Image) -> Image.Image:
    """Render a NASA science product as a readable heatmap over a dimmed base.

    Low-zoom Trek products are either dark greyscale or 8-bit colour ramps, and
    many have no-data gaps. We stretch the brightness, colourise greyscale
    products with one documented ramp, and only paint pixels that contain data.
    """
    rgb = overlay.convert("RGB")
    if rgb.size != base.size:
        rgb = rgb.resize(base.size, Image.LANCZOS)

    gray = rgb.convert("L")
    hist = gray.histogram()
    hi = max(percentile_from_hist(hist, 99.5), 12)
    gain = min(255.0 / hi, 5.0)

    data_hist = hist[8:]
    data_pixels = sum(data_hist)
    saturation = ImageStat.Stat(rgb.convert("HSV")).mean[1]
    if data_pixels and saturation < 26:  # greyscale product -> colour ramp
        colorized = ImageOps.colorize(
            rgb.convert("L"),
            black=HEAT_RAMP[0],
            mid=HEAT_RAMP[2],
            white=HEAT_RAMP[4],
        )
        rgb = Image.blend(rgb, colorized, 0.88)

    rgb = ImageEnhance.Brightness(rgb).enhance(gain)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.15)

    mask = gray.point(lambda v: 255 if v > 6 else 0)
    dimmed = Image.blend(base.convert("RGB"), Image.new("RGB", base.size, (4, 10, 24)), 0.62)
    out = dimmed.copy()
    out.paste(rgb, (0, 0), mask)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zoom-base", type=int, default=4)
    parser.add_argument("--zoom-layer", type=int, default=3)
    parser.add_argument("--only", default="", help="comma separated layer keys")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    wanted = {k.strip() for k in args.only.split(",") if k.strip()} or set(TREK_LAYERS)

    bases: dict[str, Image.Image] = {}
    for key in ("moon_base", "mars_base"):
        if key in wanted:
            body, layer, _ = TREK_LAYERS[key]
            print(f"[base] {key} zoom {args.zoom_base}")
            img = stitch(body, layer, args.zoom_base)
            if img:
                bases[key] = img
                img.convert("RGB").save(OUT / f"{key}.jpg", quality=90, optimize=True)
                print(f"  wrote {key}.jpg {img.size}")

    for key in sorted(wanted - {"moon_base", "mars_base"}):
        if not key.startswith(("moon_", "mars_")):
            continue
        body, layer, _ = TREK_LAYERS[key]
        print(f"[layer] {key} zoom {args.zoom_layer}")
        img = stitch(body, layer, args.zoom_layer)
        if not img:
            continue
        base_key = key.split("_")[0] + "_base"
        if base_key not in bases:
            body_b, layer_b, _ = TREK_LAYERS[base_key]
            bases[base_key] = stitch(body_b, layer_b, args.zoom_base)
            bases[base_key].convert("RGB").save(OUT / f"{base_key}.jpg", quality=90, optimize=True)
            print(f"  wrote {base_key}.jpg")
        composited = composite_overlay(bases[base_key], img)
        composited.save(OUT / f"{key}.jpg", quality=88, optimize=True)
        print(f"  wrote {key}.jpg {composited.size}")

    if "earth_base" in wanted:
        print("[base] earth_base (GIBS Blue Marble)")
        img = stitch_earth_base(3)
        if img:
            img.convert("RGB").save(OUT / "earth_base.jpg", quality=90, optimize=True)
            print(f"  wrote earth_base.jpg {img.size}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
