/* ==========================================================================
   30DMC KIT v3 (script). Shared by every day: load it after maplibre-gl.js.
   DAY = {
     n, title, deck, accent, author, nav, attribution, creditsEl,
     basemap:   a name or list from DMC.BASEMAPS (OneMap styles, satellite,
                CARTO, Black Marble). The first is visible, the rest start at 0.
     basemapBg, basemapPaint, underlay (a basemap always drawn beneath), underlayPaint,
     style:     a full MapLibre style (URL or object) instead of basemap rasters;
                styleCredit is then its credit line.
     bounds:    [[w, s], [e, n]] the map frames on (default: Singapore).
     maxBounds, minZoom, maxZoom,
     camera:    { pitch, bearing, tiltPitch } starting tilt and the 3D button's tilt.
     buildings: true = 3D buildings on at start, false = no buildings button.
     buildingsColor, buildingsOpacity, buildingsBefore (layer id), buildingsFocus ([lng, lat]).
   }
   Focus mode (F key or the eye button) hides every [data-dmc-overlay] and
   .dmc-chrome element and the map buttons, leaving only the map.
   ========================================================================== */
const DMC = (() => {
  const THEMES = ['Points', 'Lines', 'Polygons', 'Clusters', 'Sight', 'Vintage', '10 minute map', 'Utopia',
    'Urban-rural', 'Prompting only', 'Sound', 'Power', 'Interactions', 'Borgesian map', 'Inside out',
    'Collaborative map', 'Light & dark', 'NULL', 'Smell', 'Hexagons', 'OpenStreetMap', 'Projections',
    'Taste', 'Network', 'Is this a map?', 'Water', 'New tool', 'Feeling', 'Raster', 'Pen & paper'];
  const SG_BOUNDS = [[103.605, 1.215], [104.035, 1.47]];
  const CBD = [103.8535, 1.2835];
  const a = (href, text) => `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  const ONEMAP_CREDIT = '<img src="https://www.onemap.gov.sg/web-assets/images/logo/om_logo.png" alt="">'
    + a('https://www.onemap.gov.sg/', 'OneMap') + ' &copy; contributors &#124; ' + a('https://www.sla.gov.sg/', 'Singapore Land Authority');
  const OSM = '&copy; ' + a('https://www.openstreetmap.org/copyright', 'OpenStreetMap') + ' contributors';
  const CARTO = '&copy; ' + a('https://carto.com/attributions', 'CARTO') + ', ' + OSM;
  const BUILDINGS_CREDIT = '3D buildings: ' + a('https://openfreemap.org/', 'OpenFreeMap') + ', ' + a('https://www.openmaptiles.org/', '&copy; OpenMapTiles') + ', ' + OSM;
  const COMPACT_Q = '(max-width: 640px), (max-height: 520px)';   // phones, upright or sideways

  const onemap = (s, maxzoom = 19) => ({ tiles: [`https://www.onemap.gov.sg/maps/tiles/${s}/{z}/{x}/{y}.png`], minzoom: 11, maxzoom, credit: ONEMAP_CREDIT, onemap: true });
  const carto = s => ({ tiles: ['a', 'b', 'c', 'd'].map(h => `https://${h}.basemaps.cartocdn.com/${s}/{z}/{x}/{y}@2x.png`), maxzoom: 20, credit: CARTO });
  // Every basemap a day can name. OneMap only has tiles from z11, so those get a
  // second, low-zoom layer (see createMap).
  const BASEMAPS = {
    Default: onemap('Default'), Night: onemap('Night'), Grey: onemap('Grey'), GreyLite: onemap('GreyLite'),
    Original: onemap('Original'), LandLot: onemap('LandLot'), Satellite: onemap('Satellite', 20),
    'esri-imagery': { tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], maxzoom: 19,
      credit: 'Imagery &copy; ' + a('https://www.esri.com/', 'Esri') + ', Maxar, Earthstar Geographics, and the GIS User Community' },
    'carto-dark': carto('dark_all'), 'carto-dark-nolabels': carto('dark_nolabels'),
    'carto-light': carto('light_all'), 'carto-light-nolabels': carto('light_nolabels'),
    'carto-voyager': carto('rastertiles/voyager'), 'carto-voyager-nolabels': carto('rastertiles/voyager_nolabels'),
    blackmarble: { tiles: ['https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png'], maxzoom: 8,
      credit: 'Night lights: ' + a('https://earthdata.nasa.gov/gibs', 'NASA GIBS') + ', VIIRS Black Marble 2016' },
  };

  const pad2 = n => String(n).padStart(2, '0');
  const rgb = hex => { const h = hex.replace('#', ''); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)).join(', '); };
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const svg = paths => `<svg viewBox="0 0 20 20" aria-hidden="true">${paths}</svg>`;

  /* ---------- stamp ---------- */
  function mountStamp(day, host = document.getElementById('dmc-stamp')) {
    const root = document.documentElement.style;
    if (day.accent) { root.setProperty('--day-accent', day.accent); root.setProperty('--day-accent-rgb', rgb(day.accent)); }
    if (day.basemapBg) root.setProperty('--map-bg', day.basemapBg);
    const theme = THEMES[day.n - 1];
    const date = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(Date.UTC(2026, 10, day.n)));
    host.setAttribute('aria-label', `#30DayMapChallenge 2026, day ${day.n} of 30: ${theme}`);

    const num = el('p', 'dmc-num', pad2(day.n));
    num.setAttribute('aria-hidden', 'true');
    const meta = el('div', 'dmc-meta');
    meta.append(el('p', 'dmc-theme', theme), el('p', 'dmc-date', `${date} · #30DayMapChallenge`));
    const more = el('button', 'dmc-more', 'About');
    more.type = 'button';
    more.setAttribute('aria-expanded', 'false');
    more.setAttribute('aria-controls', 'dmc-body');
    const head = el('div', 'dmc-head');
    head.append(num, meta, more);

    const index = el('ol', 'dmc-index');
    index.setAttribute('aria-label', 'Series index, November 2026');
    for (const d of 'SMTWTFS') { const h = el('li', 'dow', d); h.setAttribute('aria-hidden', 'true'); index.append(h); }
    for (let d = 1; d <= 30; d++) {
      const li = el('li', d < day.n ? 'done' : d === day.n ? 'today' : '');
      li.dataset.d = d;
      const label = `Day ${d}: ${THEMES[d - 1]}`;
      li.title = label;
      if (d === day.n) li.setAttribute('aria-current', 'date');
      if (day.nav && d !== day.n) {
        const link = el('a');
        link.href = day.nav.replace('{nn}', pad2(d)).replace('{n}', String(d));
        link.setAttribute('aria-label', label);
        li.append(link);
      } else li.setAttribute('aria-label', label);
      index.append(li);
    }
    const keys = el('p', 'dmc-keys');
    keys.innerHTML = 'Drag to pan · right-drag or <kbd>Ctrl</kbd>+drag to tilt and turn · <kbd>F</kbd> focus mode';
    const foot = el('p', 'dmc-foot');
    foot.append(el('span', null, day.author ? `#30DayMapChallenge by ${day.author}` : '#30DayMapChallenge 2026'), el('span', null, day.creditsEl ? '' : (day.credit || '')));
    const body = el('div', 'dmc-body');
    body.id = 'dmc-body';
    body.append(...(day.deck ? [el('p', 'dmc-deck', day.deck)] : []), index, keys, foot);

    const setOpen = open => {
      host.classList.toggle('open', open);
      more.setAttribute('aria-expanded', String(open));
      more.textContent = open ? 'Close' : 'About';
    };
    more.addEventListener('click', () => setOpen(!host.classList.contains('open')));
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && host.classList.contains('open')) { setOpen(false); more.focus(); }
    });
    host.replaceChildren(head, el('h1', 'dmc-title', day.title), body);
    if (!host.hasAttribute('data-dmc-overlay')) host.setAttribute('data-dmc-overlay', '');
  }
  // Kept for days written against kit v2; the v3 stamp is always compact.
  function fitStamp() { return false; }

  /* ---------- framing ---------- */
  const mercY = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
  const aspect = b => ((b[1][0] - b[0][0]) * Math.PI / 180) / (mercY(b[1][1]) - mercY(b[0][1]));
  let frameBounds = SG_BOUNDS;
  // Map padding that keeps the framed area clear of every visible [data-dmc-overlay] sheet.
  // Each sheet can be cleared by keeping the area below, above, right or left of it; every
  // combination is tried and the one where the area would be drawn largest wins.
  function overlayPadding() {
    const vw = innerWidth, vh = innerHeight, ar = aspect(frameBounds);
    if (document.documentElement.classList.contains('dmc-focus')) return { top: 16, right: 16, bottom: 16, left: 16 };
    const rects = [...document.querySelectorAll('[data-dmc-overlay]')].map(e => e.getBoundingClientRect()).filter(r => r.width && r.height).slice(0, 6);
    let best = null;
    for (let k = 0; k < 4 ** rects.length; k++) {
      const p = { top: 16, right: 16, bottom: 16, left: 16 };
      rects.forEach((r, i) => {
        const side = Math.floor(k / 4 ** i) % 4;
        if (side === 0) p.top = Math.max(p.top, r.bottom + 10);
        else if (side === 1) p.bottom = Math.max(p.bottom, vh - r.top + 10);
        else if (side === 2) p.left = Math.max(p.left, r.right + 16);
        else p.right = Math.max(p.right, vw - r.left + 16);
      });
      const score = Math.min((vw - p.left - p.right) / ar, vh - p.top - p.bottom);
      if (!best || score > best.score) best = { score, p };
    }
    return best && best.score >= 70 ? best.p : { top: 12, right: 12, bottom: 12, left: 12 };
  }

  // Fit the framed area into the space the sheets leave free, keeping the day's tilt and turn.
  function frame(map, focus) {
    const bearing = map.getBearing(), pitch = map.getPitch();
    map.__dmcFraming = true;   // setPadding fires its own move events
    map.setPadding({ top: 0, right: 0, bottom: 0, left: 0 });
    const padding = overlayPadding();
    const cam = map.cameraForBounds(frameBounds, { padding, bearing });
    if (cam && cam.zoom >= map.getMinZoom()) map.jumpTo({ center: cam.center, zoom: cam.zoom, bearing, pitch });
    else map.jumpTo({ center: focus || (frameBounds === SG_BOUNDS ? [103.875, 1.345] : map.getCenter()), zoom: map.getMinZoom(), padding, bearing, pitch });
    map.__dmcFraming = false;
  }

  // Lifts bottom-right map controls above a bottom sheet that reaches the right edge (phones).
  function watchOverlays(onChange) {
    let queued = false;
    const update = () => {
      let clear = 0;
      for (const e of document.querySelectorAll('[data-dmc-overlay]')) {
        const r = e.getBoundingClientRect();
        if (r.width && r.top > innerHeight * 0.45 && r.right > innerWidth - 140) clear = Math.max(clear, innerHeight - r.top + 8);
      }
      document.documentElement.style.setProperty('--dmc-clear-bottom', `${clear}px`);
      if (onChange && !queued) { queued = true; requestAnimationFrame(() => { queued = false; onChange(); }); }
    };
    const ro = new ResizeObserver(update);
    document.querySelectorAll('[data-dmc-overlay]').forEach(e => ro.observe(e));
    addEventListener('resize', update);
    update();
  }

  /* ---------- focus mode ---------- */
  let focusBtn = null, exitPill = null, sleepTimer = 0;
  function wake() {
    const root = document.documentElement;
    if (!root.classList.contains('dmc-focus')) return;
    root.classList.add('dmc-awake');
    clearTimeout(sleepTimer);
    sleepTimer = setTimeout(() => root.classList.remove('dmc-awake'), 1800);
  }
  function setFocus(on) {
    const root = document.documentElement;
    on = on ?? !root.classList.contains('dmc-focus');
    if (!exitPill) {
      exitPill = el('button', 'dmc-focus-exit');
      exitPill.type = 'button';
      exitPill.innerHTML = 'Exit focus mode <kbd>F</kbd>';
      exitPill.addEventListener('click', () => setFocus(false));
      document.body.append(exitPill);
      for (const ev of ['mousemove', 'touchstart', 'keydown']) addEventListener(ev, wake, { passive: true });
    }
    root.classList.toggle('dmc-focus', on);
    if (focusBtn) focusBtn.setAttribute('aria-pressed', String(on));
    if (on) wake(); else root.classList.remove('dmc-awake');
    document.dispatchEvent(new CustomEvent('dmc:focus', { detail: { on } }));
  }
  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest('input, textarea, select, [contenteditable]')) return;
    if (e.key === 'f' || e.key === 'F') setFocus();
    else if (e.key === 'Escape' && document.documentElement.classList.contains('dmc-focus')) setFocus(false);
  });

  /* ---------- 3D buildings (OpenFreeMap, free, no key) ---------- */
  function addBuildings(map, o = {}) {
    if (map.getLayer('dmc-buildings')) return;
    if (!map.getSource('dmc-buildings')) map.addSource('dmc-buildings', { type: 'vector', url: 'https://tiles.openfreemap.org/planet' });
    const h = ['coalesce', ['get', 'render_height'], 8];
    map.addLayer({
      id: 'dmc-buildings', type: 'fill-extrusion', source: 'dmc-buildings', 'source-layer': 'building', minzoom: 13,
      filter: ['!=', ['get', 'hide_3d'], true],
      paint: {
        'fill-extrusion-color': o.color || ['interpolate', ['linear'], h, 0, '#cfd6e2', 60, '#e9edf3', 200, '#ffffff'],
        'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], 13, 0, 14.2, h],
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': o.opacity ?? 0.88,
        'fill-extrusion-vertical-gradient': true,
      },
    }, o.before && map.getLayer(o.before) ? o.before : undefined);
  }
  function setBuildings(map, on) {
    if (on) addBuildings(map, map.__dmcBuildingOpts);
    if (map.getLayer('dmc-buildings')) map.setLayoutProperty('dmc-buildings', 'visibility', on ? 'visible' : 'none');
  }

  // The glass button stack under the zoom buttons: 3D tilt, buildings, focus mode.
  class KitControl {
    constructor(day) { this.day = day; }
    onAdd(map) {
      const day = this.day, box = this.box = el('div', 'maplibregl-ctrl maplibregl-ctrl-group dmc-ctrl');
      const button = (label, html, onClick) => {
        const b = el('button');
        b.type = 'button'; b.title = label; b.setAttribute('aria-label', label); b.setAttribute('aria-pressed', 'false');
        b.innerHTML = html;
        b.addEventListener('click', onClick);
        box.append(b);
        return b;
      };
      const tiltTo = (day.camera && day.camera.tiltPitch) || 55;
      const tilt = button('Tilt the map (3D view)', '<span class="lbl">3D</span>', () => {
        if (map.getPitch() > 8) map.easeTo({ pitch: 0, bearing: 0, duration: 900 });
        else map.easeTo({ pitch: tiltTo, bearing: map.getBearing() || -18, duration: 900 });
      });
      const syncTilt = () => tilt.setAttribute('aria-pressed', String(map.getPitch() > 8));
      map.on('pitchend', syncTilt); map.on('load', syncTilt);
      if (day.buildings !== false) {
        let on = day.buildings === true;
        const bld = button('3D buildings', svg('<path d="M3 17V8l5-3v12M8 17V3l6 3v11M14 17V9l3 1.5V17M2 17h16"/>'), () => {
          on = !on;
          setBuildings(map, on);
          bld.setAttribute('aria-pressed', String(on));
          if (on && (map.getZoom() < 13.5 || map.getPitch() < 20)) {
            const inSG = frameBounds === SG_BOUNDS;
            const center = map.getZoom() < 13.5 ? (day.buildingsFocus || (inSG ? CBD : map.getCenter())) : map.getCenter();
            map.flyTo({ center, zoom: Math.max(map.getZoom(), 15.2), pitch: Math.max(map.getPitch(), 58), bearing: map.getBearing() || -25, duration: 2200, essential: true });
          }
        });
        bld.setAttribute('aria-pressed', String(on));
        if (on) (map.loaded() ? setBuildings(map, true) : map.once('load', () => setBuildings(map, true)));
        this.toggleBuildings = () => bld.click();
      }
      focusBtn = button('Focus mode: only the map (F)', svg('<path d="M3 7V3h4M13 3h4v4M17 13v4h-4M7 17H3v-4"/><circle cx="10" cy="10" r="2.2"/>'), () => setFocus());
      return box;
    }
    onRemove() {}
  }

  /* ---------- map ---------- */
  const MIN_ZOOM = 8.6;   // the 128 px z11 OneMap tiles round to z11 down to zoom 8.5
  function createMap(day, options = {}) {
    frameBounds = day.bounds || SG_BOUNDS;
    const inSG = frameBounds === SG_BOUNDS;
    const names = day.style ? [] : [].concat(day.basemap || 'Default');
    const sources = {}, layers = [{ id: 'background', type: 'background', paint: { 'background-color': day.basemapBg || '#0B1220' } }];
    const credits = [];
    let onemapOnly = names.length > 0;
    // underlay: a basemap always drawn beneath the others, e.g. 'esri-imagery' under OneMap
    // Satellite so the world beyond OneMap's coverage is never black.
    if (day.underlay && !day.style) {
      const u = BASEMAPS[day.underlay];
      sources['underlay'] = { type: 'raster', tiles: u.tiles, tileSize: 256, minzoom: u.minzoom || 0, maxzoom: u.maxzoom };
      layers.push({ id: 'underlay', type: 'raster', source: 'underlay', paint: { 'raster-fade-duration': 0, ...(day.underlayPaint || day.basemapPaint || {}) } });
      credits.push(u.credit);
      onemapOnly = false;
    }
    names.forEach((name, i) => {
      const b = BASEMAPS[name];
      if (!b) throw new Error(`DMC: unknown basemap "${name}"`);
      if (!b.onemap) onemapOnly = false;
      if (!credits.includes(b.credit)) credits.push(b.credit);
      const paint = { 'raster-opacity': i ? 0 : 1, 'raster-fade-duration': 0, ...(day.basemapPaint || {}) };
      sources[`basemap-${name}`] = { type: 'raster', tiles: b.tiles, tileSize: 256, minzoom: b.minzoom || 0, maxzoom: b.maxzoom };
      if (b.onemap) {
        // Below z11 the same z11 tiles are drawn at 128 px, so the whole island fits on a phone.
        // From 9.5 to 11 both layers draw, so a fast zoom never shows a gap.
        sources[`basemap-${name}-lo`] = { type: 'raster', tiles: b.tiles, tileSize: 128, minzoom: 11, maxzoom: 11 };
        layers.push({ id: `basemap-${name}-lo`, type: 'raster', source: `basemap-${name}-lo`, maxzoom: 11, paint: { ...paint } });
        layers.push({ id: `basemap-${name}`, type: 'raster', source: `basemap-${name}`, minzoom: 9.5, paint: { ...paint } });
      } else {
        layers.push({ id: `basemap-${name}`, type: 'raster', source: `basemap-${name}`, paint: { ...paint } });
      }
    });
    if (day.style && day.styleCredit) credits.push(day.styleCredit);
    if (day.buildings !== false) credits.push(BUILDINGS_CREDIT);
    const cam = day.camera || {};
    let map;
    try {
      map = new maplibregl.Map({
        container: 'map',
        style: day.style || { version: 8, sources, layers },
        center: inSG ? [103.82, 1.35] : [(frameBounds[0][0] + frameBounds[1][0]) / 2, (frameBounds[0][1] + frameBounds[1][1]) / 2],
        zoom: inSG ? 10.5 : 4,
        pitch: cam.pitch || 0, bearing: cam.bearing || 0,
        minZoom: day.minZoom ?? (onemapOnly ? MIN_ZOOM : inSG ? 8 : 1), maxZoom: day.maxZoom ?? 19,
        maxPitch: 78,
        maxBounds: day.maxBounds !== undefined ? day.maxBounds : inSG ? [[102.6, 0.5], [105.0, 2.2]] : undefined,
        attributionControl: false, dragRotate: true, pitchWithRotate: true, touchPitch: true,
        ...options,
      });
    } catch (err) {   // no WebGL (blocklisted GPU, locked-down browser): say so instead of a blank page
      noMap();
      throw err;
    }
    map.__dmcBuildingOpts = { color: day.buildingsColor, opacity: day.buildingsOpacity, before: day.buildingsBefore };
    frame(map);
    // Re-fit after resize and web-font load, until the viewer has moved the map themselves.
    let userMoved = false, timer = 0;
    // Any move but the kit's own framing (the viewer, or the day's own camera work) stops it.
    map.on('movestart', () => { if (!map.__dmcFraming) userMoved = true; });
    const refit = () => { if (!userMoved) frame(map); };
    addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(refit, 160); });
    if (document.fonts) document.fonts.ready.then(refit);
    // Phones drop WebGL contexts under memory pressure; a reload is the reliable way back.
    map.on('webglcontextrestored', () => location.reload());
    map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right');
    const kit = new KitControl(day);
    map.addControl(kit, 'top-right');
    const creditsEl = day.creditsEl && document.getElementById(day.creditsEl);
    const all = credits.concat(day.attribution || []);
    if (creditsEl) {
      creditsEl.innerHTML = all.join('<br>');
      // Focus mode hides the panel the credits sit in, so a one-line copy shows instead.
      const line = el('p', 'dmc-focus-credit');
      line.innerHTML = all.join(' · ');
      document.body.append(line);
    } else {
      map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: all }), 'bottom-right');
      // Compact attribution opens expanded on wide screens; start it folded to the (i) button.
      map.once('load', () => map.getContainer().querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show'));
    }
    watchOverlays(refit);
    // Shareable views: ?view=lng,lat,zoom,pitch,bearing  ?focus  ?buildings
    const q = new URLSearchParams(location.search);
    if (q.has('view')) {
      const [lng, lat, zoom, pitch = 0, bearing = 0] = q.get('view').split(',').map(Number);
      if (isFinite(lng) && isFinite(lat) && isFinite(zoom)) { userMoved = true; map.jumpTo({ center: [lng, lat], zoom, pitch, bearing }); }
    }
    if (q.has('buildings') && day.buildings !== true && kit.toggleBuildings) map.once('load', () => kit.toggleBuildings());
    if (q.has('focus')) setFocus(true);
    return map;
  }

  // Shown when the map can't start. The other sheets are hidden, since nothing in them works.
  function noMap() {
    document.documentElement.classList.add('dmc-nomap');
    const box = el('div', 'dmc-glass dmc-nomap-msg');
    box.setAttribute('role', 'alert');
    box.append(el('p', 'dmc-title', 'This map needs WebGL'),
      el('p', 'dmc-deck', 'Your browser or device has it turned off. Try another browser, or turn on hardware acceleration in your browser settings.'));
    document.body.append(box);
  }

  function setBasemapPaint(map, style, prop, value) {
    for (const id of [`basemap-${style}`, `basemap-${style}-lo`]) if (map.getLayer(id)) map.setPaintProperty(id, prop, value);
  }
  // Where the two OneMap layers overlap (zoom 9.5 to 11) each gets opacity b, so together they
  // show 1 - (1 - b)^2 = a; outside the overlap the one layer drawn gets a itself.
  function setBasemapOpacity(map, style, a) {
    const hi = `basemap-${style}`, lo = `${hi}-lo`;
    if (!map.getLayer(lo)) { if (map.getLayer(hi)) map.setPaintProperty(hi, 'raster-opacity', a); return; }
    const b = 1 - Math.sqrt(Math.max(0, 1 - a)), same = Math.abs(a - b) < 1e-4;
    map.setPaintProperty(hi, 'raster-opacity', same ? a : ['step', ['zoom'], b, 11, a]);
    map.setPaintProperty(lo, 'raster-opacity', same ? a : ['step', ['zoom'], a, 9.5, b]);
  }
  function setBasemapVisible(map, style, on) {
    for (const id of [`basemap-${style}`, `basemap-${style}-lo`]) {
      if (map.getLayer(id) && (map.getLayoutProperty(id, 'visibility') !== 'none') !== on) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    }
  }

  return { THEMES, SG_BOUNDS, CBD, BASEMAPS, ONEMAP_CREDIT, OSM_CREDIT: OSM, COMPACT_Q, pad2, rgb, mountStamp, fitStamp, overlayPadding,
    createMap, frame, setBasemapPaint, setBasemapOpacity, setBasemapVisible, addBuildings, setBuildings, setFocus };
})();
/* ===== end 30DMC KIT v3 ===== */
