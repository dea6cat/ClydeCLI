"""The station's page: one HTML string with its CSS and JS inline, and the pictures it shows from station_art/ (served from this machine: it works offline).

Three views of the same recorded state: the station (a floating island seen from a corner: rooms, hallways, furniture and crew, in generated pixel art),
the member cards with their approvals, and the event feed.

The scene shows only what the run recorded. Rooms, furniture and hallways come from station_layout.py. Every movement of the
crew is a pure function of the recorded events and the clock: a worker walks to the furniture for a tool when it used that
tool, Clyde and Bonnie walk to a worker when a `check` event says they did, and a worker waits with a "?" while its approval
is pending. Nobody else wanders: a crew member with nothing recorded stands at its place. The one exception is scenery: after QUIET seconds in which
nothing at all was recorded, Clyde and Bonnie go to the bar together and now and then look into a workshop; any record ends it.

Everything else that moves (clouds, flickering lamps, the walks to the bar) is scenery: it says nothing about the run.

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
main { margin: 0; padding: 0; }
/* The scene is the page: each run fills the window, and the title bar, the run's line, the legend and the rail float over it. */
header { position: fixed; top: 10px; left: 10px; z-index: 6; display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-radius: 12px; max-width: calc(100vw - 20px);
  background: color-mix(in srgb, var(--panel) 82%, transparent); border: 1px solid color-mix(in srgb, var(--ink) 14%, transparent); backdrop-filter: blur(8px); box-shadow: 0 6px 22px rgba(0,0,0,.28); }
h1 { font-size: 16px; margin: 0; white-space: nowrap; }
header .spacer { display: none; }
header .tool { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; white-space: nowrap; }
header .tool[aria-pressed="true"] { border-color: var(--accent); }
header .tool.alert { border-color: var(--warn); color: var(--warn); animation: pulse 1.2s ease-in-out infinite; }
header .link { display: inline-flex; align-items: center; gap: 6px; }
header .link i { width: 8px; height: 8px; border-radius: 50%; background: var(--idle); }
header .link.live i { background: var(--accent); animation: pulse 1.2s ease-in-out infinite; } header .link.down i { background: var(--bad); } header .link.down { color: var(--bad); border-color: var(--bad); }
#counts { font-size: 13px; white-space: nowrap; }
.needs { margin-top: 8px; padding-top: 8px; border-top: 1px solid color-mix(in srgb, var(--ink) 14%, transparent); }
.needs-head { font-size: 11px; letter-spacing: 2px; text-transform: uppercase; font-weight: 700; color: var(--warn); margin-bottom: 4px; }
.need { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; padding: 3px 0; }
.need i { width: 8px; height: 8px; border-radius: 50%; background: var(--warn); flex: none; } .need.failure i { background: var(--bad); }
.need .age { color: var(--muted); font-size: 12px; }
.need .grow { flex: 1 1 140px; min-width: 0; overflow-wrap: anywhere; }
button.mini { font: inherit; font-size: 12px; padding: 2px 9px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; }
button.mini:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
body.cinema header, body.cinema .run-info, body.cinema .legend, body.cinema .zoom, body.cinema .rail { display: none; }   /* cinema: only the island */
#cinemaTab { display: none; position: fixed; top: 10px; left: 10px; z-index: 6; opacity: .45; font: inherit; font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; }
#cinemaTab:hover, #cinemaTab:focus-visible { opacity: 1; }
body.cinema #cinemaTab { display: block; }
.railgrip { position: absolute; left: -8px; top: 0; bottom: 0; width: 12px; cursor: col-resize; touch-action: none; z-index: 1; }
.railgrip::after { content: ""; position: absolute; left: 5px; top: 40%; bottom: 40%; width: 2px; border-radius: 2px; background: var(--ink); opacity: 0; transition: opacity .15s; }
.railgrip:hover::after { opacity: .35; }
header .tool:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 700px) { header > .muted:not(#status):not(#counts) { display: none; } }
.muted { color: var(--muted); }
.spacer { flex: 1; }
select { font: inherit; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); }
.run { position: relative; height: 100vh; min-height: 420px; background: #000; overflow: hidden; }
.run-info { position: absolute; top: 58px; left: 10px; z-index: 3; max-width: min(560px, calc(100vw - 20px)); padding: 8px 12px; border-radius: 12px; background: color-mix(in srgb, var(--panel) 78%, transparent); border: 1px solid color-mix(in srgb, var(--ink) 14%, transparent); backdrop-filter: blur(8px); }
.run-head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.run-head h2 { font-size: 14px; margin: 0; flex: 1 1 260px; overflow-wrap: anywhere; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.chip.running, .chip.reviewing { color: var(--accent); border-color: var(--accent); }
.chip.awaiting_approval { color: var(--warn); border-color: var(--warn); }
.chip.failed, .chip.stopped { color: var(--bad); border-color: var(--bad); }
.chip.done { color: var(--ok); border-color: var(--ok); }
.clyde { margin: 4px 0 0; font-size: 13px; }
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
.legend { position: absolute; left: 12px; bottom: 12px; z-index: 3; display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: var(--muted); padding: 8px 12px; border-radius: 12px; max-width: min(540px, calc(100vw - 24px)); max-height: 60vh; overflow: auto;
  background: color-mix(in srgb, var(--panel) 80%, transparent); border: 1px solid color-mix(in srgb, var(--ink) 14%, transparent); backdrop-filter: blur(8px); }
.legend details { flex-basis: 100%; } .legend summary { cursor: pointer; }
.legend i { display: inline-block; width: 22px; height: 0; border-top: 3px solid; vertical-align: middle; margin-right: 5px; }
.legend i.dark { border-top-style: dotted; border-color: var(--idle); } .legend i.lit { border-color: var(--accent); }
.legend i.waiting { border-color: var(--warn); border-top-style: dashed; } .legend i.refused { border-color: var(--bad); }

/* A run: the scene on the left, a glass rail on the right (crew, what needs your OK, the event feed), as StarNet frames its station. */
.run-body, .scene-col, .stage { position: absolute; inset: 0; }
.zoom { position: absolute; left: 12px; bottom: 72px; display: flex; gap: 6px; z-index: 3; }
@media (max-width: 700px) { .zoom { left: auto; right: 12px; bottom: 110px; } }   /* the legend wraps tall on a phone, so the zoom keys move out from under it */
.zoom button { width: 30px; height: 30px; border-radius: 8px; border: 1px solid rgba(255,255,255,.25); background: rgba(10,10,16,.65); color: #fff; font: 600 16px/1 system-ui; cursor: pointer; backdrop-filter: blur(6px); }
.zoom button:hover { background: rgba(10,10,16,.85); } .zoom button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.rail { position: absolute; top: 12px; right: 12px; bottom: 12px; z-index: 5; width: min(var(--railw, 340px), calc(100vw - 24px)); display: flex; flex-direction: column; gap: 12px; min-height: 0; transition: transform .25s ease; }
body.rail-off .rail { transform: translateX(calc(100% + 24px)); visibility: hidden; transition: transform .25s ease, visibility 0s .25s; }
.rail > .glass.crew { flex: 1 1 0; min-height: 120px; }   /* the crew list gives way first and scrolls */
.rail > .glass.asking { flex: none; max-height: 45%; overflow: auto; }   /* a request is never squeezed: it keeps its buttons and scrolls inside if it is long */
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
.map { position: absolute; inset: 0; overflow: hidden; background: #000; }
.map svg { display: block; width: 100%; height: 100%; touch-action: none; cursor: grab; }   /* the whole station fits the window; the world around it fills what is left */
.map svg:active { cursor: grabbing; }
.map text { font-family: ui-monospace, Menlo, Consolas, monospace; paint-order: stroke; stroke-linejoin: round; }
.map .name { font-size: 11.5px; font-weight: 700; text-anchor: middle; }
.map .sign { font-size: 11px; font-weight: 700; text-anchor: middle; letter-spacing: .5px; }
.map .badge-n { font-size: 9px; font-weight: 700; text-anchor: middle; }
.map .sprite { cursor: pointer; }
.map .sprite .tag { opacity: 0; transition: opacity .12s; pointer-events: none; }   /* a name shows only while the pointer is over the person */
.map .sprite:hover .tag { opacity: 1; }
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

/* ---- polish: the chrome is ink glass with brass hairlines whatever the system theme (the island is always night); one ivory telegram slip, the list of what needs you ---- */
body { --panel: #15172a; --ink: #efe6cc; --muted: #aaa28e; --line: #3b3a52; --accent: #7bd6a6; --ok: #7bd6a6; --warn: #e9a94c; --bad: #f08a82; --idle: #8b8577; --brass: #c99a2e; --brass-soft: rgba(201,154,46,.38); --display: "Futura", "Avenir Next", "Century Gothic", "Trebuchet MS", system-ui, sans-serif; background: #0b0e1c; }
h1, .glass h3, .run-head h2, .crew-row .nm, .needs-head { font-family: var(--display); }
header, .run-info, .legend, .glass { background: linear-gradient(160deg, rgba(255,255,255,.055), rgba(255,255,255,0) 42%), rgba(15,17,32,.86); border: 1px solid var(--brass-soft); box-shadow: inset 0 0 0 1px rgba(0,0,0,.45), 0 10px 28px rgba(0,0,0,.4); backdrop-filter: blur(10px); }
header { border-radius: 14px; padding: 7px 12px; gap: 10px; }
h1 { font-size: 17px; font-weight: 600; letter-spacing: .02em; color: #f6ecce; }
.run-info { border-radius: 14px; padding: 12px 14px; }
.run-head h2 { font-size: 16px; font-weight: 600; letter-spacing: .01em; }
.clyde { color: var(--muted); }
.chip { background: rgba(255,255,255,.04); font-variant-numeric: tabular-nums; }
.chip.running, .chip.reviewing { background: rgba(123,214,166,.1); }
header .tool, button.mini, button.act { font-family: inherit; border: 1px solid rgba(239,230,204,.28); background: rgba(255,255,255,.04); color: var(--ink); border-radius: 8px; transition: background .15s, border-color .15s; }
header .tool:hover, button.mini:hover, button.act:hover { background: rgba(201,154,46,.16); border-color: var(--brass); }
header .tool[aria-pressed="true"] { border-color: var(--brass); background: rgba(201,154,46,.12); }
header .tool:focus-visible, button.mini:focus-visible, button.act:focus-visible, #cinemaTab:focus-visible, .crew-row:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }
button.act.allow { border-color: rgba(123,214,166,.6); } button.act.deny { border-color: rgba(240,138,130,.6); }
.glass { border-radius: 14px; }
.glass h3 { padding: 11px 14px 9px; font-size: 15px; font-weight: 600; letter-spacing: .01em; text-transform: none; border-bottom: 1px solid var(--brass-soft); }
.glass h3 small { font-family: system-ui, sans-serif; font-size: 12px; font-variant-numeric: tabular-nums; }
.glass.asking { border-color: var(--warn); }
.crew-row { border-radius: 10px; }
.crew-row:hover, .crew-row[aria-pressed="true"] { background: rgba(201,154,46,.09); border-color: var(--brass-soft); }
.portrait { border-color: var(--brass-soft); }
.rail .ask { border-radius: 10px; }
.log { font-variant-numeric: tabular-nums; }
.legend { border-radius: 12px; font-size: 12px; padding: 7px 12px; }
.legend summary { color: var(--ink); }
#cinemaTab { background: rgba(15,17,32,.86); border-color: var(--brass-soft); }
#counts, .need .age { font-variant-numeric: tabular-nums; }
/* the telegram slip */
.needs { margin: 12px -4px -4px; padding: 10px 14px 12px; background: #eee2c2; color: #251d14; border-radius: 6px; border: 0; border-left: 5px solid #8c2f39; box-shadow: inset 0 1px 0 rgba(255,255,255,.55), 0 10px 22px rgba(0,0,0,.45); }
.needs-head { font-size: 15px; font-weight: 600; letter-spacing: .01em; text-transform: none; color: #8c2f39; margin-bottom: 4px; }
.need { padding: 6px 0; border-top: 1px dashed rgba(37,29,20,.28); font-size: 14px; }
.need:first-of-type { border-top: 0; }
.need i { background: #b26a12; } .need.failure i { background: #a3302a; }
.need .age { color: #655840; }
.needs button.mini { border-color: rgba(37,29,20,.55); background: transparent; color: #251d14; }
.needs button.mini:hover { background: rgba(37,29,20,.09); border-color: #251d14; }
.needs button.mini:focus-visible { outline-color: #8c2f39; }
/* phones: the header may wrap to two rows (the counts keep their line), so the run's card sits below it; this block comes last so it wins */
@media (max-width: 700px) { header { flex-wrap: wrap; row-gap: 4px; } #counts { flex-basis: 100%; order: 5; white-space: normal; } .run-info { top: 96px; padding: 8px 12px; } .run-head h2 { font-size: 14px; flex-basis: 100%; } .run-info .chip.run-id { display: none; } }
@media (pointer: coarse) { header .tool, button.mini, button.act { min-height: 40px; padding-inline: 14px; } }
@media (prefers-reduced-motion: reduce) { .link.live i, .dot.on, .portrait .lamp.on { animation: none; } * { transition-duration: .01ms !important; } }
</style>
</head>
<body>
<main>
  <header>
    <h1>Clyde station</h1>
    <span id="link" class="chip link standby" role="status"><i></i><span id="linkText">standby</span></span>
    <button id="linkRetry" class="tool" type="button" hidden>Retry</button>
    <span id="counts" class="muted" aria-live="polite"></span><span id="status" class="muted" aria-live="polite"></span>
    <span class="spacer"></span>
    <button id="railToggle" class="tool" type="button" aria-pressed="true" title="Show or hide the crew and the events">Crew &amp; events</button>
    <button id="cinemaToggle" class="tool" type="button" aria-pressed="false" title="Hide every panel and show only the island (C)">Cinema</button>
  </header>
  <button id="cinemaTab" type="button" title="Bring the panels back (C or Esc)">&#9666; panels</button>
  <div id="runs"></div>
</main>
<script>
"use strict";
const TOKEN = "__TOKEN__";
const NS = "http://www.w3.org/2000/svg";
const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const state = { dismissed: [], runs: [], feeds: {}, filter: {}, polling: {}, theme: "city", loadedAt: Date.now() / 1000, scenes: [], link: { ok: true, reason: "" } };
const $runs = document.getElementById("runs");
const $status = document.getElementById("status");
const $rail = document.getElementById("railToggle");
const $link = document.getElementById("link"), $linkText = document.getElementById("linkText"), $retry = document.getElementById("linkRetry"), $counts = document.getElementById("counts");
let UID = 0;

// A theme is a look (palette, materials, backdrop) and the words it gives the same things. It never changes what a room, object or hallway means.
const THEMES = {
  city: { name: "1930s city",
    pal: { bg: "#0a0f24", floorA: "#8a6038", floorB: "#7a5230", corr: "#4a3827", grout: "#2a1a0c", wallL: "#b9a47a", wallR: "#d6c397", trim: "#b08d57", wood: "#8a5a2b", metal: "#b08d57", steel: "#5d6b5a",
           screen: "#9fd6b4", accent: "#e3b04b", lamp: "#ffd98a", ink: "#f6ecd2", paper: "#f4ecd2", dark: "#2b2118", dim: "#7a6850", wait: "#f08a24", bad: "#e0605a",
           sky1: "#070b1e", sky2: "#5a3a2a", bldg: "#141223", win: "#f2c15c", rug1: "#7a1f2b", rug2: "#c99a2e", neonA: "#ff6a3d", neonB: "#f2c15c" },
    words: { deck: "Front office", bay: "Workshop", outbox: "Mail slot", bar: "Speakeasy", approvals: "Signing desk", ledger: "Cash register", table: "Planning table",
      read: "Filing cabinet", write: "Typewriter", shell: "Safe", web: "Radio set", mcp: "Switchboard", other: "Cupboard",
      task: "Orders", results: "Reports", approvalsLane: "Messages", review: "Review", report: "Report", landing: "Delivery" } },
};
function stored(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* a private window: the choice just isn't remembered */ } }

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
// <status>
function dotClass(doing) {
  if (/approval/.test(doing)) return "wait";
  if (/failed|stopped/.test(doing)) return "bad";
  if (/finished|done|written/.test(doing)) return "fin";
  if (doing === "idle") return "";
  return "on";
}
const LIVE_RUN = ["running", "reviewing", "awaiting_approval"];
function memberState(run, member) {   // working only while the run itself is live: a missed "finished" event cannot leave someone working for ever
  const dot = dotClass(member.doing || "");
  if (dot === "on") return LIVE_RUN.includes(run.status) ? "working" : "idle";
  return dot === "wait" ? "waiting" : dot === "bad" ? "failed" : "idle";
}
function crewCounts(runs, crewOf) {
  const counts = { working: 0, waiting: 0, idle: 0, failed: 0 };
  for (const run of runs) for (const member of crewOf(run)) counts[memberState(run, member)]++;
  return counts;
}
function countsText(counts) {
  const parts = [counts.working + " working"];
  if (counts.waiting) parts.push(counts.waiting + " waiting");
  if (counts.failed) parts.push(counts.failed + " failed");
  parts.push(counts.idle + " idle");
  return parts.join(" \u00b7 ");
}
function linkState(reachable, runs) {   // live only when the server answered and a run is live; standby is neutral, never green
  return !reachable ? "down" : runs.some((run) => LIVE_RUN.includes(run.status)) ? "live" : "standby";
}
const NEEDS_MAX_AGE = 3 * 24 * 3600;   // a failure older than this drops off the list; a pending request never does
function ageText(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? s + "s" : s < 3600 ? Math.floor(s / 60) + "m" : s < 86400 ? Math.floor(s / 3600) + "h" : Math.floor(s / 86400) + "d";
}
function needsYou(runs, eventsOf, now, dismissed) {   // everything waiting on the user, each row from a recorded fact: a pending request, a worker whose last event is a failure, a failed run
  const rows = [];
  for (const run of runs) {
    const events = eventsOf(run.id) || [], last = {};
    for (const a of run.asks) rows.push({ key: run.id + ":ask:" + a.id, kind: "approval", run: run.id, id: a.id, who: a.who, text: a.who + " wants to use " + a.tool, since: a.t });
    for (const e of events) if (!["tools", "constraint", "check"].includes(e.kind)) last[e.who] = e;
    for (const who of Object.keys(last)) {
      const e = last[who];
      if (e.kind === "failed") rows.push({ key: run.id + ":fail:" + who + ":" + e.t, kind: "failure", run: run.id, who, text: who + " failed", since: e.t });
      else if (e.kind === "tool_error") rows.push({ key: run.id + ":err:" + who + ":" + e.t, kind: "failure", run: run.id, who, text: who + ": " + (e.tool || "a tool") + " failed", since: e.t });
    }
    if (run.status === "failed") rows.push({ key: run.id + ":runfailed", kind: "failure", run: run.id, who: "clyde", text: "the run failed", since: events.length ? events[events.length - 1].t : run.started });
  }
  return rows.filter((r) => !dismissed.includes(r.key) && (r.kind === "approval" || now - r.since < NEEDS_MAX_AGE)).sort((a, b) => a.since - b.since);
}
// </status>
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
const SPEED = REDUCED ? 1e6 : 4;   // tiles per second; reduced motion: no walking, crew just appear at the spot
const DWELL_USE = 2.4, DWELL_CHECK = 2.0;
const QUIET = 25, BAR_DWELL = 7, TOUR_DWELL = 5;   // seconds with nothing recorded before Clyde and Bonnie go to the bar, how long they stay put there, and how long they look into a workshop
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
function faceTo(box, from) { return [box[0] + box[2] / 2 - from[0], box[1] + box[3] / 2 - from[1]]; }   // the way to look from a spot at a piece of furniture
// The walkers' schedules. Workers: one trip per tool they used, to the furniture for that tool, starting from wherever they are.
function workerTrips(events, name, scene, liveFrom, leisure) {
  const trips = [], home = scene.homes[name];
  let lastOwn = -Infinity;
  for (const e of events) {
    if (e.who === name && e.t >= liveFrom) lastOwn = Math.max(lastOwn, e.t);
    if (e.who !== name || e.kind !== "tool_use" || e.t < liveFrom) continue;
    const stand = scene.stands[name + ":" + family(e.tool)];
    if (!stand) continue;
    const piece = scene.furniture.find((f) => f.room.id === name && f.family === family(e.tool));
    let from = home;
    if (trips.length) { const s = tripState(trips[trips.length - 1], e.t); from = s ? s.pos : home; }
    trips.push({ t0: e.t, go: [from, stand], back: [stand, home], dwell: DWELL_USE, pose: "work", bubble: "dots", face: piece ? faceTo(piece.box, stand) : [0, -1], tool: e.tool });
  }
  if (leisure && scene.barSpots[name]) {   // idle or finished, and nothing of its own recorded for a while: it goes to the bar like Clyde and Bonnie
    const free = trips.length ? tripEnd(trips[trips.length - 1]) : liveFrom, quietFrom = Math.max(free, (lastOwn === -Infinity ? liveFrom : lastOwn) + QUIET);
    trips.push(...leisureTrips(name, scene, { room: name, at: home }, quietFrom, liveFrom + 10800, 0, false).trips);
  }
  return trips;
}
// When nothing has been recorded for QUIET seconds (by anyone), Clyde and Bonnie walk to the bar together, stay a while, now and then look
// into a workshop and come back. It is scenery, a function of the recorded times and the clock: any recorded event ends it (after the leg they
// are on), and nothing is shown that the run did not record.
function leisureTrips(name, scene, from, start, until, tours, tour) {
  const trips = [], spot = scene.barSpots[name], counter = scene.furniture.find((f) => f.family === "bar"), bays = tour === false ? [] : scene.bayRooms, bubble = (name === "clyde" || ((/(\d+)$/.exec(name) || [0, 1])[1] % 2 === 0 && name !== "bonnie")) ? "smoke" : "drink";
  let t = start, room = from.room, at = from.at, n = 0;
  while (t < until && n++ < 400) {
    const phase = (n - 1) % 4;
    let trip;
    if (phase === 3 && bays.length) {
      const bay = bays[tours++ % bays.length], door = bay.inner;
      trip = { t0: t, go: scene.route("bar", spot, bay.id, door), back: null, dwell: TOUR_DWELL, pose: "idle", face: [scene.homes[bay.id][0] - door[0], scene.homes[bay.id][1] - door[1]], bubble: null, leisure: true };
      trip.back = trip.go.slice().reverse();
    } else {
      trip = { t0: t, go: room === "bar" ? [spot, spot] : scene.route(room, at, "bar", spot), back: [spot, spot], dwell: BAR_DWELL, pose: "idle", face: counter ? faceTo(counter.box, spot) : [0, -1], bubble, leisure: true };   // leaning on the counter, looking at it
    }
    trips.push(trip);
    t = tripEnd(trip);
    room = "bar"; at = spot;
  }
  return { trips, end: t, room, at, tours };
}
// Clyde and Bonnie: one trip per recorded `check` of theirs (plus Clyde carrying the landed work to the outbox), taken in order; `leisure` fills the quiet gaps.
function orchestratorTrips(events, name, scene, liveFrom, leisure) {
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
  const times = events.map((e) => e.t);
  let free = 0, where = { room: "deck", at: home }, tours = 0;
  const rest = (until) => {   // the quiet before `until`: nothing was recorded for QUIET seconds, so they are at the bar
    if (!leisure) return;
    const quietFrom = Math.max(free, liveFrom, Math.max(-Infinity, ...times.filter((t) => t < until)) + QUIET);
    if (quietFrom >= until) return;
    const spell = leisureTrips(name, scene, where, quietFrom, until === Infinity ? liveFrom + 10800 : until, tours);
    trips.push(...spell.trips);
    free = spell.end; where = { room: spell.room, at: spell.at }; tours = spell.tours;
  };
  for (const w of wanted) {
    const stand = scene.checkStands[w.target];
    if (!stand) continue;
    rest(w.t);
    const t0 = Math.max(w.t, free), r = REASONS[w.reason] || REASONS.result, target = w.target === "outbox" ? "outbox" : w.target;
    const piece = w.target === "outbox" ? scene.furniture.find((f) => f.family === "crate") : null;   // at the outbox they face the crate; at a bay, the worker
    const face = piece ? faceTo(piece.box, stand) : scene.homes[w.target] ? [scene.homes[w.target][0] - stand[0], scene.homes[w.target][1] - stand[1]] : [0, 1];
    const trip = { t0, go: scene.route(where.room, where.at, target, stand), back: scene.route(target, stand, "deck", home), dwell: DWELL_CHECK, pose: "check", face, ...r };
    trips.push(trip);
    free = tripEnd(trip); where = { room: "deck", at: home };
  }
  rest(Infinity);
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
function facesDownLeft(f) {   // the pictures face down-right (toward +x); a piece against its room's north wall must face down-left (toward +y), so its picture is mirrored
  if (f.flip !== undefined) return f.flip;
  const r = f.room, cx = f.box[0] + f.box[2] / 2 - r.x, cy = f.box[1] + f.box[3] / 2 - r.y;
  return cy < cx;
}
function convexHull(points) {   // the outline of a set of points (monotone chain), in order
  const pts = points.slice().sort((p, q) => p[0] - q[0] || p[1] - q[1]), cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]), build = (list) => { const h = []; for (const q of list) { while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], q) <= 0) h.pop(); h.push(q); } h.pop(); return h; };
  return build(pts).concat(build(pts.slice().reverse()));
}
// ---- geometry: the station is an island seen from a corner. Every room and hallway is on one slab; a tile is a diamond HX*2 wide and HY*2 tall on screen ----
const HX = 24, HY = 12, WALL = 60, SLAB = 22;
function at(x, y, f, h) { return [(x - y) * HX, (x + y) * HY - (h || 0)]; }   // a spot on the island, h px above the ground, on screen (f is unused: there is one level)
function pts(list) { return list.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" "); }
function shade(hex, pct) {
  const n = parseInt(hex.slice(1), 16), f = pct / 100;
  const c = (v) => Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f)));
  return "#" + [c(n >> 16), c((n >> 8) & 255), c(n & 255)].map((v) => v.toString(16).padStart(2, "0")).join("");
}
function hash(a, b) { let h = Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
const BAY_SIZES = [[12, 12], [13, 12], [12, 13], [13, 13]];   // workshop sizes in tiles, so neighbours differ
const PIECES = [["read", 1.6, 1.1], ["write", 2.4, 1.2], ["mcp", 1.6, 1.1], ["shell", 1.5, 1.2], ["web", 1.4, 1.1], ["other", 1.5, 1.1]];   // [family, length along the wall, depth]
function bayLayout(i, wall) {   // a workshop floor plan: every one-sided piece against the north or west wall (the pictures only show a front), the door on `wall`, and a clear lane from the door across the room
  const [w, d] = BAY_SIZES[i % BAY_SIZES.length], vertical = wall !== "e", door = vertical ? w - 2.6 : d - 2.6, slots = {}, lane = (a, b) => a < door + 1.5 && b > door - 1.5;
  let cx = 2.2, cy = 2.0;   // the north row starts clear of the west column
  for (const [f, len, dep] of PIECES) {
    if (vertical && lane(cx, cx + len)) cx = door + 1.6;
    if (cx + len <= w - 0.5) { slots[f] = { box: [cx, 0.15, len, dep], stand: [cx + len / 2, 0.15 + dep + 1.0] }; cx += len + 0.5; continue; }
    if (!vertical && lane(cy, cy + len)) cy = door + 1.6;
    slots[f] = { box: [0.15, cy, dep, len], stand: [0.15 + dep + 1.0, cy + len / 2] };   // what does not fit on the north wall goes down the west wall
    cy += len + 0.5;
  }
  const home = vertical ? [door, d * 0.56] : [w * 0.56, door], check = wall === "n" ? [door, home[1] - 1.7] : wall === "s" ? [door, home[1] + 1.7] : [home[0] + 1.7, door];
  const runner = wall === "n" ? [door - 1.4, 0.4, 2.8, home[1] + 1.6 - 0.4] : wall === "s" ? [door - 1.4, home[1] - 1.6, 2.8, d - 0.4 - (home[1] - 1.6)] : [home[0] - 1.6, door - 1.4, w - 0.4 - (home[0] - 1.6), 2.8];
  return { w, d, door, home, check, slots, props: [], runner };
}
function plan(layout) {
  const bays = layout.rooms.filter((r) => r.kind === "bay"), DW = 26, DD = 12, deckCx = DW / 2;
  // The deck is the centre. Workshops hang off it in three arms, down, left and up; a workshop past the first in an arm is reached through the one before it.
  const ARMS = [{ wall: "n", hub: [[deckCx, DD - 0.5]], door: ["s", deckCx - 1, deckCx + 1] }, { wall: "e", hub: [[1, 6]], door: ["w", 5, 7] }, { wall: "s", hub: [[6, 1], [9.2, 7.8]], door: ["n", 5, 7] }];
  const rooms = { deck: { id: "deck", kind: "deck", f: 0, x: 0, y: 0, w: DW, d: DD } }, deck = rooms.deck, armsUsed = Math.max(1, Math.min(3, bays.length));
  deck.doors = [["e", 5, 7], ["n", 20, 22], ...ARMS.slice(0, armsUsed).map((a) => a.door)];   // the north door is the visitors' entrance, from the car park
  const corridors = [{ x: DW, y: 5, w: 4, d: 2 }, { x: 20, y: -3.5, w: 2, d: 3.5 }], edge = [DD, 0, 0], chains = [[], [], []], lanes = {}, outs = {};
  bays.forEach((b, i) => {
    const a = i % 3, arm = ARMS[a], O = bayLayout(i, arm.wall), chain = chains[a], gap = chain.length ? 3 : 4;
    let x, y, corr, entry, inner, lane;
    if (a === 0) { x = deckCx - O.door; y = edge[0] + gap; corr = { x: deckCx - 1, y: edge[0], w: 2, d: gap }; edge[0] = y + O.d; entry = [deckCx, y]; inner = [deckCx, y + 1.5]; lane = (off) => [[deckCx + off, DD], [deckCx + off, y + 1.2]]; }
    else if (a === 1) { x = edge[1] - gap - O.w; y = 6 - O.door; corr = { x: x + O.w, y: 5, w: gap, d: 2 }; edge[1] = x; entry = [x + O.w, 6]; inner = [x + O.w - 1.5, 6]; lane = (off) => [[0, 6 + off], [x + O.w - 1.2, 6 + off]]; }
    else { y = edge[2] - gap - O.d; x = 6 - O.door; corr = { x: 5, y: y + O.d, w: 2, d: gap }; edge[2] = y; entry = [6, y + O.d]; inner = [6, y + O.d - 1.5]; lane = (off) => [[6 + off, 0], [6 + off, y + O.d - 1.2]]; }
    corridors.push(corr);
    const room = { id: b.id, kind: "bay", f: 0, x, y, w: O.w, d: O.d, wall: arm.wall, entry, inner, tpl: O, src: b, through: false, runner: [x + O.runner[0], y + O.runner[1], O.runner[2], O.runner[3]] };
    if (chain.length) chain[chain.length - 1].through = true;
    outs[b.id] = [inner, ...chain.slice().reverse().map((r) => r.inner), ...arm.hub];
    for (const [kind, off] of [["task", -0.5], ["results", 0], ["approvals", 0.5]]) lanes[kind + ":" + b.id] = lane(off);
    chain.push(room);
    rooms[b.id] = room;
  });
  // East of the front office, along the same hallway: the bar, then the mail slot behind it.
  rooms.bar = { id: "bar", kind: "bar", f: 0, x: DW + 4, y: 1, w: 12, d: 10, doors: [["w", 5, 7], ["e", 5, 7]] };
  rooms.outbox = { id: "outbox", kind: "outbox", f: 0, x: DW + 4 + 12 + 3, y: 3, w: 8, d: 7, doors: [["w", 5, 7]] };
  corridors.push({ x: rooms.bar.x + rooms.bar.w, y: 5, w: 3, d: 2 });
  const bayRooms = Object.values(rooms).filter((r) => r.kind === "bay");
  // The long sides of every corridor have a rail (lines in tile space).
  const edges = [];
  for (const c of corridors) {
    if (c.d > c.w) edges.push([[c.x, c.y], [c.x, c.y + c.d]], [[c.x + c.w, c.y], [c.x + c.w, c.y + c.d]]);
    else edges.push([[c.x, c.y], [c.x + c.w, c.y]], [[c.x, c.y + c.d], [c.x + c.w, c.y + c.d]]);
  }
  const at = (room, p) => [room.x + p[0], room.y + p[1]];
  const homes = { clyde: at(deck, [11.2, 8.9]), bonnie: at(deck, [14.8, 8.9]), master: at(deck, [3.5, 4.6]), advisor: at(deck, [22.5, 4.6]) };
  const stands = {}, checkStands = { outbox: at(rooms.outbox, [3.5, 3.8]) };
  for (const r of bayRooms) {
    homes[r.id] = at(r, r.tpl.home);
    checkStands[r.id] = at(r, r.tpl.check);
    for (const f in r.tpl.slots) stands[r.id + ":" + f] = at(r, r.tpl.slots[f].stand);
  }
  const toDeck = (room, pos) => {   // from a spot in a room to the deck, by way of the doors on its arm
    if (room === "deck") return [pos];
    if (room === "bar") return [pos, [rooms.bar.x + 1.5, 6], [deck.x + DW - 1, 6]];
    if (room === "outbox") return [pos, [rooms.outbox.x + 1.5, 6], [rooms.bar.x + rooms.bar.w - 1.5, 6], [rooms.bar.x + 1.5, 6], [deck.x + DW - 1, 6]];
    return [pos, ...outs[room]];
  };
  const route = (fromRoom, from, toRoom, to) => {
    if (fromRoom === toRoom) return [from, to];
    const out = toDeck(fromRoom, from), back = toDeck(toRoom, to).reverse();
    return out.concat(back);
  };
  const LAND = Math.min(20, 3 + 0.55 * (Object.keys(rooms).length + corridors.length));   // how far the island reaches past the rooms: more rooms and hallways, more land
  const furniture = [], props = [], prop = (kind, x, y, size) => props.push({ kind, x, y, size, f: 0 });
  for (const r of bayRooms) {
    for (const o of r.src.objects) { const s = r.tpl.slots[o.family]; if (s) furniture.push({ room: r, family: o.family, obj: o, box: [r.x + s.box[0], r.y + s.box[1], s.box[2], s.box[3]] }); }
    for (const q of r.tpl.props) prop(q[0], r.x + q[1], r.y + q[2]);
  }
  const dk = layout.rooms.find((r) => r.id === "deck");
  const deckBoxes = { approvals: [3, 8, 3, 1.6], ledger: [13.4, 0.3, 2.8, 1.3] };
  for (const o of dk.objects) furniture.push({ room: deck, family: o.family, obj: o, box: [deck.x + deckBoxes[o.family][0], deck.y + deckBoxes[o.family][1], deckBoxes[o.family][2], deckBoxes[o.family][3]] });
  furniture.push({ room: deck, family: "desk", obj: null, lane: "report", box: [deck.x + 2, deck.y + 2, 3, 2] }, { room: deck, family: "desk", obj: null, lane: "review", box: [deck.x + 21, deck.y + 2, 3, 2] },
                 { room: deck, family: "table", obj: null, box: [deck.x + 11, deck.y + 5, 4.2, 2] });
  for (const [kind, x, y, size] of [["plant", 2.2, 10.8], ["plant", 24.8, 10.6], ["lamp", 9, 1.3], ["lamp", 17.4, 1.3], ["bookcase", 0.3, 8.0, 3.2], ["tank", 24.6, 8.8], ["coat", 7.6, 10.8]]) prop(kind, deck.x + x, deck.y + y, size);
  const ob = layout.rooms.find((r) => r.kind === "outbox");
  const ox = rooms.outbox.x, oy = rooms.outbox.y;   // a post room: pigeonhole cabinets along the back wall (the one that lights up is the real outbox), sacks and crates in the corner
  furniture.push({ room: rooms.outbox, family: "mailbox", obj: null, box: [ox + 1.2, oy + 0.3, 1.8, 1.1] }, { room: rooms.outbox, family: "mailbox", obj: null, box: [ox + 3.2, oy + 0.3, 1.8, 1.1] },
                 { room: rooms.outbox, family: "crate", obj: ob, box: [ox + 5.2, oy + 0.3, 1.8, 1.1] });
  for (const [kind, x, y, size] of [["crates", 6.9, 5.7], ["plant", 7.3, 3.6], ["lamp", 0.7, 5.6]]) prop(kind, rooms.outbox.x + x, rooms.outbox.y + y, size);
  // Each workshop gets its own look: a rug style and colours, and a few extra pieces, all picked from the room's number and placed only where they fit.
  const RUGS = [["#7a1f2b", "#c99a2e"], ["#24432f", "#c99a2e"], ["#232f55", "#e2d3a8"], ["#8a5a1f", "#7a1f2b"]];
  const nearSeg = (px, py, a, b) => { const dx = b[0] - a[0], dy = b[1] - a[1], k = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy || 1))); return Math.hypot(px - a[0] - dx * k, py - a[1] - dy * k); };
  const walks = [];   // the lines workers and visitors walk through the rooms on the way to the far workshops of an arm
  chains.forEach((c, a) => { for (let k = 1; k < c.length; k++) walks.push([c[k].inner, c[k - 1].inner]); if (c.length) walks.push([c[0].inner, ARMS[a].hub[0]]); });
  bayRooms.forEach((r, i) => {
    const seed = (parseInt((/(\d+)$/.exec(r.id) || [0, i + 1])[1], 10) || i + 1) * 7;
    const [c1, c2] = RUGS[Math.floor(hash(seed, 1) * RUGS.length)], style = Math.floor(hash(seed, 2) * 3), h = homes[r.id], ck = checkStands[r.id];
    r.rugs = style === 0 ? [{ box: r.runner, c1, c2 }] : style === 1 ? [{ box: [h[0] - 1.8, h[1] - 1.3, 3.6, 2.6], c1, c2 }, { box: r.runner, c1: RUGS[(RUGS.indexOf(RUGS.find((q) => q[0] === c1)) + 1) % RUGS.length][0], c2 }] : [{ box: [ck[0] - 1.1, ck[1] - 0.9, 2.2, 1.8], c1, c2 }, { box: [h[0] - 1.4, h[1] - 1.0, 2.8, 2.0], c1: c2 === "#c99a2e" ? "#3a2a1c" : c1, c2: c1 }];
    r.rugs = r.rugs.map((q) => ({ ...q, box: [Math.max(r.x + 0.6, q.box[0]), Math.max(r.y + 0.6, q.box[1]), Math.min(q.box[2], r.x + r.w - 0.6 - Math.max(r.x + 0.6, q.box[0])), Math.min(q.box[3], r.y + r.d - 0.6 - Math.max(r.y + 0.6, q.box[1]))] }));
    const marks = [homes[r.id], checkStands[r.id], ...Object.keys(r.tpl.slots).map((k) => stands[r.id + ":" + k])];
    const free = (x, y) => x > r.x + 0.9 && x < r.x + r.w - 0.9 && y > r.y + 0.9 && y < r.y + r.d - 0.9
      && !furniture.some((f) => f.room === r && x > f.box[0] - 0.9 && x < f.box[0] + f.box[2] + 0.9 && y > f.box[1] - 0.9 && y < f.box[1] + f.box[3] + 0.9)
      && !props.some((q) => Math.hypot(q.x - x, q.y - y) < 1.6) && !marks.some((m) => Math.hypot(m[0] - x, m[1] - y) < 1.5)
      && nearSeg(x, y, r.entry, r.inner) > 1.4 && nearSeg(x, y, r.inner, h) > 1.4 && nearSeg(x, y, r.inner, checkStands[r.id]) > 1.4 && marks.every((m) => nearSeg(x, y, h, m) > 1.3) && walks.every((w) => nearSeg(x, y, w[0], w[1]) > 1.4);   // never on a line anyone walks
    const spots = [];
    for (let gx = r.x + 1; gx < r.x + r.w; gx += 1) for (let gy = r.y + 1; gy < r.y + r.d; gy += 1) spots.push([gx, gy, hash(Math.round(gx * 3) + seed, Math.round(gy * 5))]);
    spots.sort((a, b) => a[2] - b[2]);
    const kinds = ["plant", "lamp", "coat", "crates", "tank", "plant"];
    let placed = 0;
    const used = [];
    for (const [gx, gy] of spots) {
      if (placed >= 3) break;
      const kind = kinds[Math.floor(hash(seed + placed + used.length, 9) * kinds.length)];
      if (kind !== "plant" && used.includes(kind)) { used.push(kind); if (used.length > 12) break; continue; }   // one coat rack, one cooler: only plants may repeat
      if (free(gx, gy)) { prop(kind, gx, gy); used.push(kind); placed++; }
    }
  });
  const bar = rooms.bar;
  const barSpots = { clyde: [bar.x + 4.0, bar.y + 3.0], bonnie: [bar.x + 5.4, bar.y + 3.0] };   // where Clyde and Bonnie lean on the counter
  const crowd = [[6.8, 3.0], [8.2, 3.0], [9.6, 3.0], [2.6, 4.6], [4.2, 4.6], [5.8, 4.6], [7.4, 4.6], [9.0, 4.6]];   // and where the workers stand, one spot each, round the counter
  bayRooms.forEach((r, i) => { barSpots[r.id] = [bar.x + crowd[i % crowd.length][0], bar.y + crowd[i % crowd.length][1]]; });
  // the speakeasy: a counter along the back with stools, sofas and a little table in front; the way through (row 5) stays clear
  furniture.push({ room: bar, family: "bar", obj: null, box: [bar.x + 1.5, bar.y + 0.5, 6, 1.4] }, { room: bar, family: "sofa", obj: null, box: [bar.x + 0.5, bar.y + 6.4, 1.4, 3.2] },
                 { room: bar, family: "sofa", obj: null, box: [bar.x + 8.4, bar.y + 0.5, 3.2, 1.4] }, { room: bar, family: "smalltable", obj: null, box: [bar.x + 3.2, bar.y + 7.2, 1.8, 1.4] });
  for (const [kind, x, y] of [["plant", 0.9, 4.0], ["plant", 11.1, 4.0], ["plant", 11.3, 9.2], ["lamp", 9.2, 3.0], ["lamp", 0.8, 3.0]]) prop(kind, bar.x + x, bar.y + y);
  lanes.landing = [[deck.x + DW - 1, 6], [rooms.outbox.x + 1.5, 6]];
  // the island: every room and hallway on one slab that follows their outline, with a few trees and lamps round its edge
  const xs = Object.values(rooms), gx = [Math.min(...xs.map((r) => r.x)), Math.max(...xs.map((r) => r.x + r.w))], gy = [Math.min(...xs.map((r) => r.y)), Math.max(...xs.map((r) => r.y + r.d))];
  prop("tower", gx[0] - 1.5, gy[0] - 1.5); prop("tower", gx[1] + 1.5, gy[0] - 1.5);   // a deco tower at two corners of the island
  const lot = { x: 15.8, y: -7.9, w: 10.4, d: 4.4 };   // the car park, north of the front office: three bays side by side, its path ends at the office's north door
  ["car-black", "car-red", "car-green"].forEach((name, i) => prop("car", lot.x + 1.9 + i * 3.3, lot.y + 2.4, name));
  const around = [[lot.x - 2, lot.y - 2], [lot.x + lot.w + 2, lot.y - 2], [lot.x + lot.w + 2, lot.y + lot.d + 2], [lot.x - 2, lot.y + lot.d + 2]];
  for (const r of Object.values(rooms)) for (const [cx, cy] of [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.d], [r.x, r.y + r.d]]) around.push([cx + (cx === r.x ? -LAND : LAND), cy + (cy === r.y ? -LAND : LAND)]);
  for (const c of corridors) for (const [cx, cy] of [[c.x, c.y], [c.x + c.w, c.y], [c.x + c.w, c.y + c.d], [c.x, c.y + c.d]]) around.push([cx + (cx === c.x ? -LAND : LAND), cy + (cy === c.y ? -LAND : LAND)]);
  for (const q of props) if (q.kind === "car" || q.kind === "tower") for (const [dx, dy] of [[-2, -2], [2, -2], [2, 2], [-2, 2]]) around.push([q.x + dx, q.y + dy]);
  const slab = convexHull(around), mid = [slab.reduce((a, q) => a + q[0], 0) / slab.length, slab.reduce((a, q) => a + q[1], 0) / slab.length];
  slab.forEach((a, i) => {
    const b = slab[(i + 1) % slab.length], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    for (let t = 2, k = i; t < len - 1; t += 6, k++) {
      const x = a[0] + (b[0] - a[0]) * t / len, y = a[1] + (b[1] - a[1]) * t / len, away = Math.hypot(x - mid[0], y - mid[1]) || 1, px = x + (mid[0] - x) / away * 1.6, py = y + (mid[1] - y) / away * 1.6;
      if (!props.some((q) => (q.kind === "car" || q.kind === "tower") && Math.hypot(q.x - px, q.y - py) < 3.2)) prop(k % 3 ? "tree" : "lamppost", px, py);
    }
  });
  return { rooms, lot, bayRooms, corridors, edges, homes, stands, checkStands, barSpots, route, furniture, props, lanes, deckCx, DW, DD, slab };
}
function bounds(p) {   // the rooms with a little air round them: the island and its rock run on past the edges of the picture
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const r of Object.values(p.rooms)) { x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y); x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.d); }
  return [at(x0, y1)[0] - 120, at(x0, y0)[1] - WALL - 130, at(x1, y0)[0] + 120, at(x1, y1)[1] + 150];
}
function rockDepth(p) { const xs = p.slab.map((q) => at(q[0], q[1])[0]); return (Math.max(...xs) - Math.min(...xs)) * 0.42; }   // the rock under the island grows with it   // the rock under the island grows with it
// </geometry>

// ---- the island: a night sky around it, floors, low glass walls, then furniture and the crew, all generated pixel art (THIRD_PARTY.md) ----
const ART_V = "__ARTV__";   // changes whenever a picture does, so a browser never shows an old one from its cache
function artUrl(name) { return "/assets/" + name + ".png?v=" + ART_V; }
const SPR = __SPRITES__;   // each sprite's natural size [w, h], read from the files by the server
const FX = { grain: "", grime: "", soft: "" };
const RAIL = 22;   // the height of a rail along an open edge
const BRICK = "#8c3b2e", SKEW = Math.tan(Math.atan(HY / HX));   // brick for the outside; the slope of a wall running along an axis
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
  FX.soft = make("soft" + uid, (f) => f.append(sv("feGaussianBlur", { stdDeviation: 4 })));
}
function sprite(name, x, y, w, h, extra) { return sv("image", { href: artUrl(name), x, y, width: w, height: h, style: "image-rendering:pixelated", ...(extra || {}) }); }
function standing(name, cx, by, wpx, extra) {   // a sprite standing on the floor: bottom centre at (cx, by), wpx wide
  const [sw, sh] = SPR[name], hpx = wpx * sh / sw;
  return sprite(name, cx - wpx / 2, by - hpx, wpx, hpx, extra);
}
function poly(layer, points, fill, extra) { const n = sv("polygon", { points: pts(points), fill, ...(extra || {}) }); layer.append(n); return n; }
function mixc(a, b, t) { const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)), x = p(a), y = p(b); return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join(""); }
function quad(x, y, w, d, f, h) { return [at(x, y, f, h), at(x + w, y, f, h), at(x + w, y + d, f, h), at(x, y + d, f, h)]; }   // a rectangle on a floor
function wallQuad(plane, c, a, b, h0, h1, f) {   // a vertical rectangle on a wall: plane "x" (x = c, running along y from a to b) or "y" (y = c, along x)
  const P = (u, h) => plane === "x" ? at(c, u, f, h) : at(u, c, f, h);
  return [P(a, h0), P(b, h0), P(b, h1), P(a, h1)];
}
function tilePath(i, j, f) { const q = quad(i, j, 1, 1, f); return "M" + q.map((v) => v[0].toFixed(1) + " " + v[1].toFixed(1)).join("L") + "Z"; }
function lineAt(a, b) { return "M" + a[0].toFixed(1) + " " + a[1].toFixed(1) + "L" + b[0].toFixed(1) + " " + b[1].toFixed(1); }
function ground(svg, defs, B, pal, uid) {   // the building floats in a night sky that never ends: stars, a moon, a few wisps of cloud; scenery only
  const [x0, y0, x1, y1] = B, big = Math.max(x1 - x0, y1 - y0), ex = big * 1.6, ey = big * 0.6, gx0 = x0 - ex, gx1 = x1 + ex, gy0 = y0 - ey, gy1 = y1 + ey, layer = sv("g", { "aria-hidden": "true" });
  layer.append(sv("rect", { x: gx0, y: gy0, width: gx1 - gx0, height: gy1 - gy0, fill: gradient(defs, "sky" + uid, [[0, "#060919"], [0.55, "#121634"], [1, "#2a2d52"]]) }));
  for (let i = 0; i < 260; i++) layer.append(sv("circle", { cx: gx0 + hash(41, i) * (gx1 - gx0), cy: gy0 + hash(42, i) * (gy1 - gy0), r: 0.7 + hash(43, i) * 1.5, fill: "#fff6d8", opacity: 0.3 + hash(44, i) * 0.6, class: "twinkle amb", style: "animation-delay:-" + (hash(45, i) * 4).toFixed(1) + "s" }));
  const mx = x1 + (x1 - x0) * 0.5, my = y0 + (y1 - y0) * 0.1;   // a moon off to one side, and clouds that drift past
  layer.append(sv("circle", { cx: mx, cy: my, r: 300, fill: gradient(defs, "moonglow" + uid, [[0, "#f4ecd2", 0.26], [1, "#f4ecd2", 0]], { r: "50%" }) }), sprite("scene-moon", mx - 110, my - 114, 220, 228));
  for (let i = 0; i < 9; i++) { const cx = gx0 + hash(51, i) * (gx1 - gx0), cy = gy0 + hash(52, i) * (gy1 - gy0), name = "scene-cloud-" + (1 + (i % 5)), [cw, ch] = SPR[name], wide = 260 + hash(54, i) * 260; layer.append(sprite(name, cx - wide / 2, cy, wide, wide * ch / cw, { opacity: 0.5, class: (i % 2 ? "drift" : "drift2") + " amb", style: "image-rendering:pixelated;animation-delay:-" + (hash(53, i) * 60).toFixed(0) + "s" })); }
  svg.append(layer);
}
function underside(layer, defs, p, pal, uid) {   // the rock the island floats on: it hangs below the slab, narrowing to a point, with a lantern on a chain
  const H = p.slab.map((q) => at(q[0], q[1])), down = (q, h) => [q[0], q[1] + h];
  const L = H.reduce((a, q) => (q[0] < a[0] ? q : a)), R = H.reduce((a, q) => (q[0] > a[0] ? q : a)), B = H.reduce((a, q) => (q[1] > a[1] ? q : a));
  const lower = H.filter((q) => q[1] >= Math.min(L[1], R[1]) - 1).sort((a, b) => a[0] - b[0]).map((q) => down(q, SLAB)), tip = [(L[0] + R[0]) / 2 + 20, down(B, SLAB)[1] + rockDepth(p)];
  const left = lower.filter((q) => q[0] <= B[0]), right = lower.filter((q) => q[0] >= B[0]);
  const edge = (a, b, seed) => { const out = [a]; for (let i = 1; i < 9; i++) { const k = i / 9, wob = (hash(seed, i) - 0.5) * 60 * Math.sin(k * Math.PI); out.push([a[0] + (b[0] - a[0]) * k + wob, a[1] + (b[1] - a[1]) * k * (0.85 + hash(seed + 1, i) * 0.3)]); } out.push(b); return out; };
  const ridge = edge(down(B, SLAB), tip, 23), leftEdge = edge(left[0], tip, 11), rightEdge = edge(right[right.length - 1], tip, 37);
  const pat = (id, name, w, h) => { const t = sv("pattern", { id, width: w, height: h, patternUnits: "userSpaceOnUse" }); t.append(sprite(name, 0, 0, w, h)); defs.append(t); return "url(#" + id + ")"; };
  const lf = [...left, ...ridge.slice(1), ...leftEdge.slice().reverse()], rt = [...right, ...rightEdge.slice(1), ...ridge.slice().reverse()];
  poly(layer, lf, pat("rockL" + uid, "scene-rock", 160, 102)); poly(layer, lf, "#000", { opacity: 0.2 });
  poly(layer, rt, pat("rockR" + uid, "scene-rock", 160, 102)); poly(layer, rt, "#000", { opacity: 0.5 });
  for (let k = 1; k < 8; k++) layer.append(sv("path", { d: lineAt(leftEdge[k], ridge[k]), stroke: "#000", "stroke-width": 1.4, opacity: 0.25 }), sv("path", { d: lineAt(ridge[k], rightEdge[k]), stroke: "#000", "stroke-width": 1.4, opacity: 0.3 }));
  layer.append(sv("path", { d: lineAt(tip, [tip[0], tip[1] + 90]), stroke: pal.metal, "stroke-width": 2 }), sv("circle", { cx: tip[0], cy: tip[1] + 100, r: 40, fill: gradient(defs, "lant" + uid, [[0, pal.lamp, 0.5], [1, pal.lamp, 0]], { r: "50%" }), class: "flick2 amb" }), sv("rect", { x: tip[0] - 5, y: tip[1] + 90, width: 10, height: 16, rx: 2, fill: pal.lamp, stroke: "#000", "stroke-width": 1 }));
}
function plaque(layer, plane, c, u, h, text, pal, f) {   // a name plate on a wall
  const p = plane === "x" ? at(c, u, f, h) : at(u, c, f, h), half = text.length * 3.6 + 12;
  const g = sv("g", { transform: "translate(" + p[0].toFixed(1) + " " + p[1].toFixed(1) + ") skewY(" + (plane === "x" ? -26.565 : 26.565) + ")" });
  g.append(sv("rect", { x: -half, y: -10, width: half * 2, height: 19, rx: 3, fill: pal.dark, stroke: pal.trim, "stroke-width": 2 }), sv("text", { x: 0, y: 4, class: "sign", fill: pal.ink, stroke: "none" }, text));
  layer.append(g);
}
function wallRuns(a, b, gaps) {   // the stretches of a wall between its doorways
  const runs = [];
  let from = a;
  for (const [g0, g1] of gaps.slice().sort((x, y) => x[0] - y[0]).concat([[b, b]])) { if (g0 > from) runs.push([from, g0]); from = Math.max(from, g1); }
  return runs;
}
const WALL_BASE = { "glass-a": [137.2, 0.57], "glass-b": [140.0, 0.55], "brick-a": [121.7, 0.60], "brick-b": [124.1, 0.58] };   // [row where the front bottom edge crosses the middle, its slope], measured from the pictures   // the row, in each picture, where the wall's front bottom edge crosses its middle (measured from the pictures): this is what stands on the floor's edge, not the lowest corner
function wallRun(layer, plane, c, a, b, kind) {   // a back wall of sprites, two tiles to a piece: the "-a" pictures run along x (the north wall), the "-b" ones along y (the west wall); glass-topped for a see-through room, solid brick where things hang on it
  const n = Math.max(1, Math.round((b - a) / 2)), key = kind + (plane === "y" ? "-a" : "-b"), name = "tile-wall-" + key, [sw, sh] = SPR[name], [base, slope] = WALL_BASE[key];
  for (let i = 0; i < n; i++) {
    const u0 = a + (b - a) * i / n, u1 = a + (b - a) * (i + 1) / n, mid = plane === "y" ? at((u0 + u1) / 2, c, 0) : at(c, (u0 + u1) / 2, 0), w = (u1 - u0) * HX + 4, kx = w / sw, ky = kx * HY / HX / slope;   // squeezed in height so the piece's base slopes exactly like the floor's tiles, and neighbours meet edge to edge
    layer.append(sprite(name, mid[0] - w / 2, mid[1] - base * ky + 1, w, sh * ky, { preserveAspectRatio: "none" }));
  }
}
function paved(layer, defs, x, y, w, d, name, uid) {   // a floor: the picture repeated over blocks of 2 x 2 tiles and cut to the rectangle
  const [sw, sh] = SPR[name], k = 4 * HX / sw, id = "fc" + uid + Math.round(x * 7 + y * 13 + w * 3), clip = sv("clipPath", { id }), g = sv("g", { "clip-path": "url(#" + id + ")" }), blocks = [];
  clip.append(sv("polygon", { points: pts(quad(x, y, w, d, 0)) }));
  defs.append(clip);
  for (let i = 0; i < Math.ceil(w / 2); i++) for (let j = 0; j < Math.ceil(d / 2); j++) blocks.push([i, j]);
  blocks.sort((a, b) => a[0] + a[1] - b[0] - b[1]);
  for (const [i, j] of blocks) { const t = at(x + i * 2, y + j * 2, 0); g.append(sprite(name, t[0] - sw * k / 2, t[1], sw * k, sh * k)); }
  layer.append(g);
}
function worldStatic(layer, defs, p, pal, uid, words) {   // the slab, the courtyard, hallways, rooms with their floors and low glass walls
  const H = p.slab.map((q) => at(q[0], q[1])), down = (q, h) => [q[0], q[1] + h];
  const pat = (id, name, w, h) => { const t = sv("pattern", { id, width: w, height: h, patternUnits: "userSpaceOnUse" }); t.append(sprite(name, 0, 0, w, h)); defs.append(t); return "url(#" + id + ")"; };
  H.forEach((a, i) => { const b = H[(i + 1) % H.length], face = [a, b, down(b, SLAB), down(a, SLAB)]; poly(layer, face, pat("cliff" + uid + i, "scene-rock", 110, 70)); poly(layer, face, "#000", { opacity: i % 2 ? 0.1 : 0.35 }); });
  poly(layer, H, "#2f4a2a");
  const grass = poly(layer, H, pat("grass" + uid, "scene-grass", 328, 120), { opacity: 0.9 });
  defs.querySelector("#grass" + uid).setAttribute("patternTransform", "matrix(0.5 0.25 -0.5 0.25 0 0)");   // laid flat on the ground, along the tile axes
  poly(layer, H, "#0a0f24", { opacity: 0.45 });   // night over the grass
  const xs = p.slab.map((q) => q[0]), ys = p.slab.map((q) => q[1]), clip = sv("clipPath", { id: "slab" + uid });
  clip.append(sv("polygon", { points: pts(H) }));
  defs.append(clip);
  let paving = "";
  for (let i = Math.ceil(Math.min(...xs) / 2) * 2; i <= Math.max(...xs); i += 2) paving += lineAt(at(i, Math.min(...ys)), at(i, Math.max(...ys)));
  for (let j = Math.ceil(Math.min(...ys) / 2) * 2; j <= Math.max(...ys); j += 2) paving += lineAt(at(Math.min(...xs), j), at(Math.max(...xs), j));
  layer.append(sv("path", { d: paving, stroke: "#000", "stroke-width": 1, opacity: 0.28, fill: "none", "clip-path": "url(#slab" + uid + ")" }));
  const lot = p.lot;   // asphalt, with a white line between the bays
  poly(layer, quad(lot.x, lot.y, lot.w, lot.d, 0), "#23232d"); poly(layer, quad(lot.x, lot.y, lot.w, lot.d, 0), "none", { stroke: "#e8c020", "stroke-width": 1.5, opacity: 0.7 });
  for (let i = 0; i <= 3; i++) poly(layer, quad(lot.x + 0.25 + i * 3.3, lot.y + 0.4, 0.12, 3.4, 0), "#ddd", { opacity: 0.8 });
  for (const c of p.corridors) { poly(layer, quad(c.x, c.y, c.w, c.d, 0), pal.corr); paved(layer, defs, c.x, c.y, c.w, c.d, "tile-floor-stone", uid); }
  const rooms = Object.values(p.rooms).sort((a, b) => a.x + a.y - b.x - b.y);
  for (const r of rooms) {
    const q = quad(r.x, r.y, r.w, r.d, 0), lip = (a, b) => [a, b, down(b, 5), down(a, 5)];
    poly(layer, lip(q[3], q[2]), shade(pal.trim, -45)); poly(layer, lip(q[2], q[1]), shade(pal.trim, -65));
    poly(layer, q, pal.floorA); paved(layer, defs, r.x, r.y, r.w, r.d, r.kind === "bar" ? "tile-floor-checker" : r.kind === "outbox" ? "tile-floor-stone" : "tile-floor-parquet", uid);
    if (r.kind === "deck") poly(layer, quad(r.x + 9, r.y + 3.4, 8.4, 6.4, 0), pal.rug1, { opacity: 0.92, stroke: pal.rug2, "stroke-width": 2 });
    else if (r.kind === "bay") for (const g of r.rugs) { poly(layer, quad(g.box[0], g.box[1], g.box[2], g.box[3], 0), g.c1, { opacity: 0.9, stroke: g.c2, "stroke-width": 1.6 }); poly(layer, quad(g.box[0] + 0.25, g.box[1] + 0.25, g.box[2] - 0.5, g.box[3] - 0.5, 0), "none", { stroke: g.c2, "stroke-width": 0.8, opacity: 0.6 }); }
    else if (r.kind === "bar") poly(layer, quad(r.x + 3.5, r.y + 6.8, 5, 3, 0), pal.rug1, { opacity: 0.9, stroke: pal.rug2, "stroke-width": 1.6 });
    const gaps = (side) => doorsOf(p, r).filter((d) => d[0] === side).map((d) => [d[1], d[2]]);
    for (const [a, b] of wallRuns(r.y, r.y + r.d, gaps("w"))) wallRun(layer, "x", r.x, a, b, r.kind === "bay" ? "glass" : "brick");
    for (const [a, b] of wallRuns(r.x, r.x + r.w, gaps("n"))) wallRun(layer, "y", r.y, a, b, r.kind === "bay" ? "glass" : "brick");
    const title = r.kind === "deck" ? words.deck : r.kind === "outbox" ? words.outbox : r.kind === "bar" ? words.bar : words.bay + " " + number(r.id);
    plaque(layer, "y", r.y, r.x + r.w / 2, WALL + 16, title, pal, 0);
    const hang = (name, u, h, wpx) => { const [sw, sh] = SPR[name], c = at(u, r.y, 0, h); layer.append(sprite(name, c[0] - wpx / 2, c[1] - wpx * sh / sw / 2, wpx, wpx * sh / sw)); };   // something hung on the back wall
    if (r.kind === "deck") { hang("tile-clock-a", r.x + 13, 40, 34); hang("tile-picture-city", r.x + 8, 38, 30); hang("tile-picture-hills-a", r.x + 18, 38, 34); }
    else if (r.kind === "bar") { hang("tile-neon-a", r.x + 2.8, 42, 52); hang("tile-picture-hills-a", r.x + 9.5, 38, 32); }
    else if (r.kind === "outbox") hang("tile-clock-a", r.x + 4, 40, 30);
  }
}
function frontStatic(layer, defs, p, pal, uid) {   // what stands in front of the crew: a rail along each hallway, with a post every so often
  for (const [a, b] of p.edges) {
    const A = at(a[0], a[1]), Bq = at(b[0], b[1]), len = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(1, Math.round(len / 1.5));
    layer.append(sv("path", { d: lineAt([A[0], A[1] - 20], [Bq[0], Bq[1] - 20]), stroke: pal.trim, "stroke-width": 2.6 }), sv("path", { d: lineAt([A[0], A[1] - 10], [Bq[0], Bq[1] - 10]), stroke: pal.trim, "stroke-width": 1.1, opacity: 0.7 }));
    for (let i = 0; i <= n; i++) { const q = at(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n); layer.append(sv("path", { d: lineAt(q, [q[0], q[1] - 20]), stroke: pal.trim, "stroke-width": 2 })); }
  }
}
function doorsOf(p, r) {   // where a room's wall has a doorway: [side, from, to] in tiles along that side
  if (r.doors) return r.doors;
  const along = r.wall === "n" || r.wall === "s" ? r.entry[0] : r.entry[1], opposite = { n: "s", s: "n", e: "w", w: "e" }[r.wall];
  return [[r.wall, along - 1, along + 1], ...(r.through ? [[opposite, along - 1, along + 1]] : [])];
}
const FURN = { read: "file-cabinet", write: "writer-desk", shell: "safe", web: "radio", mcp: "switchboard", other: "cupboard", approvals: "signing-desk", ledger: "cash-register",
  desk: "report-desk", table: "planning-table", crate: "mail-cabinet", mailbox: "mail-cabinet", bar: "bar", sofa: "sofa", smalltable: "small-table" };   // the picture for each kind of furniture
function furnitureSprite(f, pal, now, defs, uid) {
  const g = sv("g", {}), [x, y, w, d] = f.box, o = f.obj, fl = f.room.f, id = "fg" + uid + f.family + Math.round(x * 3 + y * 5) + fl, fresh = o && o.last && now - o.last < 4;
  const lit = fresh || (f.family === "approvals" && o && o.pending) || (f.family === "crate" && o && o.state === "landed") || (f.lane && f.laneState === "lit") || f.family === "bar";
  const name = "furn-" + FURN[f.family] + (lit ? "-on" : "-off"), [sw, sh] = SPR[name], c = at(x + w / 2, y + d / 2, fl), wpx = Math.max(30, (w + d) * HX * 0.62), hpx = wpx * sh / sw, by = c[1] + (w + d) * HY / 2;
  poly(g, quad(x, y, w, d, fl), "#000", { opacity: 0.3, filter: FX.soft });
  const pic = sprite(name, c[0] - wpx / 2, by - hpx, wpx, hpx);
  if (facesDownLeft(f)) pic.setAttribute("transform", "translate(" + (2 * c[0]).toFixed(1) + " 0) scale(-1 1)");
  g.append(pic);
  if (fresh) g.append(sv("ellipse", { cx: c[0], cy: by - 4, rx: wpx * 0.55, ry: wpx * 0.2, fill: "none", stroke: pal.accent, "stroke-width": 3, opacity: 0.85, class: "blink amb" }));
  if (f.lane && f.laneState) { const on = f.laneState === "lit"; g.append(sv("circle", { cx: c[0] + wpx * 0.3, cy: by - hpx * 0.8, r: 5, fill: on ? pal.accent : shade(pal.dark, 20), stroke: "#000", "stroke-width": 1, class: on ? "flick amb" : "" })); }   // the handoff tray: lit once that handoff was recorded
  if (o && f.family !== "crate") {   // a count plate: how often it was used; amber dot: it asked you; red dot: denied or failed
    const n = f.family === "ledger" ? "$" + o.usd.toFixed(3) : f.family === "approvals" ? o.asked : o.used, py = by - hpx - 6;
    g.append(sv("rect", { x: c[0] - 17, y: py - 9, width: 34, height: 15, rx: 4, fill: pal.dark, stroke: pal.trim, "stroke-width": 1, opacity: 0.94 }), sv("text", { x: c[0], y: py + 2, class: "badge-n", fill: pal.ink, stroke: "none" }, String(n)));
    if (o.pending || (o.asked && f.family !== "approvals")) g.append(sv("circle", { cx: c[0] - 20, cy: py - 7, r: 4.5, fill: pal.wait, stroke: "#000", "stroke-width": 1 }));
    if (o.denied || o.failed) g.append(sv("circle", { cx: c[0] + 20, cy: py - 7, r: 4.5, fill: pal.bad, stroke: "#000", "stroke-width": 1 }));
  }
  return g;
}
function box(g, x, y, w, d, f, h0, h, base) {   // a plain block, for the few things without a picture
  const P = (px, py, hh) => at(px, py, f, hh), edge = { stroke: "#000", "stroke-width": 0.8, "stroke-opacity": 0.45 };
  poly(g, [P(x, y + d, h0), P(x + w, y + d, h0), P(x + w, y + d, h0 + h), P(x, y + d, h0 + h)], base, edge);
  poly(g, [P(x + w, y + d, h0), P(x + w, y, h0), P(x + w, y, h0 + h), P(x + w, y + d, h0 + h)], shade(base, -28), edge);
  poly(g, [P(x, y, h0 + h), P(x + w, y, h0 + h), P(x + w, y + d, h0 + h), P(x, y + d, h0 + h)], shade(base, 16), edge);
}
function stand(name, cx, by, wpx) { const [sw, sh] = SPR[name]; return sprite(name, cx - wpx / 2, by - wpx * sh / sw, wpx, wpx * sh / sw); }   // a picture standing on a spot, wpx wide
function propSprite(q, pal, defs, uid) {   // scenery: it says nothing about the run
  const g = sv("g", {}), f = q.f, [px, py] = at(q.x, q.y, f), seed = hash(Math.round(q.x * 3), Math.round(q.y * 5));
  poly(g, quad(q.x - 0.35, q.y - 0.35, 0.7, 0.7, f), "#000", { opacity: 0.25, filter: FX.soft });
  if (q.kind === "plant") g.append(stand(seed < 0.5 ? "furn-fern-off" : "furn-ficus-off", px, py + 10, 46));
  else if (q.kind === "lamp") g.append(sv("circle", { cx: px, cy: py - 50, r: 62, fill: gradient(defs, "pr" + uid + Math.round(q.x * 3 + q.y * 7), [[0, pal.lamp, 0.4], [1, pal.lamp, 0]], { r: "50%" }), class: "flick2 amb" }), stand("furn-floor-lamp-on", px, py + 10, 36));
  else if (q.kind === "tank") g.append(stand("furn-water-cooler-off", px, py + 10, 34));
  else if (q.kind === "coat") g.append(stand("furn-coat-rack-off", px, py + 10, 42));
  else if (q.kind === "bookcase") { const n = Math.max(1, Math.round((q.size || 2) / 1.1)); for (let i = 0; i < n; i++) { const p = at(q.x, q.y + (i + 0.5) * (q.size || 2) / n, f); g.append(stand("furn-bookcase-off", p[0], p[1] + 10, 54)); } }
  else if (q.kind === "tree") g.append(stand(["scene-tree-blossom", "scene-tree-pine", "scene-hedge"][Math.floor(seed * 3)], px, py + 12, [78, 64, 70][Math.floor(seed * 3)]));
  else if (q.kind === "tower") g.append(stand(seed < 0.5 ? "tile-tower-a" : "tile-tower-b", px, py + 14, 74));
  else if (q.kind === "car") g.append(stand("scene-" + (q.size || "car-black"), px, py + 14, 92));
  else if (q.kind === "lamppost") g.append(sv("circle", { cx: px, cy: py - 80, r: 70, fill: gradient(defs, "lp" + uid + Math.round(q.x * 3 + q.y * 7), [[0, pal.lamp, 0.38], [1, pal.lamp, 0]], { r: "50%" }), class: "flick2 amb" }), stand("scene-lamppost", px, py + 8, 26));
  else if (q.kind === "crates") { box(g, q.x - 0.4, q.y - 0.3, 0.8, 0.6, f, 0, 22, pal.wood); box(g, q.x + 0.3, q.y - 0.1, 0.6, 0.5, f, 0, 15, shade(pal.wood, -12)); }
  return g;
}
const CREW = __CREW__;   // each person's frames: person -> animation -> direction -> frame count (station_art/<person>-<animation>-<direction>-<nn>.png), filled in by the server
const FIGURE = {   // each person's idle picture facing south: [picture width, height, then the left, top, right and bottom of the figure in it]
  clyde: [96, 96, 30, 2, 66, 90], bonnie: [96, 96, 33, 2, 63, 90], master: [96, 96, 26, 2, 69, 90], advisor: [96, 96, 26, 2, 70, 90], newsboy: [96, 96, 32, 3, 64, 90], mechanic: [96, 96, 24, 2, 73, 90], clerk: [96, 96, 27, 2, 68, 90] };
const TYPING_FACE = { "south-west": "south-west", west: "south-west", "north-west": "south-west", south: "south", north: "south", "south-east": "south-east", east: "south-east", "north-east": "south-east" };   // the typing pictures exist for three facings
const CREW_H = 58;   // every figure is drawn this tall, standing on its spot
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
function personItem(name, role) {
  const pack = crewPack(name), box = crewBox(pack), g = sv("g", { class: "sprite", "data-sprite": name }), body = sv("g", {}), carry = sv("g", { style: "display:none" });
  const img = sv("image", { x: box.x, y: box.y, width: box.w, height: box.h, "image-rendering": "pixelated" });
  img.setAttribute("href", artUrl(crewFrame(pack, "idle", "south", 0).file));
  body.append(img);
  carry.append(sv("rect", { x: -13, y: -CREW_H * 0.5, width: 26, height: 18, rx: 2, fill: "#a8782f", stroke: "#0b0b12", "stroke-width": 1.6 }), sv("rect", { x: -2, y: -CREW_H * 0.5, width: 4, height: 18, fill: "#d8b060" }));
  const shadowEl = sv("ellipse", { cx: 0, cy: -1, rx: 13, ry: 5, fill: "#000", opacity: 0.32 }), tag = sv("g", { class: "tag", transform: "translate(0 " + (-CREW_H - 8) + ")" }), bubble = sv("g", { transform: "translate(0 " + (-CREW_H - 28) + ")" });
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
  const fill = { q: pal.wait, ok: "#3ec283", bad: pal.bad, dots: pal.accent, paper: pal.paper, mail: pal.paper, glass: pal.screen, folder: pal.accent, box: pal.wood, drink: pal.screen, smoke: pal.ink }[kind] || pal.accent;
  person.bubble.append(sv("rect", { x: -11, y: -9, width: 22, height: 18, rx: 5, fill: pal.dark, stroke: fill, "stroke-width": 2 }), sv("polygon", { points: "-3,9 3,9 0,14", fill: fill }));
  if (kind === "q") person.bubble.append(sv("text", { y: 5, class: "sign", fill, stroke: "none" }, "?"));
  else if (kind === "ok") person.bubble.append(sv("path", { d: "M-5 0l3 4 7-8", fill: "none", stroke: fill, "stroke-width": 2.5 }));
  else if (kind === "bad") person.bubble.append(sv("path", { d: "M-5 -4l10 8M5 -4l-10 8", fill: "none", stroke: fill, "stroke-width": 2.5 }));
  else if (kind === "dots") for (const [i, x] of [-6, 0, 6].entries()) person.bubble.append(sv("circle", { cx: x, cy: 0, r: 2, fill, class: "blink" + (i ? i + 1 : "") }));
  else if (kind === "paper") person.bubble.append(sv("rect", { x: -5, y: -5, width: 10, height: 10, fill }), sv("path", { d: "M-3 -2h6M-3 1h6", stroke: "#444", "stroke-width": 1 }));
  else if (kind === "mail") person.bubble.append(sv("rect", { x: -6, y: -4, width: 12, height: 8, fill }), sv("path", { d: "M-6 -4l6 5 6 -5", fill: "none", stroke: "#444", "stroke-width": 1 }));
  else if (kind === "glass") person.bubble.append(sv("circle", { cx: -1, cy: -1, r: 4, fill: "none", stroke: fill, "stroke-width": 2 }), sv("path", { d: "M2 2l4 4", stroke: fill, "stroke-width": 2 }));
  else if (kind === "folder") person.bubble.append(sv("rect", { x: -6, y: -4, width: 12, height: 8, fill }), sv("rect", { x: -6, y: -6, width: 5, height: 3, fill }));
  else if (kind === "drink") person.bubble.append(sv("path", { d: "M-5 -5h10l-2 9h-6z", fill: "none", stroke: fill, "stroke-width": 2 }), sv("path", { d: "M-3 -1h6", stroke: fill, "stroke-width": 2 }));
  else if (kind === "smoke") person.bubble.append(sv("rect", { x: -7, y: 1, width: 11, height: 3, fill: pal.paper }), sv("circle", { cx: 6, cy: 2, r: 1.6, fill: pal.wait }), sv("path", { d: "M5 -2q-3 -3 0 -5", fill: "none", stroke: fill, "stroke-width": 1.6, opacity: 0.8, class: "drift2 amb" }));
  else if (kind === "box") person.bubble.append(sv("rect", { x: -5, y: -5, width: 10, height: 10, fill, stroke: "#222", "stroke-width": 1 }));
}

// ---- assembling and animating the scene ----------------------------------------------------------------------------------
function buildScene(run) {
  const layout = run.layout, pal = THEMES.city.pal, words = THEMES.city.words, p = plan(layout), uid = ++UID;
  const B = bounds(p), [x0, y0, x1, y1] = B, now = Date.now() / 1000, events = state.feeds[run.id] || [], liveFrom = state.loadedAt - 3;
  const svg = sv("svg", { viewBox: [x0, y0, x1 - x0, y1 - y0].map((v) => v.toFixed(0)).join(" "), role: "img", "aria-label": "Station for " + (run.task || run.id) + ", a 1930s building" });
  const defs = sv("defs", {});
  svg.append(defs);
  materials(defs, uid);
  ground(svg, defs, B, pal, uid);
  const floorLayer = sv("g", {}), laneLayer = sv("g", {}), items = sv("g", {}), frontLayer = sv("g", {});
  underside(floorLayer, defs, p, pal, uid);
  worldStatic(floorLayer, defs, p, pal, uid, words);
  const order = { dark: 0, lit: 1, waiting: 2, refused: 3 };   // the strongest state is drawn last where lanes share a stretch
  const laneColor = { dark: pal.dim, lit: pal.accent, waiting: pal.wait, refused: pal.bad }, described = [];
  for (const lane of layout.hallways.slice().sort((a, b) => order[a.state] - order[b.state])) {
    const path = p.lanes[lane.id] || p.lanes[lane.kind];
    if (!path) continue;   // the two inside the front office are shown as a lamp on the desk instead
    const proj = path.map((q) => at(q[0], q[1], 0, 1)), color = laneColor[lane.state];
    const line = sv("polyline", { points: pts(proj), class: "lane " + lane.state, stroke: color, "stroke-width": lane.state === "dark" ? 3 : 5, "stroke-linejoin": "round",
      "stroke-dasharray": lane.state === "dark" ? "3 11" : lane.state === "waiting" ? "14 10" : "none", opacity: lane.state === "dark" ? 0.6 : 0.95 });
    line.append(sv("title", {}, laneTitle(lane, words)));
    laneLayer.append(line);
    if (lane.state === "lit") laneLayer.append(sv("polyline", { points: pts(proj), class: "lane", stroke: color, "stroke-width": 14, opacity: 0.14, "stroke-linejoin": "round" }));
    if (lane.state !== "dark") {   // chevrons along it, pointing the way the work goes
      const toward = lane.from === "deck" || lane.kind === "landing" ? 1 : -1;   // task and landing go away from the front office; results and approvals come back
      for (let i = 1; i < path.length; i++) {
        const a = path[i - 1], b = path[i], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len < 0.1) continue;
        const sa = at(a[0], a[1], 0, 1), sb = at(b[0], b[1], 0, 1), sl = Math.hypot(sb[0] - sa[0], sb[1] - sa[1]), ux = (sb[0] - sa[0]) / sl * toward, uy = (sb[1] - sa[1]) / sl * toward;
        for (let t = 0.8; t < len; t += 1.6) {
          const c = at(a[0] + (b[0] - a[0]) * t / len, a[1] + (b[1] - a[1]) * t / len, 0, 1);
          laneLayer.append(sv("polygon", { points: pts([[c[0] + ux * 8, c[1] + uy * 8], [c[0] - ux * 5 - uy * 6, c[1] - uy * 5 + ux * 6], [c[0] - ux * 5 + uy * 6, c[1] - uy * 5 - ux * 6]]), fill: color, opacity: 0.9, class: lane.state === "waiting" ? "blink amb" : "" }));
        }
      }
    }
  }
  for (const lane of layout.hallways) described.push(laneTitle(lane, words));
  const dyn = [];   // everything that can pass in front of or behind something else: furniture, scenery and crew, back to front
  for (const f of p.furniture) {
    if (f.lane) { const l = layout.hallways.find((h) => h.id === f.lane); f.laneState = l ? l.state : null; if (l) described.push(laneTitle(l, words)); }
    const g = furnitureSprite(f, pal, now, defs, uid), tip = f.obj && f.obj.tools ? words[f.family] + ": " + f.obj.tools.join(", ") + " · used " + f.obj.used + " · asked " + f.obj.asked + " (allowed " + f.obj.allowed + ", denied " + f.obj.denied + ")" + (f.obj.failed ? " · failed " + f.obj.failed : "")
      : f.family === "approvals" ? words.approvals + ": asked " + f.obj.asked + " · allowed " + f.obj.allowed + " · denied " + f.obj.denied + " · waiting " + f.obj.pending
      : f.family === "ledger" ? words.ledger + ": $" + f.obj.usd.toFixed(4) + (f.obj.unpriced ? " + " + f.obj.unpriced + " unpriced" : "")
      : f.family === "crate" ? words.outbox + ": " + f.obj.state : f.lane && f.laneState ? words[f.lane] + " tray: " + { dark: "not used yet", lit: "used", waiting: "waiting", refused: "refused" }[f.laneState] : (words[f.family] || f.family);
    g.append(sv("title", {}, tip));
    if (f.obj) described.push((f.room.kind === "bay" ? words.bay + " " + number(f.room.id) : f.room.kind === "deck" ? words.deck : words.outbox) + ": " + tip);
    dyn.push({ el: g, depth: () => f.box[0] + f.box[2] / 2 + f.box[1] + f.box[3] / 2 });
  }
  for (const q of p.props) dyn.push({ el: propSprite(q, pal, defs, uid), depth: () => q.x + q.y + 0.3 });
  const deck = layout.rooms.find((r) => r.id === "deck"), cards = {};
  for (const m of deck.members) cards[m.name] = m;
  for (const room of layout.rooms) for (const m of room.members || []) cards[m.name] = m;
  const crewNames = ["clyde", ...(cards.bonnie ? ["bonnie"] : []), "master", ...(cards.advisor ? ["advisor"] : []), ...p.bayRooms.map((r) => r.id)];
  const people = crewNames.map((name) => {
    const person = personItem(name, name), card = cards[name] || { name, doing: "" };
    person.card = card;
    person.g.addEventListener("click", () => { if (dragged) return; state.filter[run.id] = state.filter[run.id] === name ? null : name; draw(); });
    person.title.textContent = name + (card.model ? " · " + card.model : "") + " · " + (card.doing || "");
    described.push(name + ": " + (card.doing || ""));
    return person;
  });
  const trips = {};
  for (const person of people) {
    if (person.name === "clyde" || person.name === "bonnie") trips[person.name] = orchestratorTrips(events, person.name, p, liveFrom, !run.asks.length && run.status !== "awaiting_approval");   // not while an approval waits for you
    else if (p.rooms[person.name]) trips[person.name] = workerTrips(events, person.name, p, liveFrom, /^(idle|finished)$/.test(person.card.doing || "") && !run.asks.length);
    dyn.push({ el: person.g, person, depth: () => (person.at ? person.at[0] + person.at[1] : 0) });
  }
  frontStatic(frontLayer, defs, p, pal, uid);
  svg.append(floorLayer, laneLayer, items, frontLayer);
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
    if (Math.abs(s.dir[0]) > 0.05 || Math.abs(s.dir[1]) > 0.05) person.dir = headingDir((s.dir[0] - s.dir[1]) * HX, (s.dir[0] + s.dir[1]) * HY);   // they face the way they walk on screen, and keep it when they stop
    const typing = !moving && (pose === "work" || pose === "check") && !!(CREW[person.pack].type && CREW[person.pack].type.south);   // a crew member using a tool taps at the keys, turned toward it as far as the three typing pictures (front-left, front, front-right) allow
    person.show(typing ? TYPING_FACE[person.dir] || "south" : person.dir, moving ? "walk" : typing ? "type" : "idle", Math.floor(now * (moving ? 10 : typing ? 6 : 3)));
    let dy = 0, rot = 0, squash = 1;
    if (!REDUCED) {
      if (moving) { dy = -Math.abs(Math.sin(now * 13)) * 4; rot = Math.sin(now * 13) * 3; }
      else squash = 1 + Math.sin(now * 2.2) * 0.012;
    }
    const sp = at(s.pos[0], s.pos[1]);
    person.at = s.pos;
    person.g.setAttribute("transform", "translate(" + sp[0].toFixed(1) + " " + sp[1].toFixed(1) + ")");
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
  const more = el("details");
  more.append(el("summary", "", "About this picture"), el("span", "", "Furniture is a capability the member was given; its plate counts how often it was used. Crew walk only when something was recorded: a worker to the furniture for a tool it used, Clyde with a task or an approval request, Bonnie to collect a result. Clyde and Bonnie in the speakeasy, and the clouds, trees and lamps, are only scenery: after 25 quiet seconds the two go to the bar together and now and then look into a workshop. Drag to pan, Ctrl-scroll or the + and − keys to zoom. Pictures: generated for this project."));
  box.append(more);
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
  const left = el("div", "scene-col");
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
  const grip = el("div", "railgrip");
  grip.setAttribute("role", "separator"); grip.setAttribute("aria-orientation", "vertical"); grip.title = "Drag to resize, double-click to reset";
  side.append(grip);
  if (run.asks.length) {
    const needs = el("section", "glass asking"), head = el("h3", "", "To approve");
    head.append(el("small", "", run.asks.length + " waiting"));
    needs.append(head, asks(run));
    side.append(needs);
  }
  const box = el("section", "glass crew"), head = el("h3", "", "Crew"), body = el("div", "body");
  const working = crew.filter((m) => dotClass(m.doing) === "on").length, waiting = crew.filter((m) => dotClass(m.doing) === "wait").length;
  head.append(el("small", "", crew.length + " · " + working + " working" + (waiting ? " · " + waiting + " waiting" : "")));
  for (const m of crew) body.append(crewRow(run, m));
  box.append(head, body);
  const events = el("section", "glass");
  events.append(feed(run));
  side.append(box, events);
  return side;
}
function needsBox(run) {   // the top-left card's "needs you" list: only what waits on the user, hidden when nothing does
  const rows = needsYou([run], (id) => state.feeds[id], Date.now() / 1000, state.dismissed), box = el("div", "needs");
  if (!rows.length) { box.hidden = true; return box; }
  box.setAttribute("role", "region"); box.setAttribute("aria-label", "Needs you");
  box.append(el("div", "needs-head", "Needs you \u00b7 " + rows.length));
  for (const r of rows.slice(0, 4)) {
    const row = el("div", "need " + r.kind), age = el("span", "age", ageText(Date.now() / 1000 - r.since));
    age.dataset.since = String(r.since);
    row.append(el("i"), el("span", "grow", r.text), age);
    const look = el("button", "mini", r.kind === "approval" ? "Open" : "Look");
    look.type = "button";
    look.addEventListener("click", () => { setRail(true); if (r.kind === "failure" && r.who !== "clyde") state.filter[run.id] = r.who; draw(); });
    row.append(look);
    if (r.kind === "approval") {
      const deny = el("button", "mini", "Deny");
      deny.type = "button";
      deny.addEventListener("click", async () => { deny.disabled = true; try { await api("/api/answer", { run: run.id, id: r.id, allow: false }); } catch (e) { $status.textContent = String(e); } refresh(); });
      row.append(deny);
    } else {
      const dismiss = el("button", "mini", "Dismiss");
      dismiss.type = "button";
      dismiss.addEventListener("click", () => { state.dismissed.push(r.key); store("station.dismissed", JSON.stringify(state.dismissed.slice(-200))); draw(); });
      row.append(dismiss);
    }
    box.append(row);
  }
  if (rows.length > 4) { const more = el("button", "mini", "+" + (rows.length - 4) + " more"); more.type = "button"; more.addEventListener("click", () => { setRail(true); }); box.append(more); }
  return box;
}
function paintHeader() {   // the link chip and the crew counts: only what the server answered and the runs recorded
  const kind = linkState(state.link.ok, state.runs);
  $link.className = "chip link " + kind;
  $linkText.textContent = kind === "live" ? "live" : kind === "standby" ? "standby" : "link down";
  $link.title = kind === "live" ? "The server answers and a run is live" : kind === "standby" ? "The server answers, nothing is running" : "The server did not answer" + (state.link.reason ? ": " + state.link.reason : "");
  $retry.hidden = kind !== "down";
  $counts.textContent = state.runs.length ? countsText(crewCounts(state.runs, crewList)) : "";
}
function setLink(ok, reason) { state.link = { ok, reason: reason || "" }; paintHeader(); }
let lastSignature = "";
function draw() {
  paintHeader();
  // Rebuild only when something visible changed: a rebuild every few seconds would swap the buttons out from under a click.
  const signature = JSON.stringify([state.dismissed, state.runs, Object.keys(state.feeds).map((id) => [id, state.feeds[id].length]), state.filter, state.theme]);
  if (signature === lastSignature) return;
  lastSignature = signature;
  $rail.classList.toggle("alert", state.runs.some((r) => r.asks.length));   // a request for your OK never hides behind a closed panel
  $runs.replaceChildren();
  state.scenes = [];
  if (!state.runs.length) { $runs.append(el("div", "empty", "No runs yet. Start one with /orchestrate in clyde.")); return; }
  for (const run of state.runs) {
    const section = el("section", "run");
    const head = el("div", "run-head");
    const spend = "$" + run.spend.usd.toFixed(4) + (run.spend.unpriced ? " + " + run.spend.unpriced + " unpriced" : "");
    head.append(el("h2", "", run.task || run.id), el("span", "chip " + run.status, run.status.replace("_", " ")), el("span", "chip", spend), el("span", "chip run-id", run.id));
    const info = el("div", "run-info");
    info.append(head, el("div", "clyde", "Clyde: " + run.clyde), needsBox(run));
    section.append(info);
    const body = el("div", "run-body");
    body.append(mapSection(run), rail(run));
    section.append(body);
    $runs.append(section);
  }
}
async function refresh() {
  try {
    state.runs = (await api("/api/state")).runs;
    setLink(true);
  } catch (e) { setLink(false, e.message); }
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
      setLink(true);
      if (data.events.length) {
        state.feeds[id] = (state.feeds[id] || []).concat(data.events);
        after = data.next;
        const fresh = (await api("/api/state?run=" + encodeURIComponent(id))).runs[0];
        const at = state.runs.findIndex((r) => r.id === id);
        if (fresh && at >= 0) state.runs[at] = fresh;
        draw();
      }
    } catch (e) { setLink(false, e.message); await new Promise((r) => setTimeout(r, 2000)); }
  }
}
function setRail(on) {   // the crew and events panel slides away so the scene has the whole window
  document.body.classList.toggle("rail-off", !on);
  $rail.setAttribute("aria-pressed", String(on));
  store("station.rail", on ? "1" : "0");
}
const savedRail = stored("station.rail");
setRail(savedRail === null ? window.innerWidth >= 900 : savedRail === "1");
$rail.addEventListener("click", () => setRail(document.body.classList.contains("rail-off")));
$retry.addEventListener("click", () => refresh());
const $cinema = document.getElementById("cinemaToggle");
function setCinema(on) {   // every panel away: the island alone, remembered, with a slim tab to bring them back
  document.body.classList.toggle("cinema", on);
  $cinema.setAttribute("aria-pressed", String(on));
  store("station.cinema", on ? "1" : "0");
}
setCinema(stored("station.cinema") === "1");
$cinema.addEventListener("click", () => setCinema(true));
document.getElementById("cinemaTab").addEventListener("click", () => setCinema(false));
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target.tagName || ""))) return;
  if (e.key === "c" || e.key === "C") setCinema(!document.body.classList.contains("cinema"));
  else if (e.key === "Escape" && document.body.classList.contains("cinema")) setCinema(false);
});
const railW = stored("station.railw");   // the panel's width: drag its edge; a double click puts it back
if (railW) document.documentElement.style.setProperty("--railw", railW + "px");
document.addEventListener("pointerdown", (e) => {
  if (!e.target.classList || !e.target.classList.contains("railgrip")) return;
  e.preventDefault();
  const move = (m) => { const w = Math.round(Math.max(260, Math.min(560, window.innerWidth - m.clientX - 12))); document.documentElement.style.setProperty("--railw", w + "px"); store("station.railw", String(w)); };
  const stop = () => { document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", stop); };
  document.addEventListener("pointermove", move); document.addEventListener("pointerup", stop);
});
document.addEventListener("dblclick", (e) => { if (e.target.classList && e.target.classList.contains("railgrip")) { document.documentElement.style.removeProperty("--railw"); store("station.railw", ""); } });
for (const pack in CREW) for (const anim in CREW[pack]) for (const dir in CREW[pack][anim]) preload(pack, anim, dir);   // every picture is fetched once up front, so a frame never blinks while it loads
try { state.dismissed = JSON.parse(stored("station.dismissed") || "[]"); } catch (e) { state.dismissed = []; }
setInterval(() => { for (const age of document.querySelectorAll("[data-since]")) age.textContent = ageText(Date.now() / 1000 - Number(age.dataset.since)); }, 15000);   // how long each row has waited
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
