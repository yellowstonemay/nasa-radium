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
        "Terrain and climate for every Earth pin are computed from NOAA ETOPO1 samples and the NASA POWER 2001-2020 climatology.",
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
      { id: "earth_base", label: "Blue Marble", legend: "NASA Blue Marble shaded relief + bathymetry" },
      { id: "earth_temp", label: "Surface temp", legend: "MODIS Terra land surface temperature, 2024-07-01" },
      { id: "earth_lights", label: "Night lights", legend: "VIIRS Black Marble night lights (2016)" }
    ]
  };

  const state = {
    body: "moon",
    layer: { moon: "moon_base", mars: "mars_base", earth: "earth_base" },
    selected: { moon: null, mars: null, earth: null },
    weights: Object.assign({}, R.DEFAULT_WEIGHTS),
    twinSource: null
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
    state.body = body;
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
      if (top) selectSite(top.site.id);
    }
  }

  /* ---------------------------------------------------------------- rail */
  function renderRail() {
    const list = $("#rail-list");
    list.innerHTML = "";
    const rows = sortedSites(state.body);
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

  function selectSite(id) {
    state.selected[state.body] = id;
    renderRail();
    renderDetail();
    highlightOnStage();
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
      .pointAltitude(0.008)
      .pointRadius((d) => d.radius)
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

  function renderGlobePoints() {
    if (!globe) return;
    const points = activeSites().map((site) => {
      const card = scoreFor(site);
      return {
        id: site.id,
        name: site.name,
        region: site.region,
        lat: site.lat,
        lng: site.lon,
        color: GRADE_COLOR[card.letter],
        radius: state.selected[state.body] === site.id ? 0.95 : 0.5,
        alt: 0.004 + (card.value / 100) * 0.02
      };
    });
    globe.pointsData(points);

    const current = selectedSite();
    globe.ringsData(current ? [{ lat: current.lat, lng: current.lon }] : []);
  }

  function stageAltitude() {
    const host = document.getElementById("view-globe");
    if (!host) return 2.4;
    const rect = host.getBoundingClientRect();
    const aspect = rect.width / Math.max(1, rect.height);
    const halfFov = Math.atan(Math.tan((25 * Math.PI) / 180) * Math.min(aspect, 1));
    return Math.min(7, Math.max(1.15, 1 / Math.sin(halfFov * 0.8) - 1));
  }

  function highlightOnStage() {
    const site = selectedSite();
    if (state.body === "earth") {
      renderEarthMarkers();
      if (site && earthMap) earthMap.flyTo([site.lat, site.lon], Math.max(earthMap.getZoom(), 2.5), { duration: 0.8 });
      return;
    }
    renderGlobePoints();
    if (site && globe) {
      cameraTarget = { lat: site.lat * 0.8, lng: site.lon };
      globe.pointOfView(Object.assign({}, cameraTarget, { altitude: stageAltitude() }), 900);
    }
  }

  function handleGlobeClick(lat, lng) {
    const nearest = R.nearestEarth(activeSites(), lat, lng);
    if (nearest && nearest.km < 900) {
      selectSite(nearest.site.id);
      return;
    }
    const legend = $("#legend");
    legend.innerHTML =
      '<p class="eyebrow">No analyzed site nearby</p>' +
      '<p class="mt-1 text-[11px] leading-relaxed text-muted">RADIUM grades curated candidate sites, not arbitrary pixels. ' +
      "Nearest shortlisted site is " + (nearest ? fmt(nearest.km) + " km away (" + nearest.site.name + ")" : "unavailable") + ".</p>";
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

    earthLayers.earth_temp = L.tileLayer(
      "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_Land_Surface_Temp_Day/default/2024-07-01/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png",
      { opacity: 0.82, maxNativeZoom: 7, tileSize: 256, crossOrigin: true }
    );

    earthLayers.earth_lights = L.tileLayer(
      "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Night_Lights/default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png",
      { opacity: 0.9, maxNativeZoom: 8, tileSize: 256, crossOrigin: true }
    );

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

  function applyEarthLayer() {
    if (!earthMap) return;
    [earthLayers.earth_temp, earthLayers.earth_lights].forEach((layer) => earthMap.removeLayer(layer));
    earthLayers.earth_base.addTo(earthMap);
    const overlay = earthLayers[state.layer.earth];
    if (overlay && overlay !== earthLayers.earth_base) {
      overlay.addTo(earthMap);
      overlay.bringToFront();
    }
    earthMap.getContainer().style.background = state.layer.earth === "earth_lights" ? "#02040a" : "#05070f";
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
      });
      host.appendChild(btn);
    });

    const active = LAYERS[state.body].find((l) => l.id === state.layer[state.body]);
    const sourceNote =
      state.body === "earth"
        ? "Live NASA GIBS tiles · cached Blue Marble base"
        : state.body === "moon"
        ? "NASA Moon Trek (LRO)"
        : "NASA Mars Trek (MGS/TES)";
    $("#legend").innerHTML =
      '<p class="eyebrow">Layer</p>' +
      '<p class="mt-1 text-[11px] leading-relaxed text-bone">' + (active ? active.legend : "") + "</p>" +
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

  function renderDetail() {
    const host = $("#detail");
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
  }

  function openTwin(siteId) {
    const source = Object.values(SITES).flat().find((s) => s.id === siteId);
    if (!source) return;
    state.twinSource = source;
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
    if (state.body === "earth") renderEarthMarkers();
    else renderGlobePoints();
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
      ["MODIS Terra land surface temperature", "NASA GIBS, 2024-07-01", "https://gibs.earthdata.nasa.gov/"],
      ["VIIRS night lights / Blue Marble", "NASA GIBS", "https://worldview.earthdata.nasa.gov/"]
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
  setBody("moon");

  const bootTop = sortedSites("moon")[0];
  if (bootTop) selectSite(bootTop.site.id);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
    if (state.twinSource && state.body === "earth") {
      state.twinSource = null;
      renderTwinBanner();
    }
  });

  window.RADIUM_APP = { state, SITES, selectSite };
})();
