/* Pokémon Spectrum — interactive mosaic viewer.
 * Renders the packed layout from a sprite atlas onto a full-resolution
 * offscreen "world" canvas, then pans/zooms that. Hover uses per-sprite
 * 1-bit silhouette masks for pixel-exact identification. */
"use strict";

const $ = (id) => document.getElementById(id);
const view = $("view");
const ctx = view.getContext("2d");

const state = {
  meta: null, sprites: [], atlas: null, masks: null, maskOff: [],
  world: null,           // full-res composited poster (offscreen)
  scale: 1, ox: 0, oy: 0, minScale: 0.05,
  hover: null, grid: null, gridSize: 128,
  matches: null,         // search results (array) or null
  matchIdx: -1,
  assembling: false, assembleStart: 0, assembleStamped: 0,
  fly: null,             // camera animation
  dpr: window.devicePixelRatio || 1,
};

const ASSEMBLE_MS = 6500, DROP_MS = 280, MAX_ZOOM = 24;

/* ---------- loading ---------- */

async function load() {
  const fill = $("loader-fill"), msg = $("loader-msg");
  const progress = [0, 0, 0];
  const tick = () => { fill.style.width = (progress.reduce((a, b) => a + b) / 3 * 100) + "%"; };
  try {
    // layout.json is fetched uncached; its build stamp then versions the other
    // assets so a rebuild can never mix with a stale browser cache.
    const doc = JSON.parse(new TextDecoder().decode(
      await fetchProgress("assets/layout.json", 0, progress, tick)));
    const v = encodeURIComponent(doc.meta.builtAt || doc.meta.count);
    const [masks, atlas] = await Promise.all([
      fetchProgress(`assets/masks.bin?v=${v}`, 1, progress, tick),
      loadImage(`assets/atlas.png?v=${v}`, 2, progress, tick),
    ]);
    state.meta = doc.meta;
    state.sprites = doc.sprites.sort((a, b) => a.o - b.o);
    state.masks = new Uint8Array(masks);
    state.atlas = atlas;
    init();
  } catch (err) {
    $("loader").classList.add("error");
    msg.textContent = "Couldn't load assets — serve this folder over HTTP " +
      "(run ./run.sh or `python3 -m http.server` in the project root) " +
      "and make sure the pipeline has been built. " + err.message;
  }
}

async function fetchProgress(url, slot, progress, tick) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  const total = +res.headers.get("Content-Length") || 0;
  if (!res.body || !total) { progress[slot] = 1; tick(); return await res.arrayBuffer(); }
  const reader = res.body.getReader(), chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length;
    progress[slot] = Math.min(1, got / total); tick();
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  progress[slot] = 1; tick();
  return out.buffer;
}

function loadImage(url, slot, progress, tick) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => { progress[slot] = 1; tick(); resolve(img); };
    img.onerror = () => reject(new Error(url + " failed to load"));
    img.src = url;
  });
}

/* ---------- setup ---------- */

function init() {
  const { meta, sprites } = state;

  // mask byte offsets (row-padded 1-bit masks, sprite order)
  let off = 0;
  for (const s of sprites) { state.maskOff[s.o] = off; off += Math.ceil(s.w / 8) * s.h; }

  // spatial hash for hover hit-testing
  const gs = state.gridSize, grid = new Map();
  for (const s of sprites) {
    for (let gy = (s.y / gs) | 0; gy <= ((s.y + s.h) / gs) | 0; gy++)
      for (let gx = (s.x / gs) | 0; gx <= ((s.x + s.w) / gs) | 0; gx++) {
        const k = gx + gy * 4096;
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push(s);
      }
  }
  state.grid = grid;

  state.world = document.createElement("canvas");
  state.world.width = meta.width;
  state.world.height = meta.height;

  buildSpectrumBar();
  $("hud-count").textContent = meta.count.toLocaleString() + " Pokémon";
  fitView();
  resize();
  $("loader").style.opacity = "0";
  setTimeout(() => $("loader").remove(), 550);
  setTimeout(() => {
    $("hint").style.opacity = "0";      // fade the onboarding hint out…
    $("social").style.opacity = "1";    // …and reveal the X handle in its place
  }, 7000);

  startAssembly();
  requestAnimationFrame(frame);
}

