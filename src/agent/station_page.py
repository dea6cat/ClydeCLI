"""The station's page: one HTML string with its CSS and JS inline, and the pictures it shows from station_art/ (served from this machine: it works offline).

Three views of the same recorded state: the station (a top-down scene of rooms, furniture and crew: floors and walls drawn in code, furniture and crew from the Cozy Space Station sprites),
the member cards with their approvals, and the event feed.

The scene shows only what the run recorded. Rooms, furniture and hallways come from station_layout.py. Every movement of the
crew is a pure function of the recorded events and the clock: a worker walks to the furniture for a tool when it used that
tool, Clyde and Bonnie walk to a worker when a `check` event says they did, and a worker waits with a "?" while its approval
is pending. Nobody wanders: a crew member with nothing recorded stands at its place. A theme changes only the look and the words.

Everything else that moves (clouds, rain, searchlights, flickering lamps) is scenery: it says nothing about the run.

Everything is set with textContent and attributes, never parsed as markup: event text carries paths, commands and model output.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

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
.map svg { display: block; min-width: 640px; width: 100%; height: auto; max-height: calc(100vh - 150px); touch-action: none; cursor: grab; }   /* the whole station fits the window; letterboxing shows the map's own black */
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
@keyframes drive { from { transform: translateX(-120px); } to { transform: translateX(120px); } }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-40px); } }
.amb { transform-box: fill-box; }
.blink { animation: blink 1.4s steps(1) infinite; } .blink2 { animation: blink 1.1s steps(1) infinite .3s; } .blink3 { animation: blink 1.9s steps(1) infinite .7s; }
.flick { animation: flick 3.2s linear infinite; } .flick2 { animation: flick 4.1s linear infinite 1.1s; }
.drift { animation: drift 70s ease-in-out infinite alternate; } .drift2 { animation: drift 110s ease-in-out infinite alternate-reverse; }
.spin { animation: spin 60s linear infinite; transform-origin: center; transform-box: fill-box; } .spinr { animation: spinr 45s linear infinite; transform-origin: center; transform-box: fill-box; }
.rain { animation: rain 1.1s linear infinite; }
.puff { animation: puff 3s ease-out infinite; transform-origin: center; transform-box: fill-box; }
.sweep { animation: sweep 9s ease-in-out infinite alternate; }
.drive { animation: drive 24s linear infinite alternate; }
.twinkle { animation: twinkle 3s ease-in-out infinite; }
.mote { animation: mote 14s linear infinite; }
.bars { animation: bars 2.2s ease-in-out infinite; transform-origin: left center; transform-box: fill-box; }
.glint { animation: glint 5s linear infinite; }
@media (prefers-reduced-motion: reduce) {
  .portrait .lamp, .dot, .map .lane.waiting, .amb, .blink, .blink2, .blink3, .flick, .flick2, .drift, .drift2, .spin, .spinr, .rain, .puff, .sweep, .twinkle, .mote, .bars, .glint, .drive { animation: none !important; }
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
    pal: { bg: "#1d2b44", floorA: "#6b5545", floorB: "#5c4a3c", corr: "#3a2f28", grout: "#201710", wallL: "#2b565c", wallR: "#36737d", trim: "#c0773a", wood: "#3b484d", metal: "#c0773a", steel: "#7a8a8a",
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
// ---- geometry: tile space; the station is seen from above, one tile is T px ----------------------------------------------
const T = 44;
function pos(x, y) { return [x * T, y * T]; }
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
  for (const r of Object.values(p.rooms)) { x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y); x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.d); }
  const X0 = x0 * T - 120, Y0 = y0 * T - 110, X1 = x1 * T + 120, Y1 = y1 * T + 110, want = (Y1 - Y0) * 1.8, extra = Math.max(0, (want - (X1 - X0)) / 2);   // wide enough to fill a landscape window with the world around the station
  return [X0 - extra, Y0, X1 + extra, Y1];
}
// </geometry>

// ---- the station seen from above: a world, floors, walls, then the Cozy Space Station sprites (CC-BY 4.0, Bramble & Byte) for furniture and crew ----
const ART_V = "__ARTV__";   // changes whenever a picture does, so a browser never shows an old one from its cache
function artUrl(name) { return "/assets/" + name + ".png?v=" + ART_V; }
const SPR = __SPRITES__;   // each sprite's natural size [w, h], read from the files by the server
const WT = 14;   // wall thickness, px
const FX = { grain: "", grime: "", soft: "" };
function gradient(defs, id, stops, attrs) {
  const g = sv(attrs && attrs.r ? "radialGradient" : "linearGradient", attrs || { x1: 0, y1: 0, x2: 0, y2: 1 });
  g.setAttribute("id", id);
  for (const [off, color, op] of stops) g.append(sv("stop", { offset: off, "stop-color": color, "stop-opacity": op === undefined ? 1 : op }));
  defs.append(g);
  return "url(#" + id + ")";
}
function materials(defs, uid) {   // grain, grime and a soft shadow: filters the browser draws
  const make = (id, build) => { const f = sv("filter", { id, x: "-10%", y: "-10%", width: "120%", height: "120%", "color-interpolation-filters": "sRGB" }); build(f); defs.append(f); return "url(#" + id + ")"; };
  const noise = (freq, oct, seed, a, b) => (f) => f.append(sv("feTurbulence", { type: "fractalNoise", baseFrequency: freq, numOctaves: oct, seed, result: "n" }), sv("feColorMatrix", { in: "n", type: "matrix", values: "0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  " + a + " 0 0 0 " + b, result: "m" }), sv("feComposite", { in: "m", in2: "SourceAlpha", operator: "in" }));
  FX.grain = make("grain" + uid, noise("0.85", 2, 4, 1.6, -0.55));
  FX.grime = make("grime" + uid, noise("0.03", 3, 11, 2.4, -1.05));
  FX.soft = make("soft" + uid, (f) => f.append(sv("feGaussianBlur", { stdDeviation: 5 })));
}
const TINT = { city: "sepia(0.55) saturate(1.1) brightness(0.96)", steam: "sepia(0.7) saturate(1.3) hue-rotate(-12deg) brightness(0.92)", cyber: "hue-rotate(205deg) saturate(1.25) brightness(0.78) contrast(1.1)" };   // the same sprites, seen in each theme's light
function sprite(name, x, y, w, h, theme, extra) { return sv("image", { href: artUrl(name), x, y, width: w, height: h, style: "filter:" + TINT[theme], ...(extra || {}) }); }
function fit(name, bx, by, bw, bh, theme, extra) {   // a sprite as large as fits the box, bottom centre on the box's bottom edge
  const [w, h] = SPR[name], k = Math.min(bw * 1.25 / w, bh * 1.5 / h);   // a little larger than its box: the art has air around it
  return sprite(name, bx + bw / 2 - w * k / 2, by + bh - h * k, w * k, h * k, theme, extra);
}
function ground(svg, defs, B, pal, theme, uid) {   // what lies around the station: a street, a sea of cloud, a neon grid; scenery only
  const [x0, y0, x1, y1] = B, w = x1 - x0, h = y1 - y0, layer = sv("g", { "aria-hidden": "true" });
  layer.append(sv("rect", { x: x0, y: y0, width: w, height: h, fill: gradient(defs, "sky" + uid, [[0, pal.sky1], [1, theme === "steam" ? mixc(pal.sky2, "#10181c", 0.5) : pal.sky2]]) }));
  if (theme === "city") {
    for (let gx = Math.ceil(x0 / 352) * 352; gx < x1; gx += 352) layer.append(sv("rect", { x: gx - 18, y: y0, width: 36, height: h, fill: "#0b0e1a", opacity: 0.55 }), sv("line", { x1: gx, x2: gx, y1: y0, y2: y1, stroke: pal.neonB, "stroke-width": 1.5, "stroke-dasharray": "14 18", opacity: 0.4 }));
    for (let gy = Math.ceil(y0 / 352) * 352; gy < y1; gy += 352) layer.append(sv("rect", { x: x0, y: gy - 18, width: w, height: 36, fill: "#0b0e1a", opacity: 0.55 }), sv("line", { x1: x0, x2: x1, y1: gy, y2: gy, stroke: pal.neonB, "stroke-width": 1.5, "stroke-dasharray": "14 18", opacity: 0.4 }));
    for (let i = 0; i < 40; i++) { const lx = x0 + hash(91, i) * w, ly = y0 + hash(92, i) * h; layer.append(sv("circle", { cx: lx, cy: ly, r: 34, fill: gradient(defs, "sl" + uid + i, [[0, pal.lamp, 0.32], [1, pal.lamp, 0]], { r: "50%" }), class: "flick2 amb" }), sv("circle", { cx: lx, cy: ly, r: 3, fill: pal.lamp })); }
    for (let c = 0; c < 8; c++) { const cy = Math.ceil(y0 / 352) * 352 + Math.floor(hash(93, c) * 3) * 352, car = sv("g", { class: "drive amb", style: "animation-duration:" + (14 + hash(94, c) * 20).toFixed(0) + "s;animation-delay:-" + (hash(95, c) * 30).toFixed(0) + "s" }), cx = x0 + hash(96, c) * w; car.append(sv("circle", { cx, cy: cy - 5, r: 4, fill: "#fff6d8" }), sv("circle", { cx: cx + 16, cy: cy - 5, r: 4, fill: "#fff6d8" }), sv("circle", { cx: cx - 14, cy: cy - 5, r: 3, fill: "#ff4d4d" })); layer.append(car); }
  } else if (theme === "steam") {
    for (let i = 0; i < 70; i++) layer.append(sv("path", { d: "M" + (x0 + hash(81, i) * w).toFixed(0) + " " + (y0 + hash(82, i) * h).toFixed(0) + "q12 -8 24 0t24 0", stroke: "#9fd8c8", "stroke-width": 1.4, fill: "none", opacity: 0.22, class: "twinkle amb", style: "animation-delay:-" + (hash(83, i) * 3).toFixed(1) + "s" }));
    for (let i = 0; i < 7; i++) { const cloud = sv("g", { class: (i % 2 ? "drift" : "drift2") + " amb", style: "animation-delay:-" + (hash(87, i) * 60).toFixed(0) + "s" }), cx = x0 + hash(85, i) * w, cy = y0 + hash(86, i) * h; for (let k = 0; k < 5; k++) cloud.append(sv("ellipse", { cx: cx + (k - 2) * 60, cy: cy + (k % 2) * 14, rx: 90 + hash(88, i + k) * 40, ry: 28 + hash(89, i + k) * 14, fill: "#ffc58a", opacity: 0.16 })); layer.append(cloud); }
  } else {
    for (let gx = Math.ceil(x0 / 88) * 88; gx < x1; gx += 88) layer.append(sv("line", { x1: gx, x2: gx, y1: y0, y2: y1, stroke: pal.neonA, "stroke-width": 1, opacity: 0.14 }));
    for (let gy = Math.ceil(y0 / 88) * 88; gy < y1; gy += 88) layer.append(sv("line", { x1: x0, x2: x1, y1: gy, y2: gy, stroke: pal.neonB, "stroke-width": 1, opacity: 0.14 }));
    for (let i = 0; i < 12; i++) layer.append(sv("circle", { cx: x0 + hash(71, i) * w, cy: y0 + hash(72, i) * h, r: 40 + hash(73, i) * 60, fill: gradient(defs, "ng" + uid + i, [[0, i % 2 ? pal.neonA : pal.neonB, 0.22], [1, pal.neonA, 0]], { r: "50%" }), class: "flick2 amb" }));
    for (let i = 0; i < 90; i++) layer.append(sv("line", { x1: 0, y1: 0, x2: -4, y2: 24, transform: "translate(" + (x0 + hash(61, i) * w).toFixed(0) + " " + (y0 + hash(62, i) * h).toFixed(0) + ")", stroke: "#9fd8ff", "stroke-width": 1, opacity: 0.3, class: "rain amb", style: "animation-delay:-" + (hash(63, i) * 1.1).toFixed(2) + "s" }));
  }
  svg.append(layer);
}
function mixc(a, b, t) { const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)), x = p(a), y = p(b); return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join(""); }
function rect(layer, x, y, w, h, fill, extra) { const n = sv("rect", { x, y, width: w, height: h, fill, ...(extra || {}) }); layer.append(n); return n; }
function floors(layer, defs, p, pal, theme, uid) {
  for (const r of Object.values(p.rooms)) { const q = [r.x * T, r.y * T, r.w * T, r.d * T]; rect(layer, q[0] - 6, q[1] - 2, q[2] + 12, q[3] + 14, "#000", { opacity: 0.45, filter: FX.soft, rx: 10 }); }   // a soft shadow under each room
  const plates = (r, ri, a, b, grout, kind) => {
    const W = Math.round(r.w), D = Math.round(r.d), x = r.x * T, y = r.y * T;
    rect(layer, x, y, W * T, D * T, a);
    let alt = "", lines = "", rivets = "";
    for (let i = 0; i < W; i++) for (let j = 0; j < D; j++) {
      if ((i + j) % 2) alt += "M" + (x + i * T) + " " + (y + j * T) + "h" + T + "v" + T + "h-" + T + "Z";
      for (const [u, v] of [[0.12, 0.12], [0.88, 0.12], [0.12, 0.88], [0.88, 0.88]]) rivets += "M" + (x + (i + u) * T).toFixed(1) + " " + (y + (j + v) * T).toFixed(1) + "h0";
    }
    for (let i = 0; i <= W; i++) lines += "M" + (x + i * T) + " " + y + "v" + D * T;
    for (let j = 0; j <= D; j++) lines += "M" + x + " " + (y + j * T) + "h" + W * T;
    layer.append(sv("path", { d: alt, fill: b }), sv("path", { d: lines, stroke: grout, "stroke-width": 1.2, opacity: 0.5, fill: "none" }), sv("path", { d: lines, stroke: "#fff", "stroke-width": 1, opacity: 0.08, fill: "none", transform: "translate(1 1)" }), sv("path", { d: rivets, stroke: shade(grout, 55), "stroke-width": 2.4, "stroke-linecap": "round", opacity: 0.5, fill: "none" }));
    if (kind === "room") for (let k = 0; k < 2; k++) {   // a vent grating set into a plate
      const i = Math.floor(hash(ri + 31, k) * (W - 2)) + 1, j = Math.floor(hash(ri + 37, k) * (D - 2)) + 1, vx = x + i * T + 6, vy = y + j * T + 6;
      let slats = ""; for (let t = 1; t < 6; t++) slats += "M" + (vx + t * 5.4) + " " + vy + "v" + (T - 12);
      rect(layer, vx, vy, T - 12, T - 12, shade(grout, -30), { opacity: 0.8, rx: 2 }); layer.append(sv("path", { d: slats, stroke: shade(a, 25), "stroke-width": 1.6, opacity: 0.7, fill: "none" }));
    }
    rect(layer, x, y, W * T, D * T, "#000", { filter: FX.grain, opacity: 0.2 }); rect(layer, x, y, W * T, D * T, "#000", { filter: FX.grime, opacity: 0.24 });
  };
  p.corridors.forEach((c, ci) => plates({ x: c.x, y: c.y, w: c.w, d: c.d }, 90 + ci, shade(pal.floorA, theme === "cyber" ? 40 : -4), shade(pal.floorB, theme === "cyber" ? 28 : -14), pal.grout, "corridor"));
  Object.values(p.rooms).forEach((r, ri) => {
    plates(r, ri, pal.floorA, pal.floorB, pal.grout, "room");
    const x = r.x * T, y = r.y * T, w = r.w * T, d = r.d * T;
    rect(layer, x + 14, y + 14, w - 28, d - 28, "none", { stroke: "#000", "stroke-width": 4, opacity: 0.35 });
    rect(layer, x + 14, y + 14, w - 28, d - 28, "none", { stroke: theme === "cyber" ? pal.neonB : "#e8c020", "stroke-width": 3, "stroke-dasharray": "9 9", opacity: 0.5 });   // a hazard inlay inside the walls
  });
  const deck = p.rooms.deck, rug = [deck.x + 9, deck.y + 3.4, 8.4, 6.4];   // the deck's rug under the planning table
  rect(layer, rug[0] * T, rug[1] * T, rug[2] * T, rug[3] * T, pal.rug1, { rx: 6 }); rect(layer, rug[0] * T + 12, rug[1] * T + 12, rug[2] * T - 24, rug[3] * T - 24, "none", { stroke: pal.rug2, "stroke-width": 3, rx: 4, opacity: 0.8 });
  for (const r of Object.values(p.rooms)) {   // a runner down each doorway's aisle
    if (r.kind !== "bay" && r.kind !== "outbox") continue;
    const run = r.kind === "bay" ? [r.x + p.BW / 2 - 1.4, r.y + 0.4, 2.8, 8.4] : [r.x + 0.4, r.y + 2.1, 4.2, 1.8];
    rect(layer, run[0] * T, run[1] * T, run[2] * T, run[3] * T, pal.rug1, { opacity: 0.85, rx: 4 }); rect(layer, run[0] * T + 8, run[1] * T + 8, run[2] * T - 16, run[3] * T - 16, "none", { stroke: pal.rug2, "stroke-width": 2, opacity: 0.7, rx: 3 });
  }
  for (const [a, b] of p.edges) {   // a rail along each long side of a corridor, with a light every so often
    const A = pos(a[0], a[1]), Bq = pos(b[0], b[1]);
    layer.append(sv("line", { x1: A[0], y1: A[1], x2: Bq[0], y2: Bq[1], stroke: shade(pal.trim, -30), "stroke-width": 7 }), sv("line", { x1: A[0], y1: A[1], x2: Bq[0], y2: Bq[1], stroke: pal.trim, "stroke-width": 2.4 }));
    const len = Math.hypot(Bq[0] - A[0], Bq[1] - A[1]), steps = Math.max(1, Math.floor(len / 66));
    for (let t = 0; t <= steps; t++) { const k = steps ? t / steps : 0; layer.append(sv("circle", { cx: A[0] + (Bq[0] - A[0]) * k, cy: A[1] + (Bq[1] - A[1]) * k, r: 2.8, fill: theme === "cyber" ? pal.neonB : pal.lamp, class: "blink" + (t % 3 ? String(t % 3 + 1) : "") + " amb" })); }
  }
}
function doorsOf(p, r) {   // where a room's wall has a doorway: [side, from, to] in tiles along that side
  if (r.kind === "deck") return [["s", p.deckCx - 1, p.deckCx + 1], ["e", 5, 7]];
  if (r.kind === "bay") return [["n", r.x + p.BW / 2 - 1, r.x + p.BW / 2 + 1]];
  return [["w", 5, 7]];
}
function hazard(defs, uid) {   // diagonal yellow and black warning stripes, as a fill
  const pat = sv("pattern", { id: "haz" + uid, width: 16, height: 16, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
  pat.append(sv("rect", { x: 0, y: 0, width: 16, height: 16, fill: "#14110a" }), sv("rect", { x: 0, y: 0, width: 8, height: 16, fill: "#e8b820" }));
  defs.append(pat);
  return "url(#haz" + uid + ")";
}
function screenTD(g, x, y, w, h, pal, kind, seed, lit) {   // a display seen from above: a radar, a graph or lines of text
  const col = pal.screen, on = lit ? 1 : 0.7;
  rect(g, x, y, w, h, "#03060c", { rx: 2, stroke: shade(pal.metal, -10), "stroke-width": 1.2 });
  rect(g, x, y, w, h, col, { rx: 2, opacity: 0.1 * on });
  if (kind === 0) {
    const cx = x + w / 2, cy = y + h / 2, r = Math.min(w, h) * 0.38;
    g.append(sv("circle", { cx, cy, r, fill: "none", stroke: col, "stroke-width": 0.9, opacity: 0.8 * on }), sv("circle", { cx, cy, r: r * 0.5, fill: "none", stroke: col, "stroke-width": 0.8, opacity: 0.7 * on }), sv("line", { x1: cx - r, y1: cy, x2: cx + r, y2: cy, stroke: col, "stroke-width": 0.6, opacity: 0.6 * on }), sv("line", { x1: cx, y1: cy - r, x2: cx, y2: cy + r, stroke: col, "stroke-width": 0.6, opacity: 0.6 * on }));
    for (let b = 0; b < 3; b++) g.append(sv("circle", { cx: cx + (hash(seed, b) - 0.5) * r * 1.4, cy: cy + (hash(b, seed) - 0.5) * r * 1.4, r: 1.3, fill: "#fff", class: "blink" + (b ? String(b + 1) : "") + " amb" }));
  } else if (kind === 1) {
    let d = ""; for (let i = 0; i <= 8; i++) d += (i ? "L" : "M") + (x + 3 + i * (w - 6) / 8).toFixed(1) + " " + (y + h - 3 - hash(seed + i, i * 3) * (h - 6)).toFixed(1);
    g.append(sv("path", { d, fill: "none", stroke: col, "stroke-width": 1.2, opacity: on }));
  } else for (let l = 0; l < Math.max(2, Math.floor(h / 4.5)); l++) rect(g, x + 3, y + 3 + l * 4.4, (w - 6) * (0.3 + hash(seed, l) * 0.65), 1.4, l % 3 === 2 ? pal.accent : col, { opacity: 0.85 * on });
}
function consoleBanks(layer, defs, r, doors, pal, theme, uid) {   // modules of consoles along a room's top wall: screens, buttons and a glow, as on a ship's bridge
  const gaps = doors.filter((q) => q[0] === "n").map((q) => [q[1] * T - 14, q[2] * T + 14]);
  const y = r.y * T + WT / 2 + 1, step = 96;
  for (let mx = r.x * T + 22, i = 0; mx + step - 10 < (r.x + r.w) * T - 20; mx += step, i++) {
    if (gaps.some(([a, b]) => mx < b && mx + step - 8 > a)) continue;
    const seed = Math.round(r.x * 7 + r.y * 13) + i * 5;
    rect(layer, mx + 3, y + 3, step - 8, 34, "#000", { opacity: 0.45, filter: FX.soft });
    rect(layer, mx, y, step - 8, 34, shade(pal.dark, 14), { rx: 3, stroke: pal.trim, "stroke-width": 1, "stroke-opacity": 0.55 });
    rect(layer, mx, y, step - 8, 3, "#fff", { opacity: 0.1, rx: 1.5 });
    screenTD(layer, mx + 6, y + 5, 36, 18, pal, hash(seed, 1) > 0.5 ? 0 : 1, seed, true); screenTD(layer, mx + 46, y + 5, 36, 18, pal, hash(seed, 2) > 0.5 ? 2 : 1, seed + 3, true);
    for (let b = 0; b < 7; b++) layer.append(sv("circle", { cx: mx + 9 + b * 11, cy: y + 28, r: 2, fill: [pal.accent, pal.lamp, pal.screen, pal.bad][Math.floor(hash(seed + b, 5) * 4)], class: hash(seed, b) > 0.6 ? "blink" + (b % 3 ? String(b % 3 + 1) : "") + " amb" : "", opacity: 0.9 }));
    layer.append(sv("ellipse", { cx: mx + step / 2 - 4, cy: y + 46, rx: 52, ry: 22, fill: gradient(defs, "cb" + uid + i + Math.round(r.x), [[0, pal.screen, 0.2], [1, pal.screen, 0]], { r: "50%" }), class: "flick2 amb" }));
  }
}
function chairTD(g, cx, cy, pal, theme, rot) {   // an office chair seen from above: a seat, a curved back, five castors
  const tone = theme === "city" ? "#5a2b2b" : shade(pal.dark, 26), c = sv("g", { transform: "translate(" + cx + " " + cy + ") rotate(" + (rot || 0) + ")" });
  for (let k = 0; k < 5; k++) { const a = k / 5 * Math.PI * 2; c.append(sv("circle", { cx: Math.cos(a) * 10.5, cy: Math.sin(a) * 10.5, r: 2.2, fill: "#111" })); }
  c.append(sv("circle", { cx: 0, cy: 0, r: 9.5, fill: tone, stroke: "#000", "stroke-width": 1 }), sv("circle", { cx: 0, cy: 0, r: 6, fill: shade(tone, 12) }), sv("path", { d: "M-10 -6Q0 -17 10 -6", fill: "none", stroke: shade(tone, -25), "stroke-width": 5, "stroke-linecap": "round" }));
  g.append(c);
}
function holoTable(g, box, pal, theme, defs, id) {   // the planning table: a glowing holographic map in the steampunk and cyberpunk themes, a paper map on a wooden table in the city
  const [x, y, w, d] = box, cx = (x + w / 2) * T, cy = (y + d / 2) * T, rx = w * T / 2, ry = d * T / 2, cut = Math.min(rx, ry) * 0.45;
  const oct = [[cx - rx + cut, cy - ry], [cx + rx - cut, cy - ry], [cx + rx, cy - ry + cut], [cx + rx, cy + ry - cut], [cx + rx - cut, cy + ry], [cx - rx + cut, cy + ry], [cx - rx, cy + ry - cut], [cx - rx, cy - ry + cut]];
  g.append(sv("polygon", { points: pts(oct.map((q) => [q[0] + 4, q[1] + 6])), fill: "#000", opacity: 0.45, filter: FX.soft }), sv("polygon", { points: pts(oct), fill: theme === "city" ? shade(pal.wood, -10) : "#0c1118", stroke: pal.trim, "stroke-width": 4 }));
  const inner = oct.map((q) => [cx + (q[0] - cx) * 0.86, cy + (q[1] - cy) * 0.82]);
  g.append(sv("polygon", { points: pts(inner), fill: theme === "city" ? pal.paper : "#040a10", stroke: theme === "city" ? shade(pal.paper, -30) : pal.screen, "stroke-width": 1.6 }));
  const clip = sv("clipPath", { id: id + "tc" }); clip.append(sv("polygon", { points: pts(inner) })); defs.append(clip);
  const map = sv("g", { "clip-path": "url(#" + id + "tc)" }), line = theme === "city" ? shade(pal.paper, -35) : pal.screen;
  for (let i = -6; i <= 6; i++) map.append(sv("line", { x1: cx + i * 16, y1: cy - ry, x2: cx + i * 16, y2: cy + ry, stroke: line, "stroke-width": 0.7, opacity: theme === "city" ? 0.5 : 0.28 }));
  for (let j = -3; j <= 3; j++) map.append(sv("line", { x1: cx - rx, y1: cy + j * 16, x2: cx + rx, y2: cy + j * 16, stroke: line, "stroke-width": 0.7, opacity: theme === "city" ? 0.5 : 0.28 }));
  for (const k of [0.3, 0.55, 0.8]) map.append(sv("ellipse", { cx, cy, rx: rx * k, ry: ry * k, fill: "none", stroke: line, "stroke-width": 1, opacity: 0.6 }));
  if (theme !== "city") { const sweep = sv("g", { class: "spin amb", style: "transform-origin:" + cx + "px " + cy + "px" }); sweep.append(sv("line", { x1: cx, y1: cy, x2: cx + rx * 0.85, y2: cy, stroke: pal.screen, "stroke-width": 2, opacity: 0.8 }), sv("path", { d: "M" + cx + " " + cy + "L" + (cx + rx * 0.85) + " " + cy + "A" + rx * 0.85 + " " + ry * 0.85 + " 0 0 0 " + (cx + rx * 0.85 * Math.cos(0.7)) + " " + (cy - ry * 0.85 * Math.sin(0.7)) + "Z", fill: pal.screen, opacity: 0.18 })); map.append(sweep); }
  for (let b = 0; b < 5; b++) map.append(sv("circle", { cx: cx + (hash(b, 17) - 0.5) * rx * 1.3, cy: cy + (hash(17, b) - 0.5) * ry * 1.3, r: 3, fill: theme === "city" ? pal.bad : "#fff", class: "blink" + (b % 3 ? String(b % 3 + 1) : "") + " amb" }));
  g.append(map);
  if (theme !== "city") g.append(sv("ellipse", { cx, cy, rx: rx * 1.5, ry: ry * 1.6, fill: gradient(defs, id + "hg", [[0, pal.screen, 0.3], [1, pal.screen, 0]], { r: "50%" }), class: "flick2 amb" }));
  for (const [dx, dy, rot] of [[-rx * 0.6, -ry - 16, 180], [rx * 0.6, -ry - 16, 180], [-rx * 0.6, ry + 16, 0], [rx * 0.6, ry + 16, 0]]) chairTD(g, cx + dx, cy + dy, pal, theme, rot);
}
function cableTD(g, x0, y0, x1, y1, pal, theme) {   // a lead on the floor from a machine to the wall: bends at right angles
  const mid = (y0 + y1) / 2, d = "M" + x0.toFixed(0) + " " + y0.toFixed(0) + "V" + mid.toFixed(0) + "H" + x1.toFixed(0) + "V" + y1.toFixed(0);
  g.append(sv("path", { d, fill: "none", stroke: "#000", "stroke-width": 5.5, opacity: 0.5, "stroke-linejoin": "round" }), sv("path", { d, fill: "none", stroke: theme === "cyber" ? pal.neonA : "#2b2b30", "stroke-width": 3, "stroke-linejoin": "round" }), sv("path", { d, fill: "none", stroke: "#fff", "stroke-width": 0.8, opacity: 0.18, "stroke-linejoin": "round" }));
}
function walls(layer, defs, p, pal, theme, uid) {
  const haz = hazard(defs, uid);
  for (const r of Object.values(p.rooms)) {
    const doors = doorsOf(p, r), x = r.x * T, y = r.y * T, w = r.w * T, d = r.d * T, runs = [];
    const cut = (side, from, to, fixed) => {   // the stretches of one side that are wall, once the doorways are taken out
      const gaps = doors.filter((q) => q[0] === side).map((q) => [q[1] * T, q[2] * T]).sort((a, b) => a[0] - b[0]);
      let at = from; for (const [a, b] of gaps.concat([[to, to]])) { if (a > at) runs.push(side === "n" || side === "s" ? [at, fixed - WT / 2, a - at, WT] : [fixed - WT / 2, at, WT, a - at]); at = b; }
    };
    cut("n", x - WT / 2, x + w + WT / 2, y); cut("s", x - WT / 2, x + w + WT / 2, y + d); cut("w", y + WT / 2, y + d - WT / 2, x); cut("e", y + WT / 2, y + d - WT / 2, x + w);
    for (const q of runs) rect(layer, q[0] + 4, q[1] + 6, q[2], q[3], "#000", { opacity: 0.45, filter: FX.soft });
    consoleBanks(layer, defs, r, doors, pal, theme, uid);
    for (const q of runs) {
      const horiz = q[2] > q[3], len = horiz ? q[2] : q[3];
      rect(layer, q[0], q[1], q[2], q[3], pal.wallL, { stroke: "#000", "stroke-width": 1.4, "stroke-opacity": 0.6 });
      rect(layer, q[0], q[1], horiz ? q[2] : 3, horiz ? 3 : q[3], "#fff", { opacity: 0.2 });   // the lit edge
      rect(layer, horiz ? q[0] : q[0] + q[2] - 3, horiz ? q[1] + q[3] - 3 : q[1], horiz ? q[2] : 3, horiz ? 3 : q[3], "#000", { opacity: 0.3 });   // the shaded edge
      let seams = "", bolts = "";
      for (let t = 33; t < len - 8; t += 66) { seams += horiz ? "M" + (q[0] + t) + " " + q[1] + "v" + q[3] : "M" + q[0] + " " + (q[1] + t) + "h" + q[2]; bolts += horiz ? "M" + (q[0] + t - 6) + " " + (q[1] + 3.5) + "h0M" + (q[0] + t + 6) + " " + (q[1] + 3.5) + "h0" : "M" + (q[0] + 3.5) + " " + (q[1] + t - 6) + "v0M" + (q[0] + 3.5) + " " + (q[1] + t + 6) + "v0"; }
      layer.append(sv("path", { d: seams, stroke: "#000", "stroke-width": 1.2, opacity: 0.45, fill: "none" }), sv("path", { d: bolts, stroke: shade(pal.wallL, 45), "stroke-width": 2.2, "stroke-linecap": "round", fill: "none", opacity: 0.8 }));
      if (theme === "city") for (let t = 20; t < len - 12; t += 66) { if (horiz) rect(layer, q[0] + t, q[1] + 5, 22, 4, pal.win, { opacity: 0.85 }); else rect(layer, q[0] + 5, q[1] + t, 4, 22, pal.win, { opacity: 0.85 }); }
      else if (theme === "steam") for (let t = 33; t < len - 8; t += 66) layer.append(sv("circle", { cx: horiz ? q[0] + t : q[0] + WT / 2, cy: horiz ? q[1] + WT / 2 : q[1] + t, r: 4.2, fill: "#7fe0d0", stroke: pal.metal, "stroke-width": 2 }));
      else for (let t = 14; t < len - 8; t += 66) { if (horiz) rect(layer, q[0] + t, q[1] + 5, 34, 3, pal.neonB, { opacity: 0.9, class: "blink2 amb" }); else rect(layer, q[0] + 5, q[1] + t, 3, 34, pal.neonB, { opacity: 0.9, class: "blink2 amb" }); }
    }
    for (const [side, a, b] of doors) {   // a door: posts, a warning-striped threshold and a lamp over it
      const A = side === "n" || side === "s" ? [a * T, (side === "n" ? y : y + d)] : [(side === "w" ? x : x + w), a * T], Bq = side === "n" || side === "s" ? [b * T, A[1]] : [A[0], b * T], horiz = side === "n" || side === "s";
      rect(layer, horiz ? A[0] : A[0] - 11, horiz ? A[1] - 11 : A[1], horiz ? Bq[0] - A[0] : 22, horiz ? 22 : Bq[1] - A[1], haz, { opacity: 0.88, stroke: "#000", "stroke-width": 1.2 });
      for (const q of [A, Bq]) layer.append(sv("rect", { x: q[0] - 8, y: q[1] - 8, width: 16, height: 16, rx: 3, fill: pal.trim, stroke: "#000", "stroke-width": 1.4 }), sv("circle", { cx: q[0], cy: q[1], r: 3, fill: "#000", opacity: 0.55 }));
      layer.append(sv("circle", { cx: (A[0] + Bq[0]) / 2, cy: (A[1] + Bq[1]) / 2, r: 24, fill: gradient(defs, "dl" + uid + side + Math.round(x + y), [[0, theme === "cyber" ? pal.neonB : pal.lamp, 0.4], [1, pal.lamp, 0]], { r: "50%" }), class: "flick2 amb" }), sv("circle", { cx: (A[0] + Bq[0]) / 2, cy: (A[1] + Bq[1]) / 2, r: 4, fill: theme === "cyber" ? pal.neonB : pal.lamp, class: "flick amb" }));
    }
  }
}
function lightPools(layer, defs, p, pal, theme, uid) {   // ceiling lights: a soft pool of light on the floor under each, so the rooms are not evenly lit
  let n = 0;
  for (const r of Object.values(p.rooms)) for (let i = 3; i < r.w; i += 6) for (let j = 3; j < r.d; j += 6) {
    layer.append(sv("circle", { cx: (r.x + i) * T, cy: (r.y + j) * T, r: 190, fill: gradient(defs, "lp" + uid + n++, [[0, theme === "cyber" ? pal.neonB : pal.lamp, theme === "cyber" ? 0.13 : 0.18], [1, pal.lamp, 0]], { r: "50%" }) }), sv("circle", { cx: (r.x + i) * T, cy: (r.y + j) * T, r: 5, fill: "#fff", opacity: 0.5 }), sv("circle", { cx: (r.x + i) * T, cy: (r.y + j) * T, r: 9, fill: "none", stroke: "#000", "stroke-width": 1.5, opacity: 0.5 }));
  }
}
const FAMILY_SPRITE = { read: "file-cabinet", write: "writer-desk", shell: "console", web: "comm-booth", mcp: "server-rack", other: "crate", approvals: "dual-monitor-desk", ledger: "counter", desk: "desk", table: "meeting-table", crate: "crate" };
const PLANTS = ["plant-fern", "plant-ficus", "plant-flowering", "plant-monstera", "plant-snake-plant"];
function furnitureSprite(f, pal, theme, now, defs, uid) {
  const g = sv("g", {}), [x, y, w, d] = f.box, o = f.obj, id = "fg" + uid + f.family + Math.round(x * 3 + y * 5), fresh = o && o.last && now - o.last < 4;
  const bx = x * T, by = y * T, bw = w * T, bh = d * T;
  if (f.family === "table") { holoTable(g, f.box, pal, theme, defs, id); return g; }
  if (f.room && f.family !== "crate" && y - f.room.y < 3.2) cableTD(g, bx + bw * 0.35, by + bh * 0.3, bx + bw * 0.35 + (hash(Math.round(x * 5), Math.round(y * 3)) - 0.5) * 60, f.room.y * T + WT + 34, pal, theme);   // a lead up to the console bank on the wall
  rect(g, bx + 4, by + bh * 0.55, bw - 4, bh * 0.5, "#000", { opacity: 0.4, filter: FX.soft, rx: 8 });
  g.append(fit(FAMILY_SPRITE[f.family] || "crate", bx, by, bw, bh + 6, theme));
  if (f.family === "desk" || f.family === "approvals") chairTD(g, bx + bw / 2, by + bh + 22, pal, theme, 0);   // someone sits at a desk
  if (fresh && (f.family === "write" || f.family === "shell" || f.family === "read")) g.append(sv("ellipse", { cx: bx + bw / 2, cy: by + bh / 2, rx: bw * 0.9, ry: bh * 0.9, fill: gradient(defs, id + "w", [[0, pal.screen, 0.35], [1, pal.screen, 0]], { r: "50%" }), class: "flick amb" }));
  if (f.family === "approvals" && o && o.pending) g.append(sv("circle", { cx: bx + bw / 2, cy: by + bh / 2, r: 46, fill: gradient(defs, id + "p", [[0, pal.wait, 0.5], [1, pal.wait, 0]], { r: "50%" }), class: "flick2 amb" }));
  if (f.lane && f.laneState) { const on = f.laneState === "lit"; g.append(sv("circle", { cx: bx + bw - 10, cy: by + 12, r: 5, fill: on ? pal.accent : shade(pal.dark, 20), stroke: "#000", "stroke-width": 1, class: on ? "flick amb" : "" })); }   // the handoff tray: lit once that handoff was recorded
  if (f.family === "crate" && o && o.state === "landed") g.append(sv("circle", { cx: bx + bw / 2, cy: by + bh / 2, r: 56, fill: gradient(defs, id + "l", [[0, pal.accent, 0.55], [1, pal.accent, 0]], { r: "50%" }), class: "flick amb" }));
  if (fresh) g.append(sv("rect", { x: bx - 6, y: by - 6, width: bw + 12, height: bh + 12, rx: 10, fill: "none", stroke: pal.accent, "stroke-width": 3, opacity: 0.85, class: "blink amb" }));
  if (o && f.family !== "crate") {   // a count plate: how often it was used; amber dot: it asked you; red dot: denied or failed
    const n = f.family === "ledger" ? "$" + o.usd.toFixed(3) : f.family === "approvals" ? o.asked : o.used, cx = bx + bw / 2, cy = by - 4;
    g.append(sv("rect", { x: cx - 17, y: cy - 9, width: 34, height: 15, rx: 4, fill: pal.dark, stroke: pal.trim, "stroke-width": 1, opacity: 0.94 }), sv("text", { x: cx, y: cy + 2, class: "badge-n", fill: pal.ink, stroke: "none" }, String(n)));
    if (o.pending || (o.asked && f.family !== "approvals")) g.append(sv("circle", { cx: cx - 20, cy: cy - 7, r: 4.5, fill: pal.wait, stroke: "#000", "stroke-width": 1 }));
    if (o.denied || o.failed) g.append(sv("circle", { cx: cx + 20, cy: cy - 7, r: 4.5, fill: pal.bad, stroke: "#000", "stroke-width": 1 }));
  }
  return g;
}
function propSprite(kind, x, y, pal, theme, defs, uid, size) {   // scenery: it says nothing about the run
  const g = sv("g", {}), px = x * T, py = y * T, id = "pr" + uid + kind + Math.round(x * 3 + y * 7);
  if (kind === "plant") g.append(fit(PLANTS[Math.floor(hash(Math.round(x * 3), Math.round(y * 5)) * PLANTS.length)], px - 26, py - 36, 62, 62, theme));
  else if (kind === "lamp") g.append(sv("circle", { cx: px, cy: py, r: 56, fill: gradient(defs, id, [[0, pal.lamp, 0.4], [1, pal.lamp, 0]], { r: "50%" }), class: "flick2 amb" }), sv("circle", { cx: px, cy: py, r: 6, fill: pal.lamp, stroke: "#000", "stroke-width": 1.2 }));
  else if (kind === "crates") g.append(fit("crate", px - 6, py - 30, 54, 54, theme), fit("crate", px + 34, py - 18, 44, 44, theme));
  else if (kind === "tank") g.append(fit("water-cooler", px - 10, py - 40, 36, 66, theme));
  else if (kind === "bookcase") { const len = (size || 3.4) * T, n = Math.max(1, Math.floor(len / 40)); for (let i = 0; i < n; i++) g.append(fit("bookshelf", px - 6, py + i * (len / n), 50, len / n + 14, theme)); }
  else if (kind === "coat") g.append(fit("clothes-rack", px - 18, py - 40, 56, 56, theme));
  return g;
}
const CREW = __CREW__;   // each person's frames: person -> animation -> direction -> frame count (station_art/<person>-<animation>-<direction>-<nn>.png), filled in by the server
const FIGURE = {   // each person's idle picture facing south: [picture width, height, then the left, top, right and bottom of the figure in it]
  clyde: [96, 96, 34, 29, 61, 88], bonnie: [96, 96, 34, 29, 61, 88], master: [96, 96, 33, 28, 62, 88], advisor: [96, 96, 34, 29, 61, 88],
  newsboy: [96, 96, 34, 30, 61, 88], mechanic: [96, 96, 34, 30, 61, 88], clerk: [96, 96, 33, 33, 61, 88] };
const CREW_H = 80;   // every figure is drawn this tall, standing on its spot
const CREW_NAMED = ["clyde", "bonnie", "master", "advisor"], WORKER_LOOKS = ["newsboy", "mechanic", "clerk"];   // each worker is one of three people, by number
function crewPack(name) { return CREW_NAMED.includes(name) ? name : WORKER_LOOKS[(parseInt(number(name) || "1", 10) - 1) % WORKER_LOOKS.length]; }
function crewBox(pack) { const [w, h, x0, y0, x1, y1] = FIGURE[pack], k = CREW_H / (y1 - y0 + 1); return { w: w * k, h: h * k, x: -(x0 + x1 + 1) / 2 * k, y: -(y1 + 1) * k }; }
function headingDir(dx, dy) { const names = ["east", "south-east", "south", "south-west", "west", "north-west", "north", "north-east"]; return names[((Math.round(Math.atan2(dy, dx) * 4 / Math.PI) % 8) + 8) % 8]; }
function crewFrame(pack, anim, dir, f) { const n = CREW[pack][anim][dir] || 1; return { file: pack + "-" + anim + "-" + dir + "-" + String(f % n).padStart(2, "0"), n }; }
const PRELOADED = {};
function preload(pack, anim, dir) {   // fetch a whole animation the first time it is needed, so the next frame is already there
  const key = pack + anim + dir;
  if (PRELOADED[key]) return;
  PRELOADED[key] = true;
  for (let f = 0; f < crewFrame(pack, anim, dir, 0).n; f++) new Image().src = artUrl(crewFrame(pack, anim, dir, f).file);
}
function personItem(name, role, theme) {
  const pack = crewPack(name), box = crewBox(pack), g = sv("g", { class: "sprite", "data-sprite": name }), body = sv("g", {}), carry = sv("g", { style: "display:none" });
  const img = sv("image", { x: box.x, y: box.y, width: box.w, height: box.h, "image-rendering": "pixelated" });
  img.setAttribute("href", artUrl(crewFrame(pack, "idle", "south", 0).file));
  body.append(img);
  carry.append(sv("rect", { x: -13, y: -CREW_H * 0.5, width: 26, height: 18, rx: 2, fill: "#a8782f", stroke: "#0b0b12", "stroke-width": 1.6 }), sv("rect", { x: -2, y: -CREW_H * 0.5, width: 4, height: 18, fill: "#d8b060" }));
  const shadowEl = sv("ellipse", { cx: 0, cy: -2, rx: 16, ry: 6, fill: "#000", opacity: 0.32 }), tag = sv("g", { transform: "translate(0 " + (-CREW_H - 8) + ")" }), bubble = sv("g", { transform: "translate(0 " + (-CREW_H - 28) + ")" });
  tag.append(sv("rect", { x: -(name.length * 3.6 + 6), y: -9, width: name.length * 7.2 + 12, height: 14, rx: 3, fill: "#000", opacity: 0.6 }), sv("text", { y: 3, class: "name", fill: "#fff", stroke: "#000" }, name));
  g.append(shadowEl, body, carry, tag, bubble, sv("title", {}, name));
  const person = { name, role, g, body, carry, bubble, pack, dir: "south", shown: "", bubbleKind: null, title: g.lastChild };
  person.show = (dir, anim, f) => {   // set the picture for this pose; nothing happens when it is already showing
    const fr = crewFrame(pack, anim, dir, f);
    if (person.shown === fr.file) return;
    preload(pack, anim, dir);
    person.shown = fr.file;
    img.setAttribute("href", artUrl(fr.file));
  };
  return person;
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
  materials(defs, uid);
  ground(svg, defs, B, pal, theme, uid);
  const floorLayer = sv("g", {}), laneLayer = sv("g", {}), wallLayer = sv("g", {}), items = sv("g", {}), signs = sv("g", {});
  floors(floorLayer, defs, p, pal, theme, uid);
  lightPools(floorLayer, defs, p, pal, theme, uid);
  const order = { dark: 0, lit: 1, waiting: 2, refused: 3 };   // the strongest state is drawn last where lanes share a corridor
  const laneColor = { dark: pal.dim, lit: pal.accent, waiting: pal.wait, refused: pal.bad }, described = [];
  for (const lane of layout.hallways.slice().sort((a, b) => order[a.state] - order[b.state])) {
    const path = p.lanes[lane.id] || p.lanes[lane.kind];
    if (!path) continue;   // the two inside the deck are shown as a lamp on the desk instead
    const proj = path.map((q) => pos(q[0], q[1])), color = laneColor[lane.state];
    const line = sv("polyline", { points: pts(proj), class: "lane " + lane.state, stroke: color, "stroke-width": lane.state === "dark" ? 3 : 5, "stroke-linejoin": "round",
      "stroke-dasharray": lane.state === "dark" ? "3 11" : lane.state === "waiting" ? "14 10" : "none", opacity: lane.state === "dark" ? 0.6 : 0.95 });
    line.append(sv("title", {}, laneTitle(lane, words)));
    laneLayer.append(line);
    if (lane.state === "lit") laneLayer.append(sv("polyline", { points: pts(proj), class: "lane", stroke: color, "stroke-width": 14, opacity: 0.14, "stroke-linejoin": "round" }));
    if (lane.state !== "dark") {   // chevrons along it, pointing the way the work goes
      const toward = lane.from === "deck" || lane.kind === "landing" ? 1 : -1;   // task and landing go away from the deck; results and approvals come back
      for (let i = 1; i < path.length; i++) {
        const a = path[i - 1], b = path[i], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        for (let t = 1; t < len; t += 1.6) {
          const c = pos(a[0] + (b[0] - a[0]) * t / len, a[1] + (b[1] - a[1]) * t / len), ux = (b[0] - a[0]) / len * toward, uy = (b[1] - a[1]) / len * toward;
          laneLayer.append(sv("polygon", { points: pts([[c[0] + ux * 8, c[1] + uy * 8], [c[0] - ux * 5 - uy * 6, c[1] - uy * 5 + ux * 6], [c[0] - ux * 5 + uy * 6, c[1] - uy * 5 - ux * 6]]), fill: color, opacity: 0.9, class: lane.state === "waiting" ? "blink amb" : "" }));
        }
      }
    }
  }
  for (const lane of layout.hallways) described.push(laneTitle(lane, words));
  walls(wallLayer, defs, p, pal, theme, uid);
  for (const r of Object.values(p.rooms)) {   // each room's sign, on its top wall
    const title = r.kind === "deck" ? words.deck : r.kind === "outbox" ? words.outbox : words.bay + " " + number(r.id), half = title.length * 3.6 + 12, cx = r.x * T + 20 + half, cy = r.y * T - 22;
    signs.append(sv("rect", { x: cx - half, y: cy - 10, width: half * 2, height: 19, rx: 3, fill: pal.dark, stroke: pal.trim, "stroke-width": 2 }), sv("text", { x: cx, y: cy + 4, class: "sign", fill: pal.ink, stroke: "none" }, title));
  }
  const dyn = [];   // everything that can pass in front of or behind something else: furniture, scenery and crew, back to front
  for (const f of p.furniture) {
    if (f.lane) { const l = layout.hallways.find((h) => h.id === f.lane); f.laneState = l ? l.state : null; if (l) described.push(laneTitle(l, words)); }
    const g = furnitureSprite(f, pal, theme, now, defs, uid), tip = f.obj && f.obj.tools ? words[f.family] + ": " + f.obj.tools.join(", ") + " · used " + f.obj.used + " · asked " + f.obj.asked + " (allowed " + f.obj.allowed + ", denied " + f.obj.denied + ")" + (f.obj.failed ? " · failed " + f.obj.failed : "")
      : f.family === "approvals" ? words.approvals + ": asked " + f.obj.asked + " · allowed " + f.obj.allowed + " · denied " + f.obj.denied + " · waiting " + f.obj.pending
      : f.family === "ledger" ? words.ledger + ": $" + f.obj.usd.toFixed(4) + (f.obj.unpriced ? " + " + f.obj.unpriced + " unpriced" : "")
      : f.family === "crate" ? words.outbox + ": " + f.obj.state : f.lane && f.laneState ? words[f.lane] + " tray: " + { dark: "not used yet", lit: "used", waiting: "waiting", refused: "refused" }[f.laneState] : (words[f.family] || f.family);
    g.append(sv("title", {}, tip));
    if (f.obj) described.push((f.room.kind === "bay" ? words.bay + " " + number(f.room.id) : f.room.kind === "deck" ? words.deck : words.outbox) + ": " + tip);
    dyn.push({ el: g, depth: () => f.box[1] + f.box[3] });
  }
  for (const [kind, x, y, size] of p.props) dyn.push({ el: propSprite(kind, x, y, pal, theme, defs, uid, size), depth: () => y + (kind === "bookcase" ? size || 1 : 0.5) });
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
    dyn.push({ el: person.g, person, depth: () => (person.at ? person.at[1] : 0) });
  }
  svg.append(floorLayer, laneLayer, wallLayer, items, signs);
  svg.append(rect(sv("g", { "aria-hidden": "true", "pointer-events": "none" }), x0, y0, x1 - x0, y1 - y0, gradient(defs, "vig" + uid, [[0.6, "#000", 0], [1, "#000", 0.55]], { r: "75%" })).parentNode);
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
  const { p, pal } = scene;
  for (const person of scene.people) {
    const name = person.name, home = p.homes[name], trips = scene.trips[name], doing = person.card.doing || "";
    const s = trips ? walkerState(trips, home, now) : { pos: home, dir: [0, 0], pose: "idle", carry: null, bubble: null };
    let pose = s.pose;
    if (pose === "idle" && /using|working|splitting|reviewing|writing the report|tasks handed/.test(doing) && !/waiting/.test(doing)) pose = "work";
    const moving = pose === "walk";
    if (!moving && s.carry) pose = "carry";
    if (Math.abs(s.dir[0]) > 0.05 || Math.abs(s.dir[1]) > 0.05) person.dir = headingDir(s.dir[0], s.dir[1]);   // they face the way they walk, and keep it when they stop
    const typing = !moving && (pose === "work" || pose === "check");   // a crew member using a tool taps at the keys
    person.show(person.dir, moving ? "walk" : typing ? "type" : "idle", Math.floor(now * (moving ? 10 : typing ? 8 : 5)));
    let dy = 0, rot = 0, squash = 1;
    if (!REDUCED) {
      if (moving) { dy = -Math.abs(Math.sin(now * 13)) * 4; rot = Math.sin(now * 13) * 3; }
      else if (pose === "work" || pose === "check") { dy = -Math.abs(Math.sin(now * 9)) * 1.5; rot = Math.sin(now * 9) * 2; }
      else squash = 1 + Math.sin(now * 2.2) * 0.012;
    }
    const at = pos(s.pos[0], s.pos[1]);
    person.at = s.pos;
    person.g.setAttribute("transform", "translate(" + at[0].toFixed(1) + " " + at[1].toFixed(1) + ")");
    person.body.setAttribute("transform", "translate(0 " + dy.toFixed(1) + ") rotate(" + rot.toFixed(1) + ") scale(1 " + squash.toFixed(3) + ")");
    person.carry.style.display = pose === "carry" ? "" : "none";
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
  box.append(el("span", "", "Furniture is a capability the member was given; its plate counts how often it was used. Crew walk only when something was recorded: a worker to the furniture for a tool it used, Clyde with a task or an approval request, Bonnie to collect a result. Clouds, rain, lamps and neon are only scenery. Drag to pan, Ctrl-scroll or the + and − keys to zoom. Furniture art: \"Cozy Space Station\" by Bramble & Byte (CC-BY 4.0). Crew: drawn for this station."));
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
function portrait(name, doing) {   // the same person as in the scene, in a small well with a lamp
  const pack = crewPack(name), [w, h, x0, y0, x1, y1] = FIGURE[pack], vh = y1 - y0 + 6, vw = vh * 0.55, svg = sv("svg", { viewBox: [(x0 + x1 + 1) / 2 - vw / 2, y0 - 3, vw, vh].join(" "), "aria-hidden": "true" });
  const img = sv("image", { x: 0, y: 0, width: w, height: h, "image-rendering": "pixelated" });
  img.setAttribute("href", artUrl(crewFrame(pack, "idle", "south", 0).file));
  svg.append(img);
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


_CREW_FRAME = re.compile(r"(clyde|bonnie|master|advisor|newsboy|mechanic|clerk)-(idle|walk|type)-([a-z\-]+)-(\d+)")


def _crew_index() -> dict[str, dict[str, dict[str, int]]]:
    """Which frames each crew pack has: pack -> animation -> direction -> how many, read from the file names in station_art/."""
    index: dict[str, dict[str, dict[str, int]]] = {}
    for file in sorted((Path(__file__).parent / "station_art").glob("*.png")):
        if m := _CREW_FRAME.fullmatch(file.stem):
            counts = index.setdefault(m[1], {}).setdefault(m[2], {})
            counts[m[3]] = max(counts.get(m[3], 0), int(m[4]) + 1)
    return index


def _art_version() -> str:
    """A short fingerprint of the pictures in station_art/ (names and sizes), used to refresh a browser's cached copies."""
    files = sorted((Path(__file__).parent / "station_art").glob("*.png"))
    return hashlib.sha256("|".join(f"{f.name}:{f.stat().st_size}" for f in files).encode()).hexdigest()[:10]


def _sprite_sizes() -> dict[str, list[int]]:
    """The natural size [width, height] of each sprite in station_art/, read from its PNG header, so the page can fit it to a box."""
    sizes = {}
    for file in sorted((Path(__file__).parent / "station_art").glob("*.png")):
        if _CREW_FRAME.fullmatch(file.stem):
            continue
        head = file.read_bytes()[:24]
        sizes[file.stem] = list(struct.unpack(">II", head[16:24]))
    return sizes


PAGE = PAGE.replace("__ARTV__", _art_version()).replace("__SPRITES__", json.dumps(_sprite_sizes(), separators=(",", ":"))).replace("__CREW__", json.dumps(_crew_index(), separators=(",", ":")))
