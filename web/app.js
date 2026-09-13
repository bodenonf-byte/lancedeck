// The team composition page. State arrives over the websocket whenever the helper reads a
// frame; the page just renders it. Three views: LANCE SETUP (both teams as three lances of
// four, with a team overview each), FIELD (the football pitch), MECH BOARD (cards by class).
const CLASSES = ["Light", "Medium", "Heavy", "Assault", "Unknown"];
let lastVersion = -1;
let assets = new Set(), mapFiles = new Set(), cutFiles = new Set(), assetsV = -1, roles = {};
function loadAssets() { return fetch("/api/assets").then(r => r.json()).then(d => { assets = new Set(d.files || []); mapFiles = new Set(d.maps || []); cutFiles = new Set(d.cut || []); }); }
let lastMap = "";
Promise.all([loadAssets(), fetch("/static/roles.json").then(r => r.json()).then(d => { roles = d; }).catch(() => {})])
  .then(() => { lastVersion = -1; if (new URLSearchParams(location.search).get("demo") === "1") { apply(demoState()); return; } fetch("/api/state").then(r => r.json()).then(apply); });

// ── options, remembered per browser ──────────────────────────────────────────────────
const prefs = (() => { try { return JSON.parse(localStorage.getItem("mwo-tracker") || "{}"); } catch (e) { return {}; } })();
function savePrefs() { try { localStorage.setItem("mwo-tracker", JSON.stringify(prefs)); } catch (e) {} }
const VIEWS = {lances: "lancesView", board: "board", records: "recordsView"};
function applyPrefs() {
  document.documentElement.dataset.theme = prefs.theme || "dark";
  const view = VIEWS[prefs.view] ? prefs.view : "lances";
  for (const [k, id] of Object.entries(VIEWS)) document.getElementById(id).hidden = k !== view;
  document.querySelectorAll(".navbtn[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  document.getElementById("themeBtn").textContent = (prefs.theme || "dark").toUpperCase();
  document.getElementById("optMap").checked = prefs.mapbg !== false;
  paintMap(lastMap);
  if (view === "records") loadRecords();
  if (view === "board") loadMyMechs();
}
document.querySelectorAll(".navbtn[data-view]").forEach(b => b.onclick = () => { if (b.dataset.view !== prefs.view) undoable.clear(); prefs.view = b.dataset.view; savePrefs(); applyPrefs(); });
document.getElementById("themeBtn").onclick = () => { prefs.theme = (prefs.theme || "dark") === "dark" ? "normal" : "dark"; savePrefs(); applyPrefs(); };
document.getElementById("optMap").onchange = e => { prefs.mapbg = e.target.checked; savePrefs(); applyPrefs(); };

// ── maps: a real frame of the map when one was harvested, else a colour theme ─────────
const MAP_TONES = {
  "Alpine Peaks": ["#1c2a3a", "#8fb3d9"], "Bearclaw": ["#2a2418", "#c9a15a"], "Boreal Vault": ["#16262c", "#7fd0e6"],
  "Canyon Network": ["#3a2414", "#d68a3c"], "Caustic Valley": ["#2b2f14", "#c4c936"], "Crimson Strait": ["#3a1a1e", "#e07a6a"],
  "Emerald Taiga": ["#12301c", "#5fbf7a"], "Forest Colony": ["#1a2e1a", "#7cc27c"], "Free Worlds Coliseum": ["#2a2224", "#d9b06a"],
  "Frozen City": ["#1a2630", "#a9d6ee"], "Grim Plexus": ["#22182e", "#a380d6"], "Grim Portico": ["#26201a", "#c98a5a"],
  "Hellebore Springs": ["#1c2a24", "#8ad6b0"], "Hibernal Rift": ["#1a2632", "#9ccae6"], "HPG Manifold": ["#1a1a26", "#8c8ce0"],
  "Mining Collective": ["#2a2016", "#d9a05a"], "Polar Highlands": ["#202a34", "#cfe6f5"], "River City": ["#1a2430", "#7fb8e6"],
  "Rubellite Oasis": ["#2c1a24", "#e08ab8"], "Solaris City": ["#26221a", "#f0c65a"], "Sulfurous Rift": ["#2c2a12", "#e6d24a"],
  "Terra Therma": ["#301a12", "#f07a3a"], "Tourmaline Desert": ["#2e2a1c", "#e6c07a"], "Viridian Bog": ["#14261e", "#6fc79a"],
  "Vitric Forge": ["#2c1c14", "#f09a5a"],
};
function slug(m) { return m.toLowerCase().replace(/[^a-z0-9]+/g, "-"); }
function mapFile(map) { return map ? [...mapFiles].find(f => f.toLowerCase().startsWith(slug(map))) : null; }
function paintMap(map) {
  const bg = document.getElementById("mapbg");
  if (!map || prefs.mapbg === false) { bg.style.backgroundImage = ""; bg.classList.remove("show"); document.documentElement.style.removeProperty("--map-tone"); return; }
  const file = mapFile(map);
  const tones = MAP_TONES[map] || ["#1a2028", "#9ab"];
  document.documentElement.style.setProperty("--map-tone", tones[1]);
  bg.style.backgroundImage = file ? `linear-gradient(rgba(8,10,14,.35), rgba(8,10,14,.78)), url("/assets/maps/${file}")`
                                  : `radial-gradient(ellipse at 30% 0%, ${tones[1]}66, transparent 60%), radial-gradient(ellipse at 90% 100%, ${tones[1]}33, transparent 50%), linear-gradient(180deg, ${tones[0]}, var(--bg) 85%)`;
  bg.classList.add("show");
}

// ── pictures: the exact variant's icon first, then the chassis ──────────────────────
function picFor(code) {
  if (!code) return null;
  for (const ext of ["_turn.gif", ".png", ".jpg", ".webp"]) if (assets.has(code + ext)) return `/assets/mechs/${code}${ext}`;
  return null;
}
function picOf(s) {
  if (!s.code) return null;
  if (s.variant) for (const ext of [".png", ".jpg", ".webp"]) if (assets.has(`${s.code}-${s.variant}${ext}`)) return `/assets/mechs/${s.code}-${s.variant}${ext}`;
  return picFor(s.code);
}
// the cut-out (mech only, transparent backdrop) for the 3D pads, when the cutter made one
function cutOf(s) {
  if (!s.code) return null;
  if (s.variant && cutFiles.has(`${s.code}-${s.variant}.png`)) return `/assets/mechs/cut/${s.code}-${s.variant}.png`;
  if (cutFiles.has(`${s.code}.png`)) return `/assets/mechs/cut/${s.code}.png`;
  return null;
}
function escapeHtml(t) { return String(t).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
const MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"};
function medalOf(s) { return s.medal ? `<span class="medal m${s.medal}" title="match score ${s.score}">${MEDAL[s.medal]}</span>` : ""; }
function roleOf(s) { const r = roles[s.code]; return r ? r[0] : ""; }
function tagsOf(s) { const r = roles[s.code]; return r ? r[1] : []; }

// ── who am I ─────────────────────────────────────────────────────────────────────────
let myName = "";
function isMe(s) {
  const n = (myName || "").toLowerCase().replace(/\s+/g, ""), p = (s.pilot || "").toLowerCase().replace(/\s+/g, "");
  return n.length >= 3 && p.length >= 3 && (p.includes(n) || n.includes(p));
}

// ── LANCE SETUP: three lances of four a side, seats fixed in roster order ────────────
const LANCES = [
  {key: "ALPHA", name: "ALPHA LANCE", emblem: '<svg viewBox="0 0 512 512"><path d="M179.3 38.94C154.7 77.7 142.7 139.7 168.4 185.9l-16.3 9.2c-6.7-11.9-11.2-24.4-13.9-37.2-34.5-6.3-69.42-7.5-104.98-2.1 34.07 10.1 52.77 23.7 76.68 46.7-26.82 9.7-60.25 30.2-92.93 70.2 35.47-8.8 64.83-11.5 89.43-6.3-36.94 22.5-64.06 56.1-88.34 114.1 35.9-17.2 64.89-18.8 102.94-18.8-23.07 32.7-35.27 77.2-36.31 112.8 24.51-26 57.61-60.2 87.21-79 3 29.9 15 58.3 35.9 85.3-.2-43.9 10.3-88.3 31.6-133.4-18.8 9-32.4 18.1-49.9 29.3 6.2-27.9 12.4-55.8 18.7-83.7-23.3 2.4-39 10-60.5 18.5 16.3-33.1 32.7-66.1 49.1-99.2l16.8 8.3-28.4 57.4c18.4-4.4 28.7-4.1 45.7-1.3-4.5 20.4-9 40.7-13.6 61 65.3-36.2 148.3-45.9 226.7-50 7.6-12.9 13.8-24.2 18.8-34.8l-6.3-24.4-24.4 30.8-7.8-27.5-22.5 29.2-7.5-26.1-23.9 31.5-7.7-28.2-23.8 31.4 1.2-41.1 22.6-42.7 7.6 28.3 23.9-31.5 7.6 28.2 23.5-30 6.5 26.9 24.5-30.8 7.8 27.5 24.6-32c2.3-10.8 4.6-22.4 7.4-35.7-55.5-3.7-106.3 4.8-154 9.8-38-20.8-80.8-26.8-121.9-18.5-13.6-29.69-27.2-59.38-40.9-89.06zM325.5 158.3c-4.5 14.2-13 18.3-24.7 20.6-16.1-4.4-28.3-15.5-34.4-30.2 20.4-3.8 42.4 3.4 59.1 9.6z"/></svg>', motto: "“HOLD THE LINE”", tone: "alpha"},
  {key: "BRAVO", name: "BRAVO LANCE", emblem: '<svg viewBox="0 0 512 512"><path d="M242.9 20.46c6.7 19.75 19.7 41.39 4 50.44-38.6 22.04-81.4 41.5-106.2 90.7C103.3 235.7 91.69 412 29.81 451c48.6 3.8 89.69-16.3 108.89-44.2 7.1 34.3 32.6 67 63 84.7-5.2-29-1.8-59.4 19-92.5 16.5 22.9 31.1 59.3 73.8 75.3-16.4-27.5-13.7-52.8-10.7-84.2 8.8 26.9 38.5 50 72.9 58.9-16.8-18.6-23.9-45.5-21-66 14.6 24.9 43.4 38.4 67.1 39.7-153.3-179.6-48.7-291.6 79.4-194.4-.5-49.7-31.4-66.7-67.2-95.7-.9-15.4-9.6-29.3-17.5-43.36-53.7-9.99-121.5-42.01-154.6-68.78zm81.2 74.88c26.1 10.86 46.2 22.56 56.4 35.46-16.6-3.6-39.8-3.5-70-1.1 15-9.7 16.5-21.7 13.6-34.36z"/></svg>', motto: "“FIRE AND MANEUVER”", tone: "bravo"},
  {key: "CHARLIE", name: "CHARLIE LANCE", emblem: '<svg viewBox="0 0 512 512"><path d="M68.596 28.182c-86.767 50.67-51.027 136.884 123.35 136.884l2.835-70.433c-71.07 14-169.105 15.57-126.184-66.45zm378.455 0c42.92 82.022-55.114 80.45-126.185 66.45l2.836 70.434c174.378 0 210.117-86.213 123.35-136.884zM174.206 220.768c-3.798.104-7.758.785-11.816 2.087-1.887 29.822 11.63 50.308 48.516 39.88-.462-26.26-16.194-42.53-36.7-41.967zm167.213 0c-20.507-.563-36.24 15.707-36.7 41.966 36.886 10.43 50.404-10.057 48.518-39.88-4.058-1.3-8.02-1.982-11.818-2.086zm-53.123 162.7l-10.793 15.266c15.535 10.978 19.19 32.196 8.21 47.73C274.736 462 253.533 465.64 238 454.663c-15.535-10.978-19.19-32.193-8.21-47.728 2.03-2.875 4.483-5.42 7.288-7.543l-11.263-14.894c-4.34 3.283-8.153 7.203-11.292 11.645-16.805 23.784-11.098 56.982 12.685 73.788 23.784 16.806 56.956 11.098 73.762-12.686 16.806-23.783 11.11-56.967-12.672-73.773z"/></svg>', motto: "“EYES EVERYWHERE”", tone: "charlie"},
];
const CLASS_ICON = {Light: "▲", Medium: "◆", Heavy: "⬢", Assault: "⬟", Unknown: "?"};
function seatLances(slots) {
  // a pilot whose lance the TAB named sits in it; the rest fill the open seats in roster order
  const seats = LANCES.map(() => [null, null, null, null]);
  const rest = [];
  for (const s of slots.slice(0, 12)) {
    const li = LANCES.findIndex(l => (s.lance || "").toUpperCase().startsWith(l.key));
    const free = li >= 0 ? seats[li].indexOf(null) : -1;
    if (li >= 0 && free >= 0) seats[li][free] = s; else rest.push(s);
  }
  for (const s of rest) {
    for (const row of seats) { const f = row.indexOf(null); if (f >= 0) { row[f] = s; break; } }
  }
  return seats;
}
function pad(s, i) {
  if (!s) return `<div class="pad open"><div class="render"><span class="seatno">${i + 1}</span></div><div class="plate"><div class="pl-name">OPEN SEAT</div><div class="pl-pilot">waiting for the drop screen</div></div></div>`;
  const cutp = cutOf(s), pic = cutp || picOf(s), me = isMe(s);
  const spec = !!specName && !!s.pilot && specName.toLowerCase().replace(/\s+/g, "") === s.pilot.toLowerCase().replace(/\s+/g, "");
  const role = roleOf(s);
  const hpv = hpOf(s);
  // damage taken, as read off the lance panel / target readout: the bar is what is LEFT, the
  // red track behind it is what is gone; nothing read yet = an empty grey bar, not a full one
  const lvl = !s.alive ? "dead" : hpv == null ? "unk" : hpv > 66 ? "hi" : hpv > 33 ? "mid" : "lo";
  const hp = s.code || s.alive ? `<div class="thp ${lvl}"><i style="width:${hpv != null && s.alive ? hpv : 0}%"></i></div>` : "";
  const dmg = !s.alive ? "DESTROYED" : hpv == null ? "HP —" : `HP ${hpv}%`;
  // damage DEALT comes from the results table only, so it shows once the end screen is read
  const dealt = s.damage != null ? `<span class="dealt" title="damage dealt, from the results table">DMG ${s.damage}</span>` : "";
  return `<div class="pad c-${s.cls || "Unknown"} ${s.alive ? "" : "dead"} ${me ? "me" : ""} ${spec ? "spec" : ""} ${s.code ? "" : "nomech"} ${cutp ? "cut" : ""} ${s.guess ? "guess" : ""} ${s.medal ? "medal" + s.medal : ""}" title="${escapeHtml(s.pilot)}${s.pros ? " · + " + escapeHtml(s.pros) + " · − " + escapeHtml(s.cons) : ""}">
    <div class="render">
      <div class="floor"></div>
      ${s.code ? `<a class="build" href="${buildUrl(s)}" target="_blank" rel="noopener" title="builds for the ${escapeHtml(s.name)} ${s.code}${s.variant ? "-" + escapeHtml(s.variant) : ""} on GrimMechs">` : ""}${pic ? `<img src="${pic}" alt="">` : `<span class="code">${s.code || "?"}</span>`}${s.code ? "</a>" : ""}
      ${s.code ? `<b class="tons">${s.tons}t</b>` : ""}
      ${me ? '<span class="you">YOU</span>' : ""}
      ${s.alive ? "" : '<span class="tx">✕</span>'}
      ${s.status === "SEEN" ? '<span class="spotted">SPOTTED</span>' : ""}
      ${s.guess ? '<span class="spotted guessed" title="the mech this pilot drove in a recent game — not read yet this match">LAST GAME?</span>' : ""}
    </div>
    <div class="plate">
      ${medalOf(s) || `<span class="cls-ico">${CLASS_ICON[s.cls] || "?"}</span>`}
      ${spec && !s.medal ? '<span class="spectag" title="the mech you are watching from the spectator view">SPECTATING</span>' : ""}
      <div class="pl-name">${s.code ? `${escapeHtml(s.name)} <b>${s.code}${s.variant ? "-" + escapeHtml(s.variant) : ""}</b>` : "MECH NOT SHOWN"}</div>
      <div class="pl-pilot">${escapeHtml(s.pilot)}</div>
      <div class="pl-meta">${s.code ? `<span>${s.tons}t</span>` : ""}${role ? `<span class="role">${role}</span>` : ""}${s.score != null ? `<span class="score">${s.score}</span>` : ""}${dealt}<span class="dmg ${lvl}" title="${hpv != null && s.alive ? hpv + "% left, as read off the lance panel or the target readout" : s.alive ? "no health read yet for this mech" : "destroyed"}">${dmg}</span></div>
      ${hp}
      ${loadoutOf(s) ? `<div class="pl-load" title="weapons read when this mech was locked">${escapeHtml(loadoutOf(s))}</div>` : ""}
    </div>
  </div>`;
}
// the community build guides for this mech: GrimMechs lists them by chassis, one anchor per
// variant (BuildGuides?c=Shadow+Cat#SHC-PRIME).  Opened by the viewer's own browser on a click;
// the helper itself still makes no outbound connection.
function buildUrl(s) {
  const chassis = encodeURIComponent(s.name || s.code).replace(/%20/g, "+");
  const anchor = s.variant ? `#${s.code}-${encodeURIComponent(s.variant.toUpperCase())}` : "";
  return `https://grimmechs.isengrim.org/BuildGuides?c=${chassis}${anchor}`;
}
function hpOf(s) { if (!s.alive || s.health == null) return null; return s.health; }   // null = nothing read yet
function loadoutOf(s) {
  if (!s.loadout || !s.loadout.length) return "";
  const n = new Map(); for (const w of s.loadout) n.set(w, (n.get(w) || 0) + 1);
  return [...n.entries()].map(([w, c]) => (c > 1 ? c + "× " : "") + w.replace("MEDIUM", "MED").replace("SMALL", "SML").replace("LARGE", "LRG")).join(" · ");
}
function tonnage(slots) { return slots.reduce((a, s) => a + (s.tons || 0), 0); }
// the weight-class mix as a spider chart: four axes, Assault up, rings at 2/4/6 mechs
function radar(counts, enemy) {
  const axes = ["Assault", "Heavy", "Medium", "Light"], R = 44, cx = 62, cy = 58, MAX = 6;
  const pt = (i, v) => { const a = -Math.PI / 2 + i * Math.PI / 2; const r = R * Math.min(1, v / MAX); return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; };
  const ring = k => axes.map((_, i) => pt(i, k).join(",")).join(" ");
  const poly = axes.map((c, i) => pt(i, counts[c]).join(",")).join(" ");
  const lab = (i, dx, dy) => { const [x, y] = pt(i, MAX * 1.32); return [x + dx, y + dy]; };
  return `<svg class="radar ${enemy ? "foe" : ""}" viewBox="0 0 124 116" aria-label="weight class mix">
    ${[2, 4, 6].map(k => `<polygon class="ring" points="${ring(k)}"/>`).join("")}
    ${axes.map((_, i) => { const [x, y] = pt(i, MAX); return `<line class="axis" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}"/>`; }).join("")}
    <polygon class="area" points="${poly}"/>
    ${axes.map((c, i) => { const [x, y] = pt(i, counts[c]); return counts[c] ? `<circle class="dot c-${c}" cx="${x}" cy="${y}" r="2.6"/>` : ""; }).join("")}
    ${axes.map((c, i) => { const [x, y] = lab(i, 0, 0); return `<text class="lbl c-${c}" x="${x}" y="${y}" text-anchor="middle">${c.toUpperCase()}<tspan class="n"> ${counts[c]}</tspan></text>`; }).join("")}
  </svg>`;
}
function overview(slots, enemy) {
  const known = slots.filter(s => s.code);
  const tons = tonnage(slots), max = 12 * 100;
  const counts = {Assault: 0, Heavy: 0, Medium: 0, Light: 0};
  for (const s of known) if (counts[s.cls] != null) counts[s.cls]++;
  const cap = {ECM: 0, JJ: 0, LRM: 0, BRAWL: 0, SNIPER: 0, SCOUT: 0};
  for (const s of known) {
    const r = roleOf(s), t = tagsOf(s);
    if (t.includes("ECM")) cap.ECM++;
    if (t.includes("JJ")) cap.JJ++;
    if (r === "FIRE SUPPORT") cap.LRM++;
    if (r === "BRAWLER") cap.BRAWL++;
    if (r === "SNIPER") cap.SNIPER++;
    if (r === "SCOUT" || r === "FLANK") cap.SCOUT++;
  }
  const alive = slots.filter(s => s.alive).length;
  const checks = [];
  if (known.length >= 6) {
    const spread = Object.values(counts).filter(v => v > 0).length;
    checks.push([spread >= 3 && counts.Assault <= 6, spread >= 3 ? "Balanced tonnage" : "Lopsided weight classes"]);
    checks.push([cap.ECM >= 1, cap.ECM ? "ECM coverage" : "No ECM"]);
    checks.push([cap.BRAWL >= 1 && (cap.SNIPER + cap.LRM) >= 1, "Good range mix"]);
    checks.push([cap.SCOUT >= 1, cap.SCOUT ? "Scout presence" : "No scouts"]);
    checks.push([cap.BRAWL >= 3, cap.BRAWL >= 3 ? "Brawl capability" : "Light on brawlers"]);
    if (cap.LRM >= 4) checks.push([null, enemy ? "Missile heavy: bring AMS, use cover" : "Missile heavy: needs a spotter"]);
    if (cap.SNIPER >= 4) checks.push([null, enemy ? "Sniper heavy: close the distance" : "Sniper heavy: hold the ridges"]);
  } else {
    checks.push([null, "Analysis once six mechs are known"]);
  }
  const ok = v => v === null ? "warn" : v ? "ok" : "bad";
  return `<div class="overview">
    <div class="ov-col">
      <h4>TEAM OVERVIEW</h4>
      <div class="ov-big">${slots.length} / 12 <small>PILOTS</small></div>
      <div class="ov-sub">${alive} alive${known.length < slots.length ? ` · ${slots.length - known.length} mech${slots.length - known.length > 1 ? "s" : ""} not shown` : ""}</div>
      <div class="ov-label">TONNAGE</div>
      <div class="ov-big">${tons} <small>/ ${max}</small></div>
      <div class="ov-bar"><i style="width:${Math.min(100, tons / max * 100)}%"></i></div>
      ${radar(counts, enemy)}
    </div>
    <div class="ov-col">
      <h4>CAPABILITIES</h4>
      <ul class="ov-caps">
        ${[["ECM", cap.ECM], ["JUMP JETS", cap.JJ], ["LRM / FIRE SUPPORT", cap.LRM], ["BRAWL", cap.BRAWL], ["SNIPER", cap.SNIPER], ["SCOUT / FLANK", cap.SCOUT]]
          .map(([n, v]) => `<li><span>${n}</span><b>${v}</b><i class="${v ? "ok" : "no"}">${v ? "✓" : "–"}</i></li>`).join("")}
      </ul>
    </div>
    <div class="ov-col">
      <h4>COMPOSITION ANALYSIS</h4>
      <ul class="ov-checks">${checks.map(([v, t]) => `<li class="${ok(v)}"><i>${v === null ? "⚠" : v ? "✓" : "✕"}</i>${t}</li>`).join("")}</ul>
    </div>
  </div>`;
}
const LANCE_ROLES = ["FRONTLINE<br><small>(BRAWL)</small>", "FIRE SUPPORT<br><small>(MID RANGE)</small>", "MANEUVER<br><small>(SCOUT)</small>"];
let specName = "";                                   // the team-mate being watched after your death, this render
function renderTeam(id, slots, enemy, d) {
  specName = enemy ? "" : (d.spectating || "");
  const seats = seatLances(slots);
  const alive = slots.filter(s => s.alive).length;
  document.getElementById(id).innerHTML = `
    <div class="teamhead ${enemy ? "foe" : "me"}">
      <h3>${enemy ? "ENEMY TEAM" : "MY TEAM"}</h3>
      <span>${slots.length ? `${alive} / ${slots.length} ALIVE` : (enemy ? "NOT SEEN YET" : "WAITING FOR THE DROP SCREEN")}${d.frozen ? " · 🔒 LOCKED" : ""}</span>
    </div>
    ${LANCES.map((l, li) => `
      <div class="lance ${l.tone} ${enemy ? "foe" : ""}">
        <div class="lancehead">
          <div class="lname">${l.name.replace(" ", "<br>")}</div>
          <div class="emblem">${l.emblem}</div>
          <div class="motto">${l.motto}</div>
        </div>
        <div class="pads">${seats[li].map((s, i) => pad(s, li * 4 + i)).join("")}</div>
        <div class="lancerole">${LANCE_ROLES[li]}</div>
      </div>`).join("")}
    ${overview(slots, enemy)}`;
}
function renderLances(d) {
  renderTeam("lancesMine", d.mine || [], false, d);
  renderTeam("lancesEnemy", d.enemy || [], true, d);
}

// ── RECORDS: the final screen of every match, newest first ──────────────────────────
let recordsV = -1, recordsBusy = false, recordsAgain = false;
function fmtDate(ts) { const d = new Date((ts || 0) * 1000); return d.toLocaleDateString(undefined, {weekday: "short", day: "2-digit", month: "short"}) + " · " + d.toLocaleTimeString(undefined, {hour: "2-digit", minute: "2-digit"}); }
async function loadRecords() {
  if (recordsBusy) { recordsAgain = true; return; } recordsBusy = true;
  try {
    const list = await fetch("/api/records").then(r => r.json());
    list.sort((a, b) => (b.started || b.saved || 0) - (a.started || a.saved || 0));
    document.getElementById("recCount").textContent = list.length ? `${list.length} MATCH${list.length > 1 ? "ES" : ""} · ${list.filter(r => r.result === "VICTORY").length} W / ${list.filter(r => r.result === "DEFEAT").length} L` : "NO MATCH RECORDED YET";
    const byDay = new Map();
    for (const r of list) { const k = new Date((r.started || r.saved || 0) * 1000).toDateString(); if (!byDay.has(k)) byDay.set(k, []); byDay.get(k).push(r); }
    document.getElementById("records").innerHTML = list.length ? [...byDay.entries()].map(([day, rs]) => `
      <h4 class="recday">${day.toUpperCase()}</h4>
      <div class="recgrid">${rs.map(r => `
        <article class="rec ${(r.result || "").toLowerCase()}">
          <a class="shot" href="${r.image || "#"}" target="_blank" title="open the full screen">${r.image ? `<img src="${r.image}?v=${r.saved || 0}" alt="">` : '<div class="noshot">no screen kept</div>'}
            <span class="res">${r.result || "MATCH"}</span></a>
          <div class="recbody">
            <div class="rechead"><b>${escapeHtml(r.map || "unknown map")}</b><span>${escapeHtml(r.mode || "")}</span><span class="recright"><time>${fmtDate(r.started || r.saved)}</time><button class="recboard" data-id="${r.match_id}">BOARD ▾</button><button class="recdel" data-id="${r.match_id}" title="delete this record">✕</button></span></div>
            <div class="recscore"><span class="mine">${r.mine_alive}/${r.mine}</span> alive <em>vs</em> <span class="foe">${r.enemy_alive}/${r.enemy}</span></div>
            ${r.me ? `<div class="recme">${r.me.code ? escapeHtml(r.me.name) + " " + r.me.code + (r.me.variant ? "-" + escapeHtml(r.me.variant) : "") : "mech not shown"}${r.me.score != null ? ` · score ${r.me.score}` : ""}${r.me.medal ? " " + MEDAL[r.me.medal] : ""}${r.me.alive ? "" : " · destroyed"}</div>` : ""}
            <div class="recrow">
              <ul class="recmedals">${(r.medals || []).map(m => `<li><i>${MEDAL[m.medal]}</i><b class="${m.side}">${escapeHtml(m.pilot)}</b><span>${m.code ? escapeHtml(m.name || "") + " " + m.code + (m.variant ? "-" + escapeHtml(m.variant) : "") : ""}</span><em>${m.score != null ? m.score : ""}</em></li>`).join("") || '<li class="none">no scores read</li>'}</ul>
              ${podiumOf(r)}
            </div>
          </div>
          <div class="recteams" id="rb-${r.match_id}" hidden></div>
        </article>`).join("")}</div>`).join("") : '<div class="empty">The final screen of each match is kept here once the results table has been read. Stay on the results screen a couple of seconds at the end of a match.</div>';
  } catch (e) { /* the helper may be restarting */ }
  finally { recordsBusy = false; if (recordsAgain) { recordsAgain = false; loadRecords(); } }
}
// the podium: the winning side's gold, silver and bronze as portraits (your side on a tie)
function podiumOf(r) {
  const side = r.result === "DEFEAT" ? "enemy" : "mine";
  const top = (r.medals || []).filter(m => m.side === side && m.medal).sort((a, b) => a.medal - b.medal).slice(0, 3);
  if (!top.length) return "";
  return `<div class="recpodium ${side}">${top.map(m => {
    const s = {code: m.code, variant: m.variant};
    const pic = m.code ? (cutOf(s) || picOf(s)) : null;
    return `<div class="pseat m${m.medal}" title="${escapeHtml(m.pilot)}${m.score != null ? " · score " + m.score : ""}">
      <div class="ppic">${pic ? `<img src="${pic}" alt="">` : `<span>${m.code || "?"}</span>`}<i>${MEDAL[m.medal]}</i></div>
      <b>${escapeHtml(m.pilot)}</b>
      <span>${m.code ? escapeHtml(m.name || m.code) : "mech not shown"}</span>
      <em>${m.score != null ? m.score : ""}</em>
    </div>`;
  }).join("")}</div>`;
}
document.getElementById("records").addEventListener("click", async e => {
  const bb = e.target.closest(".recboard");
  if (bb) {                                              // unfold the match's board: both teams, medals and all
    const host = document.getElementById("rb-" + bb.dataset.id);
    if (!host.hidden) { host.hidden = true; bb.textContent = "BOARD ▾"; return; }
    const d = await fetch("/api/records/" + encodeURIComponent(bb.dataset.id)).then(r => r.json());
    host.innerHTML = `<div class="teams"><div class="teamcol mine" id="rbm-${bb.dataset.id}"></div><div class="teamcol enemy" id="rbe-${bb.dataset.id}"></div></div>`;
    renderTeam("rbm-" + bb.dataset.id, d.mine || [], false, d);
    renderTeam("rbe-" + bb.dataset.id, d.enemy || [], true, d);
    host.hidden = false; bb.textContent = "BOARD ▴";
    return;
  }
  const b = e.target.closest(".recdel"); if (!b) return;
  if (!armed(b, "SURE?")) return;
  const r = await fetch("/api/records/" + encodeURIComponent(b.dataset.id), {method: "DELETE"}).then(r => r.json()).catch(() => null);
  if (!r || !r.removed) { b.textContent = "FAILED"; b.title = "the helper could not remove the record files"; return; }
  loadRecords();
});

// Two-step buttons instead of the browser's confirm box, which game overlays and app windows
// tend to swallow: the first click arms the button (red, new label), a second click within 4 s
// goes through, otherwise it disarms itself.
function armed(btn, label) {
  if (btn.dataset.armed) { clearTimeout(btn._disarm); delete btn.dataset.armed; btn.classList.remove("armed"); btn.innerHTML = btn._label; return true; }
  btn.dataset.armed = "1"; btn._label = btn.innerHTML; btn.innerHTML = label; btn.classList.add("armed");
  btn._disarm = setTimeout(() => { delete btn.dataset.armed; btn.classList.remove("armed"); btn.innerHTML = btn._label; }, 4000);
  return false;
}

// ── MY MECHS: what the pilot has played, mech by mech, out of the records ──────────────
let myMechsBusy = false, myMechsAgain = false;   // a call during a load runs once more after it
const undoable = new Set();                       // mechs reset on this visit of the board: UNDO stays until the menu changes
async function loadMyMechs() {
  if (myMechsBusy) { myMechsAgain = true; return; } myMechsBusy = true;
  try {
    const d = await fetch("/api/mymechs").then(r => r.json());
    const t = d.total || {};
    document.getElementById("myTotal").textContent = t.games
      ? `${escapeHtml(d.pilot).toUpperCase()} · ${t.games} GAME${t.games > 1 ? "S" : ""} · ${t.wins} W / ${t.losses} L${t.avg != null ? " · AVG SCORE " + t.avg : ""}${t.best ? " · BEST " + t.best : ""} · ${MEDAL[1]} ${t.medals[0]} ${MEDAL[2]} ${t.medals[1]} ${MEDAL[3]} ${t.medals[2]}`
      : (d.pilot ? (d.mechs && d.mechs.length ? escapeHtml(d.pilot).toUpperCase() + " · NO GAME COUNTED SINCE THE RESET" : "NO MATCH RECORDED YET FOR " + escapeHtml(d.pilot).toUpperCase()) : "SET YOUR PILOT NAME FIRST");
    const host = document.getElementById("myMechs");
    if (!d.mechs || !d.mechs.length) { host.innerHTML = '<div class="empty">Your mechs appear here after the first match whose results screen was read. Stay on the results a couple of seconds at the end of a match.</div>'; return; }
    host.innerHTML = d.mechs.map(m => {
      const s = {code: m.code, variant: m.variant, cls: m.cls};
      const pic = cutOf(s) || picOf(s);
      const wr = m.wins + m.losses ? Math.round(100 * m.wins / (m.wins + m.losses)) : null;
      const surv = m.games ? Math.round(100 * m.survived / m.games) : 0;
      const since = m.since ? `<em class="mm-since" title="stats count from this moment; earlier records are kept but not counted">SINCE ${fmtDate(m.since).toUpperCase()}</em>` : "";
      const tools = m.since && undoable.has(m.key)
        ? `<span class="mm-tools">${since}<button class="mmundo" data-key="${escapeHtml(m.key)}" title="count every record for this mech again">UNDO</button></span>`
        : `<span class="mm-tools">${since}<button class="mmreset" data-key="${escapeHtml(m.key)}" title="clean start for this mech: stats count from now on, match records are kept">RESET</button></span>`;
      return `<article class="mymech c-${m.cls}${m.games ? "" : " fresh"}">
        <div class="mm-pic">${pic ? `<img src="${pic}" alt="">` : `<span>${m.code}</span>`}<b class="tons">${m.tons}t</b></div>
        <div class="mm-body">
          <div class="mm-head"><b>${escapeHtml(m.name || m.code)}</b><i>${m.code}${m.variant ? "-" + escapeHtml(m.variant) : ""}</i><span class="role">${roleOf(s)}</span>${tools}</div>
          <div class="mm-stats">
            <div><b>${m.games}</b><span>GAMES</span></div>
            <div><b class="${wr == null ? "" : wr >= 50 ? "good" : "bad"}">${m.wins}<small>W</small> ${m.losses}<small>L</small></b><span>${wr != null ? wr + "% WIN" : "RESULT"}</span></div>
            <div><b>${m.avg != null ? m.avg : "–"}</b><span>AVG SCORE</span></div>
            <div><b>${m.best || "–"}</b><span>BEST</span></div>
            <div><b>${surv}%</b><span>SURVIVED</span></div>
            <div><b class="medals">${m.medals[0] ? MEDAL[1] + m.medals[0] : ""}${m.medals[1] ? " " + MEDAL[2] + m.medals[1] : ""}${m.medals[2] ? " " + MEDAL[3] + m.medals[2] : ""}${!m.medals.some(x => x) ? "–" : ""}</b><span>MEDALS</span></div>
          </div>
          <div class="mm-matches">${!m.games && m.since ? '<span class="none">clean start · no match recorded since</span>' : ""}${m.matches.slice(0, 8).map(x => `<span class="${(x.result || "").toLowerCase()}" title="${escapeHtml(x.map || "")} · ${escapeHtml(x.mode || "")}${x.score != null ? " · score " + x.score : ""}${x.alive ? "" : " · destroyed"}">${x.result === "VICTORY" ? "W" : x.result === "DEFEAT" ? "L" : "·"}${x.medal ? MEDAL[x.medal] : ""}${x.score != null ? " " + x.score : ""}</span>`).join("")}</div>
          ${m.pros ? `<div class="pros">+ ${escapeHtml(m.pros)}</div><div class="cons">&minus; ${escapeHtml(m.cons || "")}</div>` : ""}
        </div>
      </article>`;
    }).join("");
  } catch (e) { /* the helper may be restarting */ }
  finally { myMechsBusy = false; if (myMechsAgain) { myMechsAgain = false; loadMyMechs(); } }
}
document.getElementById("myMechs").addEventListener("click", async e => {
  const r = e.target.closest(".mmreset"), u = e.target.closest(".mmundo");
  if (!r && !u) return;
  if (r && !armed(r, "SURE? RECORDS ARE KEPT")) return;
  const key = (r || u).dataset.key;
  await fetch(r ? "/api/mymechs/reset" : "/api/mymechs/restore", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mech: key})});
  if (r) undoable.add(key); else undoable.delete(key);
  loadMyMechs();
});

// ── the bottom strip: spotted mechs, the map card, the match state ───────────────────
function renderFooter(d) {
  const seen = d.seen || [];
  document.getElementById("seenStrip").innerHTML = `<h5>SPOTTED, PILOT UNKNOWN</h5><div class="seenrow">${seen.length ? seen.map(s => {
    const pic = picOf(s);
    return `<div class="mini ${s.alive ? "" : "dead"} c-${s.cls}">${s.code ? `<a class="build" href="${buildUrl(s)}" target="_blank" rel="noopener" title="builds on GrimMechs">` : ""}${pic ? `<img src="${pic}" alt="">` : `<span>${s.code}</span>`}${s.code ? "</a>" : ""}<div class="mname">${escapeHtml(s.name)}</div><div class="msub">${s.code}-${escapeHtml(s.variant)}${s.health != null ? " · " + s.health + "%" : ""}</div></div>`;
  }).join("") : '<div class="none">enemy mechs seen before their pilot is known appear here</div>'}</div>`;
  const file = mapFile(d.map);
  document.getElementById("mapCard").innerHTML = d.map ? `<div class="mappic" style="${file ? `background-image:url('/assets/maps/${file}')` : `background:${(MAP_TONES[d.map] || ["#1a2028"])[0]}`}"></div><div class="maptxt"><b>${escapeHtml(d.map).toUpperCase()}</b><span>${escapeHtml(d.mode || "")}</span></div>`
                                               : `<div class="mappic"></div><div class="maptxt"><b>NO MAP YET</b><span>read from the loading screen</span></div>`;
  const st = document.getElementById("dropState");
  let text = "WAITING FOR DROP", cls = "";
  if (d.result) { text = d.result; cls = d.result.toLowerCase(); }
  else if (d.spectating) { text = "SPECTATING " + escapeHtml(d.spectating).toUpperCase(); cls = "spec"; }
  else if (d.frozen) { text = "IN MATCH · LOCKED"; cls = "live"; }
  else if ((d.mine || []).length) { text = "READING THE DROP"; cls = "live"; }
  st.textContent = text; st.className = "dropstate " + cls;
  document.getElementById("navstats").innerHTML = `${(d.mine || []).length || 12} PILOTS<br>${d.map ? escapeHtml(d.map) : "1 MAP"}<br>${d.mode ? escapeHtml(d.mode) : "1 OBJECTIVE"}`;
}

// ── the balance bar: who is winning ──────────────────────────────────────────────────
function strength(slots, fallbackCount) {
  if (!slots.length) return fallbackCount * 100;
  let total = 0;
  for (const s of slots) total += s.alive ? (s.health != null ? s.health : 100) : 0;
  if (slots.length < 12) total += (12 - slots.length) * 100;
  return total;
}
function renderBalance(d) {
  const mine = d.mine || [], enemy = d.enemy || [];
  const a = strength(mine, 12), b = strength(enemy, 12);
  const share = a + b > 0 ? a / (a + b) : 0.5;
  const pct = Math.round(share * 100);
  document.getElementById("balBlue").style.width = pct + "%";
  document.getElementById("balRed").style.width = (100 - pct) + "%";
  document.getElementById("balMid").style.left = pct + "%";
  const am = mine.filter(s => s.alive).length, ae = enemy.filter(s => s.alive).length;
  document.getElementById("balBlueText").textContent = `MY TEAM ${mine.length ? am + "/" + mine.length : ""} · ${pct}%`;
  document.getElementById("balRedText").textContent = `${100 - pct}% · ${enemy.length ? ae + "/" + enemy.length : ""} ENEMY`;
  document.getElementById("balance").classList.toggle("winning", pct > 55);
  document.getElementById("balance").classList.toggle("losing", pct < 45);
}

let lastState = null;
// pictures can appear while the page is open (the cutter, a harvest): refresh the lists now and then
setInterval(() => loadAssets().then(() => { if (lastState) { lastVersion = -1; apply(lastState); } }), 45000);
function apply(d) {
  if (d.version === lastVersion) return;
  lastVersion = d.version; lastState = d;
  if (d.my_name != null && d.my_name !== myName) { myName = d.my_name; if (document.activeElement !== meBox) meBox.value = myName; }
  if (d.donate_url) { document.getElementById("donateBtn").href = d.donate_url; document.getElementById("aboutDonate").href = d.donate_url; }
  if (d.app_version) document.getElementById("aboutVer").textContent = "v" + d.app_version;
  if (d.assets_v != null && d.assets_v !== assetsV) {
    const first = assetsV < 0; assetsV = d.assets_v;
    if (!first) { loadAssets().then(() => { lastVersion = -1; apply(d); }); return; }
  }
  renderBalance(d);
  renderLances(d);
  renderFooter(d);
  if (d.records_v != null && d.records_v !== recordsV) { recordsV = d.records_v; if ((prefs.view || "lances") === "records") loadRecords(); }
  lastMap = d.map || ""; paintMap(lastMap);
  document.getElementById("src").textContent = d.source === "none" ? "no frame" : `${d.source} · ${d.kind || ""} · ${new Date(d.ts * 1000).toLocaleTimeString()}`;
  document.getElementById("ocr").textContent = d.stats && d.stats.ocr_ms != null ? `ocr ${d.stats.ocr_ms} ms · ${d.stats.frames} frames · ${d.stats.last_kind}${d.stats.last_error ? " · " + d.stats.last_error : ""}` : "";
  document.getElementById("liveBtn").textContent = "LIVE: " + (d.live ? "ON" : "OFF");
  document.getElementById("liveBtn").classList.toggle("off", !d.live);
  const note = document.getElementById("note"); note.textContent = d.note || ""; note.hidden = !d.note;
  if (d.records_v != null && (prefs.view || "lances") === "board") loadMyMechs();
}

// ?demo=1 shows a canned match (for screenshots and a first look); ?view=lances|field|board|records picks the view
const DEMO = new URLSearchParams(location.search).get("demo") === "1";
const VIEW_PARAM = new URLSearchParams(location.search).get("view");
if (VIEW_PARAM && VIEWS[VIEW_PARAM]) { prefs.view = VIEW_PARAM; }
function demoState() {
  const mk = (pilot, code, variant, name, tons, cls, lance, alive = true, health = null, medal = 0, loadout = null, score = null) =>
    ({pilot, code, variant, name, tons, cls, faction: "IS", pros: "", cons: "", alive, status: alive ? "ALIVE" : "DEAD", health, lance, conf: 0.9, score, medal, locked: true, guess: false, loadout});
  const mine = [
    mk("Phoenix", "AS7", "D-DC", "Atlas", 100, "Assault", "ALPHA", true, 82), mk("Razor", "KGC", "000", "King Crab", 100, "Assault", "ALPHA", true, 61),
    mk("Torque", "WHM", "6R", "Warhammer", 70, "Heavy", "ALPHA", false, null, 0, null, 210), mk("Mako", "DWF", "A", "Dire Wolf", 100, "Assault", "ALPHA", true, 97, 1, null, 612),
    mk("Viper", "TBR", "S", "Timber Wolf", 75, "Heavy", "BRAVO", true, 55), mk("Shade", "MDD", "A", "Mad Dog", 60, "Heavy", "BRAVO", true, 100),
    mk("Kestrel", "HBR", "F", "Hellbringer", 65, "Heavy", "BRAVO", false), mk("Nyx", "SHC", "PRIME", "Shadow Cat", 45, "Medium", "BRAVO", true, 74),
    mk("You", "RVN", "3L", "Raven", 35, "Light", "CHARLIE", true, 88), mk("Sprite", "LCT", "1V", "Locust", 20, "Light", "CHARLIE", true, 100),
    mk("Fang", "PIR", "2", "Piranha", 20, "Light", "CHARLIE", true, 23), mk("Blitz", "JR7", "D", "Jenner", 35, "Light", "CHARLIE", false),
  ];
  const enemy = [
    mk("Stalker Jack", "STK", "3F", "Stalker", 85, "Assault", "", true, 70, 2, ["LRM 15", "LRM 15", "MED LASER", "MED LASER"], 540), mk("Yankee", "CPLT", "C1", "Catapult", 65, "Heavy", "", true, 100),
    mk("Xray", "AWS", "8Q", "Awesome", 80, "Assault", "", false), mk("Whisk", "NVA", "PRIME", "Nova", 50, "Medium", "", true, 44, 0, ["ER MED LASER", "ER MED LASER", "ER MED LASER", "ER MED LASER", "ER MED LASER", "ER MED LASER"]),
    mk("Victor", "ACW", "PRIME", "Arctic Wolf", 40, "Medium", "", true, 90), mk("Uniform", null, "", "", 0, "Unknown", ""),
    mk("Tango", "BSW", "X1", "Bushwacker", 55, "Medium", "", true, 100), mk("Sierra", "UM", "R60", "Urbanmech", 30, "Light", "", true, 100, 3, null, 480),
    mk("Romeo", "MAD", "3R", "Marauder", 75, "Heavy", "", false), mk("Quebec", null, "", "", 0, "Unknown", ""),
    mk("Papa", "HBK", "4G", "Hunchback", 50, "Medium", "", true, 100), mk("Oscar", "COM", "2D", "Commando", 25, "Light", "", true, 100),
  ];
  return {version: 1, kind: "scoreboard", source: "demo", ts: Date.now() / 1000, mine, enemy, map: "Canyon Network", mode: "CONQUEST", note: "", stats: {ocr_ms: 140, frames: 42, last_kind: "demo"}, live: true, my_name: "You", frozen: true, seen: [], assets_v: 0, app_version: "demo"};
}
function connect() {
  if (DEMO) return;                                        // the canned match is applied once the pictures are listed
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.onmessage = e => apply(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);
}
applyPrefs();
connect();

// ── the pilot using the app ──────────────────────────────────────────────────────────
const meBox = document.getElementById("meName");
async function saveMe() {
  const v = meBox.value.trim();
  if (v === myName) return;
  myName = v; lastVersion = -1;
  await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({my_name: v})});
}
meBox.addEventListener("change", saveMe);
meBox.addEventListener("keydown", e => { if (e.key === "Enter") { meBox.blur(); } });
document.getElementById("content").addEventListener("click", e => {          // click a pilot name: "that's me"
  const p = e.target.closest(".card .pilot, .pl-pilot");
  if (!p) return;
  meBox.value = p.textContent.trim(); saveMe();
});
document.getElementById("liveBtn").onclick = async () => {
  const on = document.getElementById("liveBtn").textContent.endsWith("OFF");
  await fetch("/api/live", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({on})});
  document.getElementById("liveBtn").textContent = "LIVE: " + (on ? "ON" : "OFF");
  document.getElementById("liveBtn").classList.toggle("off", !on);
};
document.getElementById("aboutBtn").onclick = () => { document.getElementById("about").hidden = false; };
document.getElementById("aboutClose").onclick = () => { document.getElementById("about").hidden = true; };
document.getElementById("about").addEventListener("click", e => { if (e.target.id === "about") e.target.hidden = true; });
document.getElementById("resetBtn").onclick = async () => {
  await fetch("/api/reset", {method: "POST"});
  lastVersion = -1; fetch("/api/state").then(r => r.json()).then(apply);
};

// drag & drop a screenshot anywhere
const drop = document.getElementById("drop");
window.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("show"); });
window.addEventListener("dragleave", e => { if (!e.relatedTarget) drop.classList.remove("show"); });
window.addEventListener("drop", async e => {
  e.preventDefault(); drop.classList.remove("show");
  const f = e.dataTransfer.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch("/api/screenshot", {method: "POST", body: fd});
  lastVersion = -1; apply(await r.json());
});
