/* RADIUM front-end. Vanilla JS so five people can edit it in parallel. */
(function () {
  "use strict";

  const R = window.RADIUM;
  const SITES = R.buildSites();
  const GRADE_COLOR = {
    A: "#6fe7b0", B: "#b9e36b", C: "#f5c451",
    D: "#f09a4c", E: "#de6a45", F: "#c0443c"
  };
  const BODY_META = {
    moon: {
      label: "Moon", title: "Lunar base suitability", note:
        "Graded from LRO/LOLA/Diviner-derived terrain, illumination and ice estimates. Letter grades weight water, ops and terrain most heavily by default.",
      center: { lat: -60, lng: 40, altitude: 1.9 }
    },
    mars: {
      label: "Mars", title: "Mars landing suitability", note:
        "Graded from MOLA relief, published ice mapping and atmospheric/dust climatology. Mars scores assume relay comms, not direct-to-Earth.",
      center: { lat: 12, lng: 90, altitude: 1.9 }
    },
    earth: {
      label: "Earth", title: "Terrestrial analog candidates", note:
        "Climate and terrain for every Earth pin are computed from NASA POWER + NOAA ETOPO1. Grades use the same eight-row rubric, so science- and habitability-rich analogs can outrank sites that are merely easy to land on.",
      center: { lat: 12, lng: 15 }
    }
  };
  const LAYERS = {
    moon: [
      { id: "moon_base", label: "LROC mosaic", legend: "Visible surface mosaic (LRO WAC, 303 ppd)" },
      { id: "moon_day", label: "Day temperature", legend: "Diviner average daytime temperature (K)" },
      { id: "moon_night", label: "Night temperature", legend: "Diviner average nighttime temperature (K)" }
    ],
    mars: [
      { id: "mars_base", label: "MOLA relief", legend: "MOLA colour-shaded elevation (km)" },
      { id: "mars_visible", label: "Viking colour", legend: "Viking MDIM 2.1 colour mosaic" }
    ],
    earth: [
      { id: "earth_base", label: "Blue Marble", legend: "NASA Blue Marble shaded relief + bathymetry", kind: "base" },
      {
        id: "earth_temp",
        label: "Surface temp",
        legend: "Interpolated mean air temperature, NASA POWER 2001-2020 (real measurements at 40 sites; faded beyond 2,500 km)",
        kind: "temp"
      },
      {
        id: "earth_suit",
        label: "Analog grade field",
        legend: "Weighted analog score interpolated from the 40 shortlisted sites — reacts to the mission designer",
        kind: "suit"
      },
      {
        id: "earth_twin",
        label: "Twin similarity",
        legend: "Similarity to the selected Moon/Mars target, interpolated across Earth",
        kind: "twin"
      }
    ]
  };

  const state = {
    body: "moon",
    layer: { moon: "moon_base", mars: "mars_base", earth: "earth_base" },
    selected: { moon: null, mars: null, earth: null },
    weights: Object.assign({}, R.DEFAULT_WEIGHTS),
    twinSource: null,
    point: null
  };

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, html) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html != null) node.innerHTML = html;
    return node;
  };

  const fmt = (v, digits) => {
    if (v == null || Number.isNaN(v)) return "—";
    return Number(v).toFixed(digits == null ? 0 : digits);
  };

  function scoreFor(site) {
    return R.scoreSite(site, state.weights);
  }

  function sortedSites(body) {
    const rows = SITES[body].map((site) => ({ site, card: scoreFor(site) }));
    if (state.twinSource && body === "earth") {
      return rows
        .map((row) => Object.assign(row, { match: R.similarity(state.twinSource, row.site).score }))
        .sort((a, b) => b.match - a.match);
    }
    return rows.sort((a, b) => b.card.value - a.card.value);
  }

  function activeSites() { return SITES[state.body]; }

  function selectedSite() {
    const id = state.selected[state.body];
    return activeSites().find((s) => s.id === id) || null;
  }

  /* ---------------------------------------------------------------- tabs */
  function renderTabs() {
    const nav = $("#body-tabs");
    nav.innerHTML = "";
    Object.keys(BODY_META).forEach((key) => {
      const btn = el("button", "tab", BODY_META[key].label);
      btn.type = "button";
      btn.dataset.body = key;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", String(state.body === key));
      btn.addEventListener("click", () => setBody(key));
      nav.appendChild(btn);
    });
  }

  function setBody(body) {
    if (state.body === body && state.point) {
      state.point = null;
    }
    state.body = body;
    state.point = null;
    if (body !== "earth") state.twinSource = null;
    $("#view-globe").classList.toggle("hidden", body === "earth");
    $("#view-earth").classList.toggle("hidden", body !== "earth");
    renderTabs();
    $("#rail-title").textContent = BODY_META[body].title;
    $("#rail-note").textContent = BODY_META[body].note;
    $("#stage-title").textContent = BODY_META[body].title;
    renderLayers();
    renderRail();
    renderDetail();
    if (body === "earth") {
      ensureEarthMap();
      setTimeout(() => earthMap && earthMap.invalidateSize(), 60);
      renderEarthMarkers();
      applyEarthLayer();
    } else {
      ensureGlobe();
      applyGlobeTexture();
      renderGlobePoints();
      cameraTarget = { lat: BODY_META[body].center.lat, lng: BODY_META[body].center.lng };
    }

    if (!state.selected[body]) {
      const top = sortedSites(body)[0];
      if (top) selectSite(top.site.id, body !== "earth");
    }
  }

  /* ---------------------------------------------------------------- rail */
  function renderRail() {
    const list = $("#rail-list");
    list.innerHTML = "";

    if (state.point) {
      const point = state.point;
      $("#rail-title").textContent = "Earth matches";
      $("#rail-count").textContent = point.matches.length;
      $("#rail-note").textContent =
        "Closest terrestrial analogs for " + point.site.name +
        ". Compared on temperature, day/night swing, slope and roughness; water and dust are not resolved at 0.5°.";
      point.matches.forEach((match, index) => {
        const btn = el("button", "site-row");
        btn.type = "button";
        btn.innerHTML =
          '<span class="grid h-[2.1rem] w-[2.1rem] shrink-0 place-items-center rounded-[10px] border border-ice/35 bg-ice/[0.10] text-[13px] font-semibold tabular-nums text-ice">' +
            fmt(match.match.score, 0) + "</span>" +
          '<span class="min-w-0 flex-1">' +
            '<span class="block truncate text-[13px] text-bone">' + match.site.name + "</span>" +
            '<span class="mt-0.5 block truncate text-[11px] text-muted">' + match.site.region + "</span>" +
          "</span>" +
          '<span class="text-right">' +
            '<span class="block text-[10px] uppercase tracking-widest text-muted">match</span>' +
            '<span class="block text-[10px] uppercase tracking-widest text-muted">#' + (index + 1) + "</span>" +
          "</span>";
        btn.addEventListener("click", () => openPointTwins(match.site.id));
        list.appendChild(btn);
      });
      return;
    }

    const rows = sortedSites(state.body);
    $("#rail-title").textContent = BODY_META[state.body].title;
    $("#rail-note").textContent = BODY_META[state.body].note;
    $("#rail-count").textContent = rows.length;
    rows.forEach(({ site, card, match }, index) => {
      const btn = el("button", "site-row");
      btn.type = "button";
      btn.setAttribute("aria-current", String(state.selected[state.body] === site.id));
      btn.innerHTML =
        '<span class="grade" style="color:' + GRADE_COLOR[card.letter] + ';background:' +
        GRADE_COLOR[card.letter] + '14">' + card.letter + "</span>" +
        '<span class="min-w-0 flex-1">' +
          '<span class="block truncate text-[13px] text-bone">' + site.name + "</span>" +
          '<span class="mt-0.5 block truncate text-[11px] text-muted">' + site.region + "</span>" +
        "</span>" +
        '<span class="text-right">' +
          '<span class="block text-[13px] tabular-nums text-bone">' +
            fmt(match != null ? match : card.value, 1) + "</span>" +
          '<span class="block text-[10px] uppercase tracking-widest text-muted">' +
            (match != null ? "match" : "#" + (index + 1)) + "</span>" +
        "</span>";
      btn.addEventListener("click", () => selectSite(site.id));
      list.appendChild(btn);
    });
  }

  function selectSite(id, fly) {
    state.point = null;
    state.selected[state.body] = id;
    renderRail();
    renderDetail();
    highlightOnStage(fly !== false);
  }

  /* ------------------------------------------------------ conditions grids */
  const GRID_META = { moon: window.RADIUM_GRID_MOON, mars: window.RADIUM_GRID_MARS };
  const gridCache = { moon: {}, mars: {} };

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("grid failed: " + src));
      img.src = src;
    });
  }

  async function ensureGrids(body) {
    if (gridCache[body].__ready) return gridCache[body];
    await Promise.all(
      Object.entries(GRID_META[body].layers).map(async ([key, layer]) => {
        const img = await loadImage(layer.file);
        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        gridCache[body][key] = Object.assign({}, layer, {
          ctx,
          width: canvas.width,
          height: canvas.height
        });
      })
    );
    gridCache[body].__ready = true;
    return gridCache[body];
  }

  function sampleLayer(body, key, lat, lon) {
    const layer = gridCache[body][key];
    if (!layer) return NaN;
    const lonN = (((lon + 180) % 360) + 360) % 360;
    const x = Math.min(layer.width - 1, Math.floor((lonN / 360) * layer.width));
    const y = Math.min(layer.height - 1, Math.max(0, Math.floor(((90 - lat) / 180) * layer.height)));
    const byte = layer.ctx.getImageData(x, y, 1, 1).data[0] / 255;
    const raw = layer.min + byte * (layer.max - layer.min);
    return key === "roughnessM" ? Math.pow(10, raw) - 1 : raw;
  }

  function pointLabel(lat, lon) {
    const latTxt = Math.abs(lat).toFixed(1) + "\u00b0" + (lat >= 0 ? "N" : "S");
    const lonTxt = Math.abs(lon).toFixed(1) + "\u00b0" + (lon >= 0 ? "E" : "W");
    return latTxt + " " + lonTxt;
  }

  async function queryPoint(body, lat, lon) {
    if (body !== state.body) return;
    try {
      await ensureGrids(body);
    } catch (err) {
      console.error(err);
      return;
    }
    const conditions = {
      lat,
      lon,
      elevationM: sampleLayer(body, "elevationM", lat, lon),
      slopeDeg: sampleLayer(body, "slopeDeg", lat, lon),
      roughnessM: sampleLayer(body, "roughnessM", lat, lon),
      tempDayC: sampleLayer(body, "tempDayC", lat, lon),
      tempNightC: sampleLayer(body, "tempNightC", lat, lon)
    };
    const label = pointLabel(lat, lon);
    const pseudo = {
      id: "query-point",
      body,
      name: label,
      region: "Custom point query",
      lat,
      lon,
      elevationM: conditions.elevationM,
      slopeDeg: conditions.slopeDeg,
      roughnessM: conditions.roughnessM,
      tempDayC: conditions.tempDayC,
      tempNightC: conditions.tempNightC,
      tempMeanC: (conditions.tempDayC + conditions.tempNightC) / 2,
      pressurePa: NaN,
      solarKwh: NaN,
      iceIndex: NaN,
      dustIndex: NaN,
      isPoint: true
    };
    state.point = {
      body,
      conditions,
      site: pseudo,
      matches: R.topTwins(SITES.earth, pseudo, 6)
    };
    state.selected[body] = null;
    $("#stage-title").textContent = "Point query · " + label;
    renderRail();
    renderDetail();
    if (globe) {
      updateRings();
      globe.pointOfView({ lat: lat * 0.9, lng: lon, altitude: stageAltitude() }, 700);
    }
  }

  function openPointTwins(matchId) {
    if (!state.point) return;
    const twin = state.point.site;
    const target = matchId || (state.point.matches[0] && state.point.matches[0].site.id);
    state.twinSource = twin;
    state.layer.earth = "earth_twin";
    state.point = null;
    setBody("earth");
    renderTwinBanner();
    if (target) selectSite(target);
  }

  /* --------------------------------------------------------------- globe */
  let globe = null;
  let earthMap = null;
  let earthLayers = {};
  let earthMarkers = [];
  let cameraTarget = { lat: -20, lng: 20 };

  function ensureGlobe() {
    if (globe) return;
    const host = document.getElementById("view-globe");

    globe = Globe()(host)
      .backgroundColor("rgba(0,0,0,0)")
      .showAtmosphere(true)
      .atmosphereColor("#9fc4ff")
      .atmosphereAltitude(0.17)
      .pointAltitude((d) => d.alt)
      .pointRadius((d) => d.radius)
      .pointResolution(24)
      .pointColor((d) => d.color)
      .pointLabel(
        (d) =>
          '<div style="font:12px/1.45 Inter,Segoe UI,sans-serif;color:#ece6d8;padding:2px 4px">' +
          d.name + '<br><span style="color:#8d97ac">' + d.region + "</span></div>"
      )
      .onPointClick((d) => selectSite(d.id))
      .onGlobeClick(({ lat, lng }) => handleGlobeClick(lat, lng));

    const controls = globe.controls();
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.rotateSpeed = 0.5;
    controls.zoomSpeed = 0.7;
    controls.minDistance = 140;
    controls.maxDistance = 680;
    controls.autoRotateSpeed = 0.35;
    controls.addEventListener("change", schedulePinScale);

    const resize = () => {
      const rect = host.getBoundingClientRect();
      const width = Math.max(240, rect.width);
      const height = Math.max(240, rect.height);
      globe.width(width).height(height);
      globe.pointOfView(Object.assign({}, cameraTarget, { altitude: stageAltitude() }), 0);
    };
    resize();
    new ResizeObserver(resize).observe(host);
  }

  function applyGlobeTexture() {
    if (!globe) return;
    globe.globeImageUrl("assets/textures/" + state.layer[state.body] + ".jpg");
  }

  let pinScale = 2;
  let pinScaleTimer = null;

  function updatePinScale() {
    if (!globe) return;
    const altitude = (globe.pointOfView() || {}).altitude || 2.2;
    pinScale = 0.8 + altitude * 0.55;
    globe.pointRadius((d) => d.radius * pinScale);
    globe.ringMaxRadius((d) => (d.selected ? 5 : 2.6) * (pinScale / 2));
  }

  function schedulePinScale() {
    if (pinScaleTimer) clearTimeout(pinScaleTimer);
    pinScaleTimer = setTimeout(updatePinScale, 120);
  }

  function renderGlobePoints() {
    if (!globe) return;
    const selectedId = state.selected[state.body];
    const rank = new Map(sortedSites(state.body).map((row, index) => [row.site.id, index]));
    const points = activeSites().map((site) => {
      const card = scoreFor(site);
      const isSelected = site.id === selectedId;
      return {
        id: site.id,
        name: site.name,
        region: site.region,
        lat: site.lat,
        lng: site.lon,
        color: isSelected ? "#fff3d6" : GRADE_COLOR[card.letter],
        radius: isSelected ? 1.25 : 0.9,
        // Rank-staggered height keeps polar pins from collapsing into one blob.
        alt: isSelected ? 0.05 : 0.014 + (rank.get(site.id) || 0) * 0.005 + (card.value / 100) * 0.012
      };
    });
    globe.pointsData(points);
    updatePinScale();
    updateRings();
  }

  function updateRings() {
    if (!globe) return;
    const selectedId = state.selected[state.body];
    const rings = activeSites().map((site) => ({
      lat: site.lat,
      lng: site.lon,
      selected: site.id === selectedId
    }));
    if (state.point) {
      rings.push({ lat: state.point.conditions.lat, lng: state.point.conditions.lon, selected: true, query: true });
    }
    globe
      .ringsData(rings)
      .ringColor((d) => (t) =>
        d.query
          ? "rgba(99,224,206," + (1 - t) * 0.9 + ")"
          : d.selected
          ? "rgba(245,166,35," + (1 - t) * 0.85 + ")"
          : "rgba(236,230,216," + (1 - t) * 0.32 + ")"
      )
      .ringMaxRadius((d) => (d.selected ? 5 : 2.6))
      .ringPropagationSpeed(1.8)
      .ringRepeatPeriod((d) => (d.selected ? 900 : 2200));
  }

  function stageAltitude() {
    const host = document.getElementById("view-globe");
    if (!host) return 2.4;
    const rect = host.getBoundingClientRect();
    const aspect = rect.width / Math.max(1, rect.height);
    const halfFov = Math.atan(Math.tan((25 * Math.PI) / 180) * Math.min(aspect, 1));
    return Math.min(7, Math.max(1.15, 1 / Math.sin(halfFov * 0.8) - 1));
  }

  function highlightOnStage(fly = true) {
    const site = selectedSite();
    if (state.body === "earth") {
      renderEarthMarkers();
      if (fly && site && earthMap) earthMap.flyTo([site.lat, site.lon], Math.max(earthMap.getZoom(), 2.5), { duration: 0.8 });
      return;
    }
    renderGlobePoints();
    if (fly && site && globe) {
      cameraTarget = { lat: site.lat * 0.8, lng: site.lon };
      globe.pointOfView(Object.assign({}, cameraTarget, { altitude: stageAltitude() }), 900);
    }
  }

  function handleGlobeClick(lat, lng) {
    queryPoint(state.body, lat, lng);
  }

  /* --------------------------------------------------------------- earth */
  function ensureEarthMap() {
    if (earthMap) return;
    earthMap = L.map("view-earth", {
      zoomControl: false,
      attributionControl: false,
      worldCopyJump: true,
      minZoom: 1,
      maxZoom: 6,
      zoomSnap: 0.5
    }).setView([12, 15], 2);

    L.control.zoom({ position: "bottomright" }).addTo(earthMap);

    const offlineBase = L.imageOverlay("assets/textures/earth_base.jpg", [[-85, -180], [85, 180]], {
      opacity: 1
    });
    const liveBase = L.tileLayer(
      "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
      { opacity: 1, maxNativeZoom: 8, tileSize: 256, crossOrigin: true }
    );
    earthLayers.earth_base = L.layerGroup([offlineBase, liveBase]);

    earthLayers.earth_temp = L.imageOverlay("assets/grids/earth-temp.png", [[-90, -180], [90, 180]], {
      opacity: 0.92,
      interactive: false
    });

    earthMap.on("click", (event) => {
      const nearest = R.nearestEarth(SITES.earth, event.latlng.lat, event.latlng.lng);
      if (nearest && nearest.km < 700) {
        selectSite(nearest.site.id);
      } else {
        $("#legend").innerHTML =
          '<p class="eyebrow">Nearest analog</p><p class="mt-1 text-[11px] leading-relaxed text-muted">' +
          (nearest ? nearest.site.name + " is " + fmt(nearest.km) + " km away." : "No analog nearby.") + "</p>";
      }
    });
  }

  /* ------------------------------------------- computed Earth field layers */
  const FIELD_W = 720;
  const FIELD_H = 360;
  const FIELD_MASK_KM = 2200;

  const FIELD_RAMP = [
    [0.0, [9, 22, 66]],
    [0.3, [30, 96, 152]],
    [0.52, [56, 186, 168]],
    [0.74, [233, 178, 68]],
    [1.0, [247, 219, 172]]
  ];

  function rampAt(t) {
    const v = Math.min(1, Math.max(0, t));
    for (let i = 0; i < FIELD_RAMP.length - 1; i += 1) {
      const [p0, c0] = FIELD_RAMP[i];
      const [p1, c1] = FIELD_RAMP[i + 1];
      if (v <= p1) {
        const f = (v - p0) / Math.max(1e-6, p1 - p0);
        return [
          Math.round(c0[0] + (c1[0] - c0[0]) * f),
          Math.round(c0[1] + (c1[1] - c0[1]) * f),
          Math.round(c0[2] + (c1[2] - c0[2]) * f)
        ];
      }
    }
    return FIELD_RAMP[FIELD_RAMP.length - 1][1];
  }

  function fieldDistanceKm(lat1, lon1, lat2, lon2) {
    const p = Math.PI / 180;
    const dLat = (lat2 - lat1) * p;
    const dLon = (lon2 - lon1) * p;
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * p) * Math.cos(lat2 * p) * Math.sin(dLon / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  /* Inverse-distance interpolation, masked by distance to the nearest real site
     so the layer never invents a value in the middle of an empty ocean. */
  function buildFieldCanvas(points, lo, hi) {
    const span = Math.max(1e-6, hi - lo);
    const canvas = document.createElement("canvas");
    canvas.width = FIELD_W;
    canvas.height = FIELD_H;
    const ctx = canvas.getContext("2d");
    const image = ctx.createImageData(FIELD_W, FIELD_H);
    const data = image.data;

    for (let y = 0; y < FIELD_H; y += 1) {
      const lat = 90 - ((y + 0.5) * 180) / FIELD_H;
      for (let x = 0; x < FIELD_W; x += 1) {
        const lon = -180 + ((x + 0.5) * 360) / FIELD_W;
        let wSum = 0;
        let vSum = 0;
        let nearest = Infinity;
        for (let i = 0; i < points.length; i += 1) {
          const p = points[i];
          const d = fieldDistanceKm(lat, lon, p.lat, p.lon);
          if (d < nearest) nearest = d;
          const w = Math.exp(-(d * d) / (2 * 820 * 820)) + 0.02 / Math.max(d, 200);
          wSum += w;
          vSum += w * p.value;
        }
        const idx = (y * FIELD_W + x) * 4;
        if (!wSum || nearest > FIELD_MASK_KM) {
          data[idx + 3] = 0;
          continue;
        }
        const value = vSum / wSum;
        const rgb = rampAt((value - lo) / span);
        const fade = Math.min(1, Math.max(0, (FIELD_MASK_KM - nearest) / 600));
        data[idx] = rgb[0];
        data[idx + 1] = rgb[1];
        data[idx + 2] = rgb[2];
        data[idx + 3] = Math.round(fade * 200);
      }
    }
    ctx.putImageData(image, 0, 0);
    return canvas.toDataURL("image/png");
  }

  function fieldPoints(kind) {
    if (kind === "suit") {
      const points = SITES.earth.map((site) => ({
        lat: site.lat,
        lon: site.lon,
        value: scoreFor(site).value
      }));
      const values = points.map((p) => p.value);
      return { points, lo: Math.min(...values), hi: Math.max(...values) };
    }
    if (kind === "twin") {
      if (!state.twinSource) return null;
      const points = SITES.earth.map((site) => ({
        lat: site.lat,
        lon: site.lon,
        value: R.similarity(state.twinSource, site).score
      }));
      const values = points.map((p) => p.value);
      return { points, lo: Math.min(...values), hi: Math.max(...values) };
    }
    return null;
  }

  function refreshFieldLayer() {
    if (!earthMap || state.body !== "earth") return;
    const active = LAYERS.earth.find((l) => l.id === state.layer.earth);
    if (!active || (active.kind !== "suit" && active.kind !== "twin")) return;

    const field = fieldPoints(active.kind);
    if (!field) return;
    const url = buildFieldCanvas(field.points, field.lo, field.hi);
    if (earthLayers.earth_field) earthMap.removeLayer(earthLayers.earth_field);
    earthLayers.earth_field = L.imageOverlay(url, [[-90, -180], [90, 180]], {
      opacity: 0.88,
      interactive: false
    }).addTo(earthMap);
    earthLayers.earth_field.bringToFront();
    state.fieldRange = { kind: active.kind, lo: field.lo, hi: field.hi };
    renderLayers();
  }

  function applyEarthLayer() {
    if (!earthMap) return;
    ["earth_temp", "earth_field"].forEach((key) => {
      if (earthLayers[key] && earthMap.hasLayer(earthLayers[key])) earthMap.removeLayer(earthLayers[key]);
    });
    earthLayers.earth_base.addTo(earthMap);

    const active = LAYERS.earth.find((l) => l.id === state.layer.earth);
    if (!active) return;
    if (active.kind === "temp") {
      earthLayers.earth_temp.addTo(earthMap);
      earthLayers.earth_temp.bringToFront();
    } else if (active.kind === "suit" || active.kind === "twin") {
      refreshFieldLayer();
    }
    renderEarthMarkers();
  }

  function renderEarthMarkers() {
    if (!earthMap) return;
    earthMarkers.forEach((marker) => earthMap.removeLayer(marker));
    earthMarkers = [];

    const twin = state.twinSource;
    earthMap.eachLayer((layer) => {
      if (layer instanceof L.Circle) earthMap.removeLayer(layer);
    });

    SITES.earth.forEach((site) => {
      const card = scoreFor(site);
      const isSelected = state.selected.earth === site.id;
      const marker = L.circleMarker([site.lat, site.lon], {
        radius: isSelected ? 9 : 6.5,
        color: isSelected ? "#f5a623" : GRADE_COLOR[card.letter],
        weight: isSelected ? 2.4 : 1.4,
        fillColor: GRADE_COLOR[card.letter],
        fillOpacity: 0.85
      }).addTo(earthMap);

      marker.bindTooltip(site.name + " — grade " + card.letter, { direction: "top", offset: [0, -6] });
      marker.on("click", () => selectSite(site.id));
      earthMarkers.push(marker);

      if (isSelected) {
        L.circle([site.lat, site.lon], {
          radius: 120000,
          color: "rgba(245,166,35,0.5)",
          weight: 1,
          fillColor: "rgba(245,166,35,0.1)",
          fillOpacity: 1
        }).addTo(earthMap);
      }
    });
  }

  /* -------------------------------------------------------------- layers */
  function renderLayers() {
    const host = $("#layer-controls");
    host.innerHTML = "";
    LAYERS[state.body].forEach((layer) => {
      const btn = el("button", "layer-btn", layer.label);
      btn.type = "button";
      btn.setAttribute("aria-pressed", String(state.layer[state.body] === layer.id));
      btn.addEventListener("click", () => {
        state.layer[state.body] = layer.id;
        renderLayers();
        if (state.body === "earth") applyEarthLayer();
        else applyGlobeTexture();
      });      host.appendChild(btn);
    });

    const active = LAYERS[state.body].find((l) => l.id === state.layer[state.body]);
    const sourceNote =
      state.body === "earth"
        ? "Computed from NASA POWER + ETOPO1 · cached offline"
        : state.body === "moon"
        ? "NASA Moon Trek (LRO)"
        : "NASA Mars Trek (MGS/TES)";

    let scale = "";
    if (state.body === "earth" && active) {
      if (active.kind === "temp") {
        const meta = window.RADIUM_GRID_EARTH && window.RADIUM_GRID_EARTH.layer;
        if (meta) {
          scale =
            '<div class="mt-2 h-1.5 w-full rounded-full" style="background:linear-gradient(90deg,#091642,#1e6098,#3abaA8,#e9b244,#f7dbac)"></div>' +
            '<div class="mt-1 flex justify-between text-[10px] tabular-nums text-muted"><span>' +
            fmt(meta.min, 0) + " °C</span><span>" + fmt(meta.max, 0) + " °C</span></div>";
        }
      } else if (active.kind === "suit") {
        const range = state.fieldRange && state.fieldRange.kind === "suit" ? state.fieldRange : null;
        scale =
          '<div class="mt-2 h-1.5 w-full rounded-full" style="background:linear-gradient(90deg,#091642,#1e6098,#38baA8,#e9b244,#f7dbac)"></div>' +
          '<div class="mt-1 flex justify-between text-[10px] tabular-nums text-muted"><span>' +
          (range ? fmt(range.lo, 0) + " pts" : "weak") + "</span><span>" +
          (range ? fmt(range.hi, 0) + " pts" : "strong") + "</span></div>";
      } else if (active.kind === "twin") {
        const range = state.fieldRange && state.fieldRange.kind === "twin" ? state.fieldRange : null;
        scale = state.twinSource
          ? '<div class="mt-2 h-1.5 w-full rounded-full" style="background:linear-gradient(90deg,#091642,#1e6098,#38baA8,#e9b244,#f7dbac)"></div>' +
            '<div class="mt-1 flex justify-between text-[10px] tabular-nums text-muted"><span>closest ' +
            (range ? fmt(range.lo, 0) : "—") + "%</span><span>best " + (range ? fmt(range.hi, 0) : "—") + "%</span></div>"
          : '<p class="mt-2 text-[10px] leading-relaxed text-amber/80">Pick a Moon/Mars site or click the globe first, then reopen Earth Twin mode to light up this field.</p>';
      }
    }

    $("#legend").innerHTML =
      '<p class="eyebrow">Layer</p>' +
      '<p class="mt-1 text-[11px] leading-relaxed text-bone">' + (active ? active.legend : "") + "</p>" +
      scale +
      '<p class="mt-1 text-[10px] uppercase tracking-widest text-muted">' + sourceNote + "</p>";
  }

  /* -------------------------------------------------------------- detail */
  const MEASUREMENTS = {
    moon: (s) => [
      ["Day temp", fmt(s.tempDayC) + " °C"],
      ["Night temp", fmt(s.tempNightC) + " °C"],
      ["Peak illumination", fmt(s.illuminationPct) + " %"],
      ["Slope", fmt(s.slopeDeg, 1) + "°"],
      ["Water ice", fmt(s.iceIndex) + " / 100"],
      ["Ice distance", fmt(s.iceDistanceKm) + " km"],
      ["Earth visibility", fmt(s.earthVisibilityPct) + " %"],
      ["Elevation", fmt(s.elevationM) + " m"]
    ],
    mars: (s) => [
      ["Day temp", fmt(s.tempDayC) + " °C"],
      ["Night temp", fmt(s.tempNightC) + " °C"],
      ["Pressure", fmt(s.pressurePa) + " Pa"],
      ["Slope", fmt(s.slopeDeg, 1) + "°"],
      ["Subsurface ice", fmt(s.iceIndex) + " / 100"],
      ["Ice distance", fmt(s.iceDistanceKm) + " km"],
      ["Dust index", fmt(s.dustIndex) + " / 100"],
      ["Solar", fmt(s.solarKwh, 1) + " kWh/m²"]
    ],
    earth: (s) => [
      ["Mean temp", fmt(s.tempMeanC, 1) + " °C"],
      ["Max / min", fmt(s.tempDayC, 1) + " / " + fmt(s.tempNightC, 1) + " °C"],
      ["Pressure", fmt(s.pressurePa / 1000, 1) + " kPa"],
      ["Slope", fmt(s.slopeDeg, 1) + "°"],
      ["Roughness (5-pt)", fmt(s.roughnessM, 0) + " m"],
      ["Solar", fmt(s.solarKwh, 1) + " kWh/m²"],
      ["Humidity", fmt(s.humidityPct, 0) + " %"],
      ["Precipitation", fmt(s.precipMmDay, 2) + " mm/d"]
    ]
  };

  function renderPointDetail(host) {
    const point = state.point;
    const meta = GRID_META[point.body];    const c = point.conditions;
    const tiles = [
      ["Day temp", fmt(c.tempDayC, 0) + " °C"],
      ["Night temp", fmt(c.tempNightC, 0) + " °C"],
      ["Day/night swing", fmt(c.tempDayC - c.tempNightC, 0) + " K"],
      ["Slope", fmt(c.slopeDeg, 1) + "°"],
      ["Roughness", fmt(c.roughnessM, 0) + " m"],
      ["Elevation", fmt(c.elevationM, 0) + " m"]
    ]
      .map(
        ([label, value]) =>
          '<div class="rounded-xl border border-white/[0.06] bg-white/[0.02] px-2.5 py-2">' +
          '<p class="text-[10px] uppercase tracking-wider text-muted">' + label + "</p>" +
          '<p class="mt-0.5 text-[13px] tabular-nums text-bone">' + value + "</p></div>"
      )
      .join("");

    const rows = point.matches
      .map(
        (m, i) =>
          '<button type="button" class="site-row !py-1.5" data-point-match="' + m.site.id + '">' +
            '<span class="grid h-8 w-11 shrink-0 place-items-center rounded-lg border border-ice/25 bg-ice/[0.08] text-[12px] tabular-nums text-ice">' + m.match.score + "</span>" +
            '<span class="min-w-0 flex-1"><span class="block truncate text-[12px] text-bone">' + m.site.name + "</span>" +
            '<span class="block truncate text-[10px] text-muted">' + m.site.region + "</span></span>" +
          "</button>"
      )
      .join("");

    const tempMeta = meta.layers.tempDayC;
    const best = point.matches[0];
    const why = best
      ? '<div class="mt-2 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">' +
          '<p class="eyebrow">Why ' + best.site.name + ' matches</p>' +
          best.match.parts
            .map((part) => {
              const color = part.match >= 70 ? "#6fe7b0" : part.match >= 45 ? "#f5c451" : "#de6a45";
              return (
                '<div class="mt-1.5 flex items-center gap-2">' +
                  '<span class="w-[92px] shrink-0 text-[10px] uppercase tracking-wider text-muted">' + part.label + "</span>" +
                  '<span class="bar flex-1"><span style="width:' + part.match + "%;background:" + color + '"></span></span>' +
                  '<span class="w-7 text-right text-[10px] tabular-nums text-muted">' + part.match + "</span>" +
                "</div>"
              );
            })
            .join("") +
        "</div>"
      : "";
    host.innerHTML =
      '<div class="fade-in">' +
        '<div class="flex items-start gap-3">' +
          '<span class="grid h-12 w-12 shrink-0 place-items-center rounded-[14px] border border-ice/40 bg-ice/[0.10] text-ice">' +
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11Z" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="10" r="2.4" stroke="currentColor" stroke-width="1.6"/></svg>' +
          "</span>" +
          '<div class="min-w-0">' +
            '<p class="eyebrow">Point query · ' + BODY_META[point.body].label + "</p>" +
            '<h2 class="mt-1 font-display text-[1.5rem] leading-tight">' + point.site.name + "</h2>" +
            '<p class="mt-1 text-[11px] text-muted">Sampled from 0.5° mission grids, not a curated pin</p>' +
          "</div>" +
        "</div>" +
        '<div class="mt-3 grid grid-cols-2 gap-1.5">' + tiles + "</div>" +
        '<div class="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">' +
          '<p class="eyebrow">How this was measured</p>' +
          '<p class="mt-1 text-[11px] leading-relaxed text-muted">Terrain: ' + meta.provenance.terrain +
            ". Temperature: " + tempMeta.model + " (RMSE ±" + tempMeta.rmseK + " K).</p>" +
          '<p class="mt-1 text-[10px] leading-relaxed text-muted/80">Water ice and dust are not resolved at this resolution, so they are excluded from the match rather than guessed.</p>' +
        "</div>" +
        '<div class="mt-4"><div class="flex items-center justify-between gap-2">' +
          '<p class="eyebrow">Closest Earth analogs</p>' +
          '<button type="button" class="layer-btn !py-1 !text-[10px]" data-point-open="1">Open on Earth</button>' +
        "</div>" +
        why +
        '<div class="mt-2 space-y-1">' + rows + "</div></div>" +
      "</div>";
  }

  /* ------------------------------------------------------------- imagery */
  function googleMapsLinks(lat, lon) {
    const coords = lat.toFixed(5) + "," + lon.toFixed(5);
    return {
      street: "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=" + coords,
      map: "https://www.google.com/maps/search/?api=1&query=" + coords,
      world:
        "https://worldview.earthdata.nasa.gov/?v=" +
        (lon - 6).toFixed(2) + "," + (lat - 4).toFixed(2) + "," +
        (lon + 6).toFixed(2) + "," + (lat + 4).toFixed(2) +
        "&l=Reference_Labels_15m(hidden),Reference_Features_15m(hidden),Coastlines_15m,MODIS_Terra_CorrectedReflectance_TrueColor&t=2024-07-01"
    };
  }

  function imageryBlock(site) {
    if (site.body === "earth") return earthImagery(site);
    return pinImagery(site);
  }

  function pinImagery(site) {
    const src = (window.RADIUM_PIN_THUMBS || {})[site.body + ":" + site.id];
    if (!src) return "";
    const source =
      site.body === "moon"
        ? "LRO WAC mosaic, 303 ppd (NASA Moon Trek)"
        : "Viking MDIM 2.1 colour mosaic (NASA Mars Trek)";
    return (
      '<div class="mt-4">' +
        '<p class="eyebrow">Surface at this site</p>' +
        '<figure class="mt-1.5 overflow-hidden rounded-xl border border-white/[0.08]">' +
          '<img src="' + src + '" alt="Mosaic view of ' + site.name + '" loading="lazy" ' +
            'class="h-40 w-full object-cover" />' +
          '<figcaption class="border-t border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-[10px] leading-relaxed text-muted">' +
            source + " · 0.5° field of view" +
          "</figcaption>" +
        "</figure>" +
      "</div>"
    );
  }

  function earthImagery(site) {
    const entry = (window.RADIUM_PHOTOS || {})[site.id];
    const links = googleMapsLinks(site.lat, site.lon);
    const parts = [];

    if (entry && entry.satellite) {
      parts.push(
        '<figure class="overflow-hidden rounded-xl border border-white/[0.08]">' +
          '<img src="' + entry.satellite.file + '" alt="Sentinel-2 satellite view of ' + site.name + '" ' +
            'loading="lazy" class="h-36 w-full object-cover" />' +
          '<figcaption class="border-t border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-[10px] leading-relaxed text-muted">' +
            "Satellite · " +
            '<a class="text-ice/90 underline decoration-ice/30 underline-offset-2" href="' + entry.satellite.url +
            '" target="_blank" rel="noopener noreferrer">' + entry.satellite.credit + "</a>" +
          "</figcaption>" +
        "</figure>"
      );
    }

    if (entry && entry.photos && entry.photos.length) {
      entry.photos.forEach((photo) => {
        parts.push(
          '<figure class="overflow-hidden rounded-xl border border-white/[0.08]">' +
            '<img src="' + photo.file + '" alt="' + photo.title.replace(/"/g, "&quot;") + '" ' +
              'loading="lazy" class="h-36 w-full object-cover" />' +
            '<figcaption class="border-t border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-[10px] leading-relaxed text-muted">' +
              "Ground view · " + photo.author +
              (photo.licenseUrl
                ? ' · <a class="text-ice/90 underline decoration-ice/30 underline-offset-2" href="' + photo.licenseUrl +
                  '" target="_blank" rel="noopener noreferrer">' + photo.license + "</a>"
                : " · " + photo.license) +
              ' · <a class="text-ice/90 underline decoration-ice/30 underline-offset-2" href="' + photo.page +
              '" target="_blank" rel="noopener noreferrer">Commons</a>' +
            "</figcaption>" +
          "</figure>"
        );
      });
    }

    const body = parts.length
      ? parts.join("")
      : '<p class="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 text-[11px] leading-relaxed text-muted">No licensed ground photography is available for this site. Use the satellite buttons below.</p>';

    return (
      '<div class="mt-4">' +
        '<div class="flex items-baseline justify-between gap-2">' +
          '<p class="eyebrow">How this site looks</p>' +
          '<span class="text-[10px] text-muted">real imagery</span>' +
        "</div>" +
        '<div class="mt-1.5 space-y-1.5">' + body + "</div>" +
        '<div class="mt-2 flex flex-wrap gap-1.5">' +
          '<a class="layer-btn" href="' + links.street + '" target="_blank" rel="noopener noreferrer">Street View ↗</a>' +
          '<a class="layer-btn" href="' + links.map + '" target="_blank" rel="noopener noreferrer">Google Maps ↗</a>' +
          '<a class="layer-btn" href="' + links.world + '" target="_blank" rel="noopener noreferrer">NASA Worldview ↗</a>' +
        "</div>" +
        '<p class="mt-1.5 text-[10px] leading-relaxed text-muted/80">Street View opens Google Maps at these coordinates; coverage varies by site. Photos are Creative Commons licensed and credited.</p>' +
      "</div>"
    );
  }

  function renderDetail() {
    const host = $("#detail");
    if (state.point) {
      renderPointDetail(host);
      return;
    }
    const site = selectedSite();
    if (!site) {
      host.innerHTML =
        '<div class="flex h-full min-h-[240px] flex-col items-start justify-center gap-2">' +
        '<p class="eyebrow">No site selected</p>' +
        '<p class="font-display text-2xl">Pick a pin to open its dossier</p>' +
        '<p class="text-xs leading-relaxed text-muted">Every pin carries a letter grade, eight rubric sub-scores, the raw measurements behind them and a citation.</p>' +
        "</div>";
      return;
    }

    const card = scoreFor(site);
    const rows = MEASUREMENTS[site.body](site);
    const rubric = R.RUBRIC.map((r) => {
      const value = card.dims[r.key];
      const color = value >= 74 ? "var(--grade-a)" : value >= 54 ? "var(--grade-c)" : "var(--grade-e)";
      return (
        '<div class="flex items-center gap-2">' +
          '<span class="w-[86px] shrink-0 text-[10px] uppercase tracking-wider text-muted">' + r.short + "</span>" +
          '<span class="bar flex-1"><span style="width:' + fmt(value, 0) + "%;background:" + color + '"></span></span>' +
          '<span class="w-7 text-right text-[11px] tabular-nums text-muted">' + fmt(value, 0) + "</span>" +
        "</div>"
      );
    }).join("");

    const measurements = rows
      .map(
        ([label, value]) =>
          '<div class="rounded-xl border border-white/[0.06] bg-white/[0.02] px-2.5 py-2">' +
          '<p class="text-[10px] uppercase tracking-wider text-muted">' + label + "</p>" +
          '<p class="mt-0.5 text-[13px] tabular-nums text-bone">' + value + "</p></div>"
      )
      .join("");

    host.innerHTML =
      '<div class="fade-in">' +
        '<div class="flex items-start gap-3">' +
          '<span class="grade shrink-0" style="width:3rem;height:3rem;font-size:1.3rem;border-radius:14px;color:' +
            GRADE_COLOR[card.letter] + ";background:" + GRADE_COLOR[card.letter] + '16">' + card.letter + "</span>" +
          '<div class="min-w-0">' +
            '<p class="eyebrow">' + BODY_META[site.body].label + " · " + fmt(card.value, 1) + " / 100</p>" +
            '<h2 class="mt-1 font-display text-[1.55rem] leading-tight">' + site.name + "</h2>" +
            '<p class="mt-1 text-[11px] text-muted">' + site.region + "</p>" +
          "</div>" +
        "</div>" +
        '<div class="mt-2 flex flex-wrap gap-1.5">' +
          '<span class="chip">' + fmt(Math.abs(site.lat), 2) + "° " + (site.lat >= 0 ? "N" : "S") + "</span>" +
          '<span class="chip">' + fmt(Math.abs(site.lon), 2) + "° " + (site.lon >= 0 ? "E" : "W") + "</span>" +
          (site.confidence ? '<span class="chip">' + site.confidence + " confidence</span>" : "") +
        "</div>" +
        '<div class="mt-3 grid grid-cols-2 gap-1.5">' + measurements + "</div>" +
        '<div class="mt-4"><p class="eyebrow">Rubric sub-scores</p><div class="mt-2 space-y-1.5">' + rubric + "</div></div>" +
        (site.analog
          ? '<div class="mt-4 rounded-xl border border-amber/20 bg-amber/[0.06] p-3">' +
              '<p class="eyebrow text-amber/80">Why it is analogous</p>' +
              '<p class="mt-1 text-[12px] leading-relaxed text-bone/90">' + site.analog + "</p>" +
              '<p class="mt-2 eyebrow text-[10px]">Where it breaks down</p>' +
              '<p class="mt-1 text-[11px] leading-relaxed text-muted">' + site.limits + "</p></div>"
          : "") +
        imageryBlock(site) +
        twinBlock(site) +
        '<a class="mt-4 inline-flex items-center gap-1 text-[11px] text-ice underline decoration-ice/40 underline-offset-4 hover:decoration-ice" href="' +
          site.source.url + '" target="_blank" rel="noopener noreferrer">' + site.source.label + " ↗</a>" +
      "</div>";
  }

  function twinBlock(site) {
    if (site.body === "earth") {
      return (
        '<div class="mt-4 rounded-xl border border-white/[0.07] p-3">' +
          '<p class="eyebrow">Provenance</p>' +
          '<p class="mt-1 text-[11px] leading-relaxed text-muted">Climate: ' + site.provenance.climate + " · Terrain: " + site.provenance.terrain + "</p>" +
          '<p class="mt-2 text-[10px] leading-relaxed text-muted/80">POWER reports 0.5° grid-cell climatology, so summits read warmer than in-situ stations.</p>' +
        "</div>"
      );
    }

    const twins = R.topTwins(SITES.earth, site, 3);
    const rows = twins
      .map(
        (t) =>
          '<button type="button" class="site-row !py-1.5" data-twin="' + t.site.id + '">' +
            '<span class="grid h-8 w-11 shrink-0 place-items-center rounded-lg border border-white/10 text-[12px] tabular-nums text-bone">' + t.match.score + "</span>" +
            '<span class="min-w-0 flex-1"><span class="block truncate text-[12px] text-bone">' + t.site.name + "</span>" +
            '<span class="block truncate text-[10px] text-muted">' + t.site.region + "</span></span>" +
          "</button>"
      )
      .join("");

    return (
      '<div class="mt-4 rounded-xl border border-ice/20 bg-ice/[0.05] p-3">' +
        '<div class="flex items-center justify-between gap-2">' +
          '<p class="eyebrow text-ice/80">Earth twin mode</p>' +
          '<button type="button" class="layer-btn !py-1 !text-[10px]" data-open-twin="' + site.id + '">Open on Earth</button>' +
        "</div>" +
        '<p class="mt-1 text-[11px] leading-relaxed text-muted">Closest terrestrial matches across temperature, solar, terrain, water and dust. Atmosphere is excluded — no Earth site reproduces a vacuum or ~0.6 kPa.</p>' +
        '<div class="mt-2 space-y-1">' + rows + "</div>" +
      "</div>"
    );
  }

  /* ------------------------------------------------------------ twin mode */
  function renderTwinBanner() {
    const host = $("#twin-banner");
    if (!state.twinSource || state.body !== "earth") {
      host.classList.add("hidden");
      host.innerHTML = "";
      return;
    }
    const twins = R.topTwins(SITES.earth, state.twinSource, 3);
    host.classList.remove("hidden");
    host.innerHTML =
      '<div class="flex flex-wrap items-center gap-2 rounded-xl border border-ice/25 bg-[#061019]/85 px-3 py-2 backdrop-blur-md">' +
        '<span class="eyebrow text-ice/80">Earth twin</span>' +
        '<span class="text-[12px] text-bone">for ' + state.twinSource.name + "</span>" +
        twins.map((t) =>
          '<button type="button" class="layer-btn !py-1" data-twin="' + t.site.id + '">' +
            t.site.name + ' <span class="tabular-nums text-ice">' + t.match.score + "</span></button>"
        ).join("") +
        '<button type="button" class="layer-btn !py-1 ml-auto" data-close-twin="1" aria-label="Exit twin mode">Exit</button>' +
      "</div>";
    if (state.body === "earth") renderRail();
    renderLayers();
    if (state.body === "earth") applyEarthLayer();
  }

  function openTwin(siteId) {
    const source = Object.values(SITES).flat().find((s) => s.id === siteId);
    if (!source) return;
    state.twinSource = source;
    state.layer.earth = "earth_twin";
    setBody("earth");
    const best = R.topTwins(SITES.earth, source, 1)[0];
    if (best) selectSite(best.site.id);
    renderTwinBanner();
  }

  /* ------------------------------------------------------ mission designer */
  function renderWeightControls() {
    $("#weight-controls").innerHTML = R.RUBRIC.map((r) => {
      const value = Math.round((state.weights[r.key] || 0) * 100);
      return (
        '<label class="block">' +
          '<span class="flex items-baseline justify-between gap-2 text-[11px]">' +
            '<span class="text-bone">' + r.label + "</span>" +
            '<span class="tabular-nums text-muted" data-weight-value="' + r.key + '">' + value + "%</span>" +
          "</span>" +
          '<input type="range" min="0" max="40" step="1" value="' + value + '" data-weight="' + r.key +
            '" aria-label="' + r.label + ' importance">' +
        "</label>"
      );
    }).join("");
  }

  function refreshScores() {
    renderRail();
    renderDetail();
    if (state.body === "earth") {
      renderEarthMarkers();
      const active = LAYERS.earth.find((l) => l.id === state.layer.earth);
      if (active && active.kind === "suit") refreshFieldLayer();
    } else renderGlobePoints();
  }

  const PRESETS = {
    balanced: R.DEFAULT_WEIGHTS,
    ice: { geology: 0.08, terrain: 0.14, environment: 0.12, resources: 0.34, processes: 0.06, habitability: 0.05, subsurface: 0.05, operations: 0.16 },
    solar: { geology: 0.08, terrain: 0.14, environment: 0.18, resources: 0.10, processes: 0.06, habitability: 0.05, subsurface: 0.05, operations: 0.34 },
    science: { geology: 0.30, terrain: 0.08, environment: 0.06, resources: 0.10, processes: 0.04, habitability: 0.24, subsurface: 0.14, operations: 0.04 },
    landing: { geology: 0.08, terrain: 0.34, environment: 0.14, resources: 0.08, processes: 0.06, habitability: 0.03, subsurface: 0.03, operations: 0.24 }
  };

  /* -------------------------------------------------------------- sources */
  function renderSources() {
    const dataRows = [
      ["LRO WAC global mosaic", "Moon Trek WMTS, 303 ppd", "https://trek.nasa.gov/moon/"],
      ["Diviner average surface temperature", "Moon Trek WMTS, 32 ppd (day + night)", "https://pds-geosciences.wustl.edu/missions/lro/diviner.htm"],
      ["MGS MOLA colour shaded relief", "Mars Trek WMTS, 463 m", "https://pds-geosciences.wustl.edu/missions/mro/"],
      ["Viking MDIM 2.1 colour mosaic", "Mars Trek WMTS, 232 m", "https://astrogeology.usgs.gov/search?q=viking"],
      ["NASA POWER climatology", "2001-2020 monthly/annual means (MERRA-2, CERES)", "https://power.larc.nasa.gov/"],
      ["NOAA ETOPO1 elevation", "1 arc-minute global relief via OpenTopoData", "https://www.ngdc.noaa.gov/mgg/global/"],
      ["LOLA LDEM_4 (Moon DEM)", "4 pixels/deg int16, slope + relief computed here", "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/"],
      ["MOLA MEGDR (Mars DEM)", "16 pixels/deg int16 topography, slope + relief computed here", "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/"],
      ["MODIS Terra land surface temperature", "NASA GIBS daily swath (clear-sky only; replaced by the computed field below)", "https://gibs.earthdata.nasa.gov/"],
      ["Earth temperature field", "IDW of 40 NASA POWER climatologies, masked to 2,500 km", "https://power.larc.nasa.gov/"],
      ["Blue Marble shaded relief", "NASA GIBS (live tiles + cached fallback)", "https://worldview.earthdata.nasa.gov/"]
    ];

    $("#sources-body").innerHTML =
      '<p class="text-[13px] leading-relaxed text-bone/90">RADIUM separates three kinds of numbers, and the dossier says which is which:</p>' +
      '<ol class="mt-2 list-decimal space-y-1 pl-5 text-[12px] leading-relaxed text-muted">' +
        "<li><strong class=\"text-bone\">Measured rasters</strong> — the switchable globe/map layers are NASA products rendered from real mission data.</li>" +
        "<li><strong class=\"text-bone\">Computed point values</strong> — every Earth pin's temperature, pressure, solar, slope and roughness is calculated from POWER + ETOPO1 by <code>tools/fetch_earth_data.py</code>.</li>" +
        "<li><strong class=\"text-bone\">Compiled estimates</strong> — Moon/Mars site metrics (and the ice/dust/subsurface indices) are literature-derived with a confidence tag and a citation on each dossier.</li>" +
      "</ol>" +
      '<p class="mt-3 text-[12px] leading-relaxed text-muted">Scoring is deliberately explainable: each of the eight rubric rows is a closed-form function of a measurement (see <code>assets/scoring.js</code>), and the mission designer only changes the weights.</p>' +
      '<table class="mt-4 w-full text-left text-[12px]"><thead><tr class="text-[10px] uppercase tracking-wider text-muted">' +
        "<th class=\"pb-1\">Dataset</th><th class=\"pb-1\">Product</th><th class=\"pb-1\"></th></tr></thead><tbody>" +
        dataRows.map((r) =>
          '<tr class="border-t border-white/[0.06]"><td class="py-1.5 pr-2 text-bone">' + r[0] + "</td>" +
          '<td class="py-1.5 pr-2 text-muted">' + r[1] + "</td>" +
          '<td class="py-1.5"><a class="text-ice underline decoration-ice/40 underline-offset-2" href="' + r[2] + '" target="_blank" rel="noopener noreferrer">open</a></td></tr>'
        ).join("") +
      "</tbody></table>" +
      '<p class="mt-3 text-[10px] leading-relaxed text-muted/80">Earth gravity, the lunar vacuum, the thin Martian atmosphere and radiation environments are not reproducible on Earth. RADIUM grades only the measurable surface analog; that limitation is part of the analysis.</p>';
  }

  /* ---------------------------------------------------------------- events */
  document.addEventListener("click", (event) => {
    const pointMatch = event.target.closest("[data-point-match]");
    if (pointMatch) {
      openPointTwins(pointMatch.dataset.pointMatch);
      return;
    }
    if (event.target.closest("[data-point-open]")) {
      openPointTwins(null);
      return;
    }
    const twinBtn = event.target.closest("[data-twin]");
    if (twinBtn) {
      selectSite(twinBtn.dataset.twin);
      return;
    }
    const openBtn = event.target.closest("[data-open-twin]");
    if (openBtn) {
      openTwin(openBtn.dataset.openTwin);
      return;
    }
    if (event.target.closest("[data-close-twin]")) {
      state.twinSource = null;
      renderTwinBanner();
      renderRail();
      renderEarthMarkers();
    }
  });

  document.addEventListener("input", (event) => {
    const input = event.target.closest("[data-weight]");
    if (!input) return;
    const key = input.dataset.weight;
    state.weights[key] = Number(input.value) / 100;
    const readout = document.querySelector('[data-weight-value="' + key + '"]');
    if (readout) readout.textContent = input.value + "%";
    refreshScores();
  });

  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.weights = Object.assign({}, R.DEFAULT_WEIGHTS, PRESETS[btn.dataset.preset]);
      renderWeightControls();
      refreshScores();
    });
  });

  $("#btn-mission").addEventListener("click", () => $("#mission-dialog").showModal());
  $("#btn-sources").addEventListener("click", () => $("#sources-dialog").showModal());

  /* ------------------------------------------------------------------ boot */
  renderSources();
  renderWeightControls();
  renderTabs();

  /* Deep links: #earth:earth_twin, #mars, ... makes demo jumps and
     screenshot verification deterministic. */
  function applyHash() {
    const raw = (location.hash || "").replace(/^#/, "");
    if (!raw) return false;
    const [bodyKey, layerKey, targetId] = raw.split(":");
    if (!BODY_META[bodyKey]) return false;
    if (layerKey && LAYERS[bodyKey].some((l) => l.id === layerKey)) {
      state.layer[bodyKey] = layerKey;
    }
    if (targetId) {
      const target = Object.values(SITES).flat().find((s) => s.id === targetId);
      if (target && target.body !== "earth") state.twinSource = target;
    }
    setBody(bodyKey);
    if (targetId && SITES[bodyKey].some((s) => s.id === targetId)) {
      selectSite(targetId, bodyKey !== "earth");
    }
    return true;
  }

  if (!applyHash()) setBody("moon");
  if (state.body === "earth" && state.twinSource && !state.selected.earth) {
    const best = R.topTwins(SITES.earth, state.twinSource, 1)[0];
    if (best) selectSite(best.site.id, false);
  } else if (state.body !== "earth" && !state.selected[state.body]) {
    const top = sortedSites(state.body)[0];
    if (top) selectSite(top.site.id, true);
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
    if (state.twinSource && state.body === "earth") {
      state.twinSource = null;
      renderTwinBanner();
    }
  });

  window.RADIUM_APP = {
    state,
    SITES,
    selectSite,
    queryPoint,
    openPointTwins,
    setBody,
    setLayer: (body, layerId) => {
      state.layer[body] = layerId;
      if (state.body === body) {
        renderLayers();
        if (body === "earth") applyEarthLayer();
        else applyGlobeTexture();
      }
    }
  };
})();
