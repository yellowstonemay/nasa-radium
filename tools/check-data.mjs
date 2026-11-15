// Data sanity check: `node tools/check-data.mjs`
// Fails if any site is missing measurements, scores outside 0-100, or has no source.
import { access, readFile } from "node:fs/promises";

const load = async (file, name) => {
  const src = await readFile(new URL(`../assets/${file}`, import.meta.url), "utf8");
  const sandbox = { window: {} };
  new Function("window", src)(sandbox.window);
  return sandbox.window[name];
};

await load("data/moon-sites.js", "RADIUM_MOON");
await load("data/mars-sites.js", "RADIUM_MARS");
await load("data/earth-sites.js", "RADIUM_EARTH_SITES");
const earthMetrics = await load("earth-metrics.js", "RADIUM_EARTH");
const prospects = await load("data/prospect-sites.js", "RADIUM_PROSPECT_SITES");
const landuse = await load("data/earth-landuse.js", "RADIUM_EARTH_LANDUSE");

const scoringSource = await readFile(new URL("../assets/scoring.js", import.meta.url), "utf8");
const sandbox = { window: { RADIUM_MOON: await load("data/moon-sites.js", "RADIUM_MOON"),
  RADIUM_MARS: await load("data/mars-sites.js", "RADIUM_MARS"),
  RADIUM_EARTH_SITES: await load("data/earth-sites.js", "RADIUM_EARTH_SITES"),
  RADIUM_EARTH: earthMetrics,
  RADIUM_EARTH_LANDUSE: landuse,
  RADIUM_PROSPECT_SITES: prospects } };
new Function("window", scoringSource)(sandbox.window);

const { buildSites, scoreSite, DEFAULT_WEIGHTS, similarity, topTwins } = sandbox.window.RADIUM;
const sites = buildSites();
const problems = [];

for (const body of ["moon", "mars", "earth", "discovered"]) {
  if (!sites[body].length) problems.push(`${body}: no sites built`);
  for (const site of sites[body]) {
    if (!site.source || !site.source.url) problems.push(`${site.id}: missing source`);
    if (!Number.isFinite(site.lat) || !Number.isFinite(site.lon)) problems.push(`${site.id}: bad coordinates`);
    for (const [key, value] of Object.entries(site.dims)) {
      // Land use is an Earth-only row; the other bodies carry null on purpose.
      if (key === "landuse" && body !== "earth" && body !== "discovered") {
        if (value !== null) problems.push(`${site.id}: land use should not exist off Earth`);
        continue;
      }
      if (!Number.isFinite(value) || value < 0 || value > 100) {
        problems.push(`${site.id}: dim "${key}" = ${value}`);
      }
    }
    if (body === "earth" || body === "discovered") {
      if (!Number.isFinite(site.landUse)) problems.push(`${site.id}: no land-use value`);
      if (site.landUse === 0) problems.push(`${site.id}: sits on built-up land`);
    }
    const card = scoreSite(site, DEFAULT_WEIGHTS);
    if (!Number.isFinite(card.value) || card.value < 0 || card.value > 100) {
      problems.push(`${site.id}: score = ${card.value}`);
    }
    if (!"ABCDEF".includes(card.letter)) problems.push(`${site.id}: bad letter ${card.letter}`);
  }
  if (sites.earth.length < 30) {
    problems.push(`earth: only ${sites.earth.length} sites, expected at least 30`);
  }
  if (sites.moon.length < 20) {
    problems.push(`moon: only ${sites.moon.length} sites, expected at least 20`);
  }
  if (sites.mars.length < 20) {
    problems.push(`mars: only ${sites.mars.length} sites, expected at least 20`);
  }
}

// Discovered candidates must stay clear of the curated set, sit on buildable
// land, and remain spread out rather than clustering in one desert.
if (sites.discovered.length < 20) {
  problems.push(`discovered: only ${sites.discovered.length} candidates`);
}
const curatedIds = new Set(sites.earth.map((s) => s.id));
for (const site of sites.discovered) {
  if (curatedIds.has(site.id)) problems.push(`${site.id}: duplicate of a curated site`);
  if (!site.prospect || !site.estimated || !site.estimated.length) {
    problems.push(`${site.id}: not tagged as a screening estimate`);
  }
  if (!site.nearestAnalog || !(site.nearestAnalog.km >= 150)) {
    problems.push(`${site.id}: too close to a known analog`);
  }
  if (!(site.elevationM >= 0)) problems.push(`${site.id}: elevation ${site.elevationM} m`);
  if (!(Math.abs(site.lat) < 84)) problems.push(`${site.id}: polar ice (${site.lat})`);
  if (!(site.precipMmDay >= 0 && site.precipMmDay < 12)) problems.push(`${site.id}: rain ${site.precipMmDay}`);
  if (!(site.tempMeanC > -35 && site.tempMeanC < 40)) problems.push(`${site.id}: temp ${site.tempMeanC}`);
}
for (let i = 0; i < sites.discovered.length; i += 1) {
  for (let j = i + 1; j < sites.discovered.length; j += 1) {
    const a = sites.discovered[i];
    const b = sites.discovered[j];
    const d = sandbox.window.RADIUM.distanceKm(a.lat, a.lon, b.lat, b.lon);
    if (d < 400) problems.push(`${a.id}/${b.id} only ${d.toFixed(0)} km apart`);
  }
}

