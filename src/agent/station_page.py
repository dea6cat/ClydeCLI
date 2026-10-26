"""The station's page: one HTML string with its CSS and JS inline (no outside scripts, fonts or images: it works offline).

Three views of the same recorded state: the station (an isometric pixel-art scene of rooms, furniture and crew, drawn in code),
the member cards with their approvals, and the event feed.

The scene shows only what the run recorded. Rooms, furniture and hallways come from station_layout.py. Every movement of the
crew is a pure function of the recorded events and the clock: a worker walks to the furniture for a tool when it used that
tool, Clyde and Bonnie walk to a worker when a `check` event says they did, and a worker waits with a "?" while its approval
is pending. Nobody wanders: a crew member with nothing recorded stands at its place. A theme changes only the look and the words.

Everything else that moves (clouds, rain, searchlights, flickering lamps) is scenery: it says nothing about the run.

Everything is set with textContent and attributes, never parsed as markup: event text carries paths, commands and model output.
"""
from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clyde station</title>
<style>
:root {
  --bg: #f6f5f1; --panel: #ffffff; --ink: #1c1b19; --muted: #6b675f; --line: #dcd8cd;
  --accent: #0b6e4f; --warn: #a15c00; --bad: #b3261e; --ok: #0b6e4f; --idle: #8a867c;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14130f; --panel: #1e1d18; --ink: #ece9df; --muted: #a29e92; --line: #38362e;
    --accent: #4cc38a; --warn: #e0a64a; --bad: #f0837c; --ok: #4cc38a; --idle: #8a867c;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1680px; margin: 0 auto; padding: 20px 16px 48px; }
header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
h1 { font-size: 20px; margin: 0; }
.muted { color: var(--muted); }
.spacer { flex: 1; }
select { font: inherit; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); }
.run { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin-bottom: 18px; }
.run-head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.run-head h2 { font-size: 16px; margin: 0; flex: 1 1 260px; overflow-wrap: anywhere; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.chip.running, .chip.reviewing { color: var(--accent); border-color: var(--accent); }
.chip.awaiting_approval { color: var(--warn); border-color: var(--warn); }
.chip.failed, .chip.stopped { color: var(--bad); border-color: var(--bad); }
.chip.done { color: var(--ok); border-color: var(--ok); }
.clyde { margin: 10px 0 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; }
.card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; cursor: pointer; background: var(--bg); text-align: left; font: inherit; color: inherit;
  display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start; }   /* a button centres its content; cards must start at the top */
