"""Build the Moon's globe texture: LRO WAC detail with repaired polar caps.

The LRO WAC equirectangular mosaic carries the detail, but its polar rows are
striped. Each polar orbit track maps to a meridian, so the mosaic shows a
per-longitude gain that fans out into a pinwheel wherever the tracks converge.
NASA's own SVS "LROC colour poles" texture has full polar coverage, but it is
blurred above about 80 degrees and exposed about twice as bright. Swapping it
in wholesale - which is what this script used to do from 66 degrees - turned
the pole into a smooth bright disc, and since every candidate site is polar
that disc was the first thing the app showed.

So this builds the texture the other way round: destripe the WAC caps (divide
out the per-meridian gain), then use the SVS texture only where WAC has no
data, tone-matched to the WAC exposure. Detail is kept everywhere WAC has it,
the fill is invisible, and neither cap is brighter than the equator.

Usage: python tools/merge_moon_texture.py
Then:  python tools/build_moon_temp_textures.py   (the temp layers sit on top)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
TEX = ROOT / "assets" / "textures"

DETAIL = TEX / "moon_base.jpg"          # LRO WAC mosaic, high detail
POLES = TEX / "moon_lroc_poles.jpg"     # SVS texture with polar fill
OUT = TEX / "moon_surface.jpg"

# Where the per-meridian gain is measured, and where it starts to be removed.
STRIPE_BAND = 60.0                      # degrees of latitude
STRIPE_FADE = (54.0, 68.0)
STRIPE_SIGMA = 110.0                    # px of longitude used as the baseline
STRIPE_CLAMP = (0.70, 1.42)

# SVS takes over where WAC has no data, and carries the whole cap from here in.
HOLE = 10.0                             # pixel value below which WAC has no data
HOLE_FEATHER = 30                       # px of blur on the hole mask - a hard
                                        # edge here shows as a rectangle on the globe
HOLE_MIN_LAT = 42.0                     # do not chase holes away from the caps
CAP_FADE = (46.0, 64.0)                 # latitude ramp from WAC to the smooth cap
SVS_CORE = 80.0                         # degrees: holes are always filled inside

# Detail injection. The SVS cap is smooth and complete, the WAC cap is detailed
# but seamed by its orbit tracks; a high-pass of the WAC added to the SVS keeps
# the craters and drops the long spokes.
DETAIL_SIGMA = 5.0
DETAIL_GAIN = 1.15

# Near the pole the orbit tracks close into rings, and their seams survive the
# per-meridian destriping as fine concentric banding. A light isotropic blur,
# faded in with latitude, removes it without touching crater-scale structure.
POLAR_BLUR = (82.0, 89.0, 1.3)          # fade start, full strength, sigma px


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def circular_blur(profile: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur along the last axis, wrapping - longitudes are a circle."""
    radius = int(3 * sigma)
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.concatenate([profile[-radius:], profile, profile[:radius]])
    return np.convolve(padded, kernel, mode="same")[radius:-radius]


