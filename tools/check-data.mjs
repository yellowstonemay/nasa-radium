// Data sanity check: `node tools/check-data.mjs`
// Fails if any site is missing measurements, scores outside 0-100, or has no source.
import { readFile } from "node:fs/promises";

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

const scoringSource = await readFile(new URL("../assets/scoring.js", import.meta.url), "utf8");
const sandbox = { window: { RADIUM_MOON: await load("data/moon-sites.js", "RADIUM_MOON"),
  RADIUM_MARS: await load("data/mars-sites.js", "RADIUM_MARS"),
  RADIUM_EARTH_SITES: await load("data/earth-sites.js", "RADIUM_EARTH_SITES"),
  RADIUM_EARTH: earthMetrics } };
new Function("window", scoringSource)(sandbox.window);

const { buildSites, scoreSite, DEFAULT_WEIGHTS, similarity, topTwins } = sandbox.window.RADIUM;
const sites = buildSites();
const problems = [];

for (const body of ["moon", "mars", "earth"]) {
  if (!sites[body].length) problems.push(`${body}: no sites built`);
  for (const site of sites[body]) {
    if (!site.source || !site.source.url) problems.push(`${site.id}: missing source`);
    if (!Number.isFinite(site.lat) || !Number.isFinite(site.lon)) problems.push(`${site.id}: bad coordinates`);
    for (const [key, value] of Object.entries(site.dims)) {
      if (!Number.isFinite(value) || value < 0 || value > 100) {
        problems.push(`${site.id}: dim "${key}" = ${value}`);
      }
    }
    const card = scoreSite(site, DEFAULT_WEIGHTS);
    if (!Number.isFinite(card.value) || card.value < 0 || card.value > 100) {
      problems.push(`${site.id}: score = ${card.value}`);
    }
    if (!"ABCDEF".includes(card.letter)) problems.push(`${site.id}: bad letter ${card.letter}`);
  }
}

// Spot-check the similarity metric against expert-known analogs.
const ridge = sites.moon.find((s) => s.id === "connecting-ridge");
const twins = topTwins(sites.earth, ridge, 3).map((t) => t.site.id);
if (!twins.some((id) => ["haughton", "university-valley", "dry-valleys", "gypsum-hill"].includes(id))) {
  problems.push(`twin sanity check failed for connecting-ridge: ${twins.join(", ")}`);
}
const selfMatch = similarity(ridge, sites.earth.find((s) => s.id === "haughton")).score;
if (selfMatch < 30 || selfMatch > 90) problems.push(`similarity out of range: ${selfMatch}`);

if (problems.length) {
  console.error("FAILED\n" + problems.join("\n"));
  process.exit(1);
}
console.log(
  `OK — ${sites.moon.length} Moon + ${sites.mars.length} Mars + ${sites.earth.length} Earth sites, scores and twins valid.`
);
