/* RADIUM scoring engine.
 *
 * Every score is a transparent function of a measurement, so any judge can
 * re-derive it by hand. Weights are the only tunable part; the mission designer
 * rewrites them at run time.
 *
 * Expects the data scripts (moon-sites, mars-sites, earth-sites, earth-metrics)
 * to be loaded first.
 */
(function () {
  "use strict";

  const RUBRIC = [
    { key: "geology", label: "Geology & materials", short: "Geology" },
    { key: "terrain", label: "Terrain & topography", short: "Terrain" },
    { key: "environment", label: "Temperature & illumination", short: "Thermal" },
    { key: "resources", label: "Water, ice & resources", short: "Water" },
    { key: "processes", label: "Dust, wind & surface processes", short: "Dust" },
    { key: "habitability", label: "Habitability & biosignatures", short: "Bio" },
    { key: "subsurface", label: "Caves & subsurface access", short: "Subsurface" },
    { key: "operations", label: "Landing, mobility & comms", short: "Ops" }
  ];

  const DEFAULT_WEIGHTS = {
    geology: 0.12,
    terrain: 0.16,
    environment: 0.14,
    resources: 0.16,
    processes: 0.08,
    habitability: 0.08,
    subsurface: 0.06,
    operations: 0.20
  };

  const clamp = (v, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v));
  const roughIndex = (metres) =>
    metres == null ? 0 : clamp((Math.log10(1 + metres) / Math.log10(201)) * 10, 0, 10);

  function distanceKm(aLat, aLon, bLat, bLon) {
    const R = 6371;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(bLat - aLat);
    const dLon = toRad(bLon - aLon);
    const h =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function envScore(body, s) {
    const swing = Math.max(0, s.tempDayC - s.tempNightC);
    if (body === "moon") {
      const comfort = clamp(100 - (swing - 90) * 0.35);
      return clamp(s.illuminationPct * 0.65 + comfort * 0.35);
    }
    if (body === "mars") {
      const warmth = clamp(70 + s.tempDayC * 0.9);
      return clamp(warmth * 0.55 + clamp(100 - (swing - 45) * 0.7) * 0.45);
    }
    return clamp(100 - Math.abs(s.tempMeanC - 5) * 2.2 - Math.max(0, swing - 25) * 0.8);
  }

  function dimensionScores(body, s) {
    const comms = body === "moon" ? s.earthVisibilityPct : body === "mars" ? 55 : 90;
    const energy = clamp((s.solarKwh / 8) * 100);
    const iceReach = 1 - Math.min(0.65, s.iceDistanceKm / 300);
    return {
      geology: clamp(s.scienceScore),
      terrain: clamp(100 - s.slopeDeg * 3 - roughIndex(s.roughnessM) * 4),
      environment: envScore(body, s),
      resources: clamp(s.iceIndex * iceReach),
      processes: clamp(100 - s.dustIndex * 0.75),
      habitability: clamp(s.biosignatureScore),
      subsurface: clamp(s.subsurfaceScore),
      operations: clamp(comms * 0.55 + energy * 0.45)
    };
  }

  function grade(score) {
    if (score >= 70) return "A";
    if (score >= 62) return "B";
    if (score >= 54) return "C";
    if (score >= 46) return "D";
    if (score >= 38) return "E";
    return "F";
  }

  function normalizeWeights(weights) {
    const keys = Object.keys(DEFAULT_WEIGHTS);
    const total = keys.reduce((sum, k) => sum + Math.max(0.0001, weights[k] || 0), 0);
    return keys.reduce((acc, k) => {
      acc[k] = Math.max(0.0001, weights[k] || 0) / total;
      return acc;
    }, {});
  }

  function scoreSite(site, weights) {
    const w = normalizeWeights(weights || DEFAULT_WEIGHTS);
    const dims = site.dims;
    const value = RUBRIC.reduce((sum, r) => sum + dims[r.key] * w[r.key], 0);
    return { value, letter: grade(value), dims };
  }

  /* --- Earth Twin similarity -------------------------------------------- */
  const SIM_VECTOR = [
    { key: "Temperature", weight: 3.0, norm: (s) => clamp(((s.tempDayC + s.tempNightC) / 2 + 90) / 120, 0, 1) },
    { key: "Day/night swing", weight: 1.4, norm: (s) => Math.min(1, (s.tempDayC - s.tempNightC) / 160) },
    { key: "Solar energy", weight: 1.2, norm: (s) => s.solarKwh / 8 },
    { key: "Slope", weight: 1.0, norm: (s) => s.slopeDeg / 30 },
    { key: "Roughness", weight: 0.8, norm: (s) => roughIndex(s.roughnessM) / 10 },
    { key: "Water / ice", weight: 1.6, norm: (s) => s.iceIndex / 100 },
    { key: "Dust", weight: 0.8, norm: (s) => s.dustIndex / 100 }
  ];

  function similarity(a, b) {
    let weighted = 0;
    let total = 0;
    const parts = [];
    SIM_VECTOR.forEach((v) => {
      const na = v.norm(a);
      const nb = v.norm(b);
      if (!Number.isFinite(na) || !Number.isFinite(nb)) return; // dimension not resolved here
      const delta = Math.min(1, Math.abs(na - nb));
      weighted += v.weight * delta * delta;
      total += v.weight;
      parts.push({ label: v.key, match: Math.round((1 - delta) * 100) });
    });
    if (!total) return { score: 0, parts, used: 0 };
    const score = 100 * (1 - Math.sqrt(weighted / total));
    return { score: Math.round(clamp(score)), parts, used: total };
  }

  /* --- Data normalisation ------------------------------------------------ */
  function withDims(body, s) {
    const site = Object.assign({}, s, { body });
    site.dims = dimensionScores(body, site);
    return site;
  }

  function buildSites() {
    const moon = (window.RADIUM_MOON || []).map((s) => withDims("moon", s));

    const mars = (window.RADIUM_MARS || []).map((s) =>
      withDims("mars", Object.assign({ illuminationPct: 0, earthVisibilityPct: 55 }, s))
    );

    const metrics = window.RADIUM_EARTH || {};
    const earth = (window.RADIUM_EARTH_SITES || [])
      .map((curated) => {
        const m = metrics[curated.id];
        if (!m) return null;
        return withDims(
          "earth",
          Object.assign({}, curated, {
            lat: m.lat,
            lon: m.lon,
            elevationM: m.elevationM,
            slopeDeg: m.slopeDeg || 0,
            roughnessM: m.roughnessM || 0,
            tempDayC: m.tempMaxC,
            tempNightC: m.tempMinC,
            tempMeanC: m.tempMeanC,
            pressurePa: (m.pressureKPa || 0) * 1000,
            solarKwh: m.solarKwhM2Day,
            iceDistanceKm: 0,
            windMs: m.windMs,
            humidityPct: m.humidityPct,
            precipMmDay: m.precipMmDay,
            elevationSamples: m.elevSamplesM,
            illuminationPct: 0,
            earthVisibilityPct: 100,
            provenance: m.provenance
          })
        );
      })
      .filter(Boolean);

    return { moon, mars, earth, discovered: buildProspects() };
  }

  /* Discovered candidates come from the global screen
     (tools/build_prospect_scan.py). They already carry measured POWER/ETOPO1
     metrics, so they go through the same eight-row rubric as the curated sites;
     `prospect` and `estimated` mark which fields are proxies rather than
     published observations. */
  function buildProspects() {
    return (window.RADIUM_PROSPECT_SITES || []).map((p) =>
      withDims(
        "earth",
        Object.assign({}, p, {
          tempDayC: p.tempMaxC,
          tempNightC: p.tempMinC,
          pressurePa: (p.pressureKPa || 0) * 1000,
          solarKwh: p.solarKwhM2Day,
          iceDistanceKm: 0,
          windMs: p.windMs,
          humidityPct: p.humidityPct,
          precipMmDay: p.precipMmDay,
          elevationSamples: p.elevSamplesM || [],
          illuminationPct: 0,
          earthVisibilityPct: 100
        })
      )
    );
  }

  function nearestEarth(earthSites, lat, lon) {
    let best = null;
    earthSites.forEach((s) => {
      const d = distanceKm(lat, lon, s.lat, s.lon);
      if (!best || d < best.km) best = { site: s, km: d };
    });
    return best;
  }

  function topTwins(earthSites, site, limit) {
    return earthSites
      .map((candidate) => ({ site: candidate, match: similarity(site, candidate) }))
      .sort((a, b) => b.match.score - a.match.score)
      .slice(0, limit || 4);
  }

  window.RADIUM = {
    RUBRIC,
    DEFAULT_WEIGHTS,
    buildSites,
    withDims,
    scoreSite,
    similarity,
    topTwins,
    nearestEarth,
    distanceKm,
    roughIndex,
    grade
  };
})();