def destripe(image: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Divide out the per-meridian gain that polar orbit tracks leave behind."""
    magnitude = np.abs(lat)
    fade = smoothstep(STRIPE_FADE[0], STRIPE_FADE[1], magnitude)
    band = magnitude >= STRIPE_BAND
    log_image = np.log(np.clip(image, 1.0, None))
    # One gain per longitude, measured over the whole cap: the tracks run the
    # full meridian, so their signature is constant down the column.
    profile = log_image[band].mean(axis=0)
    gain = np.exp(profile - circular_blur(profile, STRIPE_SIGMA))
    gain = np.clip(gain, *STRIPE_CLAMP)
    effective = 1.0 + (gain - 1.0) * fade[:, None]
    return image / effective


def match_rows(source: np.ndarray, reference: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Put `source` on `reference`'s exposure.

    One gain, measured on the rows where the reference is nearly complete: SVS
    is exposed about twice as bright, and it also runs brighter toward the
    poles, so per-row fits tempt you into chasing a profile that the reference
    cannot support where it has holes (the whole north cap). A single gain
    leaves the source's own latitude gradient - which is real terrain - and
    removes only the product bias.
    """
    rows = source.shape[0]
    samples = []
    for r in range(rows):
        row_valid = valid[r]
        if row_valid.mean() < 0.9:
            continue
        off = np.median(source[r])
        if off > 1.0:
            samples.append(np.median(reference[r][row_valid]) / off)
    gain = float(np.median(samples)) if samples else 0.5
    return source * gain


def polar_smooth(image: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Fade in a light blur near the poles, where orbit seams ring the pole."""
    start, full, sigma = POLAR_BLUR
    blended = np.asarray(
        Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(sigma)
        ),
        dtype=np.float32,
    )
    weight = smoothstep(start, full, np.abs(lat))[:, None]
    return image * (1.0 - weight) + blended * weight


def main() -> int:
    detail = Image.open(DETAIL).convert("L")
    poles = Image.open(POLES).convert("L").resize(detail.size, Image.LANCZOS)

    a = np.asarray(detail, dtype=np.float32)
    b = np.asarray(poles, dtype=np.float32)
    rows, cols = a.shape
    lat = 90.0 - (np.arange(rows) + 0.5) * (180.0 / rows)
    magnitude = np.abs(lat)

    wac = destripe(a, lat)

    # SVS carries the same terrain on a different exposure - and it runs a
    # fifth brighter toward the poles, which is exactly the bright cap this is
    # trying to avoid. Row-wise matching removes the product bias and keeps the
    # latitude profile of the mosaic it is joining.
    b = np.clip(match_rows(b, wac, a > HOLE), 0, 255)

    # Inject the WAC's fine structure into the smooth cap: craters survive, the
    # orbit spokes (which live at lower frequency) do not. The high-pass has to
    # ignore the no-data holes - a black streak is not terrain, and letting it
    # through would sprinkle the fill with dark speckles - so it runs as a
    # normalised convolution and is switched off inside the holes.
    valid_mask = (a > HOLE).astype(np.float32)
    cover = np.asarray(
        Image.fromarray((valid_mask * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(DETAIL_SIGMA)
        ),
        dtype=np.float32,
    ) / 255.0
    weighted = np.asarray(
        Image.fromarray(np.clip(wac * valid_mask, 0, 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(DETAIL_SIGMA)
        ),
        dtype=np.float32,
    )
    local = weighted / np.maximum(cover, 0.02)
    detail = (wac - local) * np.clip(cover * 1.6, 0.0, 1.0)
    fill = np.clip(b + DETAIL_GAIN * detail, 0, 255)

    # Blend: WAC gives the mid-latitudes, the smooth cap composited with the
    # WAC's high-passed detail takes over across the polar caps. A hole in the
    # WAC - there are a few wedges and tracks near both poles - is filled
    # outright, so no black slice ever reaches the globe.
    cap = smoothstep(CAP_FADE[0], CAP_FADE[1], magnitude)[:, None]
    gap = (a <= HOLE) & (magnitude[:, None] >= HOLE_MIN_LAT)
    core = smoothstep(SVS_CORE - 3.0, SVS_CORE + 3.0, magnitude)[:, None]
    weight = np.clip(np.maximum(cap, np.maximum(gap.astype(np.float32), core)), 0.0, 1.0)
    weight = np.asarray(
        Image.fromarray((weight * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(HOLE_FEATHER)
        ),
        dtype=np.float32,
    ) / 255.0

    merged = wac * (1.0 - weight) + fill * weight
    merged = polar_smooth(merged, lat)
    # Soft-knee the top end: the bright ray systems stay bright without a
    # handful of pure-white pixels that the render then blows out.
    t = np.clip(merged, 0, 255) / 255.0
    knee = 0.82
    over = t > knee
    t[over] = knee + (1.0 - knee) * (
        1.0 - np.exp(-(t[over] - knee) / (1.0 - knee))
    ) / (1.0 - np.exp(-1.0))
    merged = t * 255.0

    image = Image.fromarray(np.clip(merged, 0, 255).astype(np.uint8), mode="L").convert("RGB")
    image.save(OUT, quality=90, optimize=True)

    grey = np.asarray(image.convert("L"), dtype=np.float32)
    print(f"wrote {OUT.name} {OUT.stat().st_size // 1024} KB  ({cols}x{rows})")
    print("  overall     mean %6.1f  p50 %5.1f  p99 %6.1f  max %5.0f" % (
        grey.mean(), np.median(grey), np.percentile(grey, 99), grey.max()))
    for label, lo, hi in (
        ("north cap", 0, 40), ("70-80N", 20, 90), ("equator", 1000, 1060),
        ("70-80S", rows - 90, rows - 20), ("south cap", rows - 40, rows),
    ):
        band = grey[lo:hi]
        print("  %-11s mean %6.1f  p50 %5.1f  std %5.1f" % (
            label, band.mean(), np.median(band), band.std()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