// Body coordinates must be unique and on the sphere. The lunar set is graded on
// water access, so an A or B there has to come with a real ice story; Mars keeps
// dry science sites in the B band by design, so that rule is moon-only.
for (const [body, minKm] of [["moon", 15], ["mars", 150]]) {
  const ids = new Set();
  for (const site of sites[body]) {
    if (ids.has(site.id)) problems.push(`${site.id}: duplicate ${body} id`);
    ids.add(site.id);
    if (!(Math.abs(site.lat) <= 90 && Math.abs(site.lon) <= 360)) {
      problems.push(`${site.id}: coordinates out of range`);
    }
    const card = scoreSite(site, DEFAULT_WEIGHTS);
    if (body === "moon" && (card.letter === "A" || card.letter === "B") && (site.iceIndex || 0) < 40) {
      problems.push(`${site.id}: grade ${card.letter} but iceIndex ${site.iceIndex}`);
    }
  }
  const crowded = [];
  for (let i = 0; i < sites[body].length; i += 1) {
    for (let j = i + 1; j < sites[body].length; j += 1) {
      const a = sites[body][i];
      const b = sites[body][j];
      const d = sandbox.window.RADIUM.distanceKm(a.lat, a.lon, b.lat, b.lon);
      if (d < minKm) crowded.push(`${a.id}/${b.id} only ${d.toFixed(0)} km apart`);
    }
  }
  if (crowded.length) problems.push(...crowded);
}

// Spot-check the similarity metric against expert-known analogs.
const ridge = sites.moon.find((s) => s.id === "connecting-ridge");
const twins = topTwins(sites.earth, ridge, 3).map((t) => t.site.id);
if (!twins.some((id) => ["haughton", "university-valley", "dry-valleys", "gypsum-hill"].includes(id))) {
  problems.push(`twin sanity check failed for connecting-ridge: ${twins.join(", ")}`);
}
const selfMatch = similarity(ridge, sites.earth.find((s) => s.id === "haughton")).score;
if (selfMatch < 30 || selfMatch > 90) problems.push(`similarity out of range: ${selfMatch}`);

// Grids power the click-anywhere query: files must exist and have valid ranges.
const gridChecks = [
  ["moon", "RADIUM_GRID_MOON", { elevationM: [-9000, 11000], slopeDeg: [0, 45], roughnessM: [0, 4] }],
  ["mars", "RADIUM_GRID_MARS", { elevationM: [-9000, 22000], slopeDeg: [0, 45], roughnessM: [0, 4] }]
];
for (const [body, globalName, expectations] of gridChecks) {
  const metaSrc = await readFile(new URL(`../assets/grids/${body}-meta.js`, import.meta.url), "utf8");
  const gridWindow = {};
  new Function("window", metaSrc)(gridWindow);
  const meta = gridWindow[globalName];
  if (!meta) {
    problems.push(`${body}: missing grid meta`);
    continue;
  }
  for (const [key, [lo, hi]] of Object.entries(expectations)) {
    const layer = meta.layers[key];
    if (!layer) {
      problems.push(`${body}: grid layer "${key}" missing`);
      continue;
    }
    if (!(layer.min < layer.max)) problems.push(`${body}.${key}: bad range ${layer.min}..${layer.max}`);
    if (layer.min < lo || layer.max > hi) problems.push(`${body}.${key}: implausible range ${layer.min}..${layer.max}`);
  }
  for (const key of ["tempDayC", "tempNightC"]) {
    if (!meta.layers[key] || !Number.isFinite(meta.layers[key].rmseK)) {
      problems.push(`${body}.${key}: missing model error estimate`);
    }
  }
}

// The Earth point grader samples shipped rasters directly, so they have to be
// present, mercator-square and in the range the grader decodes.
const earthFields = {
  "earth-elev-meta.js": ["RADIUM_GRID_EARTH_ELEV", -400, 6000],
  "earth-heat-meta.js": ["RADIUM_GRID_EARTH_HEAT", -25, 32],
  "earth-tmax-meta.js": ["RADIUM_GRID_EARTH_TMAX", -40, 55],
  "earth-tmin-meta.js": ["RADIUM_GRID_EARTH_TMIN", -60, 30],
  "earth-precip-meta.js": ["RADIUM_GRID_EARTH_PRECIP", 0, 12],
  "earth-slope-meta.js": ["RADIUM_GRID_EARTH_SLOPE", 0, 40],
  "earth-relief-meta.js": ["RADIUM_GRID_EARTH_RELIEF", 0, 1200],
  "earth-open-meta.js": ["RADIUM_GRID_EARTH_OPEN", 0, 100],
  "earth-landcover-meta.js": ["RADIUM_GRID_EARTH_LANDCOVER", 0, 17]
};
for (const [file, [globalName, lo, hi]] of Object.entries(earthFields)) {
  const metaSrc = await readFile(new URL(`../assets/grids/${file}`, import.meta.url), "utf8");
  const gridWindow = {};
  new Function("window", metaSrc)(gridWindow);
  const meta = gridWindow[globalName];
  if (!meta || !meta.file) {
    problems.push(`${file}: missing or unbound meta`);
    continue;
  }
  await access(new URL(`../${meta.file}`, import.meta.url));
  if (meta.width !== 1440 || meta.height !== 1440) problems.push(`${file}: raster is not 1440x1440`);
  if (meta.min !== lo || meta.max !== hi) problems.push(`${file}: decode range ${meta.min}..${meta.max}, grader expects ${lo}..${hi}`);
}

if (problems.length) {
  console.error("FAILED\n" + problems.join("\n"));
  process.exit(1);
}console.log(
  `OK — ${sites.moon.length} Moon + ${sites.mars.length} Mars + ${sites.earth.length} Earth sites, ${sites.discovered.length} discovered candidates, scores and twins valid.`
);