function buildSpectrumBar() {
  const { meta } = state;
  const bar = $("spectrum");
  const stops = meta.columns
    .map((c) => `${c.hex} ${(((c.x0 + c.x1) / 2) / meta.width * 100).toFixed(2)}%`);
  bar.style.background = `linear-gradient(90deg, ${stops.join(", ")})`;
  bar.addEventListener("click", (e) => {
    const wx = (e.clientX / innerWidth) * meta.width;
    flyTo(wx, meta.height / 2, Math.max(state.scale, fitScale() * 3));
  });
}

/* ---------- camera ---------- */

function fitScale() {
  const { meta } = state;
  return Math.min(innerWidth / meta.width, (innerHeight - 90) / meta.height) * 0.97;
}

function fitView() {
  const { meta } = state;
  state.scale = fitScale();
  state.minScale = state.scale * 0.4;
  state.ox = (innerWidth - meta.width * state.scale) / 2;
  state.oy = 66 + (innerHeight - 66 - meta.height * state.scale) / 2;
}

function clearHover() {
  state.hover = null;
  $("tooltip").hidden = true;
}

// Touch has no hover, so a tap identifies the Pokémon under the finger
// (or dismisses the tooltip when tapping empty space).
function handleTap(cx, cy) {
  const hit = hitTest((cx - state.ox) / state.scale, (cy - state.oy) / state.scale);
  if (hit) { state.hover = hit; showTooltip(hit, cx, cy); }
  else clearHover();
}

function zoomAt(mx, my, factor) {
  const s = Math.min(MAX_ZOOM, Math.max(state.minScale, state.scale * factor));
  state.ox = mx - (mx - state.ox) * (s / state.scale);
  state.oy = my - (my - state.oy) * (s / state.scale);
  state.scale = s;
  state.fly = null;
  clearHover();
}

function flyTo(wx, wy, targetScale) {
  clearHover();
  state.fly = {
    t0: performance.now(), ms: 650,
    from: { s: state.scale, ox: state.ox, oy: state.oy },
    to: {
      s: targetScale,
      ox: innerWidth / 2 - wx * targetScale,
      oy: (innerHeight + 66) / 2 - wy * targetScale,
    },
  };
}

function stepFly(now) {
  const f = state.fly;
  if (!f) return;
  const t = Math.min(1, (now - f.t0) / f.ms);
  const e = 1 - Math.pow(1 - t, 3);
  state.scale = f.from.s + (f.to.s - f.from.s) * e;
  state.ox = f.from.ox + (f.to.ox - f.from.ox) * e;
  state.oy = f.from.oy + (f.to.oy - f.from.oy) * e;
  if (t >= 1) state.fly = null;
}

/* ---------- assembly animation ---------- */

function startAssembly() {
  state.world.getContext("2d").clearRect(0, 0, state.world.width, state.world.height);
  state.assembling = true;
  state.assembleStart = performance.now();
  state.assembleStamped = 0;
}

function atlasPos(s) {
  const { atlasCols, cell } = state.meta;
  return [
    (s.o % atlasCols) * cell + ((cell - s.w) >> 1),
    ((s.o / atlasCols) | 0) * cell + ((cell - s.h) >> 1),
  ];
}

function stampSprite(wctx, s) {
  const [ax, ay] = atlasPos(s);
  wctx.drawImage(state.atlas, ax, ay, s.w, s.h, s.x, s.y, s.w, s.h);
}

function stepAssembly(now) {
  const { sprites } = state;
  const n = sprites.length;
  const wctx = state.world.getContext("2d");
  const elapsed = now - state.assembleStart;
  const startFor = (i) => (i / n) * (ASSEMBLE_MS - DROP_MS);

  while (state.assembleStamped < n &&
         elapsed >= startFor(state.assembleStamped) + DROP_MS) {
    stampSprite(wctx, sprites[state.assembleStamped++]);
  }
  if (state.assembleStamped >= n) { state.assembling = false; return null; }

  const inflight = [];
  for (let i = state.assembleStamped; i < n; i++) {
    const t = (elapsed - startFor(i)) / DROP_MS;
    if (t < 0) break;
    inflight.push([sprites[i], t]);
  }
  return inflight;
}

function skipAssembly() {
  if (!state.assembling) return;
  const wctx = state.world.getContext("2d");
  while (state.assembleStamped < state.sprites.length)
    stampSprite(wctx, state.sprites[state.assembleStamped++]);
  state.assembling = false;
}

/* ---------- render loop ---------- */