.card[aria-pressed="true"] { border-color: var(--accent); }
.card .who { display: flex; gap: 8px; align-items: center; font-weight: 600; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--idle); flex: none; }
.dot.on { background: var(--accent); animation: pulse 1.2s ease-in-out infinite; }
.dot.wait { background: var(--warn); animation: pulse 1.2s ease-in-out infinite; }
.dot.bad { background: var(--bad); }
.dot.fin { background: var(--ok); }
@keyframes pulse { 50% { opacity: .35; } }
.card .model { font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
.card .doing { margin-top: 4px; }
.card .rule { margin-top: 6px; font-size: 12px; color: var(--muted); }
.asks { margin-top: 14px; }
.ask { border: 1px solid var(--warn); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.ask pre { margin: 6px 0 8px; white-space: pre-wrap; overflow-wrap: anywhere; font: 12.5px/1.4 ui-monospace, Menlo, monospace; max-height: 160px; overflow: auto; }
button.act { font: inherit; padding: 5px 14px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; margin-right: 8px; }
button.act.allow { border-color: var(--ok); color: var(--ok); }
button.act.deny { border-color: var(--bad); color: var(--bad); }
button.act:focus-visible, .card:focus-visible, select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.feed { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
.feed h3 { font-size: 13px; margin: 0 0 6px; font-weight: 600; }
.log { font: 12.5px/1.5 ui-monospace, Menlo, monospace; max-height: 260px; overflow: auto; margin: 0; padding: 0; list-style: none; }
.log li { white-space: pre-wrap; overflow-wrap: anywhere; }
.log .t { color: var(--muted); }
.empty { color: var(--muted); padding: 30px 0; text-align: center; }
#status { font-size: 12px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; margin: 0; padding: 0; list-style: none; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: var(--muted); margin: 0 0 14px; }
.legend i { display: inline-block; width: 22px; height: 0; border-top: 3px solid; vertical-align: middle; margin-right: 5px; }
.legend i.dark { border-top-style: dotted; border-color: var(--idle); } .legend i.lit { border-color: var(--accent); }
.legend i.waiting { border-color: var(--warn); border-top-style: dashed; } .legend i.refused { border-color: var(--bad); }

/* A run: the scene on the left, a glass rail on the right (crew, what needs your OK, the event feed), as StarNet frames its station. */
.run-body { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 14px; align-items: start; }
@media (max-width: 1060px) { .run-body { grid-template-columns: minmax(0, 1fr); } }
.stage { position: relative; min-width: 0; }
.zoom { position: absolute; right: 10px; top: 10px; display: flex; gap: 6px; z-index: 2; }
.zoom button { width: 30px; height: 30px; border-radius: 8px; border: 1px solid rgba(255,255,255,.25); background: rgba(10,10,16,.65); color: #fff; font: 600 16px/1 system-ui; cursor: pointer; backdrop-filter: blur(6px); }
.zoom button:hover { background: rgba(10,10,16,.85); } .zoom button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.rail { position: sticky; top: 12px; display: flex; flex-direction: column; gap: 12px; max-height: calc(100vh - 24px); min-height: 0; }
.glass { background: linear-gradient(125deg, rgba(255,255,255,.07), rgba(255,255,255,.02) 48%, transparent), color-mix(in srgb, var(--panel) 86%, transparent);
  border: 1px solid color-mix(in srgb, var(--ink) 14%, transparent); border-radius: 12px; box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 6px 22px rgba(0,0,0,.28); min-height: 0; display: flex; flex-direction: column; }
.glass.asking { border-color: var(--warn); box-shadow: 0 0 0 1px color-mix(in srgb, var(--warn) 50%, transparent), 0 6px 22px rgba(0,0,0,.28); }
.glass h3 { margin: 0; padding: 10px 14px 8px; font-size: 12px; letter-spacing: 2.2px; text-transform: uppercase; display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
  border-bottom: 1px solid color-mix(in srgb, var(--ink) 12%, transparent); font-weight: 700; }
.glass h3 small { font-size: 11px; letter-spacing: .4px; text-transform: none; color: var(--muted); font-weight: 500; }
.glass .body { padding: 6px; overflow: auto; min-height: 0; }
.crew-row { display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: 10px; width: 100%; padding: 8px; margin: 0 0 2px; border: 1px solid transparent; border-radius: 10px; text-align: left; background: none; font: inherit; color: inherit; cursor: pointer; }
.crew-row:hover, .crew-row[aria-pressed="true"] { background: color-mix(in srgb, var(--ink) 6%, transparent); border-color: color-mix(in srgb, var(--ink) 18%, transparent); }
.crew-row:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.crew-row.asking { border-color: var(--warn); background: linear-gradient(165deg, color-mix(in srgb, var(--warn) 14%, transparent), transparent 55%); }
.portrait { position: relative; width: 46px; height: 58px; border-radius: 8px; border: 1px solid color-mix(in srgb, var(--ink) 14%, transparent); background: rgba(0,0,0,.38); box-shadow: inset 0 2px 6px rgba(0,0,0,.5); display: flex; align-items: flex-end; justify-content: center; overflow: hidden; }
.portrait svg { width: 28px; height: 51px; display: block; }
.portrait .lamp { position: absolute; right: 4px; top: 4px; width: 8px; height: 8px; border-radius: 50%; background: var(--idle); box-shadow: 0 0 0 1px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.3); }
.portrait .lamp.on { background: var(--accent); animation: pulse 1.2s ease-in-out infinite; } .portrait .lamp.wait { background: var(--warn); animation: pulse 1.2s ease-in-out infinite; }
.portrait .lamp.bad { background: var(--bad); } .portrait .lamp.fin { background: var(--ok); }
.crew-row .nm { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; font-weight: 700; }
.crew-row .nm .chip { font-weight: 500; }
.crew-row .md { font-size: 11.5px; color: var(--muted); overflow-wrap: anywhere; }
.crew-row .st { margin-top: 2px; font-size: 13px; }
.crew-row .ru { margin-top: 3px; font-size: 11px; color: var(--muted); line-height: 1.35; }
.rail .asks { margin: 0; padding: 8px; } .rail .ask { margin: 0 0 8px; background: color-mix(in srgb, var(--warn) 8%, transparent); }
.rail .feed { margin: 0; border: 0; padding: 0; overflow: hidden; flex: 0 1 auto; display: flex; flex-direction: column; } .rail .feed h3 { border-top: 0; flex: none; } .rail .log { max-height: 30vh; flex: 1 1 auto; min-height: 4.5em; padding: 8px 10px; font-size: 11.5px; }
.cards-gone { display: none; }
/* The station. The scene is SVG built in code; a theme sets the look and the words (THEMES, below). */
.map { overflow-x: auto; margin: 0 0 10px; border-radius: 10px; border: 1px solid var(--line); background: #000; }   /* a phone scrolls the scene, not the page */
.map svg { display: block; min-width: 640px; width: 100%; height: auto; touch-action: none; cursor: grab; }
.map svg:active { cursor: grabbing; }
.map text { font-family: ui-monospace, Menlo, Consolas, monospace; paint-order: stroke; stroke-linejoin: round; }
.map .name { font-size: 11.5px; font-weight: 700; text-anchor: middle; }
.map .sign { font-size: 11px; font-weight: 700; text-anchor: middle; letter-spacing: .5px; }
.map .badge-n { font-size: 9px; font-weight: 700; text-anchor: middle; }
.map .sprite { cursor: pointer; }
.map .sprite .flip { filter: drop-shadow(1px 0 0 #0d0d12) drop-shadow(-1px 0 0 #0d0d12) drop-shadow(0 1px 0 #0d0d12) drop-shadow(0 -1px 0 #0d0d12); }
.map .lane { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.map .lane.waiting { animation: flow 1s linear infinite; }
@keyframes flow { to { stroke-dashoffset: -32; } }
@keyframes blink { 0%, 55% { opacity: 1; } 60%, 100% { opacity: .25; } }
@keyframes flick { 0%, 100% { opacity: 1; } 8% { opacity: .55; } 12% { opacity: 1; } 55% { opacity: .85; } 58% { opacity: .5; } 62% { opacity: 1; } }
@keyframes drift { from { transform: translateX(-160px); } to { transform: translateX(160px); } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes spinr { to { transform: rotate(-360deg); } }
@keyframes rain { from { transform: translateY(-80px); } to { transform: translateY(120px); } }
@keyframes puff { 0% { transform: translateY(0) scale(.5); opacity: .7; } 100% { transform: translateY(-46px) scale(1.5); opacity: 0; } }
@keyframes sweep { from { transform: rotate(-14deg); } to { transform: rotate(14deg); } }
@keyframes twinkle { 0%, 100% { opacity: .9; } 50% { opacity: .25; } }
@keyframes mote { from { transform: translate(0, 0); } to { transform: translate(40px, -60px); } }
@keyframes bars { 0%, 100% { transform: scaleX(1); } 50% { transform: scaleX(.45); } }
@keyframes glint { 0%, 70% { opacity: 0; } 80% { opacity: .9; } 100% { opacity: 0; } }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-40px); } }
.amb { transform-box: fill-box; }
.blink { animation: blink 1.4s steps(1) infinite; } .blink2 { animation: blink 1.1s steps(1) infinite .3s; } .blink3 { animation: blink 1.9s steps(1) infinite .7s; }
.flick { animation: flick 3.2s linear infinite; } .flick2 { animation: flick 4.1s linear infinite 1.1s; }
.drift { animation: drift 70s ease-in-out infinite alternate; } .drift2 { animation: drift 110s ease-in-out infinite alternate-reverse; }
.spin { animation: spin 60s linear infinite; transform-origin: center; transform-box: fill-box; } .spinr { animation: spinr 45s linear infinite; transform-origin: center; transform-box: fill-box; }
.rain { animation: rain 1.1s linear infinite; }
.puff { animation: puff 3s ease-out infinite; transform-origin: center; transform-box: fill-box; }
.sweep { animation: sweep 9s ease-in-out infinite alternate; }
.twinkle { animation: twinkle 3s ease-in-out infinite; }
.mote { animation: mote 14s linear infinite; }
.bars { animation: bars 2.2s ease-in-out infinite; transform-origin: left center; transform-box: fill-box; }
.glint { animation: glint 5s linear infinite; }
@media (prefers-reduced-motion: reduce) {
  .portrait .lamp, .dot, .map .lane.waiting, .amb, .blink, .blink2, .blink3, .flick, .flick2, .drift, .drift2, .spin, .spinr, .rain, .puff, .sweep, .twinkle, .mote, .bars, .glint { animation: none !important; }
}
</style>
</head>
<body>
<main>
  <header>
    <h1>Clyde station</h1><span class="muted">what the team recorded, live</span><span id="status" class="muted" aria-live="polite"></span>
    <span class="spacer"></span>
    <label class="muted" for="theme">Theme</label>
    <select id="theme"></select>
  </header>
  <div id="runs"></div>
</main>
<script>
"use strict";
const TOKEN = "__TOKEN__";
const NS = "http://www.w3.org/2000/svg";
const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const state = { runs: [], feeds: {}, filter: {}, polling: {}, theme: "city", loadedAt: Date.now() / 1000, scenes: [] };
const $runs = document.getElementById("runs");
const $status = document.getElementById("status");
const $theme = document.getElementById("theme");
let UID = 0;

// A theme is a look (palette, materials, backdrop) and the words it gives the same things. It never changes what a room, object or hallway means.
const THEMES = {
  city: { name: "1930s city",
    pal: { bg: "#0a0f24", floorA: "#8a6038", floorB: "#7a5230", corr: "#4a3827", grout: "#2a1a0c", wallL: "#b9a47a", wallR: "#d6c397", trim: "#b08d57", wood: "#8a5a2b", metal: "#b08d57", steel: "#5d6b5a",
           screen: "#9fd6b4", accent: "#e3b04b", lamp: "#ffd98a", ink: "#f6ecd2", paper: "#f4ecd2", dark: "#2b2118", dim: "#7a6850", wait: "#f08a24", bad: "#e0605a",
           sky1: "#070b1e", sky2: "#5a3a2a", bldg: "#141223", win: "#f2c15c", rug1: "#7a1f2b", rug2: "#c99a2e", neonA: "#ff6a3d", neonB: "#f2c15c" },
    words: { deck: "Front office", bay: "Workshop", outbox: "Mail slot", approvals: "Signing desk", ledger: "Cash register", table: "Planning table",
      read: "Filing cabinet", write: "Typewriter", shell: "Safe", web: "Radio set", mcp: "Switchboard", other: "Cupboard",
      task: "Orders", results: "Reports", approvalsLane: "Messages", review: "Review", report: "Report", landing: "Delivery" } },
  steam: { name: "Steampunk ship",
    pal: { bg: "#1d2b44", floorA: "#6b5545", floorB: "#5c4a3c", corr: "#3a2f28", grout: "#201710", wallL: "#2b565c", wallR: "#36737d", trim: "#c0773a", wood: "#9c5a2e", metal: "#c0773a", steel: "#7a8a8a",
           screen: "#8fe3d1", accent: "#f0a64a", lamp: "#ffd166", ink: "#e6efe9", paper: "#ead9b0", dark: "#1b2a2e", dim: "#6f8c89", wait: "#ffd166", bad: "#e5645f",
           sky1: "#1b2a52", sky2: "#e8924a", bldg: "#3a2a20", win: "#ffd166", rug1: "#3b2a1e", rug2: "#c0773a", neonA: "#ffd166", neonB: "#f0a64a" },
    words: { deck: "Bridge", bay: "Engine bay", outbox: "Cargo hatch", approvals: "Helm", ledger: "Pressure gauge", table: "Chart table",
      read: "Chart rack", write: "Brass press", shell: "Boiler valve", web: "Signal lamp", mcp: "Speaking tubes", other: "Locker",
      task: "Orders", results: "Dispatches", approvalsLane: "Speaking tube", review: "Review", report: "Report", landing: "Unloading" } },
  cyber: { name: "Cyberpunk city",
    pal: { bg: "#06030f", floorA: "#1a1a3c", floorB: "#13132c", corr: "#0b0b1e", grout: "#05050f", wallL: "#1b1b46", wallR: "#27276a", trim: "#19e3ff", wood: "#2f2f6a", metal: "#4a4aa0", steel: "#3a3a70",
           screen: "#00f5d4", accent: "#00f5d4", lamp: "#ff2bd6", ink: "#d8f6ff", paper: "#9fd8ff", dark: "#0a0a18", dim: "#4a4a8a", wait: "#ffd23f", bad: "#ff3b5c",
           sky1: "#04020c", sky2: "#35104f", bldg: "#0b0a1e", win: "#19e3ff", rug1: "#150a30", rug2: "#ff2bd6", neonA: "#ff2bd6", neonB: "#19e3ff" },
    words: { deck: "Operations floor", bay: "Server bay", outbox: "Dead drop", approvals: "Gatekeeper", ledger: "Credit meter", table: "Ops table",
      read: "Data terminal", write: "Fabricator", shell: "Root console", web: "Uplink", mcp: "Mesh node", other: "Locker",
      task: "Tasking", results: "Returns", approvalsLane: "Auth request", review: "Review", report: "Report", landing: "Drop-off" } },
};
function storedTheme() { try { return localStorage.getItem("station-theme"); } catch (e) { return null; } }
function storeTheme(value) { try { localStorage.setItem("station-theme", value); } catch (e) { /* a private window: the choice just isn't remembered */ } }

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function sv(tag, attrs, text) {
  const node = document.createElementNS(NS, tag);
  for (const key in attrs) node.setAttribute(key, attrs[key]);
  if (text !== undefined) node.textContent = text;
  return node;
}
async function api(path, body) {
  const options = { headers: { "X-Station-Token": TOKEN } };
  if (body !== undefined) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(path + " " + response.status);
  return response.json();
}
function dotClass(doing) {
  if (/approval/.test(doing)) return "wait";
  if (/failed|stopped/.test(doing)) return "bad";
  if (/finished|done|written/.test(doing)) return "fin";
  if (doing === "idle") return "";
  return "on";
}
function clock(t) { return new Date(t * 1000).toLocaleTimeString([], { hour12: false }); }
function number(name) { const m = /(\d+)$/.exec(name); return m ? m[1] : ""; }
// <motion>
function family(tool) {   // the same grouping as station_layout.py
  if (["Read", "Glob", "Grep", "Map", "LSP", "Data", "RetrieveContext"].includes(tool)) return "read";
  if (["Edit", "Write", "NotebookEdit"].includes(tool)) return "write";
  if (["Bash", "PowerShell"].includes(tool)) return "shell";
  if (["WebFetch", "WebSearch"].includes(tool)) return "web";
  if (["MCP", "ListMcpResourcesTool", "ReadMcpResourceTool"].includes(tool) || tool.startsWith("mcp__")) return "mcp";
  return "other";
}

// Where everyone is, as a pure function of the recorded events and the clock. Nothing here remembers anything between frames, so
// the scene can be rebuilt at any moment without a jump. Positions are in tile units.
const SPEED = REDUCED ? 1e6 : 5.5;   // tiles per second; reduced motion: no walking, crew just appear at the spot
const DWELL_USE = 2.4, DWELL_CHECK = 2.0;
function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]); }
function pathLength(pts) { let s = 0; for (let i = 1; i < pts.length; i++) s += dist(pts[i - 1], pts[i]); return s; }
function along(pts, d) {   // the point `d` tiles along a polyline, and the direction of the leg it is on
  let rest = Math.max(0, d);
  for (let i = 1; i < pts.length; i++) {
    const leg = dist(pts[i - 1], pts[i]);
    if (rest <= leg || i === pts.length - 1) {
      const k = leg ? Math.min(1, rest / leg) : 1;
      return { pos: [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k], dir: [pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]] };
    }
    rest -= leg;
  }
  return { pos: pts[pts.length - 1], dir: [0, 0] };
}
// A trip: walk `go`, stay `dwell` seconds, walk `back`. Returns where the walker is at time t, or null before it starts.
function tripState(trip, t) {
  const u = t - trip.t0;
  if (u < 0) return null;
  const g = pathLength(trip.go) / SPEED, b = pathLength(trip.back) / SPEED;
  if (u < g) { const a = along(trip.go, u * SPEED); return { pos: a.pos, dir: a.dir, pose: "walk", carry: trip.carryGo, bubble: null }; }
  if (u < g + trip.dwell) { const e = trip.go[trip.go.length - 1]; return { pos: e, dir: trip.face || [0, 1], pose: trip.pose, carry: trip.carryDwell, bubble: trip.bubble }; }
  if (u < g + trip.dwell + b) { const a = along(trip.back, (u - g - trip.dwell) * SPEED); return { pos: a.pos, dir: a.dir, pose: "walk", carry: trip.carryBack, bubble: null }; }
  return { done: true, pos: trip.back[trip.back.length - 1], dir: [0, 0], pose: "idle", carry: null, bubble: null };
}
function tripEnd(trip) { return trip.t0 + (pathLength(trip.go) + pathLength(trip.back)) / SPEED + trip.dwell; }
// The walkers' schedules. Workers: one trip per tool they used, to the furniture for that tool, starting from wherever they are.
function workerTrips(events, name, scene, liveFrom) {
  const trips = [], home = scene.homes[name];
  for (const e of events) {
    if (e.who !== name || e.kind !== "tool_use" || e.t < liveFrom) continue;
    const stand = scene.stands[name + ":" + family(e.tool)];
    if (!stand) continue;
    let from = home;
    if (trips.length) { const s = tripState(trips[trips.length - 1], e.t); from = s ? s.pos : home; }
    trips.push({ t0: e.t, go: [from, stand], back: [stand, home], dwell: DWELL_USE, pose: "work", bubble: "dots", face: [0, -1], tool: e.tool });
  }
  return trips;
}
// Clyde and Bonnie: one trip per recorded `check` of theirs (plus Clyde carrying the landed work to the outbox), taken in order.
function orchestratorTrips(events, name, scene, liveFrom) {
  const trips = [], home = scene.homes[name], REASONS = {
    brief:    { carryGo: "paper", carryDwell: "paper", carryBack: null, bubble: "paper" },
    approval: { carryGo: null, carryDwell: "mail", carryBack: "mail", bubble: "mail" },
    result:   { carryGo: null, carryDwell: "glass", carryBack: "folder", bubble: "glass" },
    landing:  { carryGo: "box", carryDwell: "box", carryBack: null, bubble: "ok" },
  };
  const wanted = [];
  for (const e of events) {
    if (e.t < liveFrom) continue;
    if (e.kind === "check" && e.who === name) wanted.push({ t: e.t, target: e.target, reason: e.reason });
    if (e.kind === "landed" && e.who === "user" && name === "clyde") wanted.push({ t: e.t, target: "outbox", reason: "landing" });
  }
  let free = 0;
  for (const w of wanted) {
    const stand = scene.checkStands[w.target];
    if (!stand) continue;
    const t0 = Math.max(w.t, free), r = REASONS[w.reason] || REASONS.result;
    const trip = { t0, go: scene.route("deck", home, w.target === "outbox" ? "outbox" : w.target, stand), back: null, dwell: DWELL_CHECK, pose: "check", face: [0, 1], ...r };
    trip.back = trip.go.slice().reverse();
    trips.push(trip);
    free = tripEnd(trip);
  }
  return trips;
}
function walkerState(trips, home, t) {
  let current = null;
  for (const trip of trips) if (trip.t0 <= t) current = trip;
  const s = current && tripState(current, t);
  return s && !s.done ? s : { pos: home, dir: [0, 0], pose: "idle", carry: null, bubble: null };
}
// </motion>

// <geometry>
// ---- geometry: tile space and the isometric projection ---------------------------------------------------------------
const TW = 64, TH = 32, WALL = 60, SLAB = 9;
function iso(x, y) { return [(x - y) * TW / 2, (x + y) * TH / 2]; }
function P(x, y, z) { const p = iso(x, y); return [p[0], p[1] - (z || 0)]; }
function pts(list) { return list.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" "); }
function shade(hex, pct) {
  const n = parseInt(hex.slice(1), 16), f = pct / 100;
  const c = (v) => Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f)));
  return "#" + [c(n >> 16), c((n >> 8) & 255), c(n & 255)].map((v) => v.toString(16).padStart(2, "0")).join("");
}
function hash(a, b) { let h = Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function poly(layer, points, fill, extra) { const n = sv("polygon", { points: pts(points), fill, ...(extra || {}) }); layer.append(n); return n; }
const BAY_SLOTS = {   // furniture box [x, y, w, d] and where a worker stands to use it, in a bay's own tiles. The door aisle (x 4 to 7, from the back wall down to the worker) stays clear.
  read: { box: [0.8, 0.8, 3, 1], stand: [2.3, 2.8] }, write: { box: [7.4, 0.8, 3, 1.5], stand: [8.9, 3.4] }, shell: { box: [9.6, 4.4, 1.2, 1.8], stand: [8.3, 5.4] },
  web: { box: [0.8, 4.4, 1, 2.3], stand: [3.0, 5.6] }, mcp: { box: [0.8, 7.6, 1, 2.3], stand: [3.0, 8.8] }, other: { box: [9.2, 8.0, 1.5, 1.9], stand: [7.9, 9.0] },
};
function plan(layout) {
  const bays = layout.rooms.filter((r) => r.kind === "bay"), n = Math.max(1, bays.length);
  const BW = 11, BD = 11, GAP = 2, DW = 26, DD = 12, SPINE = 17, BAYY = 22;
  const totalW = n * BW + (n - 1) * GAP, deckX = (totalW - DW) / 2;
  const rooms = { deck: { id: "deck", kind: "deck", x: deckX, y: 0, w: DW, d: DD } };
  bays.forEach((b, i) => { rooms[b.id] = { id: b.id, kind: "bay", x: i * (BW + GAP), y: BAYY, w: BW, d: BD, src: b }; });
  rooms.outbox = { id: "outbox", kind: "outbox", x: deckX + DW + 4, y: 3, w: 8, d: 7 };
  const deck = rooms.deck, deckCx = deck.x + DW / 2, bayRooms = Object.values(rooms).filter((r) => r.kind === "bay");
  const cxs = bayRooms.map((r) => r.x + BW / 2), xmin = Math.min(deckCx, ...cxs) - 1, xmax = Math.max(deckCx, ...cxs) + 1;
  // Corridors: a trunk from the deck's door down to a spine, a branch from the spine to each bay's door, and a short one east to the outbox.
  const corridors = [{ x: deckCx - 1, y: DD, w: 2, d: SPINE - DD }, { x: xmin, y: SPINE, w: xmax - xmin, d: 2 }, { x: deck.x + DW, y: 5, w: 4, d: 2 }];
  for (const r of bayRooms) corridors.push({ x: r.x + BW / 2 - 1, y: SPINE + 2, w: 2, d: BAYY - SPINE - 2 });
  // The long sides of the corridors that have a wall or a rail (lines in tile space), left open where another corridor joins.
  const edges = [[[deckCx - 1, DD], [deckCx - 1, SPINE]], [[deckCx + 1, DD], [deckCx + 1, SPINE]], [[deck.x + DW, 5], [deck.x + DW + 4, 5]], [[deck.x + DW, 7], [deck.x + DW + 4, 7]]];
  const sides = (y, opens) => { let x = xmin; for (const [a, b] of opens.concat([[xmax, xmax]])) { if (a > x) edges.push([[x, y], [a, y]]); x = b; } };
  sides(SPINE, [[deckCx - 1, deckCx + 1]]);
  sides(SPINE + 2, bayRooms.map((r) => [r.x + BW / 2 - 1, r.x + BW / 2 + 1]).sort((a, b) => a[0] - b[0]));
  for (const r of bayRooms) { const cx = r.x + BW / 2; edges.push([[cx - 1, SPINE + 2], [cx - 1, BAYY]], [[cx + 1, SPINE + 2], [cx + 1, BAYY]]); }
  const at = (room, p) => [room.x + p[0], room.y + p[1]];
  const homes = { clyde: at(deck, [11.2, 8.9]), bonnie: at(deck, [14.8, 8.9]), master: at(deck, [3.5, 4.6]), advisor: at(deck, [22.5, 4.6]) };
  const stands = {}, checkStands = { outbox: at(rooms.outbox, [3.5, 3.8]) };
  for (const r of bayRooms) {
    homes[r.id] = at(r, [5.5, 6.4]);
    checkStands[r.id] = at(r, [7.4, 6.2]);
    for (const f in BAY_SLOTS) stands[r.id + ":" + f] = at(r, BAY_SLOTS[f].stand);
  }
  const hub = [deckCx, DD - 0.5], spineAt = (x) => [x, SPINE + 1];
  const toDeck = (room, pos) => {   // from a spot in a room to the deck's door
    if (room === "deck") return [pos];
    if (room === "outbox") return [pos, [rooms.outbox.x + 1.5, 6], [deck.x + DW - 1, 6]];
    const cx = rooms[room].x + BW / 2;
    return [pos, [cx, BAYY + 1.5], spineAt(cx), spineAt(deckCx), hub];
  };
  const route = (fromRoom, from, toRoom, to) => {
    if (fromRoom === toRoom) return [from, to];
    const out = toDeck(fromRoom, from), back = toDeck(toRoom, to).reverse();
    return out.concat(back);
  };
  const furniture = [], lanes = {}, props = [];
  for (const r of bayRooms) {
    const cx = r.x + BW / 2;
    for (const o of r.src.objects) { const s = BAY_SLOTS[o.family]; if (s) furniture.push({ room: r, family: o.family, obj: o, box: [r.x + s.box[0], r.y + s.box[1], s.box[2], s.box[3]] }); }
    for (const [kind, off] of [["task", -0.5], ["results", 0], ["approvals", 0.5]])
      lanes[kind + ":" + r.id] = [[deckCx + off, DD], [deckCx + off, SPINE + 1 + off], [cx + off, SPINE + 1 + off], [cx + off, BAYY + 1.2]];
    props.push(["tank", r.x + 6.8, r.y + 10.2], ["crates", r.x + 4.6, r.y + 10.2], ["lamp", r.x + 10.4, r.y + 3.3], ["plant", r.x + 0.9, r.y + 10.7]);
  }
  const dk = layout.rooms.find((r) => r.id === "deck");
  const deckBoxes = { approvals: [3, 8, 3, 1.6], ledger: [19, 9.2, 3, 1.4] };
  for (const o of dk.objects) furniture.push({ room: deck, family: o.family, obj: o, box: [deck.x + deckBoxes[o.family][0], deck.y + deckBoxes[o.family][1], deckBoxes[o.family][2], deckBoxes[o.family][3]] });
  furniture.push({ room: deck, family: "desk", obj: null, lane: "report", box: [deck.x + 2, deck.y + 2, 3, 2] }, { room: deck, family: "desk", obj: null, lane: "review", box: [deck.x + 21, deck.y + 2, 3, 2] },
                 { room: deck, family: "table", obj: null, box: [deck.x + 11, deck.y + 5, 4.2, 2] });
  props.push(["plant", deck.x + 0.9, deck.y + 10.6], ["plant", deck.x + 24.8, deck.y + 10.6], ["lamp", deck.x + 9, deck.y + 1.3], ["lamp", deck.x + 17.4, deck.y + 1.3],
             ["bookcase", deck.x + 0.3, deck.y + 5.4], ["tank", deck.x + 24.6, deck.y + 8.8], ["coat", deck.x + 7.6, deck.y + 10.8]);
  const ob = layout.rooms.find((r) => r.kind === "outbox");
  furniture.push({ room: rooms.outbox, family: "crate", obj: ob, box: [rooms.outbox.x + 4.8, rooms.outbox.y + 1, 2.2, 1.8] });
  props.push(["bookcase", rooms.outbox.x + 0.3, rooms.outbox.y + 0.2, 1.6], ["bookcase", rooms.outbox.x + 0.3, rooms.outbox.y + 4.8, 2], ["tank", rooms.outbox.x + 6.6, rooms.outbox.y + 5.6], ["lamp", rooms.outbox.x + 7.2, rooms.outbox.y + 4.2]);
  lanes.landing = [[deck.x + DW - 1, 6], [rooms.outbox.x + 1.5, 6]];
  return { rooms, bayRooms, corridors, edges, homes, stands, checkStands, route, furniture, props, lanes, deckCx, DW, DD, BW, BD, SPINE, BAYY };
}
function bounds(p) {
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  const take = (x, y, z) => { const q = P(x, y, z); x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); };
  for (const r of Object.values(p.rooms)) { take(r.x, r.y, WALL + 40); take(r.x + r.w, r.y, WALL); take(r.x, r.y + r.d, WALL); take(r.x + r.w, r.y + r.d, -SLAB); }
  return [x0 - 50, y0 - 40, x1 + 50, y1 + 40];
}
// </geometry>

