# RADIUM — Terrestrial Analog Intelligence

NASA Space Apps 2026 (Princeton) · 5-person team · interactive atlas that grades Moon and Mars
candidate sites and finds the Earth locations that behave most like them.

The challenge asks teams to use open Earth/Moon/Mars data to characterise *new* terrestrial
analogs for future lunar bases and Mars landing sites. RADIUM answers that with a globe you can
query anywhere, plus a graded shortlist on each body:

| View | What it does |
| --- | --- |
| **Moon / Mars** | 3D globe, real NASA layer switching, graded candidate sites with a full dossier |
| **Click anywhere** | click any point on the globe → local conditions sampled from mission grids → ranked Earth analogs |
| **Earth** | 2D map of 40 analog candidates across deserts, volcanic fields, impact craters, lava tubes, polar oases, salt pans and springs |
| **Earth Twin mode** | any curated site *or* clicked point → the map jumps to Earth and ranks its closest matches |

## Run it

```powershell
node serve.mjs        # http://localhost:3000
```

No build step, no API keys, no accounts. Libraries (globe.gl, Leaflet, Tailwind) and the NASA
textures are vendored under `assets/`, so the app still renders if the venue Wi-Fi dies.
The only live-network features are the optional NASA GIBS Earth layers.

Regenerate the derived data (all three scripts are keyless and idempotent):

```powershell
python tools\fetch_textures.py      # stitches NASA Trek/GIBS tiles into assets/textures/
python tools\build_grids.py         # LOLA + MOLA DEMs -> 0.5 deg terrain/temperature grids
python tools\build_earth_layers.py  # Earth temperature field + night-lights probe
python tools\fetch_earth_data.py    # NASA POWER + ETOPO1 -> assets/earth-metrics.js
python tools\fetch_site_photos.py   # Sentinel-2 mosaics + Commons photos (attributed)
python tools\build_site_thumbs.py   # Moon/Mars surface crops for each pin
python tools\merge_moon_texture.py  # blends WAC detail with the polar-filled texture
node   tools\check-data.mjs         # sanity check: scores, letters, sources, grids, twins
```

Deep links for demos: `#earth:earth_twin:connecting-ridge` opens Earth with the twin field lit up
for that Moon site; `#earth:earth_suit` opens the analog-grade field; `#mars` opens Mars; and
`#earth:earth_base:craters-of-the-moon:15` jumps straight to a site at zoom 15.

Screenshots: `node screenshot.mjs http://localhost:3000 [label]` (needs Puppeteer; set
`PUPPETEER_PATH` if it is installed outside this repo).

## Data sources

Everything is public and keyless. Three different kinds of number are used, and the UI labels
which is which.

**Measured rasters** — the switchable layers, rendered from real mission products:

| Layer | Product | Source |
| --- | --- | --- |
| Moon base | LRO WAC global mosaic (303 ppd) blended with NASA SVS LROC colour-poles texture above 66 deg | [Moon Trek](https://trek.nasa.gov/moon/) · [SVS](https://svs.gsfc.nasa.gov/4720) |
| Moon day / night temp | Diviner average surface temperature, 32 ppd | [Moon Trek](https://trek.nasa.gov/moon/) · [PDS Diviner](https://pds-geosciences.wustl.edu/missions/lro/diviner.htm) |
| Mars base | MGS MOLA colour shaded relief, 463 m | [Mars Trek](https://trek.nasa.gov/mars/) · [PDS MRO](https://pds-geosciences.wustl.edu/missions/mro/) |
| Mars colour | Viking MDIM 2.1 mosaic, 232 m | [Mars Trek](https://trek.nasa.gov/mars/) · [USGS Astrogeology](https://astrogeology.usgs.gov/) |
| Earth base | High-resolution satellite imagery (Esri World Imagery) over a cached Blue Marble fallback, zoomable to level 17 | [Esri](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9) |
| Earth boundaries | Country borders, place and water labels | Esri World Boundaries and Places |
| Earth surface temperature | **computed** IDW of the 40 NASA POWER climatologies, faded beyond 2,500 km | [NASA POWER](https://power.larc.nasa.gov/) |
| Earth analog grade field | **computed** from the eight-row rubric, follows the mission designer | this repo |
| Earth twin similarity field | **computed** similarity to the selected Moon/Mars target | this repo |

### Map pins

**Moon and Mars keep the original 3D pin system:** glowing spheres sized by grade, with a faint ring
pulse on every site, an amber pulse on the selection, and a teal pulse at a clicked point. They sit
in slight elevation steps so polar clusters separate, scale with camera distance, and use a brighter
grade palette than the flat map because they are read against grey lunar terrain.

**Earth uses teardrop markers** with the letter grade drawn inside — a flat map has room for labels
that a 3D globe does not. Each carries a deep, saturated fill (green A → darkest red F), a white
ring, soft glow and drop shadow, plus a dashed radius ring around the selection that shrinks from
120 km to 2.5 km as you zoom.

Both: clicking a pin selects that site; clicking bare surface drops the click marker and runs a point
query. On the globe that is enforced twice — the point handler suppresses the globe click, and a
globe click within 2.6° of a site is treated as a selection rather than a query.

### Site imagery (real, never generated)

Every dossier carries a **street-view style gallery** of the actual place.

| Body | Gallery contents | Source |
| --- | --- | --- |
| Moon | 0.5° surface crop at the pin | LRO WAC mosaic (NASA Moon Trek) |
| Mars | 0.5° surface crop at the pin | Viking MDIM 2.1 (NASA Mars Trek) |
| Earth | 1–6 **ground photographs** of the site | Wikimedia Commons, author + licence per image |
| Earth | plus one Sentinel-2 orbital mosaic for context | EOX (CC BY 4.0) |

Open it with the **Street View** button in the dossier (or click the preview image / any
thumbnail). The viewer shows the full frame with a type badge (`ground view` vs `orbital mosaic`),
previous/next arrows, a thumbnail strip, per-image credit and licence, and ←/→ keyboard support.
A "Google pano ↗" button is still there for the minority of sites where Google has a panorama.

Coverage: **40/40 sites have imagery, 192 ground photographs** across the catalogue
(38 sites have 3–6 photos; only Bunger Hills and Mistastin are sparse).

`tools/fetch_site_photos.py` downloads mosaics and photos into `assets/photos/` with a manifest of
authors and licences, so the demo works offline. Candidate selection matters more than volume:

- photos come from Commons **categories** for the place first, then geosearch within 10 km, then text search;
- facilities (housing, roads, signage, museums), flora/fauna close-ups and scanned archival photos are
  filtered or down-ranked, as are *Flora of…* / *Fauna of…* categories;
- if a site has three or more terrain-titled photos, non-terrain photos are dropped entirely;
- repeated subjects are collapsed, with a second pass only for sparse sites;
- orbital images are detected and labelled instead of masquerading as ground views.

> NASA's daily MODIS land-surface-temperature and VIIRS night-lights GIBS layers are clear-sky /
> lights-only products (16% and 0.3% opaque pixels at low zoom), so they render as dust on a dark
> map. RADIUM therefore computes complete fields from the measured site climatologies instead of
> shipping a layer that looks broken.

**Computed point values** — every Earth pin is calculated, not typed in:
`tools/fetch_earth_data.py` pulls the NASA POWER 2001–2020 climatology (temperature, pressure,
wind, humidity, precipitation, solar) and samples NOAA ETOPO1 at five points to derive elevation,
slope and roughness.

**Point queries (click anywhere)** — `tools/build_grids.py` downsamples two real PDS digital
elevation models to a 720×360 (0.5°) grid and derives slope and local relief from them:

| Grid | Source | Measured or modelled |
| --- | --- | --- |
| Moon elevation / slope / roughness | LOLA `LDEM_4` (4 ppd, int16) | measured |
| Mars elevation / slope / roughness | MOLA MEGDR (16 ppd, int16) | measured |
| Moon day / night temperature | latitude regression on 10 published site temperatures | **modelled** (±8 K / ±10 K) |
| Mars day / night temperature | latitude + elevation regression on 12 published sites | **modelled** (±5 K / ±4 K) |

Clicking the globe samples those PNG grids client-side. Water ice, dust and comms geometry are not
resolved at 0.5°, so a point match uses only temperature, day/night swing, slope and roughness, and
the dossier says so instead of inventing values.

**Compiled estimates** — the curated Moon/Mars dossiers and the ice/dust/subsurface indices are
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
assets/photos/             real site imagery: Sentinel-2 mosaics, Commons photos, Moon/Mars crops
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

1. Replace the modelled temperature grids with Diviner / THEMIS gridded products once a clean
   global file is downloaded (the 0.5° sampler and UI already accept a swapped PNG + meta).
2. Add a high-resolution DEM terrain mesh so slope is visible on the globe itself.
3. Let point queries also return nearest *curated* sites and show both in one ranked list.
4. Add photos per dossier (NASA image API) and a printable report view for the "share findings" objective.

## Attribution

NASA Moon Trek / Mars Trek / GIBS / POWER, USGS Astrogeology, NOAA ETOPO1, ESA and JAXA products
referenced in the Data & method dialog. These are public mission products — check each provider's
usage terms before republishing derived imagery.