function frame(now) {
  stepFly(now);
  const { scale: s, ox, oy, dpr } = state;

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, view.width / dpr, view.height / dpr);
  ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * ox, dpr * oy);
  ctx.imageSmoothingEnabled = s < 1;

  const inflight = state.assembling ? stepAssembly(now) : null;
  ctx.drawImage(state.world, 0, 0);

  if (inflight) {
    for (const [sp, t] of inflight) {
      const e = 1 - Math.pow(1 - t, 3);
      const [ax, ay] = atlasPos(sp);
      ctx.globalAlpha = Math.min(1, t * 2);
      ctx.drawImage(state.atlas, ax, ay, sp.w, sp.h,
        sp.x, sp.y - (1 - e) * 90, sp.w, sp.h);
    }
    ctx.globalAlpha = 1;
  }

  if (state.matches && !state.assembling) drawSearchOverlay();
  if (state.hover && !state.assembling) drawHighlight(state.hover);

  requestAnimationFrame(frame);
}

function drawHighlight(sp) {
  const [ax, ay] = atlasPos(sp);
  ctx.save();
  ctx.shadowColor = "rgba(255,255,255,0.9)";
  ctx.shadowBlur = 12 / state.scale;
  ctx.drawImage(state.atlas, ax, ay, sp.w, sp.h, sp.x, sp.y, sp.w, sp.h);
  ctx.restore();
  ctx.drawImage(state.atlas, ax, ay, sp.w, sp.h, sp.x, sp.y, sp.w, sp.h);
}

function drawSearchOverlay() {
  const { meta, matches } = state;
  ctx.fillStyle = document.body.dataset.theme === "light"
    ? "rgba(242,243,245,0.82)" : "rgba(8,9,11,0.82)";
  ctx.fillRect(-state.ox / state.scale, -state.oy / state.scale,
    view.width / state.dpr / state.scale, view.height / state.dpr / state.scale);
  const cap = Math.min(matches.length, 1200);
  for (let i = 0; i < cap; i++) stampSpriteMain(matches[i]);
  const cur = matches[state.matchIdx];
  if (cur) {
    ctx.strokeStyle = "#ffd257";
    ctx.lineWidth = 2.5 / state.scale;
    const p = 4;
    ctx.strokeRect(cur.x - p, cur.y - p, cur.w + p * 2, cur.h + p * 2);
  }
}

function stampSpriteMain(s) {
  const [ax, ay] = atlasPos(s);
  ctx.drawImage(state.atlas, ax, ay, s.w, s.h, s.x, s.y, s.w, s.h);
}

/* ---------- hover / hit-testing ---------- */

function hitTest(wx, wy) {
  if (!state.grid) return null;
  const k = ((wx / state.gridSize) | 0) + ((wy / state.gridSize) | 0) * 4096;
  const bucket = state.grid.get(k);
  if (!bucket) return null;
  for (const s of bucket) {
    const rx = (wx - s.x) | 0, ry = (wy - s.y) | 0;
    if (rx < 0 || ry < 0 || rx >= s.w || ry >= s.h) continue;
    const rowBytes = Math.ceil(s.w / 8);
    const byte = state.masks[state.maskOff[s.o] + ry * rowBytes + (rx >> 3)];
    if (byte & (0x80 >> (rx & 7))) return s;
  }
  return null;
}

function showTooltip(sp, cx, cy) {
  const tt = $("tooltip");
  tt.hidden = false;
  $("tt-name").textContent = sp.name;
  const tags = [];
  if (sp.form) tags.push(`<span class="tag">${esc(sp.form)}</span>`);
  if (sp.shiny) tags.push(`<span class="tag shiny">✨ shiny</span>`);
  if (sp.neutral) tags.push(`<span class="tag">neutral</span>`);
  $("tt-tags").innerHTML = tags.join("");
  const aka = sp.aka && sp.aka.length
    ? ` · also ${esc(sp.aka.slice(0, 2).join(", "))}${sp.aka.length > 2 ? "…" : ""}` : "";
  $("tt-meta").innerHTML =
    `<span class="swatch" style="background:${sp.hex}"></span>` +
    `#${String(sp.id).padStart(4, "0")} · ${sp.hex}${aka}`;

  const c = $("tt-sprite"), tctx = c.getContext("2d");
  tctx.imageSmoothingEnabled = false;
  tctx.clearRect(0, 0, 96, 96);
  const [ax, ay] = atlasPos(sp);
  const k = Math.min(96 / sp.w, 96 / sp.h, 3);
  tctx.drawImage(state.atlas, ax, ay, sp.w, sp.h,
    (96 - sp.w * k) / 2, (96 - sp.h * k) / 2, sp.w * k, sp.h * k);

  const pad = 16;
  let x = cx + pad, y = cy + pad;
  const r = tt.getBoundingClientRect();
  if (x + r.width > innerWidth - 8) x = cx - r.width - pad;
  if (y + r.height > innerHeight - 8) y = cy - r.height - pad;
  x = Math.max(8, Math.min(x, innerWidth - r.width - 8));   // stay on-screen (small phones)
  y = Math.max(8, Math.min(y, innerHeight - r.height - 8));
  tt.style.left = x + "px";
  tt.style.top = y + "px";
}