// ---- the world outside: a backdrop per theme (scenery only: it says nothing about the run) --------------------------------
function gradient(defs, id, stops, attrs) {
  const g = sv(attrs && attrs.r ? "radialGradient" : "linearGradient", attrs || { x1: 0, y1: 0, x2: 0, y2: 1 });
  g.setAttribute("id", id);
  for (const [off, color, op] of stops) g.append(sv("stop", { offset: off, "stop-color": color, "stop-opacity": op === undefined ? 1 : op }));
  defs.append(g);
  return "url(#" + id + ")";
}
function skyline(layer, B, base, hmin, hmax, color, seed, pal, windows, neon) {
  const [x0, , x1] = B;
  let x = x0 - 20, i = 0;
  while (x < x1 + 20) {
    const w = 38 + hash(seed, i) * 60, h = hmin + hash(seed + 7, i) * (hmax - hmin);
    layer.append(sv("rect", { x: x, y: base - h, width: w, height: h + 140, fill: color }));
    if (hash(seed + 3, i) > 0.55) { layer.append(sv("rect", { x: x + w * 0.2, y: base - h - 22, width: w * 0.6, height: 22, fill: color }), sv("rect", { x: x + w * 0.42, y: base - h - 52, width: 3, height: 30, fill: color })); }
    if (hash(seed + 5, i) > 0.7) layer.append(sv("circle", { cx: x + w * 0.43 + 1.5, cy: base - h - 52, r: 2.5, fill: "#ff4d4d", class: "blink amb" }));
    if (windows) for (let wy = base - h + 10; wy < base - 6; wy += 13) for (let wx = x + 6; wx < x + w - 8; wx += 11)
      if (hash(Math.floor(wx), Math.floor(wy)) > 0.62) layer.append(sv("rect", { x: wx, y: wy, width: 5, height: 7, fill: neon ? (hash(wx, wy + 1) > 0.5 ? pal.neonA : pal.neonB) : pal.win, opacity: 0.55 + hash(wx + 1, wy) * 0.4 }));
    x += w + 2 + hash(seed + 9, i) * 6;
    i++;
  }
}
function backdrop(svg, defs, B, pal, theme, uid) {
  const [x0, y0, x1, y1] = B, w = x1 - x0, h = y1 - y0, layer = sv("g", { "aria-hidden": "true" });
  layer.append(sv("rect", { x: x0, y: y0, width: w, height: h, fill: gradient(defs, "sky" + uid, [[0, pal.sky1], [0.7, pal.sky2], [1, shade(pal.sky2, -30)]]) }));
  const base = y0 + h * 0.66;
  if (theme === "city") {
    for (let i = 0; i < 70; i++) layer.append(sv("circle", { cx: x0 + hash(1, i) * w, cy: y0 + hash(2, i) * h * 0.5, r: 0.6 + hash(3, i) * 1.4, fill: "#fff", opacity: 0.8, class: "twinkle amb", style: "animation-delay:" + (hash(4, i) * 3).toFixed(1) + "s" }));
    layer.append(sv("circle", { cx: x0 + w * 0.82, cy: y0 + h * 0.16, r: 58, fill: gradient(defs, "moonhalo" + uid, [[0, "#fff6d8", 0.5], [1, "#fff6d8", 0]], { r: "50%" }) }), sv("circle", { cx: x0 + w * 0.82, cy: y0 + h * 0.16, r: 26, fill: "#fff1c4" }), sv("circle", { cx: x0 + w * 0.82 - 8, cy: y0 + h * 0.16 - 5, r: 5, fill: "#e8dba8", opacity: 0.8 }));
    for (const [bx, by] of [[x0 + w * 0.12, base], [x0 + w * 0.9, base]]) {
      const beam = sv("g", { class: "sweep amb", style: "transform-origin:" + bx + "px " + by + "px" });
      beam.append(sv("polygon", { points: pts([[bx - 8, by], [bx + 8, by], [bx + 70, by - h * 0.7], [bx - 70, by - h * 0.7]]), fill: gradient(defs, "beam" + uid + bx, [[0, "#fff6d8", 0.4], [1, "#fff6d8", 0]]) }));
      layer.append(beam);
    }
    skyline(layer, B, base - 10, 60, 170, shade(pal.bldg, 18), 11, pal, false, false);
    skyline(layer, B, base + 40, 70, 230, pal.bldg, 23, pal, true, false);
  } else if (theme === "steam") {
    layer.append(sv("circle", { cx: x0 + w * 0.2, cy: base - 30, r: 150, fill: gradient(defs, "sunhalo" + uid, [[0, "#ffd9a0", 0.9], [0.4, "#ff9a4a", 0.45], [1, "#ff9a4a", 0]], { r: "50%" }) }), sv("circle", { cx: x0 + w * 0.2, cy: base - 30, r: 46, fill: "#ffe6b8" }));
    for (let i = 0; i < 6; i++) {
      const cx = x0 + hash(5, i) * w, cy = y0 + h * (0.12 + hash(6, i) * 0.38), cloud = sv("g", { class: (i % 2 ? "drift" : "drift2") + " amb", style: "animation-delay:-" + (hash(7, i) * 60).toFixed(0) + "s" });
      for (let k = 0; k < 5; k++) cloud.append(sv("ellipse", { cx: cx + (k - 2) * 34, cy: cy + (k % 2) * 8, rx: 46 + hash(8, i + k) * 20, ry: 16 + hash(9, i + k) * 8, fill: "#ffc58a", opacity: 0.32 }));
      layer.append(cloud);
    }
    for (let i = 0; i < 2; i++) {
      const ax = x0 + w * (0.3 + i * 0.4), ay = y0 + h * (0.22 + i * 0.12), ship = sv("g", { class: (i ? "drift2" : "drift") + " amb", opacity: 0.85 });
      ship.append(sv("ellipse", { cx: ax, cy: ay, rx: 70, ry: 20, fill: "#3a2a20" }), sv("ellipse", { cx: ax, cy: ay - 5, rx: 62, ry: 9, fill: "#5a3d28", opacity: 0.6 }), sv("rect", { x: ax - 20, y: ay + 18, width: 40, height: 12, rx: 3, fill: "#2a1d15" }),
                  sv("polygon", { points: pts([[ax + 62, ay], [ax + 92, ay - 18], [ax + 92, ay + 18]]), fill: "#3a2a20" }), sv("circle", { cx: ax - 70, cy: ay, r: 5, fill: "#c0773a", class: "spin amb" }));
      layer.append(ship);
    }
    for (const [gx, gy, gr, cls] of [[x0 + 20, y0 + h * 0.42, 170, "spin"], [x1 - 10, y0 + h * 0.62, 210, "spinr"], [x0 + w * 0.5, y1 + 40, 190, "spin"]]) {
      const gear = sv("g", { class: cls + " amb", opacity: 0.55 });
      const teeth = 14, pointsList = [];
      for (let t = 0; t < teeth * 2; t++) { const a = t / (teeth * 2) * Math.PI * 2, r = gr * (t % 2 ? 1 : 0.86); pointsList.push([gx + Math.cos(a) * r, gy + Math.sin(a) * r]); }
      gear.append(sv("polygon", { points: pts(pointsList), fill: "#2a1d15", stroke: "#c0773a", "stroke-width": 3 }), sv("circle", { cx: gx, cy: gy, r: gr * 0.55, fill: "none", stroke: "#c0773a", "stroke-width": 3 }), sv("circle", { cx: gx, cy: gy, r: gr * 0.14, fill: "#c0773a" }));
      for (let s = 0; s < 6; s++) { const a = s / 6 * Math.PI * 2; gear.append(sv("line", { x1: gx, y1: gy, x2: gx + Math.cos(a) * gr * 0.55, y2: gy + Math.sin(a) * gr * 0.55, stroke: "#c0773a", "stroke-width": 4 })); }
      layer.append(gear);
    }
    skyline(layer, B, base + 30, 30, 90, shade(pal.bldg, -10), 31, pal, true, false);
  } else {
    layer.append(sv("circle", { cx: x0 + w * 0.5, cy: base - 70, r: 170, fill: gradient(defs, "neonsun" + uid, [[0, "#ff2bd6"], [1, "#ff9a3d"]], { x1: 0, y1: 0, x2: 0, y2: 1 }) }));
    for (let s = 0; s < 9; s++) layer.append(sv("rect", { x: x0 + w * 0.5 - 180, y: base - 70 + s * 17 - 20, width: 360, height: 2 + s * 1.5, fill: pal.sky2 }));
    for (let g = 0; g < 14; g++) layer.append(sv("line", { x1: x0 + w * 0.5 + (g - 7) * 120, y1: base + 60, x2: x0 + w * 0.5 + (g - 7) * 460, y2: y1, stroke: pal.neonA, "stroke-width": 1, opacity: 0.18 }));
    skyline(layer, B, base - 8, 70, 200, shade(pal.bldg, 14), 41, pal, true, true);
    skyline(layer, B, base + 50, 80, 260, pal.bldg, 53, pal, true, true);
    for (const [bx, by, txt, col] of [[x0 + w * 0.1, y0 + h * 0.25, "CLYDE", pal.neonA], [x0 + w * 0.88, y0 + h * 0.36, "24H", pal.neonB], [x0 + w * 0.7, y0 + h * 0.14, "▲ NET", pal.neonA]]) {
      layer.append(sv("rect", { x: bx - 46, y: by - 18, width: 92, height: 34, rx: 4, fill: "#0b0620", stroke: col, "stroke-width": 2, class: "flick amb" }), sv("text", { x: bx, y: by + 5, class: "sign flick2 amb", fill: col, stroke: "none", style: "font-size:16px" }, txt));
    }
    for (let i = 0; i < 90; i++) layer.append(sv("line", { x1: 0, y1: 0, x2: -4, y2: 24, transform: "translate(" + (x0 + hash(61, i) * w).toFixed(0) + " " + (y0 + hash(62, i) * h).toFixed(0) + ")", stroke: "#9fd8ff", "stroke-width": 1, opacity: 0.35, class: "rain amb", style: "animation-delay:-" + (hash(63, i) * 1.1).toFixed(2) + "s" }));
  }
  layer.append(sv("rect", { x: x0, y: y1 - 160, width: w, height: 160, fill: gradient(defs, "haze" + uid, [[0, pal.sky2, 0], [1, pal.sky2, 0.55]]) }));   // haze under the station
  svg.append(layer);
}

