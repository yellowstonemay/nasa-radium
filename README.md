# RADIUM — Terrestrial Analog Intelligence

NASA Space Apps 2026 (Princeton) · 5-person team · interactive atlas that grades Moon and Mars
candidate sites and finds the Earth locations that behave most like them.

The challenge asks teams to use open Earth/Moon/Mars data to characterise *new* terrestrial
analogs for future lunar bases and Mars landing sites. RADIUM answers that with a globe you can
query anywhere, plus a graded shortlist on each body:

| View | What it does |
| --- | --- |
| **Moon / Mars** | 3D globe, real NASA layer switching, graded candidate sites with a full dossier ? 25 lunar sites from the 13 Artemis III regions to far-side science targets, and 24 martian sites from Jezero to the shallow-ice belts |
| **Click anywhere** | click any point on the globe → local conditions sampled from mission grids → ranked Earth analogs, searched across **both** shortlists (40 curated + 39 discovered) |
| **Grade any point** | click any point on the *Earth* map → that coordinate is graded A–F on the same rubric (plus the Earth-only open-land row), from shipped WorldClim / AWS Terrain / MODIS rasters, and shows what it resembles on the Moon and Mars |
| **Earth** | 2D map of 40 analog candidates across deserts, volcanic fields, impact craters, lava tubes, polar oases, salt pans and springs |
| **Discovered** | the 40 curated sites stay published work; a separate switch shows 39 *new* candidates found by a global screen of every quarter-degree land cell |
| **Earth Twin mode** | any site or clicked point → the map jumps to Earth and ranks its closest matches from both shortlists; discovered hits are tagged `screened` and keep their dashed pin. The button and the match rows in a Moon or Mars dossier both enter the mode, with that match already selected |

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
python tools\build_moon_candidates.py # appends the expanded lunar candidate set (idempotent)
python tools\build_mars_candidates.py # appends the expanded martian candidate set (idempotent)
python tools\build_earth_layers.py  # Earth temperature field + night-lights probe
python tools\fetch_earth_data.py    # NASA POWER + ETOPO1 -> assets/earth-metrics.js
python tools\fetch_site_photos.py   # Sentinel-2 mosaics + Commons photos (attributed)
python tools\build_site_thumbs.py   # Moon/Mars surface crops for each pin
python tools\merge_moon_texture.py  # blends WAC detail with the polar-filled texture
python tools\build_moon_temp_textures.py # renders the day/night temperature globe textures
node   tools\check-data.mjs         # sanity check: scores, letters, sources, grids, twins
python tools\build_prospect_scan.py # global screen -> assets/grids/earth-prospect.png + data/prospect-sites.js
python tools\build_prospect_scan.py --rasters-only # terrain/climate rasters used by the Earth point grade
python tools\build_land_use.py      # MODIS land cover -> open-land, snow/ice, barren, green rasters
python tools\build_earth_atmosphere.py # sunlight + surface pressure rasters
```

Deep links for demos: `#earth:earth_twin:connecting-ridge` opens Earth with the twin field lit up
for that Moon site; `#earth:earth_suit` opens the analog-grade field; `#earth:earth_prospect` opens
the global screening field; `#earth:earth_base:prospect-01:8` jumps to a discovered candidate; `#mars`
opens Mars; and `#earth:earth_base:craters-of-the-moon:15` jumps straight to a curated site at zoom 15.

Screenshots: `node screenshot.mjs http://localhost:3000 [label]` (needs Puppeteer; set
`PUPPETEER_PATH` if it is installed outside this repo).

## Data sources

Everything is public and keyless. Three different kinds of number are used, and the UI labels
which is which.

**Measured rasters** — the switchable layers, rendered from real mission products:

