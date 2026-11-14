# RADIUM — Terrestrial Analog Intelligence

NASA Space Apps 2026 (Princeton) · 5-person team · interactive atlas that grades Moon and Mars
candidate sites and finds the Earth locations that behave most like them.

The challenge asks teams to use open Earth/Moon/Mars data to characterise *new* terrestrial
analogs for future lunar bases and Mars landing sites. RADIUM answers that with three linked views:

| View | What it does |
| --- | --- |
| **Moon / Mars** | 3D globe, real NASA layer switching, graded candidate sites with a full dossier |
| **Earth** | 2D map of 18 analog candidates, each scored from real climate + terrain data |
| **Earth Twin mode** | click any Moon/Mars site → the map jumps to Earth and ranks its closest matches |

## Run it

```powershell
node serve.mjs        # http://localhost:3000
```

No build step, no API keys, no accounts. Libraries (globe.gl, Leaflet, Tailwind) and the NASA
textures are vendored under `assets/`, so the app still renders if the venue Wi-Fi dies.
The only live-network features are the optional NASA GIBS Earth layers.

Regenerate the derived data (both scripts are keyless and idempotent):

```powershell
python tools\fetch_textures.py     # stitches NASA Trek/GIBS tiles into assets/textures/
python tools\fetch_earth_data.py   # NASA POWER + ETOPO1 -> assets/earth-metrics.js
node   tools\check-data.mjs        # sanity check: scores, letters, sources, twin sanity
```

Screenshots: `node screenshot.mjs http://localhost:3000 [label]` (needs Puppeteer; set
`PUPPETEER_PATH` if it is installed outside this repo).

## Data sources

Everything is public and keyless. Three different kinds of number are used, and the UI labels
which is which.

**Measured rasters** — the switchable layers, rendered from real mission products:

| Layer | Product | Source |
| --- | --- | --- |
| Moon base | LRO WAC global mosaic, 303 ppd | [Moon Trek](https://trek.nasa.gov/moon/) |
| Moon day / night temp | Diviner average surface temperature, 32 ppd | [Moon Trek](https://trek.nasa.gov/moon/) · [PDS Diviner](https://pds-geosciences.wustl.edu/missions/lro/diviner.htm) |
| Mars base | MGS MOLA colour shaded relief, 463 m | [Mars Trek](https://trek.nasa.gov/mars/) · [PDS MRO](https://pds-geosciences.wustl.edu/missions/mro/) |
| Mars colour | Viking MDIM 2.1 mosaic, 232 m | [Mars Trek](https://trek.nasa.gov/mars/) · [USGS Astrogeology](https://astrogeology.usgs.gov/) |
| Earth base | Blue Marble + bathymetry | [NASA GIBS](https://gibs.earthdata.nasa.gov/) (live tiles + cached fallback) |
| Earth surface temp | MODIS Terra land surface temperature, 2024-07-01 | [NASA GIBS](https://gibs.earthdata.nasa.gov/) |
| Earth night lights | VIIRS Black Marble | [NASA GIBS](https://gibs.earthdata.nasa.gov/) |

**Computed point values** — every Earth pin is calculated, not typed in:
`tools/fetch_earth_data.py` pulls the NASA POWER 2001–2020 climatology (temperature, pressure,
wind, humidity, precipitation, solar) and samples NOAA ETOPO1 at five points to derive elevation,
slope and roughness.

**Compiled estimates** — Moon/Mars site metrics and the ice/dust/subsurface indices are
literature-derived regional estimates. Each dossier shows a confidence tag and a citation, and
`assets/data/*-sites.js` holds the raw numbers so they can be replaced with in-situ values.

Known caveats: POWER is 0.5° grid-cell climatology (summit sites read warmer than station data);
Moon/Mars values are regional not in-situ; atmosphere is deliberately excluded from the Earth Twin
similarity because nothing on Earth reproduces a vacuum or ~0.6 kPa.

## Scoring

Eight rubric rows (geology, terrain, thermal, water, dust, habitability, subsurface, operations) are
closed-form functions of the measurements in `assets/scoring.js`. The weighted mean is the
suitability score; letters map to A ≥ 70, B ≥ 62, C ≥ 54, D ≥ 46, E ≥ 38, otherwise F. The mission
designer only changes the weights, so every re-grade is explainable.

Earth Twin similarity is a weighted normalised distance over temperature, day/night swing, solar,
slope, roughness, water/ice and dust, reported 0–100.

Sanity check that the metric reproduces expert judgment: the best twin for *Connecting Ridge* comes
out as Haughton Crater / University Valley, both long-standing NASA analog sites.

## Layout

```
index.html                 page shell + dialogs
assets/app.js              view controller (globe, Earth map, dossiers, twin mode)
assets/scoring.js          rubric + similarity + data normalisation
assets/app.css             design tokens and component styles
assets/data/               curated Moon / Mars / Earth site records
assets/earth-metrics.js    generated from NASA POWER + ETOPO1
assets/textures/           stitched NASA raster layers (offline fallback)
assets/vendor/             globe.gl, Leaflet, Tailwind, display font
tools/                     data + texture pipelines, sanity check
serve.mjs                  static server (:3000)
screenshot.mjs             Puppeteer screenshot helper
```

## Suggested team split

| Owner | Scope |
| --- | --- |
| Data lead | Re-derive Moon/Mars point values from LOLA/Diviner/MOLA products; fill gaps in `assets/data/*.js` |
| Frontend A | Globe interaction, camera framing, site markers, mobile layout |
| Frontend B | Dossier panel, mission designer, Earth Twin comparison view |
| Earth analyst | Add sites, extend `tools/fetch_earth_data.py`, verify terrain metrics |
| Story/demo | Problem framing, judging narrative, live demo script, backup recording |

## Next steps (pick by impact)

1. Replace Moon/Mars compiled estimates with values sampled from LOLA/Diviner/MOLA rasters.
2. Add a high-resolution DEM terrain layer so slope readouts are visible on the globe itself.
3. Rank the Earth list by *analog similarity* once a Moon/Mars site is selected (already wired for twin mode).
4. Add photos per dossier (NASA image API) and a printable report view for the "share findings" objective.

## Attribution

NASA Moon Trek / Mars Trek / GIBS / POWER, USGS Astrogeology, NOAA ETOPO1, ESA and JAXA products
referenced in the Data & method dialog. These are public mission products — check each provider's
usage terms before republishing derived imagery.