// ---- rooms: floors, walls and what hangs on them -----------------------------------------------------------------------
function tileLines(r) {   // the grout between tiles, as one path
  let d = "";
  for (let i = 0; i <= r.w; i++) { const a = iso(r.x + i, r.y), b = iso(r.x + i, r.y + r.d); d += "M" + a[0].toFixed(1) + " " + a[1].toFixed(1) + "L" + b[0].toFixed(1) + " " + b[1].toFixed(1); }
  for (let j = 0; j <= r.d; j++) { const a = iso(r.x, r.y + j), b = iso(r.x + r.w, r.y + j); d += "M" + a[0].toFixed(1) + " " + a[1].toFixed(1) + "L" + b[0].toFixed(1) + " " + b[1].toFixed(1); }
  return d;
}
function slabFaces(layer, r, pal) {   // a floor has thickness: the faces toward the viewer
  layer.append(sv("polygon", { points: pts([P(r.x, r.y + r.d, 0), P(r.x + r.w, r.y + r.d, 0), P(r.x + r.w, r.y + r.d, -SLAB), P(r.x, r.y + r.d, -SLAB)]), fill: shade(pal.corr, -25) }),
               sv("polygon", { points: pts([P(r.x + r.w, r.y, 0), P(r.x + r.w, r.y + r.d, 0), P(r.x + r.w, r.y + r.d, -SLAB), P(r.x + r.w, r.y, -SLAB)]), fill: shade(pal.corr, -45) }));
}
function drawFloors(layer, defs, p, pal, theme, uid) {
  const rooms = Object.values(p.rooms);
  for (const r of rooms) slabFaces(layer, r, pal);
  for (const c of p.corridors) slabFaces(layer, c, pal);   // all the thickness first, so a floor always covers the faces inside a junction
  const corrA = shade(pal.floorA, theme === "cyber" ? 40 : -4), corrB = shade(pal.floorB, theme === "cyber" ? 28 : -14);
  p.corridors.forEach((c, ci) => {   // walkways: a grating floor, never the colour of the sky behind it
    const W = Math.max(1, Math.round(c.w)), D = Math.max(1, Math.round(c.d)), buckets = {};
    for (let i = 0; i < W; i++) for (let j = 0; j < D; j++) {
      const q = [iso(c.x + i, c.y + j), iso(c.x + i + 1, c.y + j), iso(c.x + i + 1, c.y + j + 1), iso(c.x + i, c.y + j + 1)], k = (i + j) % 2;
      buckets[k] = (buckets[k] || "") + "M" + q.map((v) => v[0].toFixed(1) + " " + v[1].toFixed(1)).join("L") + "Z";
    }
    for (const k in buckets) layer.append(sv("path", { d: buckets[k], fill: k === "0" ? corrA : corrB }));
    layer.append(sv("path", { d: tileLines({ x: c.x, y: c.y, w: W, d: D }), stroke: pal.grout, "stroke-width": 1, opacity: 0.55, fill: "none" }));
  });
  for (const [a, b] of p.edges) {   // a rail along each long side, with a light set into it every so often
    const A = P(a[0], a[1], 0), B = P(b[0], b[1], 0), A2 = P(a[0], a[1], 9), B2 = P(b[0], b[1], 9);
    layer.append(sv("polygon", { points: pts([A, B, B2, A2]), fill: shade(pal.trim, -30), opacity: 0.9 }), sv("line", { x1: A2[0], y1: A2[1], x2: B2[0], y2: B2[1], stroke: pal.trim, "stroke-width": 2 }));
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]), steps = Math.max(1, Math.floor(len / 1.5));
    for (let t = 0; t <= steps; t++) {
      const k = steps ? t / steps : 0, q = P(a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, 11);
      layer.append(sv("circle", { cx: q[0], cy: q[1], r: 2.4, fill: theme === "cyber" ? pal.neonB : pal.lamp, class: "blink" + (t % 3 ? String(t % 3 + 1) : "") + " amb" }));
    }
  }
  rooms.forEach((r, ri) => {
    const buckets = {};
    for (let i = 0; i < Math.round(r.w); i++) for (let j = 0; j < Math.round(r.d); j++) {
      const q = [iso(r.x + i, r.y + j), iso(r.x + i + 1, r.y + j), iso(r.x + i + 1, r.y + j + 1), iso(r.x + i, r.y + j + 1)];
      const parity = (i + j) % 2, jit = Math.floor(hash(ri * 97 + i, j) * 4), key = parity * 4 + jit;
      buckets[key] = (buckets[key] || "") + "M" + q.map((v) => v[0].toFixed(1) + " " + v[1].toFixed(1)).join("L") + "Z";
    }
    for (const key in buckets) layer.append(sv("path", { d: buckets[key], fill: shade(+key >= 4 ? pal.floorB : pal.floorA, ((+key % 4) - 1.5) * 4) }));
    layer.append(sv("path", { d: tileLines(r), stroke: pal.grout, "stroke-width": 1, opacity: 0.45, fill: "none" }));
    // scuffs and stains: a few darker patches, always in the same places
    for (let s = 0; s < r.w * r.d / 18; s++) { const c = P(r.x + hash(ri, s) * r.w, r.y + hash(ri + 5, s) * r.d, 0); layer.append(sv("ellipse", { cx: c[0], cy: c[1], rx: 8 + hash(ri, s + 9) * 14, ry: 3 + hash(ri, s + 3) * 5, fill: "#000", opacity: 0.1 })); }
  });
  const deck = p.rooms.deck;   // the deck's rug under the planning table
  const rug = [deck.x + 9, deck.y + 3.6, 8.4, 6.2];
  poly(layer, [P(rug[0], rug[1], 0), P(rug[0] + rug[2], rug[1], 0), P(rug[0] + rug[2], rug[1] + rug[3], 0), P(rug[0], rug[1] + rug[3], 0)], pal.rug1);
  poly(layer, [P(rug[0] + 0.35, rug[1] + 0.35, 0), P(rug[0] + rug[2] - 0.35, rug[1] + 0.35, 0), P(rug[0] + rug[2] - 0.35, rug[1] + rug[3] - 0.35, 0), P(rug[0] + 0.35, rug[1] + rug[3] - 0.35, 0)], "none", { stroke: pal.rug2, "stroke-width": 3 });
  const mid = [rug[0] + rug[2] / 2, rug[1] + rug[3] / 2];
  poly(layer, [P(mid[0], mid[1] - 2.2, 0), P(mid[0] + 3.4, mid[1], 0), P(mid[0], mid[1] + 2.2, 0), P(mid[0] - 3.4, mid[1], 0)], "none", { stroke: pal.rug2, "stroke-width": 2, opacity: 0.8 });
  for (const r of rooms) {   // hazard stripes where a corridor comes in
    const spots = r.kind === "bay" ? [[r.x + p.BW / 2 - 1, r.y + 0.05, 2, 0.5]] : r.kind === "outbox" ? [[r.x + 0.05, r.y + 2, 0.5, 2]] : [];
    for (const s of spots) for (let k = 0; k < 8; k++) {
      const a = r.kind === "outbox" ? [s[0], s[1] + k * 0.25, 0.5, 0.25] : [s[0] + k * 0.25, s[1], 0.25, 0.5];
      if (k % 2) poly(layer, [P(a[0], a[1], 0), P(a[0] + a[2], a[1], 0), P(a[0] + a[2], a[1] + a[3], 0), P(a[0], a[1] + a[3], 0)], "#e8c020", { opacity: 0.85 });
    }
  }
}
function W(side, r, u, z) { return side === "ne" ? P(u, r.y, z) : P(r.x, u, z); }   // a spot on a room's back wall: along it in tiles, up it in px
function wq(layer, side, r, u0, z0, u1, z1, fill, extra) { return poly(layer, [W(side, r, u0, z0), W(side, r, u1, z0), W(side, r, u1, z1), W(side, r, u0, z1)], fill, extra); }
function wc(layer, side, r, u, z, rad, fill, extra) {   // a circle on the wall plane
  const list = [];
  for (let a = 0; a < 16; a++) { const t = a / 16 * Math.PI * 2; list.push(W(side, r, u + Math.cos(t) * rad / 35.8, z + Math.sin(t) * rad)); }
  return poly(layer, list, fill, extra);
}
const PX = 1 / 35.8;   // one pixel along a wall, in tiles
function wallDecor(layer, defs, side, r, u, pal, theme, k, uid, deckTitle) {
  const d = (n) => n * PX;
  if (theme === "city") {
    if (k === 0) {   // an arched window onto the night, with curtains
      wq(layer, side, r, u - d(13), 17, u + d(13), 42, "#0f1a36", { stroke: pal.trim, "stroke-width": 2 });
      const arch = []; for (let a = 0; a <= 8; a++) { const t = Math.PI * a / 8; arch.push(W(side, r, u + Math.cos(t) * d(13), 42 + Math.sin(t) * 9)); }
      poly(layer, arch, "#0f1a36", { stroke: pal.trim, "stroke-width": 2 });
      for (let i = 0; i < 6; i++) { const c = W(side, r, u - d(10) + hash(uid, i + Math.floor(u)) * d(20), 20 + hash(i, uid) * 20); layer.append(sv("circle", { cx: c[0], cy: c[1], r: 1.4, fill: pal.win, opacity: 0.9 })); }
      wq(layer, side, r, u - d(0.8), 17, u + d(0.8), 50, pal.trim); wq(layer, side, r, u - d(13), 30, u + d(13), 31.6, pal.trim);
      wq(layer, side, r, u - d(16), 15, u + d(16), 17.5, shade(pal.trim, 12));
      wq(layer, side, r, u - d(17), 16, u - d(11), 52, "#7a1f2b"); wq(layer, side, r, u + d(11), 16, u + d(17), 52, "#7a1f2b");
      wq(layer, side, r, u - d(15), 16, u - d(13.5), 52, "#9a2f3b"); wq(layer, side, r, u + d(13.5), 16, u + d(15), 52, "#9a2f3b");
    } else if (k === 1) {   // a framed picture
      wq(layer, side, r, u - d(11), 26, u + d(11), 49, pal.trim);
      wq(layer, side, r, u - d(9), 28, u + d(9), 47, hash(uid, Math.floor(u)) > 0.5 ? "#3a5a6a" : "#6a4a3a");
      wq(layer, side, r, u - d(5), 30, u + d(5), 38, shade(pal.paper, -20), { opacity: 0.8 });
      wc(layer, side, r, u, 41, 3.5, pal.paper, { opacity: 0.8 });
    } else {   // a wall lamp with its pool of light
      wq(layer, side, r, u - d(2), 30, u + d(2), 40, pal.metal);
      wc(layer, side, r, u, 44, 6, pal.lamp, { class: "flick amb" });
      wc(layer, side, r, u, 44, 20, gradient(defs, "glow" + uid + Math.floor(u * 3) + side, [[0, pal.lamp, 0.45], [1, pal.lamp, 0]], { r: "50%" }), { class: "flick2 amb" });
    }
  } else if (theme === "steam") {
    if (k === 0) {   // a brass-ringed porthole
      wc(layer, side, r, u, 36, 15, pal.metal); wc(layer, side, r, u, 36, 11.5, shade(pal.metal, -35));
      wc(layer, side, r, u, 36, 10, gradient(defs, "port" + uid + Math.floor(u * 3) + side, [[0, "#9ff0e6"], [1, "#2a7a88"]], { r: "60%" }));
      for (let b = 0; b < 8; b++) { const t = b / 8 * Math.PI * 2, c = W(side, r, u + Math.cos(t) * 13 * PX, 36 + Math.sin(t) * 13); layer.append(sv("circle", { cx: c[0], cy: c[1], r: 1.3, fill: shade(pal.metal, 30) })); }
      wq(layer, side, r, u - d(5), 36, u + d(1), 40, "#fff", { class: "glint amb", opacity: 0.0 });
    } else if (k === 1) {   // a pipe run with a valve wheel and a puff of steam
      wq(layer, side, r, u - d(26), 30, u + d(26), 38, shade(pal.metal, -20)); wq(layer, side, r, u - d(26), 34, u + d(26), 38, shade(pal.metal, 20), { opacity: 0.7 });
      for (const o of [-24, 24]) wq(layer, side, r, u + d(o) - d(3), 27, u + d(o) + d(3), 41, pal.metal);
      wc(layer, side, r, u, 46, 7, "none", { stroke: pal.metal, "stroke-width": 2.5 }); wq(layer, side, r, u - d(0.8), 39, u + d(0.8), 53, pal.metal); wq(layer, side, r, u - d(7), 45, u + d(7), 47, pal.metal);
      const c = W(side, r, u + d(16), 40); layer.append(sv("circle", { cx: c[0], cy: c[1], r: 5, fill: "#fff", opacity: 0.0, class: "puff amb" }), sv("circle", { cx: c[0] + 2, cy: c[1], r: 4, fill: "#fff", class: "puff amb", style: "animation-delay:1.2s", opacity: 0.6 }));
    } else {   // a pressure gauge on a riveted plate
      wq(layer, side, r, u - d(13), 22, u + d(13), 48, shade(pal.metal, -30), { stroke: pal.metal, "stroke-width": 1.5 });
      wc(layer, side, r, u, 36, 10, pal.paper); wc(layer, side, r, u, 36, 10, "none", { stroke: pal.metal, "stroke-width": 2.5 });
      const ang = (hash(uid, Math.floor(u)) * 1.6 - 0.8), n = W(side, r, u + Math.sin(ang) * 8 * PX, 36 + Math.cos(ang) * 8), c = W(side, r, u, 36);
      layer.append(sv("line", { x1: c[0], y1: c[1], x2: n[0], y2: n[1], stroke: "#b32", "stroke-width": 1.6 }));
      for (const [a, b] of [[-11, 24], [11, 24], [-11, 46], [11, 46]]) { const q = W(side, r, u + d(a), b); layer.append(sv("circle", { cx: q[0], cy: q[1], r: 1.3, fill: shade(pal.metal, 30) })); }
    }
  } else {
    if (k === 0) {   // a neon tube
      const col = hash(uid, Math.floor(u * 2)) > 0.5 ? pal.neonA : pal.neonB;
      wq(layer, side, r, u - d(5), 8, u + d(5), 54, col, { opacity: 0.18, class: "flick amb" }); wq(layer, side, r, u - d(1.6), 10, u + d(1.6), 52, col, { class: "flick amb" }); wq(layer, side, r, u - d(0.6), 10, u + d(0.6), 52, "#fff", { opacity: 0.8 });
    } else if (k === 1) {   // a wall screen with scrolling bars
      wq(layer, side, r, u - d(15), 22, u + d(15), 46, "#05050f", { stroke: pal.trim, "stroke-width": 2 });
      for (let b = 0; b < 4; b++) { const a = W(side, r, u - d(11), 27 + b * 5), e = W(side, r, u - d(11) + d(8 + hash(uid + b, Math.floor(u)) * 14), 27 + b * 5); layer.append(sv("line", { x1: a[0], y1: a[1], x2: e[0], y2: e[1], stroke: b % 2 ? pal.neonA : pal.neonB, "stroke-width": 2.2, class: "bars amb", style: "animation-delay:" + (b * 0.4) + "s" })); }
      wc(layer, side, r, u + d(10), 41, 2.2, pal.neonA, { class: "blink amb" });
    } else {   // a vent and a sagging cable
      wq(layer, side, r, u - d(10), 16, u + d(10), 34, "#05050f", { stroke: pal.metal, "stroke-width": 1.5 });
      for (let b = 0; b < 5; b++) wq(layer, side, r, u - d(8), 18 + b * 3.2, u + d(8), 19.4 + b * 3.2, shade(pal.metal, -20));
      const a = W(side, r, u - d(24), 50), m = W(side, r, u, 36), e = W(side, r, u + d(24), 50);
      layer.append(sv("path", { d: "M" + a[0].toFixed(1) + " " + a[1].toFixed(1) + "Q" + m[0].toFixed(1) + " " + (m[1] + 6).toFixed(1) + " " + e[0].toFixed(1) + " " + e[1].toFixed(1), fill: "none", stroke: pal.neonA, "stroke-width": 2, opacity: 0.85 }));
    }
  }
}
function drawWall(layer, defs, r, side, pal, theme, uid, gap) {
  const n = side === "ne" ? r.w : r.d, start = side === "ne" ? r.x : r.y, base = side === "ne" ? pal.wallR : pal.wallL;
  const edges = [];
  for (let i = 0; i < n; i++) {
    const u = start + i;
    if (gap && u >= gap[0] - 0.01 && u + 1 <= gap[1] + 0.01) continue;
    wq(layer, side, r, u, 0, u + 1, WALL, i % 2 ? shade(base, -3) : base);
    if (theme === "city") for (let s = 0; s < 4; s++) wq(layer, side, r, u + 0.1 + s * 0.22, 21, u + 0.16 + s * 0.22, WALL - 8, "#fff", { opacity: 0.07 });   // wallpaper stripes
    else if (theme === "steam") for (const z of [10, 52]) for (const t of [0.12, 0.88]) { const c = W(side, r, u + t, z); layer.append(sv("circle", { cx: c[0], cy: c[1], r: 1.6, fill: shade(pal.trim, 20), opacity: 0.8 })); }
    else { wq(layer, side, r, u + 0.05, 6, u + 0.95, 7.2, pal.trim, { opacity: 0.35 }); const c = W(side, r, u + 0.5, 12); layer.append(sv("circle", { cx: c[0], cy: c[1], r: 1.2, fill: i % 2 ? pal.neonA : pal.neonB, class: "blink" + (i % 3 ? "2" : "") + " amb" })); }
    wq(layer, side, r, u, 0, u + 1, 20, shade(base, -16));   // wainscot
    wq(layer, side, r, u, 0, u + 1, 4, shade(base, -34));    // baseboard
    wq(layer, side, r, u, 19, u + 1, 21.5, pal.trim);        // rail
    wq(layer, side, r, u, WALL - 7, u + 1, WALL, pal.trim); wq(layer, side, r, u, WALL - 2.4, u + 1, WALL, shade(pal.trim, 28));   // crown
    wq(layer, side, r, u, 0, u + 1, 16, "#000", { opacity: 0.12 });   // light fall-off toward the floor
    edges.push(u);
  }
  for (const u of edges) { const a = W(side, r, u, 0), b = W(side, r, u, WALL); layer.append(sv("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: "#000", "stroke-width": 1, opacity: 0.16 })); }
  for (const u of edges) {
    const i = u - start;
    if (i % 3 === 1) wallDecor(layer, defs, side, r, u + 0.5, pal, theme, Math.floor(i / 3) % 3, uid + (side === "ne" ? 1 : 2) + Math.floor(r.x * 7 + r.y * 13));
  }
  if (gap) {   // the door frame
    for (const u of [gap[0], gap[1] - 0.14]) wq(layer, side, r, u, 0, u + 0.14, 50, pal.trim);
    wq(layer, side, r, gap[0], 44, gap[1], 52, shade(pal.trim, -10));
  }
}
function drawWalls(layer, defs, p, pal, theme, uid) {
  for (const r of Object.values(p.rooms)) {
    const doorX = r.kind === "bay" ? [r.x + p.BW / 2 - 1, r.x + p.BW / 2 + 1] : null, doorY = r.kind === "outbox" ? [r.y + 2, r.y + 4] : null;
    drawWall(layer, defs, r, "ne", pal, theme, uid, doorX);
    drawWall(layer, defs, r, "nw", pal, theme, uid, doorY);
  }
}

// ---- furniture and props ----------------------------------------------------------------------------------------------
function box(g, x, y, w, d, z0, h, color, soft) {   // a cuboid: top, the face toward the viewer's left, the face toward its right
  g.append(sv("polygon", { points: pts([P(x, y + d, z0), P(x + w, y + d, z0), P(x + w, y + d, z0 + h), P(x, y + d, z0 + h)]), fill: shade(color, -14) }),
           sv("polygon", { points: pts([P(x + w, y, z0), P(x + w, y + d, z0), P(x + w, y + d, z0 + h), P(x + w, y, z0 + h)]), fill: shade(color, -32) }),
           sv("polygon", { points: pts([P(x, y, z0 + h), P(x + w, y, z0 + h), P(x + w, y + d, z0 + h), P(x, y + d, z0 + h)]), fill: color }));
  if (!soft) g.append(sv("polyline", { points: pts([P(x, y + d, z0 + h), P(x + w, y + d, z0 + h), P(x + w, y, z0 + h)]), fill: "none", stroke: shade(color, 35), "stroke-width": 1, opacity: 0.6 }));
}
function shadow(g, x, y, w, d) { poly(g, [P(x + 0.15, y + 0.15, 0), P(x + w + 0.7, y + 0.15, 0), P(x + w + 0.7, y + d + 0.7, 0), P(x + 0.15, y + d + 0.7, 0)], "#000", { opacity: 0.28 }); }
function led(g, x, y, z, color, cls) { const c = P(x, y, z); g.append(sv("circle", { cx: c[0], cy: c[1], r: 2, fill: color, class: cls || "", opacity: 0.95 })); }
function glow(g, defs, x, y, z, r, color, id, cls) { const c = P(x, y, z); g.append(sv("circle", { cx: c[0], cy: c[1], r, fill: gradient(defs, id, [[0, color, 0.5], [1, color, 0]], { r: "50%" }), class: cls || "" })); }
function furnitureGroup(f, pal, theme, now, defs, uid) {
  const g = sv("g", {}), [x, y, w, d] = f.box, o = f.obj, wood = pal.wood, dark = pal.dark, metal = pal.metal;
  const fresh = o && o.last && now - o.last < 4, busy = fresh ? "blink" : "", id = "fg" + uid + f.family + Math.round(x * 3 + y * 5);
  shadow(g, x, y, w, d);
  switch (f.family) {
    case "read": {   // filing cabinet / chart rack / data terminal
      const body = theme === "city" ? pal.steel : theme === "steam" ? shade(metal, -10) : dark;
      box(g, x, y, w, d, 0, 36, body);
      for (let i = 0; i < 3; i++) { for (let k = 0; k < Math.floor(w); k++) { const fx = x + 0.12 + k * (w / Math.floor(w)), fw = w / Math.floor(w) - 0.24; box(g, fx, y + d - 0.02, fw, 0.04, 3 + i * 11, 9, shade(body, 10), true); g.append(sv("line", { x1: P(fx + fw * 0.35, y + d, 7.5 + i * 11)[0], y1: P(fx + fw * 0.35, y + d, 7.5 + i * 11)[1], x2: P(fx + fw * 0.65, y + d, 7.5 + i * 11)[0], y2: P(fx + fw * 0.65, y + d, 7.5 + i * 11)[1], stroke: theme === "cyber" ? pal.neonB : pal.paper, "stroke-width": 2 })); } }
      if (theme === "cyber") for (let i = 0; i < 5; i++) led(g, x + 0.3 + i * 0.5, y + d, 32, i % 2 ? pal.neonA : pal.neonB, busy || "blink" + (i % 3 ? "2" : "3"));
      else for (let i = 0; i < 4; i++) box(g, x + 0.2 + i * (w - 0.4) / 4, y + 0.15, (w - 0.4) / 4 - 0.1, d * 0.6, 36, 6 + (i % 3) * 3, [pal.accent, pal.paper, pal.metal, pal.screen][i]);
      break; }
    case "write": case "desk": {   // typewriter desk / brass press / fabricator
      box(g, x, y, w, d, 0, 17, wood); box(g, x + 0.1, y + 0.1, 0.5, d - 0.2, 0, 14, shade(wood, -22), true); box(g, x + w - 0.6, y + 0.1, 0.5, d - 0.2, 0, 14, shade(wood, -22), true);
      for (let k = 0; k < 2; k++) box(g, x + w - 0.58, y + 0.2 + k * (d / 2 - 0.1), 0.02, d / 2 - 0.4, 3 + k * 0, 5, shade(wood, -45), true);
      if (theme === "city") { box(g, x + w * 0.3, y + d * 0.2, 1.0, 0.8, 17, 6, dark); box(g, x + w * 0.3 + 0.1, y + d * 0.2, 0.8, 0.1, 23, 4, "#222"); box(g, x + w * 0.3 + 0.15, y + d * 0.2 + 0.15, 0.7, 0.04, 23, 8, pal.paper, true);
        for (let k = 0; k < 4; k++) box(g, x + w * 0.3 + 0.1 + k * 0.2, y + d * 0.2 + 0.5, 0.12, 0.12, 23, 1.5, "#ddd", true); }
      else if (theme === "steam") { box(g, x + w * 0.3, y + d * 0.2, 1.2, 0.8, 17, 5, metal); box(g, x + w * 0.35, y + d * 0.25, 0.3, 0.3, 22, 14, shade(metal, -20)); box(g, x + w * 0.35 + 0.5, y + d * 0.25, 0.5, 0.3, 30, 3, metal); led(g, x + w * 0.5, y + d * 0.3, 27, pal.lamp, busy);
        if (fresh) glow(g, defs, x + w * 0.45, y + d * 0.35, 25, 22, pal.accent, id + "s", "flick amb"); }
      else { box(g, x + w * 0.36, y + d * 0.18, 1, 0.12, 17, 14, "#05050f"); box(g, x + w * 0.36 + 0.05, y + d * 0.18 + 0.12, 0.9, 0.02, 19, 10, fresh ? pal.screen : shade(pal.screen, -55), true); box(g, x + w * 0.4, y + d * 0.5, 0.8, 0.3, 17, 1.5, pal.neonB);
        if (fresh) glow(g, defs, x + w * 0.5, y + d * 0.3, 24, 24, pal.screen, id + "c", "flick amb"); }
      if (f.family === "desk") { box(g, x + 0.2, y + d + 0.1, 0.9, 0.9, 0, 9, shade(wood, -15)); box(g, x + 0.2, y + d + 0.1, 0.9, 0.12, 9, 12, shade(wood, -15), true);   // a chair
        if (f.laneState) { const on = f.laneState === "lit"; box(g, x + w - 1.1, y + d - 0.9, 0.8, 0.6, 17, 2, on ? pal.accent : shade(pal.dark, 20)); if (on) glow(g, defs, x + w - 0.7, y + d - 0.6, 22, 30, pal.accent, id + "tray", "flick amb"); } }   // the handoff tray: lit once that handoff was recorded
      break; }
    case "shell": {   // safe / boiler valve / root console
      if (theme === "city") { box(g, x, y, w, d, 0, 26, pal.steel); const c = P(x + w - 0.04, y + d * 0.5, 14); g.append(sv("circle", { cx: c[0], cy: c[1], r: 6, fill: "#cfd6cf", stroke: "#333", "stroke-width": 1.5 }), sv("line", { x1: c[0], y1: c[1], x2: c[0] + 3, y2: c[1] - 3, stroke: "#222", "stroke-width": 1.5 })); box(g, x + w - 0.04, y + d * 0.2, 0.08, 0.15, 6, 14, "#333", true); }
      else if (theme === "steam") { box(g, x, y, w, d, 0, 20, shade(metal, -25)); for (let k = 0; k < 2; k++) { const c = P(x + 0.5 + k * 0.9, y + d * 0.5, 30); g.append(sv("rect", { x: c[0] - 2, y: c[1], width: 4, height: 10, fill: metal }), sv("circle", { cx: c[0], cy: c[1], r: 7, fill: "none", stroke: pal.accent, "stroke-width": 2.5 }), sv("line", { x1: c[0] - 7, y1: c[1], x2: c[0] + 7, y2: c[1], stroke: pal.accent, "stroke-width": 2 })); }
        if (fresh) { const c = P(x + w * 0.5, y + d * 0.5, 40); g.append(sv("circle", { cx: c[0], cy: c[1], r: 6, fill: "#fff", class: "puff amb", opacity: 0.6 })); } }
      else { box(g, x, y, w, d, 0, 22, dark); box(g, x + 0.1, y + 0.1, w - 0.2, d - 0.2, 22, 3, pal.metal); for (let i = 0; i < 6; i++) led(g, x + 0.2 + (i % 3) * 0.55, y + d + 0.0, 8 + Math.floor(i / 3) * 6, [pal.neonA, pal.neonB, pal.screen][i % 3], busy || "blink" + (i % 3 ? "2" : "3"));
        box(g, x + 0.2, y + 0.3, 1.4, 0.7, 25, 1, "#05050f"); box(g, x + 0.3, y + 0.35, 1.2, 0.6, 26, 0.5, fresh ? pal.screen : shade(pal.screen, -60), true); }
      break; }
    case "web": {   // radio set / signal lamp / uplink
      box(g, x, y, w, d, 0, 22, theme === "city" ? wood : metal); const c = P(x + w / 2, y + d + 0.0, 13);
      g.append(sv("circle", { cx: c[0] - 5, cy: c[1], r: 4.5, fill: pal.paper, stroke: "#333" }), sv("circle", { cx: c[0] + 5, cy: c[1], r: 4.5, fill: pal.paper, stroke: "#333" }), sv("rect", { x: c[0] - 8, y: c[1] + 6, width: 16, height: 5, fill: shade(wood, -35) }));
      const t = P(x + w / 2, y + d / 2, 22), t2 = P(x + w / 2, y + d / 2, 64);
      g.append(sv("line", { x1: t[0], y1: t[1], x2: t2[0], y2: t2[1], stroke: pal.metal, "stroke-width": 2 }), sv("circle", { cx: t2[0], cy: t2[1], r: 3, fill: pal.lamp, class: busy || "blink2" }));
      if (fresh) for (const [r, dl] of [[10, 0], [18, 0.4]]) g.append(sv("circle", { cx: t2[0], cy: t2[1], r, fill: "none", stroke: pal.accent, "stroke-width": 1.5, class: "puff amb", style: "animation-delay:" + dl + "s" }));
      break; }
    case "mcp": {   // switchboard / speaking tubes / mesh node
      box(g, x, y, w, d, 0, 32, theme === "city" ? wood : dark);
      for (let r = 0; r < 4; r++) for (let k = 0; k < 3; k++) { const c = P(x + w, y + 0.3 + k * (d - 0.5) / 3, 8 + r * 6); g.append(sv("circle", { cx: c[0], cy: c[1], r: 2, fill: "#05050f", stroke: pal.metal, "stroke-width": 1 })); }
      for (let k = 0; k < 4; k++) { const a = P(x + w, y + 0.4 + k * 0.5, 14 + (k % 2) * 6), b = P(x + w + 0.8, y + 0.9 + k * 0.5, 2); g.append(sv("path", { d: "M" + a[0].toFixed(1) + " " + a[1].toFixed(1) + "Q" + (a[0] + 6) + " " + (b[1] - 6) + " " + b[0].toFixed(1) + " " + b[1].toFixed(1), fill: "none", stroke: [pal.accent, pal.lamp, pal.screen, pal.neonA][k], "stroke-width": 2 })); }
      for (let k = 0; k < 3; k++) led(g, x + w, y + 0.5 + k * 0.7, 36, [pal.accent, pal.lamp, pal.screen][k], busy || "blink" + (k + 1 > 1 ? k + 1 : ""));
      break; }
    case "other": {   // cupboard / locker
      box(g, x, y, w, d, 0, 32, theme === "cyber" ? pal.steel : wood);
      for (let k = 0; k < 2; k++) { box(g, x + 0.12 + k * (w / 2), y + d - 0.02, w / 2 - 0.24, 0.04, 3, 26, shade(theme === "cyber" ? pal.steel : wood, 10), true); const c = P(x + (k ? 0.12 : w - 0.12) + (k ? 0 : -0.0) + (k ? w / 2 - 0.3 : w / 2 - 0.3 - w / 2 + 0.3), y + d, 16); g.append(sv("circle", { cx: c[0], cy: c[1], r: 1.6, fill: metal })); }
      break; }
    case "approvals": {   // signing desk / helm / gatekeeper
      box(g, x, y, w, d, 0, 17, wood); for (let k = 0; k < 4; k++) box(g, x + 0.35, y + 0.25, 0.9, 0.7, 17 + k * 0.7, 0.7, k % 2 ? pal.paper : shade(pal.paper, -8), true);
      box(g, x + 1.5, y + 0.3, 0.3, 0.3, 17, 6, dark); const lamp = P(x + w - 0.5, y + 0.5, 30), on = o && o.pending;
      g.append(sv("rect", { x: lamp[0] - 1, y: lamp[1], width: 2, height: 13, fill: metal }), sv("polygon", { points: pts([[lamp[0] - 7, lamp[1]], [lamp[0] + 7, lamp[1]], [lamp[0] + 4, lamp[1] - 7], [lamp[0] - 4, lamp[1] - 7]]), fill: on ? pal.wait : shade(pal.lamp, -40), class: on ? "flick amb" : "" }));
      if (on) glow(g, defs, x + w - 0.5, y + 0.5, 20, 34, pal.wait, id + "p", "flick2 amb");
      if (theme === "steam") { const c = P(x + w * 0.5, y + d, 24); g.append(sv("circle", { cx: c[0], cy: c[1], r: 7, fill: "none", stroke: pal.accent, "stroke-width": 2.5 })); }
      break; }
    case "ledger": {   // cash register / pressure gauge / credit meter
      box(g, x, y, w, d, 0, 14, metal); box(g, x + 0.3, y + 0.2, w - 0.6, d - 0.3, 14, 9, shade(metal, -25)); box(g, x + 0.4, y + 0.25, w - 0.8, 0.1, 18, 5, pal.screen);
      for (let k = 0; k < 6; k++) box(g, x + 0.4 + k * 0.28, y + d - 0.5, 0.2, 0.2, 14, 1.4, k % 2 ? "#ddd" : "#999", true);
      if (o && o.usd > 0) led(g, x + w - 0.3, y + 0.4, 25, pal.accent, "blink");
      break; }
    case "table": {   // the planning table, with a map on it
      box(g, x, y, w, d, 0, 12, wood); box(g, x + 0.35, y + 0.3, w - 0.7, d - 0.6, 12, 1, pal.paper, true);
      const a = P(x + 0.7, y + 0.6, 13), b = P(x + w - 0.8, y + d - 0.6, 13);
      g.append(sv("path", { d: "M" + a[0] + " " + a[1] + "l30 12l24 -8l22 14", fill: "none", stroke: pal.dim, "stroke-width": 1.5 }), sv("circle", { cx: b[0], cy: b[1], r: 3, fill: pal.wait }));
      for (const [cx, cy] of [[x + 0.3, y - 0.5], [x + w - 1.2, y - 0.5], [x + 0.3, y + d + 0.2], [x + w - 1.2, y + d + 0.2]]) { box(g, cx, cy, 0.8, 0.8, 0, 8, shade(wood, -20), true); box(g, cx, cy, 0.8, 0.12, 8, 9, shade(wood, -20), true); }
      break; }
    case "crate": {   // the outbox: crates, lit when work has landed
      box(g, x, y, w, d, 0, 14, wood); for (let k = 0; k < 3; k++) box(g, x + 0.05, y + d - 0.02, w - 0.1, 0.04, 2 + k * 4, 1.4, shade(wood, -35), true);
      box(g, x + 0.3, y + 0.3, w - 0.9, d - 0.9, 14, 13, o && o.state === "landed" ? pal.accent : shade(wood, -8)); if (o && o.state === "landed") glow(g, defs, x + w / 2, y + d / 2, 20, 46, pal.accent, id + "l", "flick amb");
      break; }
  }
  if (fresh) g.append(sv("ellipse", { cx: P(x + w / 2, y + d / 2, 0)[0], cy: P(x + w / 2, y + d / 2, 0)[1] + 2, rx: 40, ry: 15, fill: "none", stroke: pal.accent, "stroke-width": 3, opacity: 0.85, class: "blink amb" }));
  if (o && f.family !== "crate") {   // a count plate: how often it was used; amber dot: it asked you; red dot: denied or failed
    const top = P(x + w / 2, y + d / 2, 58), n = f.family === "ledger" ? "$" + o.usd.toFixed(3) : f.family === "approvals" ? o.asked : o.used;
    g.append(sv("rect", { x: top[0] - 15, y: top[1] - 8, width: 30, height: 12, rx: 3, fill: pal.dark, stroke: pal.trim, "stroke-width": 1, opacity: 0.92 }), sv("text", { x: top[0], y: top[1] + 1.5, class: "badge-n", fill: pal.ink, stroke: "none" }, String(n)));
    if (o.pending || (o.asked && f.family !== "approvals")) g.append(sv("circle", { cx: top[0] - 17, cy: top[1] - 6, r: 4, fill: pal.wait, stroke: "#000", "stroke-width": 1 }));
    if (o.denied || o.failed) g.append(sv("circle", { cx: top[0] + 17, cy: top[1] - 6, r: 4, fill: pal.bad, stroke: "#000", "stroke-width": 1 }));
  }
  return g;
}
function propGroup(kind, x, y, pal, theme, defs, uid, size) {   // scenery: it says nothing about the run
  const g = sv("g", {}), id = "pr" + uid + kind + Math.round(x * 3 + y * 7);
  shadow(g, x - 0.2, y - 0.2, 1, 1);
  if (kind === "plant") {
    box(g, x - 0.3, y - 0.3, 0.7, 0.7, 0, 8, "#7a4a2a", true);
    const c = P(x + 0.05, y + 0.05, 12);
    for (const [dx, dy, rr, col] of [[0, -14, 8, "#2f7a3a"], [-9, -8, 7, "#3a8a44"], [9, -8, 7, "#2a6a34"], [-4, -20, 6, "#3f9a4c"], [5, -17, 6, "#2f7a3a"]]) g.append(sv("ellipse", { cx: c[0] + dx, cy: c[1] + dy, rx: rr, ry: rr * 1.25, fill: col }));
  } else if (kind === "lamp") {
    box(g, x - 0.1, y - 0.1, 0.25, 0.25, 0, 5, pal.metal, true);
    const c = P(x, y, 5), t = P(x, y, 44);
    g.append(sv("line", { x1: c[0], y1: c[1], x2: t[0], y2: t[1], stroke: pal.metal, "stroke-width": 2.5 }), sv("polygon", { points: pts([[t[0] - 9, t[1] + 2], [t[0] + 9, t[1] + 2], [t[0] + 5, t[1] - 9], [t[0] - 5, t[1] - 9]]), fill: pal.lamp, class: "flick amb" }));
    g.append(sv("ellipse", { cx: P(x, y, 0)[0], cy: P(x, y, 0)[1], rx: 56, ry: 24, fill: gradient(defs, id, [[0, pal.lamp, 0.4], [1, pal.lamp, 0]], { r: "50%" }), class: "flick2 amb" }));
  } else if (kind === "crates") {
    box(g, x, y, 1.2, 1.1, 0, 12, pal.wood); box(g, x + 0.1, y + 0.1, 0.9, 0.8, 12, 10, shade(pal.wood, 8));
    for (let k = 0; k < 2; k++) box(g, x + 0.05, y + 1.08, 1.1, 0.04, 2 + k * 5, 1.4, shade(pal.wood, -35), true);
  } else if (kind === "tank") {   // a barrel, a boiler or a server rack
    if (theme === "steam") {
      const c = P(x + 0.3, y + 0.3, 0);
      g.append(sv("rect", { x: c[0] - 13, y: c[1] - 38, width: 26, height: 38, fill: shade(pal.metal, -25) }), sv("ellipse", { cx: c[0], cy: c[1], rx: 13, ry: 6, fill: shade(pal.metal, -25) }), sv("ellipse", { cx: c[0], cy: c[1] - 38, rx: 13, ry: 6, fill: shade(pal.metal, 5) }));
      for (const z of [10, 28]) g.append(sv("rect", { x: c[0] - 13, y: c[1] - z - 2, width: 26, height: 3, fill: pal.metal }));
      g.append(sv("circle", { cx: c[0], cy: c[1] - 22, r: 5, fill: pal.paper, stroke: pal.metal, "stroke-width": 1.5 }), sv("circle", { cx: c[0], cy: c[1] - 44, r: 4, fill: "#fff", opacity: 0.5, class: "puff amb" }));
    } else if (theme === "cyber") {
      box(g, x, y, 0.9, 0.9, 0, 44, pal.dark);
      for (let r = 0; r < 7; r++) { led(g, x + 0.2, y + 0.9, 6 + r * 5.5, r % 2 ? pal.neonA : pal.neonB, "blink" + (r % 3 ? (r % 3 + 1) : "")); led(g, x + 0.6, y + 0.9, 6 + r * 5.5, pal.screen, "blink" + (r % 2 ? "2" : "3")); }
    } else {
      const c = P(x + 0.3, y + 0.3, 0);
      g.append(sv("rect", { x: c[0] - 11, y: c[1] - 28, width: 22, height: 28, fill: shade(pal.wood, -5) }), sv("ellipse", { cx: c[0], cy: c[1], rx: 11, ry: 5, fill: shade(pal.wood, -20) }), sv("ellipse", { cx: c[0], cy: c[1] - 28, rx: 11, ry: 5, fill: shade(pal.wood, 12) }));
      for (const z of [7, 20]) g.append(sv("rect", { x: c[0] - 11, y: c[1] - z - 1, width: 22, height: 2.5, fill: pal.metal }));
    }
  } else if (kind === "bookcase") {
    const len = size || 3.4;
    box(g, x, y, 0.9, len, 0, 46, pal.wood);
    for (let r = 0; r < 4; r++) for (let k = 0; k < Math.floor(len / 0.4); k++) { const col = [pal.accent, pal.rug1, pal.screen, pal.paper, pal.metal][Math.floor(hash(r, k + Math.round(y)) * 5)]; box(g, x + 0.85, y + 0.12 + k * 0.4, 0.05, 0.3, 4 + r * 10, 8 - (k % 3), col, true); }
  } else if (kind === "coat") {
    const c = P(x, y, 0), t = P(x, y, 52);
    g.append(sv("line", { x1: c[0], y1: c[1], x2: t[0], y2: t[1], stroke: pal.wood, "stroke-width": 3 }), sv("polygon", { points: pts([[t[0] - 9, t[1] + 4], [t[0] + 9, t[1] + 4], [t[0] + 12, t[1] + 28], [t[0] - 12, t[1] + 28]]), fill: shade(pal.rug1, 5) }), sv("ellipse", { cx: t[0], cy: t[1] - 2, rx: 8, ry: 3.5, fill: pal.dark }));
  }
  return g;
}
function atmosphere(svg, defs, B, pal, theme, uid) {   // light and dust over everything
  const [x0, y0, x1, y1] = B, w = x1 - x0, h = y1 - y0, layer = sv("g", { "aria-hidden": "true", "pointer-events": "none" });
  layer.append(sv("rect", { x: x0, y: y0, width: w, height: h, fill: gradient(defs, "vig" + uid, [[0.55, "#000", 0], [1, "#000", 0.6]], { r: "75%" }) }));
  for (let i = 0; i < 26; i++) layer.append(sv("circle", { cx: x0 + hash(71, i) * w, cy: y0 + h * 0.3 + hash(72, i) * h * 0.65, r: 1 + hash(73, i) * 1.6, fill: theme === "cyber" ? pal.neonB : pal.lamp, opacity: 0.25, class: "mote amb", style: "animation-delay:-" + (hash(74, i) * 14).toFixed(1) + "s;animation-duration:" + (10 + hash(75, i) * 10).toFixed(0) + "s" }));
  svg.append(layer);
}

// ---- the crew: pixel people --------------------------------------------------------------------------------------------
const CELL = 3, SKIN = "#e8b98a", SKIN2 = "#c99468";
const LOOKS = {
  clyde:   { coat: "#2d3a5a", shirt: "#e8e0d0", tie: "#8a2433", pants: "#1c2236", hat: "#1f2740", hair: "#2a1a10", kind: "cap" },
  bonnie:  { coat: "#b33a3a", shirt: "#f2e8e0", tie: null, pants: "#3a2a2a", hat: "#8a2433", hair: "#4a2b1a", kind: "beret", long: true },
  master:  { coat: "#c99a2e", shirt: "#f4ecd2", tie: "#3a2a14", pants: "#3a3020", hat: "#3a2a14", hair: "#222", kind: "bowler" },
  advisor: { coat: "#6a4c93", shirt: "#e8e0f0", tie: "#bdbdbd", pants: "#2b2440", hat: null, hair: "#bdbdbd", kind: "glasses" },
};
const WORKERS = ["#2f8f83", "#d17a22", "#3b78c2", "#8a5fb0", "#b05f5f", "#5fa86a", "#c2b13b", "#4f6d7a"];
function lookFor(name, theme) {
  const base = LOOKS[name] || { coat: WORKERS[(parseInt(number(name) || "1", 10) - 1) % WORKERS.length], shirt: "#d8d8d8", tie: null, pants: "#2a2f3a", hat: "#e0b020", hair: "#3a2a1a", kind: "hardhat" };
  return { ...base, theme };
}
function personFrame(look, pose, f, blink) {   // one pose as a grid of cells on 12 x 22: [x, y, w, h, colour]
  const c = [], r = (x, y, w, h, col) => c.push([x, y, w, h, col]);
  const walking = pose === "walk", working = pose === "work" || pose === "check", carrying = pose === "carry";
  const phase = walking ? f % 4 : 0, bob = walking && phase % 2 ? -1 : (pose === "idle" && f === 1 ? 0 : 0), legA = phase === 0 ? 1 : phase === 2 ? -1 : 0;
  const top = bob;   // everything above the legs rides the bob
  // legs and boots
  const lx = 3, rx = 6;
  r(lx, 16 + legA * 0, 3, 4 - Math.max(0, legA), look.pants); r(rx, 16 + (legA < 0 ? 0 : 0), 3, 4 - Math.max(0, -legA), look.pants);
  r(lx - (legA > 0 ? 0 : 0), 20 - Math.max(0, legA), 3, 2, "#15151a"); r(rx, 20 - Math.max(0, -legA), 3, 2, "#15151a");
  if (look.theme === "steam") r(lx, 17, 3, 1, "#c0773a");
  // body
  r(2, 9 + top, 8, 7, look.coat); r(5, 9 + top, 2, 6, look.shirt); if (look.tie) r(5.5, 10 + top, 1, 4, look.tie);
  r(2, 9 + top, 2, 3, shade(look.coat, 18)); r(8, 9 + top, 2, 3, shade(look.coat, -18)); r(2, 15 + top, 8, 1, shade(look.coat, -35));
  if (look.theme === "steam") { r(2, 14 + top, 8, 1, "#c0773a"); r(5, 14 + top, 2, 1, "#ffd166"); }
  if (look.theme === "cyber") { r(2, 9 + top, 8, 1, "#19e3ff"); r(2, 12 + top, 1, 3, "#ff2bd6"); }
  if (look.theme === "city" && look.kind !== "glasses") { r(3, 10 + top, 1, 5, shade(look.coat, -40)); r(8, 10 + top, 1, 5, shade(look.coat, -40)); }   // braces
  // arms
  if (working) { const s = f % 2; r(0, 10 + top + s, 2, 4, look.coat); r(10, 10 + top + (1 - s), 2, 4, look.coat); r(0, 14 + top + s, 2, 1, SKIN); r(10, 14 + top + (1 - s), 2, 1, SKIN); }
  else if (carrying) { r(0, 5 + top, 2, 6, look.coat); r(10, 5 + top, 2, 6, look.coat); r(0, 4 + top, 2, 1, SKIN); r(10, 4 + top, 2, 1, SKIN); }
  else { const sw = walking ? (phase === 0 ? 1 : phase === 2 ? -1 : 0) : 0; r(0, 9 + top + sw, 2, 6, look.coat); r(10, 9 + top - sw, 2, 6, look.coat); r(0, 15 + top + sw, 2, 1, SKIN); r(10, 15 + top - sw, 2, 1, SKIN); }
  // head
  r(5, 8 + top, 2, 1, SKIN2); r(3, 2 + top, 6, 6, SKIN); r(2, 4 + top, 1, 2, SKIN2); r(9, 4 + top, 1, 2, SKIN2); r(3, 7 + top, 6, 1, SKIN2);
  if (blink) { r(4, 5 + top, 1, 1, "#4a2a1a"); r(7, 5 + top, 1, 1, "#4a2a1a"); } else { r(4, 4 + top, 1, 2, "#1a1a22"); r(7, 4 + top, 1, 2, "#1a1a22"); r(4, 4 + top, 1, 1, "#fff"); r(7, 4 + top, 1, 1, "#fff"); }
  r(5, 6 + top, 2, 1, "#a0604a");
  if (look.kind === "glasses") { r(3, 4 + top, 3, 1, "#333"); r(6, 4 + top, 3, 1, "#333"); r(5, 4 + top, 1, 1, "#333"); }
  // hair, hats and gear
  if (look.long) { r(2, 3 + top, 1, 7, look.hair); r(9, 3 + top, 1, 7, look.hair); }
  if (look.kind === "beret") { r(2, 0 + top, 7, 2, look.hat); r(3, -1 + top, 5, 1, look.hat); r(3, 2 + top, 6, 1, look.hair); }
  else if (look.kind === "bowler") { r(3, -1 + top, 6, 2, look.hat); r(2, 1 + top, 8, 1, look.hat); r(3, 1 + top, 6, 1, shade(look.hat, 25)); }
  else if (look.kind === "hardhat") { r(3, 0 + top, 6, 2, look.hat); r(2, 2 + top, 8, 1, look.hat); r(3, 0 + top, 6, 1, shade(look.hat, 30)); }
  else if (look.kind === "glasses") { r(3, 1 + top, 6, 2, look.hair); r(2, 3 + top, 1, 2, look.hair); r(9, 3 + top, 1, 2, look.hair); }
  else { r(3, 0 + top, 6, 2, look.hat); r(3, 2 + top, 8, 1, look.hat); r(3, 2 + top, 6, 1, look.hair); }   // a flat cap with a peak
  if (look.theme === "city" && look.kind !== "beret" && look.kind !== "glasses") r(2, 2 + top, 8, 1, shade(look.hat || look.coat, -25));   // a hat band
  if (look.theme === "steam") { r(3, 2 + top, 2, 2, "#c0773a"); r(7, 2 + top, 2, 2, "#c0773a"); r(4, 2 + top, 1, 1, "#9ff0e6"); r(7, 2 + top, 1, 1, "#9ff0e6"); }   // goggles pushed up
  if (look.theme === "cyber") { r(3, 4 + top, 6, 2, "#19e3ff"); r(3, 4 + top, 6, 1, "#fff"); }   // a visor
  return c;
}
const POSES = { idle: 3, walk: 4, work: 2, check: 2, carry: 2 };
function personItem(name, role, theme) {
  const look = lookFor(name, theme), g = sv("g", { class: "sprite", "data-sprite": name }), frames = {};
  const body = sv("g", { transform: "translate(" + (-6 * CELL) + " " + (-22 * CELL) + ")" });
  for (const pose in POSES) {
    frames[pose] = [];
    for (let f = 0; f < POSES[pose]; f++) {
      const fg = sv("g", { style: "display:none" });
      for (const [x, y, w, h, col] of personFrame(look, pose, pose === "idle" ? Math.min(f, 1) : f, pose === "idle" && f === 2)) fg.append(sv("rect", { x: x * CELL, y: y * CELL, width: w * CELL, height: h * CELL, fill: col, "shape-rendering": "crispEdges" }));
      body.append(fg);
      frames[pose].push(fg);
    }
  }
  const flip = sv("g", { class: "flip" });
  flip.append(body);
  const shadowEl = sv("ellipse", { cx: 0, cy: 1, rx: 17, ry: 6, fill: "#000", opacity: 0.4 });
  const tag = sv("g", { transform: "translate(0 " + (-22 * CELL - 5) + ")" });
  const label = sv("text", { y: 3, class: "name", fill: "#fff", stroke: "#000" }, name);
  const bubble = sv("g", { transform: "translate(0 " + (-22 * CELL - 24) + ")" });
  tag.append(sv("rect", { x: -(name.length * 3.6 + 6), y: -9, width: name.length * 7.2 + 12, height: 14, rx: 3, fill: "#000", opacity: 0.6 }), label);
  g.append(shadowEl, flip, tag, bubble);
  g.append(sv("title", {}, name));
  return { name, role, g, flip, frames, bubble, shown: null, bubbleKind: null, title: g.lastChild };
}
function setBubble(person, kind, pal) {
  if (person.bubbleKind === kind) return;
  person.bubbleKind = kind;
  person.bubble.replaceChildren();
  if (!kind) return;
  const fill = { q: pal.wait, ok: "#3ec283", bad: pal.bad, dots: pal.accent, paper: pal.paper, mail: pal.paper, glass: pal.screen, folder: pal.accent, box: pal.wood }[kind] || pal.accent;
  person.bubble.append(sv("rect", { x: -11, y: -9, width: 22, height: 18, rx: 5, fill: pal.dark, stroke: fill, "stroke-width": 2 }), sv("polygon", { points: "-3,9 3,9 0,14", fill: fill }));
  if (kind === "q") person.bubble.append(sv("text", { y: 5, class: "sign", fill, stroke: "none" }, "?"));
  else if (kind === "ok") person.bubble.append(sv("path", { d: "M-5 0l3 4 7-8", fill: "none", stroke: fill, "stroke-width": 2.5 }));
  else if (kind === "bad") person.bubble.append(sv("path", { d: "M-5 -4l10 8M5 -4l-10 8", fill: "none", stroke: fill, "stroke-width": 2.5 }));
  else if (kind === "dots") for (const [i, x] of [-6, 0, 6].entries()) person.bubble.append(sv("circle", { cx: x, cy: 0, r: 2, fill, class: "blink" + (i ? i + 1 : "") }));
  else if (kind === "paper") person.bubble.append(sv("rect", { x: -5, y: -5, width: 10, height: 10, fill }), sv("path", { d: "M-3 -2h6M-3 1h6", stroke: "#444", "stroke-width": 1 }));
  else if (kind === "mail") person.bubble.append(sv("rect", { x: -6, y: -4, width: 12, height: 8, fill }), sv("path", { d: "M-6 -4l6 5 6 -5", fill: "none", stroke: "#444", "stroke-width": 1 }));
  else if (kind === "glass") person.bubble.append(sv("circle", { cx: -1, cy: -1, r: 4, fill: "none", stroke: fill, "stroke-width": 2 }), sv("path", { d: "M2 2l4 4", stroke: fill, "stroke-width": 2 }));
  else if (kind === "folder") person.bubble.append(sv("rect", { x: -6, y: -4, width: 12, height: 8, fill }), sv("rect", { x: -6, y: -6, width: 5, height: 3, fill }));
  else if (kind === "box") person.bubble.append(sv("rect", { x: -5, y: -5, width: 10, height: 10, fill, stroke: "#222", "stroke-width": 1 }));
}

// ---- assembling and animating the scene ----------------------------------------------------------------------------------
function buildScene(run) {
  const layout = run.layout, theme = state.theme, pal = THEMES[theme].pal, words = THEMES[theme].words, p = plan(layout), uid = ++UID;
  const B = bounds(p), [x0, y0, x1, y1] = B, now = Date.now() / 1000, events = state.feeds[run.id] || [], liveFrom = state.loadedAt - 3;
  const svg = sv("svg", { viewBox: [x0, y0, x1 - x0, y1 - y0].map((v) => v.toFixed(0)).join(" "), role: "img", "aria-label": "Station for " + (run.task || run.id) + ", " + THEMES[theme].name });
  const defs = sv("defs", {});
  svg.append(defs);
  backdrop(svg, defs, B, pal, theme, uid);
  const floors = sv("g", {}), laneLayer = sv("g", {}), walls = sv("g", {}), items = sv("g", {}), signs = sv("g", {});
  drawFloors(floors, defs, p, pal, theme, uid);
  const order = { dark: 0, lit: 1, waiting: 2, refused: 3 };   // the strongest state is drawn last where lanes share a corridor
  const laneColor = { dark: pal.dim, lit: pal.accent, waiting: pal.wait, refused: pal.bad }, described = [];
  for (const lane of layout.hallways.slice().sort((a, b) => order[a.state] - order[b.state])) {
    const path = p.lanes[lane.id] || p.lanes[lane.kind];
    if (!path) continue;   // the two inside the deck are shown as a lamp on the desk instead (furnitureGroup)
    const proj = path.map((q) => iso(q[0], q[1])), color = laneColor[lane.state];
    const line = sv("polyline", { points: pts(proj), class: "lane " + lane.state, stroke: color, "stroke-width": lane.state === "dark" ? 2.5 : 3.5,
      "stroke-dasharray": lane.state === "dark" ? "2 8" : lane.state === "waiting" ? "10 8" : "none", opacity: lane.state === "dark" ? 0.55 : 0.95 });
    line.append(sv("title", {}, laneTitle(lane, words)));
    laneLayer.append(line);
    if (lane.state === "lit") laneLayer.append(sv("polyline", { points: pts(proj), class: "lane", stroke: color, "stroke-width": 8, opacity: 0.14 }));
    if (lane.state !== "dark") {   // chevrons along it, pointing the way the work goes
      const toward = lane.from === "deck" || lane.kind === "landing" ? 1 : -1;   // task and landing go away from the deck; results and approvals come back
      const tiles = []; for (let i = 1; i < path.length; i++) { const a = path[i - 1], b = path[i], len = Math.hypot(b[0] - a[0], b[1] - a[1]); for (let t = 1; t < len; t += 1.6) tiles.push([a[0] + (b[0] - a[0]) * t / len, a[1] + (b[1] - a[1]) * t / len, (b[0] - a[0]) * toward, (b[1] - a[1]) * toward]); }
      for (const [x, y, dx, dy] of tiles) {
        const c = iso(x, y), d = iso(dx, dy), n = Math.hypot(d[0], d[1]) || 1, ux = d[0] / n, uy = d[1] / n;
        laneLayer.append(sv("polygon", { points: pts([[c[0] + ux * 5, c[1] + uy * 5], [c[0] - ux * 3 - uy * 3.5, c[1] - uy * 3 + ux * 3.5], [c[0] - ux * 3 + uy * 3.5, c[1] - uy * 3 - ux * 3.5]]), fill: color, opacity: 0.9, class: lane.state === "waiting" ? "blink amb" : "" }));
      }
    }
  }
  for (const lane of layout.hallways) described.push(laneTitle(lane, words));
  drawWalls(walls, defs, p, pal, theme, uid);
  for (const r of Object.values(p.rooms)) {   // room signs, on the NE wall
    const title = r.kind === "deck" ? words.deck : r.kind === "outbox" ? words.outbox : words.bay + " " + number(r.id);
    const c = P(r.x + (r.kind === "bay" ? 2.2 : r.w / 2), r.y, WALL - 18), half = title.length * 3.6 + 12;
    signs.append(sv("rect", { x: c[0] - half, y: c[1] - 10, width: half * 2, height: 19, rx: 3, fill: pal.dark, stroke: pal.trim, "stroke-width": 2 }), sv("rect", { x: c[0] - half + 3, y: c[1] - 7, width: half * 2 - 6, height: 13, rx: 2, fill: "none", stroke: pal.trim, "stroke-width": 0.8, opacity: 0.6 }),
                 sv("text", { x: c[0], y: c[1] + 4, class: "sign", fill: pal.ink, stroke: "none" }, title));
  }
  const dyn = [];   // everything that can pass in front of or behind something else: furniture, scenery and crew
  for (const f of p.furniture) {
    if (f.lane) { const l = layout.hallways.find((h) => h.id === f.lane); f.laneState = l ? l.state : null; if (l) described.push(laneTitle(l, words)); }
    const g = furnitureGroup(f, pal, theme, now, defs, uid), tip = f.obj && f.obj.tools ? words[f.family] + ": " + f.obj.tools.join(", ") + " · used " + f.obj.used + " · asked " + f.obj.asked + " (allowed " + f.obj.allowed + ", denied " + f.obj.denied + ")" + (f.obj.failed ? " · failed " + f.obj.failed : "")
      : f.family === "approvals" ? words.approvals + ": asked " + f.obj.asked + " · allowed " + f.obj.allowed + " · denied " + f.obj.denied + " · waiting " + f.obj.pending
      : f.family === "ledger" ? words.ledger + ": $" + f.obj.usd.toFixed(4) + (f.obj.unpriced ? " + " + f.obj.unpriced + " unpriced" : "")
      : f.family === "crate" ? words.outbox + ": " + f.obj.state : f.lane && f.laneState ? words[f.lane] + " tray: " + { dark: "not used yet", lit: "used", waiting: "waiting", refused: "refused" }[f.laneState] : (words[f.family] || f.family);
    g.append(sv("title", {}, tip));
    if (f.obj) described.push((f.room.kind === "bay" ? words.bay + " " + number(f.room.id) : f.room.kind === "deck" ? words.deck : words.outbox) + ": " + tip);
    dyn.push({ el: g, depth: () => f.box[0] + f.box[2] / 2 + f.box[1] + f.box[3] / 2 });
  }
  for (const [kind, x, y, size] of p.props) dyn.push({ el: propGroup(kind, x, y, pal, theme, defs, uid, size), depth: () => x + y + (size || 1) / 2 });
  const deck = layout.rooms.find((r) => r.id === "deck"), cards = {};
  for (const m of deck.members) cards[m.name] = m;
  for (const room of layout.rooms) for (const m of room.members || []) cards[m.name] = m;
  const crewNames = ["clyde", ...(cards.bonnie ? ["bonnie"] : []), "master", ...(cards.advisor ? ["advisor"] : []), ...p.bayRooms.map((r) => r.id)];
  const people = crewNames.map((name) => {
    const person = personItem(name, name, theme), card = cards[name] || { name, doing: "" };
    person.card = card;
    person.g.addEventListener("click", () => { if (dragged) return; state.filter[run.id] = state.filter[run.id] === name ? null : name; draw(); });
    person.title.textContent = name + (card.model ? " · " + card.model : "") + " · " + (card.doing || "");
    described.push(name + ": " + (card.doing || ""));
    return person;
  });
  const trips = {};
  for (const person of people) {
    if (person.name === "clyde" || person.name === "bonnie") trips[person.name] = orchestratorTrips(events, person.name, p, liveFrom);
    else if (p.rooms[person.name]) trips[person.name] = workerTrips(events, person.name, p, liveFrom);
    dyn.push({ el: person.g, person, depth: () => (person.at ? person.at[0] + person.at[1] : 0) });
  }
  svg.append(floors, laneLayer, walls, signs, items);
  atmosphere(svg, defs, B, pal, theme, uid);
  const scene = { runId: run.id, svg, items, dyn, people, trips, p, pal, layout, order: [], base: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } };
  for (const d of dyn) items.append(d.el);
  tickScene(scene, now);
  return { scene, described };
}
function laneTitle(lane, words) {
  const name = lane.kind === "approvals" ? words.approvalsLane : words[lane.kind];
  const route = lane.kind === "review" ? "advisor → master" : lane.kind === "report" ? "master → you" : lane.from + " → " + lane.to;
  const when = { dark: "not used yet", lit: "used" + (lane.count > 1 ? " " + lane.count + " times" : ""), waiting: "waiting for an answer", refused: "refused" }[lane.state];
  return name + " hallway, " + route + ": " + when;
}
function personBubble(person, s, doing) {
  if (s && s.bubble) return s.bubble;
  if (person.role === "clyde" || person.role === "bonnie") return /decision|waiting on you/.test(doing) && person.role === "clyde" ? "q" : null;
  if (/waiting for approval/.test(doing)) return "q";
  if (/failed/.test(doing)) return "bad";
  if (/^finished$|review done|report written/.test(doing)) return person.role === "master" || person.role === "advisor" ? null : "ok";
  return null;
}
function tickScene(scene, now) {
  const { p, pal } = scene, bob = REDUCED ? 0 : Math.sin(now * 2.4) * 1.0;
  for (const person of scene.people) {
    const name = person.name, home = p.homes[name], trips = scene.trips[name], doing = person.card.doing || "";
    const s = trips ? walkerState(trips, home, now) : { pos: home, dir: [0, 0], pose: "idle", carry: null, bubble: null };
    let pose = s.pose;
    if (pose === "idle" && /using|working|splitting|reviewing|writing the report|tasks handed/.test(doing) && !/waiting/.test(doing)) pose = "work";
    const moving = pose === "walk";
    if (!moving && s.carry) pose = "carry";
    const frame = pose === "walk" ? Math.floor(now * 8) % 4 : pose === "work" || pose === "check" ? Math.floor(now * 5) % 2 : pose === "carry" ? Math.floor(now * 3) % 2 : (Math.floor(now * 2) % 9 === 0 ? 2 : Math.floor(now * 0.8) % 2);
    const key = pose + ":" + frame;
    if (person.shown !== key) {
      if (person.shown) { const [pp, ff] = person.shown.split(":"); person.frames[pp][+ff].style.display = "none"; }
      person.frames[pose][frame].style.display = "";
      person.shown = key;
    }
    const screen = iso(s.pos[0], s.pos[1]), face = iso(s.dir[0], s.dir[1])[0] < -0.1 ? -1 : 1;
    person.at = s.pos;
    person.g.setAttribute("transform", "translate(" + screen[0].toFixed(1) + " " + (screen[1] + (moving ? 0 : bob * 0.5)).toFixed(1) + ")");
    person.flip.setAttribute("transform", "scale(" + face + " 1)");
    setBubble(person, personBubble(person, s, doing) || (s.carry && !s.bubble ? s.carry : null), pal);
  }
  const sorted = scene.dyn.slice().sort((a, b) => a.depth() - b.depth()), ids = sorted.map((d) => scene.dyn.indexOf(d)).join(",");
  if (ids !== scene.order.join(",")) { for (const d of sorted) scene.items.append(d.el); scene.order = ids.split(","); }
}
let frameClock = 0;
function loop(ts) {
  if (ts - frameClock > 33) {
    frameClock = ts;
    const now = Date.now() / 1000;
    for (const scene of state.scenes) tickScene(scene, now);
  }
  requestAnimationFrame(loop);
}

// ---- zoom and pan: the +/- keys, Ctrl-scroll or a pinch, and dragging ----------------------------------------------------
state.views = {};
let dragged = false;
function attachView(svg, scene, controls) {
  const base = scene.base, view = state.views[scene.runId] || (state.views[scene.runId] = { ...base });
  const apply = () => svg.setAttribute("viewBox", [view.x, view.y, view.w, view.h].map((v) => v.toFixed(1)).join(" "));
  const zoom = (k, cx, cy) => {
    const nw = Math.min(base.w, Math.max(base.w * 0.18, view.w * k)), nh = nw * base.h / base.w;
    const mx = cx === undefined ? view.x + view.w / 2 : cx, my = cy === undefined ? view.y + view.h / 2 : cy;
    view.x = mx - (mx - view.x) * nw / view.w; view.y = my - (my - view.y) * nh / view.h; view.w = nw; view.h = nh;
    view.x = Math.min(Math.max(view.x, base.x - base.w * 0.2), base.x + base.w * 1.2 - view.w); view.y = Math.min(Math.max(view.y, base.y - base.h * 0.2), base.y + base.h * 1.2 - view.h);
    apply();
  };
  apply();
  const at = (e) => { const r = svg.getBoundingClientRect(); return [view.x + (e.clientX - r.left) / r.width * view.w, view.y + (e.clientY - r.top) / r.height * view.h]; };
  svg.addEventListener("wheel", (e) => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); const [mx, my] = at(e); zoom(e.deltaY < 0 ? 0.88 : 1.14, mx, my); }, { passive: false });
  let start = null;
  svg.addEventListener("pointerdown", (e) => { if (e.button === 0) { start = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }; } });
  svg.addEventListener("pointermove", (e) => {
    if (!start) return;
    const r = svg.getBoundingClientRect(), dx = e.clientX - start.x, dy = e.clientY - start.y;
    if (!start.moved && Math.hypot(dx, dy) < 5) return;
    if (!start.moved) { start.moved = true; svg.setPointerCapture(e.pointerId); }
    view.x = start.vx - dx / r.width * view.w; view.y = start.vy - dy / r.height * view.h; apply();
  });
  const stop = () => { if (start && start.moved) { dragged = true; setTimeout(() => { dragged = false; }, 0); } start = null; };
  svg.addEventListener("pointerup", stop); svg.addEventListener("pointercancel", stop);
  svg.addEventListener("dblclick", () => { Object.assign(view, base); apply(); });
  const keys = [["+", "Zoom in", () => zoom(0.8)], ["−", "Zoom out", () => zoom(1.25)], ["⤢", "Fit the whole station", () => { Object.assign(view, base); apply(); }]];
  for (const [label, title, fn] of keys) { const b = el("button", "", label); b.type = "button"; b.title = title; b.setAttribute("aria-label", title); b.addEventListener("click", fn); controls.append(b); }
}