| Layer | Product | Source |
| --- | --- | --- |
| Moon base | LRO WAC global mosaic (303 ppd) blended with NASA SVS LROC colour-poles texture above 66 deg | [Moon Trek](https://trek.nasa.gov/moon/) · [SVS](https://svs.gsfc.nasa.gov/4720) |
| Moon day / night temp | **modelled** isotonic latitude fit to Diviner site climatology, rendered over the LRO WAC mosaic | [PDS Diviner](https://pds-geosciences.wustl.edu/missions/lro/diviner.htm) · [Moon Trek](https://trek.nasa.gov/moon/) |
| Mars base | MGS MOLA colour shaded relief, 463 m | [Mars Trek](https://trek.nasa.gov/mars/) · [PDS MRO](https://pds-geosciences.wustl.edu/missions/mro/) |
| Mars colour | Viking MDIM 2.1 mosaic, 232 m | [Mars Trek](https://trek.nasa.gov/mars/) · [USGS Astrogeology](https://astrogeology.usgs.gov/) |
| Earth base | Three interchangeable base maps: Sentinel-2 cloudless (default, ~10 m), NASA Blue Marble, Esri World Imagery (sharp to zoom 17), all over a cached offline fallback | [EOX](https://s2maps.eu/) ? [GIBS](https://worldview.earthdata.nasa.gov/) ? [Esri](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9) |
| Earth boundaries | Country borders, place and water labels | Esri World Boundaries and Places |
| Earth heat map | WorldClim 2.1 `bio_1` annual mean air temperature, 10 arc-minute, land only | [WorldClim](https://www.worldclim.org/data/worldclim21.html) |
| Earth slope, roughness, warmest/coldest month, precipitation | WorldClim 2.1 bio and AWS terrain, shipped as 0.25 degree rasters | [WorldClim](https://www.worldclim.org/data/worldclim21.html) · [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) |
| Snow/ice, barren, green cover | MODIS IGBP land cover area shares via NASA GIBS | [GIBS](https://earthdata.nasa.gov/gibs) |
| Sunlight, surface pressure | POWER site means blended with latitude; barometric pressure from elevation | [POWER](https://power.larc.nasa.gov/) · this repo |
| Earth elevation | **computed** 0.25 degree cell means of the AWS terrain tiles | [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) |
| Earth analog grade field | **computed** from the rubric (nine rows on Earth, eight elsewhere), follows the mission designer | this repo |
| Earth twin similarity field | **computed** similarity to the selected Moon/Mars target | this repo |
| Earth prospect scan | **computed** 0.25° global screening of every land cell against the analog envelope | [AWS terrain](https://registry.opendata.aws/terrain-tiles/) · [WorldClim](https://www.worldclim.org/data/worldclim21.html) · [Natural Earth](https://www.naturalearthdata.com/) |

### Map layer panel

The Earth map keeps its controls **inside the map**: two compact pills in the top-right corner
(`Satellite ?`, `Layer ?`) plus a `Boundaries` toggle. Each pill opens a small popover ? nothing is
permanently covering the map, and the popover disappears the moment you pick something (click away
or press Esc to dismiss). One **satellite view** sits underneath, one **data layer** on top, with an
opacity slider and a `Turn off` action inside the data popover.

| Group | Options |
| --- | --- |
| Satellite view | Sentinel-2 cloudless (default) · Blue Marble · Esri World Imagery |
| Terrain | Elevation · Typical slope · Roughness |
| Surface temperature | Annual mean temperature · Warmest month · Coldest month |
| Sunlight and energy | Sunlight at the surface (modelled) |
| Water and ice | Precipitation · Permanent snow and ice |
| Atmosphere and dust | Surface pressure (barometric) |
| Surface cover | Open land · Barren ground · Green cover |
| Analysis | Analog grade field (default) · Twin similarity · Prospect scan |
| Overlays | Boundaries and place labels |

Sixteen data layers, each declaring its raster, ramp and units in the layer list so the menu, the
legend and the colouriser cannot drift apart. Twelve of them are shipped 8-bit rasters sampled from
the same pipeline the point grader uses:

| Layer | Source | Kind |
| --- | --- | --- |
| Elevation, slope, roughness | AWS Terrain Tiles, slope computed at native resolution | measured |
| Annual mean / warmest month / coldest month temperature | WorldClim 2.1 `bio_1`, `bio_5`, `bio_6` | measured |
| Precipitation | WorldClim 2.1 `bio_12` / 365 | measured |
| Permanent snow and ice (class 15 share), barren ground (16), green cover (forest + shrub + savanna + grass + cropland) | MODIS IGBP land cover via GIBS, area-share binned | measured |
| Sunlight at the surface | NASA POWER means at the 79 catalogued sites blended with a clear-sky latitude term | **modelled** |
| Surface pressure | standard atmosphere applied to the elevation grid | **modelled** |

All data layers draw through **one ramp family** (deep violet at the low end, teal and lime
through the middle, amber at the top) so they read as the same instrument, and each carries a legend
with its real value range. Opacity is 86% by default, and every valid raster pixel gets full alpha so
a physical layer is unmistakable under the imagery; the opacity slider is the control. Rasters ship as 8-bit masks and are colourised in the
browser, so the ramp, the opacity slider and the legend always agree. Every Earth raster and generated field is
square (1440x1440) and resampled onto **Web Mercator rows**, because Leaflet paints an image overlay
as a single quad: shipping equirectangular data put the 30 N row at 50 N on screen (a 20 degree
drift, visible as the warm belt sitting over Canada). The two interpolated fields (grade, twin) are
computed at 1440x720 with a 1,300 km fade radius, which keeps them as local halos around measured
sites instead of washing out whole continents.

### Map pins

**Moon and Mars use projected survey pins.** Each site is drawn as three parts: a small glowing dot
on the exact ground point, a hairline leader, and a neon grade chip in the same letter style as the
rail. The pins are DOM elements anchored to the sphere, so they keep the physics that made the old
3D points readable — they rotate with the body and fade out as their ground point passes behind the
limb — without the solid cylinders that used to render as coloured bars at the limb.

Three details keep 25 densely-packed polar sites legible:

* **Fan placement.** The best-ranked pin takes the slot straight above its dot; each pin after it
  takes the nearest free slot sideways or a row higher, and the leader line is redrawn to follow.
  Pins that cannot fit fold their chip away but keep the dot, so every location stays marked.
* **Scale with zoom.** Chips shrink as the camera pulls back and grow as you close in, and the fan is
  re-solved after every camera move (throttled to 70 ms).
* **Name plate.** The selected pin wears its site name beside its chip, placed on whichever side is
  free; hovering any dot (including a folded one) reveals its chip.

The amber ring pulse marks the selection and a teal pulse marks a clicked point.

**Earth uses teardrop markers** with the letter grade drawn inside — a flat map has room for labels
that a 3D globe does not. Each carries a deep, saturated fill (green A → darkest red F), a white
ring, soft glow and drop shadow, plus a dashed radius ring around the selection that shrinks from
120 km to 2.5 km as you zoom.

Both: clicking a pin selects that site; clicking bare surface drops the click marker and runs a point
query. On the globe that is enforced twice — the point handler suppresses the globe click, and a
globe click within 2.6° of a site is treated as a selection rather than a query. Both stages also
carry a **zoom stepper** at the bottom right: Leaflet's own control on Earth, and a matching
`+ / −` group that walks the globe camera in fixed altitude ratios (0.45–5.6 globe radii) and
disables itself at either limit.

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

Coverage: **39/40 sites have imagery, 186 ground photographs** across the catalogue
(37 sites have 3–6 photos; Bunger Hills and Mistastin are sparse). University Valley has no
verifiable open-licence photography — Commons text search only returned unrelated *Valley …
University* campuses — so it is intentionally blank rather than showing the wrong place. The
pipeline now skips it and rejects blank polar satellite mosaics.

`tools/fetch_site_photos.py` downloads mosaics and photos into `assets/photos/` with a manifest of
authors and licences, so the demo works offline. Candidate selection matters more than volume:

- photos come from Commons **categories** for the place first, then geosearch within 10 km, then text search;
- facilities (housing, roads, signage, museums), flora/fauna close-ups and scanned archival photos are
  filtered or down-ranked, as are *Flora of…* / *Fauna of…* categories;
- institutional words (*university*, *college*, *campus*) are blocked, and sites in `NO_PHOTO_SITES`
  are skipped outright — no imagery beats imagery of the wrong place;
- if a site has three or more terrain-titled photos, non-terrain photos are dropped entirely;
- repeated subjects are collapsed, with a second pass only for sparse sites;
- orbital images are detected and labelled instead of masquerading as ground views.

> Moon Trek's Diviner colour product publishes only 24 of 32 tiles at its deepest zoom (z3, nothing
> at z4+), which stitched into a black northern cap, an equatorial seam and vertical no-data streaks.
> RADIUM therefore renders the temperature *grid* it already fits from that climatology, modulated by
> the real LRO WAC mosaic, so the layer is complete and seamless at 2048x1024. The earlier stitch is
> gone: the temperature textures also dropped from 2.5 MB of JPEG each to about 0.2-0.3 MB, which is
> what was stalling the layer switch.
>
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
| Moon day / night temperature | isotonic latitude fit (monotone in \|lat\|) on 10 published Diviner site temperatures | **modelled** (±8.1 K / ±11.8 K) |
| Mars day / night temperature | latitude + elevation regression on the 12 hand-curated sites | **modelled** (±5 K / ±4 K) |

Clicking the globe samples those PNG grids client-side. Water ice, dust and comms geometry are not
resolved at 0.5°, so a point match uses only temperature, day/night swing, slope and roughness, and
the dossier says so instead of inventing values.

**Earth point grade (click anywhere on the flat map)** — the same idea in reverse: instead of asking
"which Earth places match this Moon point", a click asks "how suitable is *this* Earth place". No
request leaves the browser, so it works with the venue wifi down:

| Field | Source | Kind |
| --- | --- | --- |
| Elevation | AWS Terrain Tiles, 0.25° cell means | measured |
| Slope, local relief | computed at native DEM resolution, averaged per cell | measured |
| Mean / max / min temperature | WorldClim 2.1 bio_1 / bio_5 / bio_6 | measured |
| Precipitation | WorldClim 2.1 bio_12 / 365 | measured |
| Open land + land cover class | MODIS IGBP land cover (annual, 500 m) via GIBS | measured |
| Solar, humidity, wind, pressure | inverse distance from the 4 nearest POWER-measured points | **estimated** |
| Water, dust, science, cave access, biosignature | inverse distance from the 4 nearest *curated* analogs | **estimated** |

`tools/build_prospect_scan.py --rasters-only` emits those seven fields as masked 1440×1440 mercator
rasters (0 means no data, so oceans and ice sheets are honestly blank). Two pools are kept separate
on purpose: physical climate is interpolated from any surveyed point, but the qualitative rows only
exist as team judgements on the 40 catalogued analogs, so they are interpolated from those alone —
otherwise a screened candidate's derived "science" score would leak into every nearby click.

The result is the same rubric (nine rows on Earth) and the same A–F letters as the curated sites, gated by candidate fit, plus two context numbers: how many of the 40 curated analogs it outranks, and the analog-screen score at that cell. Fields and rows that are estimated are marked `*`, and since similarity is
symmetric the dossier also lists the Moon and Mars sites the spot most resembles.

**Compiled estimates** — the curated Moon/Mars dossiers and the ice/dust/subsurface indices are
literature-derived regional estimates. Each dossier shows a confidence tag and a citation, and
`assets/data/*-sites.js` holds the raw numbers so they can be replaced with in-situ values.

Known caveats: POWER is 0.5° grid-cell climatology (summit sites read warmer than station data);
Moon/Mars values are regional not in-situ; atmosphere is deliberately excluded from the Earth Twin
similarity because nothing on Earth reproduces a vacuum or ~0.6 kPa.

## Lunar candidate set

25 graded sites, built from published lunar science rather than picked by eye:

| Group | Sites |
| --- | --- |
| Artemis III candidate regions (NASA, 2022) | Peak Near Shackleton, Connecting Ridge + Extension, Faustini Rim A, de Gerlache Rim 1/2, de Gerlache?Kocher Massif, Haworth, Malapert Massif, Leibnitz Beta Plateau, Nobile Rim 1/2, Amundsen Rim |
| Other polar (peak-of-eternal-light work) | Shackleton rim, Cabeus, Whipple rim, Peary |
| Science and resources | Aristarchus Plateau, Gruithuisen Domes, Compton?Belkovich, Von K?rm?n (Chang'e-4), Schr?dinger Basin, Marius Hills pit, Mare Tranquillitatis, Sinus Medii |

`tools/build_moon_candidates.py` appends the expanded set and is idempotent (the ten original
hand-written entries are never touched ? it rewrites only its own marked block).

Where the numbers come from:

- **Terrain** ? elevation is sampled bilinearly from the native LOLA grid (`LDEM_4`, 4 px/deg), not
  the 0.5? product the browser uses, because a polar rim can otherwise land inside the crater next to
  it. Slope and relief come from the block-averaged 0.5? grids so they stay comparable with the
  point-query numbers.
- **Rim placement** ? Artemis region centroids sometimes sit on a crater floor, so rim, peak and
  plateau sites are snapped to the highest ground within 1? of the published centre. The shift is
  printed on every run.
- **Temperature** ? the same Diviner-calibrated latitude model the point query uses, so a dossier
  always agrees with a click at those coordinates (all polar sites therefore share the model's polar
  values; that limitation is stated in the layer legend).
- **Illumination, Earth visibility, ice proximity and the qualitative scores** ? literature-derived
  (Artemis III region study, LRO illumination and PSR mapping, LROC and Diviner results), each with a
  confidence tag and a citation on the dossier.

Grades come out as expected: the Shackleton?de Gerlache ridge sites lead (A), the sunlit rims follow
(B), near-side science targets grade C for having no water, and the far-side sites grade D because
Earth visibility ? and therefore direct comms ? is zero.

## Martian candidate set

24 graded sites: the twelve original dossiers (mission-verified ground plus the classic
landing-site studies) and twelve added from published orbital results.

| Group | Sites |
| --- | --- |
| Mission ground truth | Jezero (Perseverance), Gale (Curiosity), Meridiani Planum (Opportunity), Chryse Planitia (Viking 1), Green Valley (Phoenix), Elysium Planitia (InSight) |
| Shallow-ice belts | Arcadia Planitia, Utopia Planitia, Deuteronilus Mensae, Nilosyrtis Mensae, Athabasca Valles, Korolev Crater |
| Polar ice | Planum Boreum, Korolev's 1.8 km fill, Green Valley's ice table |
| Ancient water and clay | Mawrth Vallis, Oxia Planum (ExoMars target), Nili Fossae, Holden Crater, Eberswalde Delta, Crommelin Crater, Melas Chasma |
| Volcanic and subsurface | Arsia Mons skylights (confirmed lava-tube openings), Elysium Planitia, Amazonis Planitia, Argyre Planitia |

`tools/build_mars_candidates.py` appends the expanded set and is idempotent (it rewrites only its own
marked block, and prints a model check against the twelve hand-written sites).

Where the numbers come from:

- **Elevation** ? a 5×5 median of the native MOLA MEGDR topography (16 px/deg), i.e. the ground a
  landing ellipse would touch rather than a single pixel that might sit on a crater rim. The model
  check prints its agreement with the hand-written elevations.
- **Slope, relief and temperature** ? from the same 0.5° grids the app samples on a map click, so a
  dossier always agrees with a query at those coordinates. Temperature is the latitude+elevation
  regression, labelled *modelled* in the layer legend.
- **Pressure** ? hydrostatic, from elevation (610 Pa datum, 11.1 km scale height). Arsia Mons reads
  about 140 Pa, Hellas about 1,150 Pa, which is the physical range the dossiers show.
- **Solar** ? latitude-scaled with a polar-summer floor, fitted to the curated sites.
- **Ice, dust, subsurface, biosignature and science scores** ? literature-derived (MRO/HiRISE and
  MCS, Mars Express MARSIS/OMEGA, Phoenix and Viking surface data, ExoMars site selection), each with
  a confidence tag and a citation.

The result: polar and mid-latitude ice sites grade B on water plus ops, dry science sites grade B or C
because their ice distance costs them the resource row, and nothing reaches A ? by the same rubric
that gives the Moon its A sites, Mars is the harder planet to base on.

## Global analog prospector (discovered candidates)

The 40 curated sites are published work — someone already wrote them down. The Discovered switch
adds candidates **nobody has described as analogs**, found by screening the whole planet rather
than by reading papers.

`tools/build_prospect_scan.py` runs offline-friendly global datasets over a 0.25° equirectangular
grid (1,036,800 cells, 224,663 of which pass the masks):

| Dataset | What it contributes |
| --- | --- |
| AWS Terrain Tiles (Mapzen terrarium, SRTM/NED/GMTED/ETOPO blend), zoom 5 | elevation mean, slope mean and within-cell relief from a 4.9 km DEM |
| WorldClim 2.1 bio, 10 arc-minute | annual mean / max / min temperature, precipitation, precipitation seasonality |
| Natural Earth 50m land, glaciated areas, lakes | land mask, ice-cap and lake exclusion |
| Natural Earth 50m countries, 10m populated places | country label and nearest settlement used to name each candidate |
| NASA POWER climatology + NOAA ETOPO1 | finalist refinement, identical to the curated pipeline |

How a cell is scored: the curated analogs are the training set. For each dimension the scan takes
the **measured** value at those 40 locations on the same grid, computes a robust centre and spread
(median, IQR/1.349), and scores every cell by its Gaussian membership. The memberships are combined
with a **weighted geometric mean**, so a cell cannot buy a high score by matching most dimensions
while failing one badly — an analog that is far too wet is not an analog.

Masks: land, above sea level, not an ice sheet or glacier, not a lake, no data holes, and no polar
cell below 20 m (ice shelves and lagoon flats). Then the shortlist is drawn round-robin across 12
climate zones (4 temperature × 3 precipitation) with 700 km minimum spacing, at most 3 per country,
and at least 200 km from any curated site — so the output is a spread of genuinely new places, not
one desert repeated.

Each finalist is then queried with POWER + ETOPO1 for real numbers and graded with **the same
nine-row Earth rubric** as everything else. The dossier labels the ice, dust, subsurface, biosignature
and science rows with `*` because those are proxies derived from climate and terrain, not field
observations, and says plainly that the site is a proposal to survey. Clicking anywhere on the map
also reads the shipped rasters and grades that cell.

Current output: **39 candidates in 22 countries**, e.g. 57 km WSW of Yakima (basalt plateau),
35 km SSW of Zapala (Patagonian steppe), 58 km E of Serdar (Karakum), 116 km ENE of Beaufort West
(Namaqualand), 187 km NNW of Koktokay (Junggar), 53 km SE of Green River (Utah canyonlands).

## Scoring

Eight rubric rows (geology, terrain, thermal, water, dust, habitability, subsurface, operations) are
closed-form functions of the measurements in `assets/scoring.js`. Earth adds a ninth, **open land**,
because the Moon and Mars have no owners, farms or cities but Earth very much does: without it a click
in Manhattan graded as a credible base site. Earth sites and point grades are therefore scored on nine
rows; the other bodies leave that dimension `null` and the weighted mean renormalises, so every lunar
and martian score is byte-identical to before this row existed. The weighted mean is the suitability
score; letters map to A ≥ 70, B ≥ 62, C ≥ 54, D ≥ 46, E ≥ 38, otherwise F. The mission designer only
changes the weights, so every re-grade is explainable.

**Candidate gate.** A clicked point is not a shortlisted site, and the screen is what separates the two — so a point's letter is scaled by how far inside the analog envelope it sits: `score × (0.45 + 0.55 × min(1, fit / 65))`. Below the 65-point threshold the multiplier falls off, reaching 0.45 at zero fit; at or above it the multiplier is exactly 1, so a passing cell is graded on its merits and the shortlist is never re-ranked by this. Without it a click in Manhattan graded **C 58.6** while discovered candidates sat at 53-65 — a flat, sunny, well-connected lowland outranking places the screen had actually selected. With it Manhattan is **F 28.9**, London **D 49.3** and Paris **D 48.3**, all below every discovered candidate, while a Saharan cell inside the envelope still grades **B 62.6** and is flagged "screened candidate". Shortlist sites carry no `candidateFit`, so their grades are byte-identical to before the gate existed.

**The grade field and the click grade are the same number.** The analog grade field is an
interpolation of the shortlist's scores, and it used to ignore the gate — so it painted B and C over
ground where a click graded F (the Andean valleys behind Sucre, for one). Both paths now run the same
`gateFactor()`: the field reads the screen raster, applies the gate to each interpolated value before
colouring, and falls back to the ungated interpolation only where the screen has no data. The field is
therefore a preview of what a click would grade, and the two never disagree — Sucre reads **E 43.7**
under a dark violet wash, a Saharan cell reads **B 62.0** under green.

**Open land** comes from `tools/build_land_use.py`: MODIS Combined IGBP Land Cover (500 m, annual) is
pulled from NASA GIBS as colour-decoded WMTS tiles, binned to the same 0.25° grid by area share, and
scored barren 100 → built-up 0 (grassland 92, shrub 88, savanna 82, forest 44-58, cropland 32,
wetland 45, ice 96). Water and no-data stay empty rather than scoring, because a lake is not a bad
base site - it is not a site. The result is two rasters (`earth-open.png`, `earth-landcover.png`) plus
`assets/data/earth-landuse.js` with each pin's openness and dominant class.

**Two numbers, two questions.** The Discovered tab used to print the *screen* score in the same slot
where every other tab prints the *grade* score, so a 99 could sit next to a `C` badge while a 66
showed `B`. The shortlist number is now always the grade, and the screen score is shown separately
under the site name (`Russia · screen 66.0`). They can disagree because they answer different
questions: the screen asks "does this cell's climate and terrain match the catalogued envelope?",
while the grade asks "is this a good base?" — the grade also weighs ice, dust and operations, so a
warm desert the screen loves can grade modestly for having no water ice and a 50 K day/night swing.

Earth Twin similarity is a weighted normalised distance over temperature, day/night swing, solar,
slope, roughness, water/ice and dust, reported 0–100.

Every match query — a clicked Moon/Mars point, the twin banner, the dossier's "closest Earth
analogs" — runs over `SITES.earth.concat(SITES.discovered)`, so a discovered candidate can outrank a
curated one or sit alongside it. Discovered hits are labelled `screened` in the list and keep their
dashed pin on the map; picking one switches the shortlist tab to match, so the selection is visible.

The shortlist header always names the target being matched — *Earth matches · to 89.5° S 120° E on the
Moon · day −53 °C · night −192 °C · slope 8.6°* — so a screenshot or a demo jump still says which lunar
or Martian place the ranking is about, and the map banner repeats it.

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
