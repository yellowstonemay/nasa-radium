"""Derive real Earth measurements for every candidate analog site.

Sources (both keyless, public):
  * NASA POWER climatology API  -> temperature, pressure, wind, humidity, rain, solar
  * OpenTopoData ETOPO1 (NOAA)  -> elevation, plus slope/roughness from a 5-point sample

Writes assets/earth-metrics.js so the page can load it with a plain <script> tag.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "earth-metrics.js"

POWER = "https://power.larc.nasa.gov/api/temporal/climatology/point"
PARAMS = "T2M,T2M_MAX,T2M_MIN,PS,WS2M,RH2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN"
ETOPO = "https://api.opentopodata.org/v1/etopo1"

# id: (lat, lon) - keep in sync with assets/sites.js
SITES = {
    "yungay": (-24.10, -70.00),
    "haughton": (75.43, -89.85),
    "university-valley": (-77.75, 160.70),
    "dry-valleys": (-77.63, 162.90),
    "death-valley": (36.25, -116.80),
    "mauna-kea": (19.82, -155.47),
    "kilauea": (19.41, -155.28),
    "craters-of-the-moon": (43.46, -113.56),
    "uyuni": (-20.13, -67.49),
    "qaidam": (38.50, 93.30),
    "lut": (30.50, 58.70),
    "dallol": (14.24, 40.30),
    "wadi-rum": (29.58, 35.42),
    "ojos-del-salado": (-27.11, -68.54),
    "rio-tinto": (37.69, -6.55),
    "gypsum-hill": (79.40, -90.80),
    "lakagigar": (63.90, -19.00),
    "bockfjorden": (79.80, 13.30),
    "teide": (28.27, -16.64),
    "timanfaya": (29.03, -13.63),
    "erta-ale": (13.60, 40.67),
    "sossusvlei": (-24.73, 15.29),
    "mdrs": (38.41, -110.79),
    "lunar-crater-nv": (38.13, -116.06),
    "meteor-crater": (35.03, -111.02),
    "bonneville": (40.75, -113.85),
    "white-sands": (32.79, -106.33),
    "mono-lake": (37.99, -119.01),
    "pinacate": (31.77, -113.44),
    "cuatrocienegas": (26.99, -102.06),
    "strelley-pool": (-21.30, 119.60),
    "kati-thanda": (-28.40, 137.30),
    "bunger-hills": (-66.30, 100.80),
    "don-juan-pond": (-77.57, 161.17),
    "askja": (65.03, -16.75),
    "tolbachik": (55.83, 160.33),
    "aral-sea-bed": (45.00, 59.00),
    "dash-e-kavir": (34.50, 54.00),
    "mistastin": (55.88, -63.31),
    "sechura": (-5.60, -80.40),
}


def get_json(url: str, tries: int = 4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RADIUM-hackathon/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001
            if attempt == tries - 1:
                raise
            print(f"    retry {attempt + 1}: {exc}")
            time.sleep(3 * (attempt + 1))
    return None


def power_climatology(lat: float, lon: float) -> dict:
    query = urllib.parse.urlencode(
        {
            "parameters": PARAMS,
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "format": "JSON",
            "start": 2001,
            "end": 2020,
        }
    )
    data = get_json(f"{POWER}?{query}")
    params = data["properties"]["parameter"]
    return {k: round(float(v["ANN"]), 2) for k, v in params.items()}


def elevation_grid(lat: float, lon: float, offset: float = 0.01) -> list[float]:
    pts = [
        (lat, lon),
        (lat + offset, lon),
        (lat - offset, lon),
        (lat, lon + offset),
        (lat, lon - offset),
    ]
    locs = "|".join(f"{p[0]:.4f},{p[1]:.4f}" for p in pts)
    data = get_json(f"{ETOPO}?locations={locs}")
    return [float(r["elevation"]) for r in data["results"]]


def terrain_stats(elevs: list[float], spacing_m: float = 1110.0) -> tuple[float, float]:
    """Return slope in degrees and roughness as std-dev of relief samples."""
    center, north, south, east, west = elevs
    dlat = (north - south) / (2 * spacing_m)
    dlon = (east - west) / (2 * spacing_m)
    slope = math.degrees(math.atan(math.hypot(dlat, dlon)))
    mean = sum(elevs) / len(elevs)
    var = sum((e - mean) ** 2 for e in elevs) / len(elevs)
    return round(slope, 2), round(math.sqrt(var), 1)


def main() -> int:
    out: dict[str, dict] = {}
    for site_id, (lat, lon) in SITES.items():
        print(f"[earth] {site_id}", flush=True)
        try:
            climate = power_climatology(lat, lon)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! POWER failed: {exc}")
            continue
        time.sleep(1.2)
        try:
            elevs = elevation_grid(lat, lon)
            slope, roughness = terrain_stats(elevs)
            elevation = round(elevs[0], 1)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! ETOPO failed: {exc}")
            elevs, slope, roughness, elevation = [], None, None, None
        time.sleep(1.2)

        out[site_id] = {
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
            "provenance": {
                "climate": "NASA POWER climatology 2001-2020 (MERRA-2 / CERES)",
                "terrain": "NOAA ETOPO1 1 arc-minute via OpenTopoData (5-point sample)",
            },
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = "window.RADIUM_EARTH = " + json.dumps(out, indent=2) + ";\n"
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} ({len(out)} sites)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