// ---- the rail: crew, what needs your OK, the event feed -----------------------------------------------------------------
function legend() {
  const box = el("div", "legend");
  for (const [cls, text] of [["dark", "hallway not used yet"], ["lit", "hallway used"], ["waiting", "waiting for an answer"], ["refused", "refused"]]) {
    const item = el("span");
    item.append(el("i", cls), document.createTextNode(text));
    box.append(item);
  }
  box.append(el("span", "", "Furniture is a capability the member was given; its plate counts how often it was used. Crew walk only when something was recorded: a worker to the furniture for a tool it used, Clyde with a task or an approval request, Bonnie to collect a result. Clouds, rain, lamps and neon are only scenery. Drag to pan, Ctrl-scroll or the + and − keys to zoom."));
  return box;
}
function mapSection(run) {
  const built = buildScene(run), stage = el("div", "stage"), wrap = el("div", "map"), controls = el("div", "zoom");
  wrap.append(built.scene.svg);
  stage.append(wrap, controls);
  attachView(built.scene.svg, built.scene, controls);
  state.scenes.push(built.scene);
  const text = el("ul", "sr");
  text.setAttribute("aria-label", "Station as text");
  for (const line of built.described) text.append(el("li", "", line));
  const left = el("div", "");
  left.append(stage, text, legend());
  return left;
}
function portrait(name, doing) {   // the same pixel person as in the scene, in a small well with a lamp
  const look = lookFor(name, state.theme), svg = sv("svg", { viewBox: "0 0 12 22", "shape-rendering": "crispEdges", "aria-hidden": "true" });
  for (const [x, y, w, h, col] of personFrame(look, "idle", 0, false)) svg.append(sv("rect", { x, y: y + 1, width: w, height: h, fill: col }));
  const well = el("div", "portrait");
  well.append(svg, el("span", "lamp " + dotClass(doing)));
  return well;
}
function crewRow(run, member) {
  const button = el("button", "crew-row" + (/approval/.test(member.doing) || (member.name === "clyde" && run.asks.length) ? " asking" : ""));
  button.type = "button";
  button.setAttribute("aria-pressed", String(state.filter[run.id] === member.name));
  const info = el("div", ""), nm = el("div", "nm");
  nm.append(el("span", "", member.name));
  if (member.kind) nm.append(el("span", "chip", member.kind === "cli" ? "agent CLI" : "Clyde"));
  info.append(nm, el("div", "md", member.model), el("div", "st", member.doing));
  if (member.constraint) info.append(el("div", "ru", member.constraint));
  button.append(portrait(member.name, member.doing), info);
  button.addEventListener("click", () => { state.filter[run.id] = state.filter[run.id] === member.name ? null : member.name; draw(); });
  return button;
}
function crewList(run) {
  const deck = run.layout.rooms.find((r) => r.id === "deck"), bonnie = deck.members.find((m) => m.name === "bonnie");
  return [{ name: "clyde", model: "orchestrator", doing: run.clyde }, ...(bonnie ? [{ name: "bonnie", model: "orchestrator", doing: bonnie.doing }] : []), ...run.crew];
}
function asks(run) {
  const box = el("div", "asks");
  for (const ask of run.asks) {
    const row = el("div", "ask");
    row.append(el("div", "", ask.who + " wants to use " + ask.tool));
    row.append(el("pre", "", ask.message));
    for (const [label, allow] of [["Allow", true], ["Deny", false]]) {
      const button = el("button", "act " + (allow ? "allow" : "deny"), label);
      button.type = "button";
      button.addEventListener("click", async () => { button.disabled = true; try { await api("/api/answer", { run: run.id, id: ask.id, allow }); } catch (e) { $status.textContent = String(e); } refresh(); });
      row.append(button);
    }
    box.append(row);
  }
  return box;
}
function feed(run) {
  const box = el("div", "feed"), who = state.filter[run.id];
  const head = el("h3", "", "Events");
  head.append(el("small", "", who ? who + " only · click it again for all" : (state.feeds[run.id] || []).length + " recorded"));
  box.append(head);
  const log = el("ul", "log");
  for (const e of (state.feeds[run.id] || []).filter((x) => !who || x.who === who || x.target === who).slice(-200)) {
    const detail = e.tool ? e.tool + (e.input ? " " + e.input : "") : (e.status || e.note || (e.target ? e.target + " " + (e.reason || "") : ""));
    const line = el("li");
    line.append(el("span", "t", clock(e.t) + " "), document.createTextNode(e.who + " " + e.kind + (detail ? " " + detail : "")));
    log.append(line);
  }
  box.append(log);
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  return box;
}
function rail(run) {
  const side = el("aside", "rail"), crew = crewList(run);
  side.setAttribute("aria-label", "Crew, approvals and events");
  if (run.asks.length) {
    const needs = el("section", "glass asking"), head = el("h3", "", "Needs your OK");
    head.append(el("small", "", run.asks.length + " waiting"));
    needs.append(head, asks(run));
    side.append(needs);
  }
  const box = el("section", "glass"), head = el("h3", "", "Crew"), body = el("div", "body");
  const working = crew.filter((m) => dotClass(m.doing) === "on").length, waiting = crew.filter((m) => dotClass(m.doing) === "wait").length;
  head.append(el("small", "", crew.length + " · " + working + " working" + (waiting ? " · " + waiting + " waiting" : "")));
  for (const m of crew) body.append(crewRow(run, m));
  box.append(head, body);
  const events = el("section", "glass");
  events.append(feed(run));
  side.append(box, events);
  return side;
}
let lastSignature = "";
function draw() {
  // Rebuild only when something visible changed: a rebuild every few seconds would swap the buttons out from under a click.
  const signature = JSON.stringify([state.runs, Object.keys(state.feeds).map((id) => [id, state.feeds[id].length]), state.filter, state.theme]);
  if (signature === lastSignature) return;
  lastSignature = signature;
  $runs.replaceChildren();
  state.scenes = [];
  if (!state.runs.length) { $runs.append(el("div", "empty", "No runs yet. Start one with /orchestrate in clyde.")); return; }
  for (const run of state.runs) {
    const section = el("section", "run");
    const head = el("div", "run-head");
    const spend = "$" + run.spend.usd.toFixed(4) + (run.spend.unpriced ? " + " + run.spend.unpriced + " unpriced" : "");
    head.append(el("h2", "", run.task || run.id), el("span", "chip " + run.status, run.status.replace("_", " ")), el("span", "chip", spend), el("span", "chip", run.id));
    section.append(head, el("div", "clyde", "Clyde: " + run.clyde));
    const body = el("div", "run-body");
    body.append(mapSection(run), rail(run));
    section.append(body);
    $runs.append(section);
  }
}
async function refresh() {
  try {
    state.runs = (await api("/api/state")).runs;
    $status.textContent = "";
  } catch (e) { $status.textContent = "disconnected: " + e.message; }
  draw();
  for (const run of state.runs) follow(run.id);
}
// One long poll per run: it answers as soon as the run records something new, so the page follows it live.
async function follow(id) {
  if (state.polling[id]) return;
  state.polling[id] = true;
  let after = (state.feeds[id] || []).length;
  while (state.polling[id]) {
    try {
      const data = await api("/api/events?run=" + encodeURIComponent(id) + "&after=" + after);
      if (data.events.length) {
        state.feeds[id] = (state.feeds[id] || []).concat(data.events);
        after = data.next;
        const fresh = (await api("/api/state?run=" + encodeURIComponent(id))).runs[0];
        const at = state.runs.findIndex((r) => r.id === id);
        if (fresh && at >= 0) state.runs[at] = fresh;
        draw();
      }
    } catch (e) { $status.textContent = "disconnected: " + e.message; await new Promise((r) => setTimeout(r, 2000)); }
  }
}
for (const key in THEMES) { const option = el("option", "", THEMES[key].name); option.value = key; $theme.append(option); }
if (THEMES[storedTheme()]) state.theme = storedTheme();
$theme.value = state.theme;
$theme.addEventListener("change", () => { state.theme = $theme.value; storeTheme(state.theme); draw(); });
refresh();
setInterval(refresh, 5000);   // picks up runs that start after the page opened
requestAnimationFrame(loop);
</script>
</body>
</html>
"""