const esc = (s) => s.replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- search ---------- */

function runSearch(q) {
  q = q.trim().toLowerCase();
  if (q.length < 2) { state.matches = null; state.matchIdx = -1; updateHudCount(); return; }
  state.matches = state.sprites.filter((s) => s.label.toLowerCase().includes(q) ||
    (q === "shiny" && s.shiny) || (q === "neutral" && s.neutral));
  state.matchIdx = state.matches.length ? 0 : -1;
  updateHudCount();
}

function updateHudCount() {
  const { matches, meta } = state;
  $("hud-count").textContent = matches
    ? `${matches.length.toLocaleString()} match${matches.length === 1 ? "" : "es"}`
    : meta.count.toLocaleString() + " Pokémon";
}

function cycleMatch(dir) {
  const m = state.matches;
  if (!m || !m.length) return;
  state.matchIdx = (state.matchIdx + dir + m.length) % m.length;
  const s = m[state.matchIdx];
  flyTo(s.x + s.w / 2, s.y + s.h / 2, Math.max(3, state.scale));
}

/* ---------- export ---------- */

function exportDims(scale) {
  return [state.meta.width * scale, state.meta.height * scale];
}

async function exportPNG(scale, transparent) {
  const [w, h] = exportDims(scale);
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const ec = c.getContext("2d");
  if (!transparent) {
    ec.fillStyle = getComputedStyle(document.body).getPropertyValue("--bg").trim();
    ec.fillRect(0, 0, w, h);
  }
  ec.imageSmoothingEnabled = false;
  ec.drawImage(state.world, 0, 0, w, h);
  const blob = await new Promise((res) => c.toBlob(res, "image/png"));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `pokemon-spectrum-${scale}x.png`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/* ---------- input ---------- */

function resize() {
  view.width = Math.round(innerWidth * state.dpr);
  view.height = Math.round(innerHeight * state.dpr);
  view.style.width = innerWidth + "px";
  view.style.height = innerHeight + "px";
}

window.addEventListener("resize", () => { resize(); });

view.addEventListener("wheel", (e) => {
  e.preventDefault();
  const factor = e.ctrlKey
    ? Math.exp(-e.deltaY * 0.012)   // trackpad pinch
    : Math.pow(1.0016, -e.deltaY);
  zoomAt(e.clientX, e.clientY, factor);
  $("hud-zoom").textContent = Math.round(state.scale * 100) + "%";
}, { passive: false });

// Pointer handling: 1 pointer = pan / hover, 2 pointers = pinch-zoom.
// touch-action:none disables native gestures, so we drive zoom ourselves.
// (The old code tracked a single drag object, so a second finger overwrote it
//  and the view teleported — that was the broken mobile "zoom".)
const pointers = new Map();   // pointerId -> {x, y}
let pan = null;               // active one-finger / mouse drag
let pinch = null;             // active two-finger gesture

function beginPinch() {
  const [a, b] = [...pointers.values()];
  pinch = {
    dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
    cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2,
    scale: state.scale, ox: state.ox, oy: state.oy,
  };
  pan = null;
  $("tooltip").hidden = true;
  clearHover();
}

view.addEventListener("pointerdown", (e) => {
  view.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  state.fly = null;
  if (pointers.size === 1) {
    pan = { x: e.clientX, y: e.clientY, ox: state.ox, oy: state.oy, moved: false };
    view.classList.add("dragging");
  } else if (pointers.size === 2) {
    beginPinch();
  }
});

view.addEventListener("pointermove", (e) => {
  if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

  if (pinch && pointers.size >= 2) {
    const [a, b] = [...pointers.values()];
    const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
    const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
    const s = Math.min(MAX_ZOOM, Math.max(state.minScale, pinch.scale * (dist / pinch.dist)));
    // pin the world point that began under the pinch centre to the fingers'
    // current midpoint — gives simultaneous zoom + two-finger pan, no jump
    const wx = (pinch.cx - pinch.ox) / pinch.scale;
    const wy = (pinch.cy - pinch.oy) / pinch.scale;
    state.scale = s;
    state.ox = cx - wx * s;
    state.oy = cy - wy * s;
    state.fly = null;
    $("hud-zoom").textContent = Math.round(state.scale * 100) + "%";
    $("tooltip").hidden = true;
    return;
  }

  if (pan) {
    const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
    if (Math.abs(dx) + Math.abs(dy) > 8) { pan.moved = true; clearHover(); } // 8px slop = forgiving taps
    state.ox = pan.ox + dx;
    state.oy = pan.oy + dy;
    return;
  }

  if (state.assembling) return;
  const wx = (e.clientX - state.ox) / state.scale;
  const wy = (e.clientY - state.oy) / state.scale;
  const hit = hitTest(wx, wy);
  state.hover = hit;
  if (hit) showTooltip(hit, e.clientX, e.clientY);
  else $("tooltip").hidden = true;
});

function endPointer(e) {
  const wasPan = pan;
  pointers.delete(e.pointerId);
  if (pointers.size < 2) pinch = null;
  if (pointers.size === 1) {
    // one finger remains after a pinch — resume panning from it without a jump
    const [p] = [...pointers.values()];
    pan = { x: p.x, y: p.y, ox: state.ox, oy: state.oy, moved: true };
    return;
  }
  if (pointers.size === 0) {
    view.classList.remove("dragging");
    if (wasPan && !wasPan.moved) {
      if (state.assembling) skipAssembly();
      else handleTap(e.clientX, e.clientY);   // a still tap = identify (touch has no hover)
    }
    pan = null;
  }
}
view.addEventListener("pointerup", endPointer);
view.addEventListener("pointercancel", endPointer);
// Only a real mouse leaving should clear the tooltip; on touch, pointerleave
// fires right after a tap and would wipe the tooltip we just showed.
view.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") clearHover(); });

$("btn-fit").addEventListener("click", () => { fitView(); clearHover(); });
$("btn-100").addEventListener("click", () =>
  flyTo((innerWidth / 2 - state.ox) / state.scale,
        (innerHeight / 2 - state.oy) / state.scale, 1));
$("btn-replay").addEventListener("click", () => startAssembly());
$("btn-theme").addEventListener("click", () => {
  document.body.dataset.theme =
    document.body.dataset.theme === "dark" ? "light" : "dark";
});

$("btn-export").addEventListener("click", () => {
  const menu = $("export-menu");
  menu.hidden = !menu.hidden;
  if (!menu.hidden) {
    for (const sc of [1, 2, 3]) {
      const [w, h] = exportDims(sc);
      $("dim" + sc).textContent = `${w}×${h}`;
      const ok = w <= 16000 && h <= 16000 && w * h <= 220e6;
      $("export-menu").querySelector(`[data-scale="${sc}"]`).disabled = !ok;
    }
  }
});
$("export-menu").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-scale]");
  if (!btn) return;
  btn.textContent = "rendering…";
  await new Promise((r) => setTimeout(r, 30));
  await exportPNG(+btn.dataset.scale, $("export-alpha").checked);
  $("export-menu").hidden = true;
  btn.innerHTML = `${btn.dataset.scale}× <span class="dim" id="dim${btn.dataset.scale}"></span>`;
});
document.addEventListener("click", (e) => {
  if (!$("export-wrap").contains(e.target)) $("export-menu").hidden = true;
});

$("search").addEventListener("input", (e) => runSearch(e.target.value));
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") cycleMatch(e.shiftKey ? -1 : 1);
  if (e.key === "Escape") { e.target.value = ""; runSearch(""); e.target.blur(); }
});
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "0") fitView();
  if (e.key === "1") flyTo((innerWidth / 2 - state.ox) / state.scale,
    (innerHeight / 2 - state.oy) / state.scale, 1);
  if (e.key === "+" || e.key === "=") zoomAt(innerWidth / 2, innerHeight / 2, 1.4);
  if (e.key === "-") zoomAt(innerWidth / 2, innerHeight / 2, 1 / 1.4);
  if (e.key === "/") { e.preventDefault(); $("search").focus(); }
  if (e.key === "Escape") { $("search").value = ""; runSearch(""); }
});

load();
