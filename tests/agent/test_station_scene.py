"""The station's floor plan and the crew's movement, run as the page runs them (in Node): nothing blocks a walkway, every hallway
line sits on a corridor, and everyone moves only when something was recorded."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.agent.station_page import PAGE


def _block(name: str) -> str:
    found = re.search(rf"// <{name}>\n(.*?)// </{name}>", PAGE, re.S)
    assert found, name
    return found.group(1)


# The page's geometry and motion code, plus a harness that checks it; it prints the failures as JSON.
HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const code = fs.readFileSync(process.argv[2], "utf8");
const reduced = process.argv[3] === "reduced";
const ctx = { Math, console, parseInt, REDUCED: reduced };
vm.createContext(ctx);
vm.runInContext(code + "\nthis.__api = { facesDownLeft, needsYou, ageText, memberState, crewCounts, countsText, linkState, QUIET, plan, bounds, family, workerTrips, orchestratorTrips, walkerState, tripState, tripEnd };", ctx);
const A = ctx.__api, fails = [];
const FAMILIES = ["read", "write", "shell", "web", "mcp", "other"];
const bay = (i) => ({ id: "worker-" + i, kind: "bay", members: [], objects: FAMILIES.map((f) => ({ family: f, tools: [f], used: 0, asked: 0, allowed: 0, denied: 0, failed: 0, last: null })) });
const layoutFor = (n) => ({ rooms: [{ id: "deck", kind: "deck", members: [], objects: [{ family: "approvals", asked: 0, allowed: 0, denied: 0, pending: 0 }, { family: "ledger", usd: 0, unpriced: 0 }] },
  ...Array.from({ length: n }, (_, i) => bay(i + 1)), { id: "outbox", kind: "outbox", state: "empty" }], hallways: [] });
const inside = (r, x, y, e) => x > r.x - e && x < r.x + r.w + e && y > r.y - e && y < r.y + r.d + e;
const overlap = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0.01 && Math.min(a.y + a.d, b.y + b.d) - Math.max(a.y, b.y) > 0.01;
const boxOf = (b) => ({ x: b[0], y: b[1], w: b[2], d: b[3] });
const propBox = (q) => q.kind === "bookcase" ? { x: q.x, y: q.y, w: 0.9, d: q.size || 3.4 } : { x: q.x - 0.45, y: q.y - 0.45, w: 0.9, d: 0.9 };
const LAYOUT = [], MOTION = [];
for (const n of [1, 2, 3, 4, 5, 7]) {
  const p = A.plan(layoutFor(n)), tag = "n=" + n + ": ";
  const solids = [...p.furniture.map((f) => ({ what: f.family + " in " + f.room.id, ...boxOf(f.box) })), ...p.props.map((q) => ({ what: q.kind + " near " + q.x.toFixed(1) + "," + q.y.toFixed(1), ...propBox(q) }))];
  // 1. every path a person can take is clear of every solid
  const paths = [];
  for (const r of p.bayRooms) {
    paths.push(["door to worker in " + r.id, [r.entry, p.homes[r.id]]]);
    for (const f of FAMILIES) paths.push([r.id + " to " + f, [p.homes[r.id], p.stands[r.id + ":" + f]]]);
    paths.push([r.id + " check spot", [p.homes[r.id], p.checkStands[r.id]]]);
    for (const who of ["clyde", "bonnie"]) paths.push([who + " to " + r.id, p.route("deck", p.homes[who], r.id, p.checkStands[r.id])]);
  }
  for (const who of ["clyde", "bonnie"]) paths.push([who + " to the outbox", p.route("deck", p.homes[who], "outbox", p.checkStands.outbox)], [who + " to the bar", p.route("deck", p.homes[who], "bar", p.barSpots[who])], [who + " back from the bar", p.route("bar", p.barSpots[who], "deck", p.homes[who])]);
  paths.push(["master to clyde", [p.homes.master, p.homes.clyde]], ["advisor to clyde", [p.homes.advisor, p.homes.clyde]]);
  for (const [name, pts] of paths) for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    for (let t = 0; t <= len; t += 0.15) {
      const x = a[0] + (b[0] - a[0]) * t / len, y = a[1] + (b[1] - a[1]) * t / len;
      for (const s of solids) if (inside(s, x, y, 0.25)) { LAYOUT.push(tag + name + " passes through " + s.what); break; }
    }
  }
  // 1b. a worker stands beside the furniture for a tool, and looks at it
  for (const r of p.bayRooms) for (const f of FAMILIES) {
    const st = p.stands[r.id + ":" + f], piece = p.furniture.find((q) => q.room.id === r.id && q.family === f), b = boxOf(piece.box);
    const gap = Math.hypot(Math.max(b.x - st[0], 0, st[0] - (b.x + b.w)), Math.max(b.y - st[1], 0, st[1] - (b.y + b.d)));
    if (gap > 2.4) LAYOUT.push(tag + "the stand for " + f + " in " + r.id + " is " + gap.toFixed(1) + " tiles from its furniture");
    const trip = A.workerTrips([{ t: 1001, who: r.id, kind: "tool_use", tool: { read: "Read", write: "Edit", shell: "Bash", web: "WebFetch", mcp: "mcp__x", other: "Foo" }[f] }], r.id, p, 1000)[0], to = [b.x + b.w / 2 - st[0], b.y + b.d / 2 - st[1]];
    if (!trip || trip.face[0] * to[0] + trip.face[1] * to[1] <= 0) LAYOUT.push(tag + r.id + " does not face its " + f + " furniture");
  }
  // 1c. a one-sided piece never stands against a south or east wall, where its front would face out of the room
  for (const f of p.furniture) {
    if (["table", "smalltable"].includes(f.family) || f.room.kind === "outbox") continue;
    const r = f.room, cx = f.box[0] + f.box[2] / 2 - r.x, cy = f.box[1] + f.box[3] / 2 - r.y, dS = r.d - cy, dE = r.w - cx;
    if (Math.min(dS, dE) < 2.2 && Math.min(dS, dE) < Math.min(cx, cy)) LAYOUT.push(tag + f.family + " in " + r.id + " stands against the " + (dS < dE ? "south" : "east") + " wall");
  }
  // 2. nothing stands inside another thing, and everything is inside its room
  for (let i = 0; i < solids.length; i++) for (let j = i + 1; j < solids.length; j++) if (overlap(solids[i], solids[j])) LAYOUT.push(tag + solids[i].what + " overlaps " + solids[j].what);
  for (const f of p.furniture) { const b = boxOf(f.box), r = f.room; if (b.x < r.x || b.y < r.y || b.x + b.w > r.x + r.w || b.y + b.d > r.y + r.d) LAYOUT.push(tag + f.family + " leaves " + r.id); }
  // 3. every hallway line lies on a corridor (or in a room): it follows the walkway it claims to
  const onFloor = (x, y) => p.corridors.some((c) => inside(c, x, y, 0.01)) || Object.values(p.rooms).some((r) => inside(r, x, y, 0.01));
  for (const [id, line] of Object.entries(p.lanes)) for (let i = 0; i < line.length; i++) {
    if (!onFloor(line[i][0], line[i][1])) LAYOUT.push(tag + "lane " + id + " vertex " + i + " is off the floor");
    if (i) for (let t = 0; t <= 1; t += 0.1) if (!onFloor(line[i - 1][0] + (line[i][0] - line[i - 1][0]) * t, line[i - 1][1] + (line[i][1] - line[i - 1][1]) * t)) { LAYOUT.push(tag + "lane " + id + " leaves the floor"); break; }
  }
  // 4. corridors meet the doors and never run through a room
  for (const r of p.bayRooms) if (!p.corridors.some((c) => inside(c, r.entry[0], r.entry[1], 0.01))) LAYOUT.push(tag + "no corridor ends at the door of " + r.id);
  for (const c of p.corridors) for (const r of Object.values(p.rooms)) if (overlap(c, r)) LAYOUT.push(tag + "a corridor runs through " + r.id);
  const roomList = Object.values(p.rooms);
  for (const a of roomList) for (const b of roomList) if (a.id < b.id && overlap(a, b)) LAYOUT.push(tag + a.id + " overlaps " + b.id);
  // 5. the walkways are one connected whole: from the deck, corridors and rooms reach each other through their doors
  const touch = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) >= -1e-6 && Math.min(a.y + a.d, b.y + b.d) - Math.max(a.y, b.y) >= -1e-6;
  const nodes = [...roomList.map((r) => ({ id: r.id, ...r })), ...p.corridors.map((c, i) => ({ id: "corridor " + i, ...c }))], seen = new Set(["deck"]);
  for (let again = true; again;) { again = false; for (const a of nodes) if (!seen.has(a.id) && nodes.some((b) => seen.has(b.id) && touch(a, b) && (a.id.startsWith("corridor") !== b.id.startsWith("corridor")) || nodes.some((b) => seen.has(b.id) && touch(a, b) && a.id.startsWith("corridor") && b.id.startsWith("corridor")))) { seen.add(a.id); again = true; } }
  if (seen.size !== nodes.length) LAYOUT.push(tag + "not everything is connected by walkways: " + nodes.filter((a) => !seen.has(a.id)).map((a) => a.id).join(", "));
}
// 6. the crew move only on a record: a trip per event, none for history, the walk continuous, reduced motion instant
const p = A.plan(layoutFor(2)), live = 1000;
const ev = (t, who, kind, extra) => ({ t, who, kind, ...(extra || {}) });
const old = A.workerTrips([ev(10, "worker-1", "tool_use", { tool: "Edit" })], "worker-1", p, live);
if (old.length) MOTION.push("history older than the page was replayed");
const trips = A.workerTrips([ev(1001, "worker-1", "tool_use", { tool: "Edit" }), ev(1010, "worker-1", "tool_use", { tool: "Bash" }), ev(1011, "worker-2", "tool_use", { tool: "Edit" })], "worker-1", p, live);
if (trips.length !== 2) MOTION.push("expected one trip per tool use, got " + trips.length);
const home = p.homes["worker-1"], at = (t) => A.walkerState(trips, home, t);
if (at(1000.9).pose !== "idle" || at(1000.9).pos[0] !== home[0]) MOTION.push("moved before anything was recorded");
const mid = at(1001.4);
if (reduced ? mid.pose !== "work" : mid.pose !== "walk") MOTION.push("wrong pose just after a tool use: " + mid.pose);
const stand = p.stands["worker-1:write"], there = at(1001 + (reduced ? 1 : 3));
if (Math.hypot(there.pos[0] - stand[0], there.pos[1] - stand[1]) > 1e-6 || there.pose !== "work") MOTION.push("did not stand at the furniture for Edit");
const back = at(1008);
if (back.pose !== "idle" || Math.hypot(back.pos[0] - home[0], back.pos[1] - home[1]) > 1e-6) MOTION.push("did not return home");
if (!reduced) { let last = at(1001), jump = 0; for (let t = 1001; t < 1012; t += 0.05) { const s = at(t); jump = Math.max(jump, Math.hypot(s.pos[0] - last.pos[0], s.pos[1] - last.pos[1])); last = s; } if (jump > 0.5) MOTION.push("the walk jumps " + jump.toFixed(2) + " tiles in 50 ms"); }
const checks = [ev(1001, "clyde", "check", { target: "worker-1", reason: "brief" }), ev(1001.2, "clyde", "check", { target: "worker-2", reason: "approval" }), ev(1002, "bonnie", "check", { target: "worker-2", reason: "result" }), ev(10, "clyde", "check", { target: "worker-1", reason: "brief" })];
const clyde = A.orchestratorTrips(checks, "clyde", p, live), bonnie = A.orchestratorTrips(checks, "bonnie", p, live);
if (clyde.length !== 2 || bonnie.length !== 1) MOTION.push("checks became " + clyde.length + " and " + bonnie.length + " trips (history must not replay)");
if (clyde.length === 2 && clyde[1].t0 < A.tripEnd(clyde[0]) - 1e-9) MOTION.push("Clyde started a second walk before finishing the first");
const door = p.rooms["worker-1"].entry;
if (clyde.length && !clyde[0].go.some((q) => Math.hypot(q[0] - door[0], q[1] - door[1]) < 2.5)) MOTION.push("Clyde's walk to worker-1 does not pass its door");
const homeAgain = A.walkerState(clyde, p.homes.clyde, 1500);
if (Math.hypot(homeAgain.pos[0] - p.homes.clyde[0], homeAgain.pos[1] - p.homes.clyde[1]) > 1e-6) MOTION.push("Clyde did not end at home");
const landed = A.orchestratorTrips([ev(1005, "user", "landed", { outbox: "/x" })], "clyde", p, live);
const end = landed.length ? landed[0].go[landed[0].go.length - 1] : [0, 0];
if (landed.length !== 1 || Math.hypot(end[0] - p.checkStands.outbox[0], end[1] - p.checkStands.outbox[1]) > 1e-6) MOTION.push("landing did not send Clyde to the outbox");
// 7. a quiet spell: Clyde and Bonnie go to the bar together, not before QUIET seconds with nothing recorded, and a record ends it after the leg they are on
const quietEvents = [ev(1001, "worker-1", "tool_use", { tool: "Edit" })];
const lc = A.orchestratorTrips(quietEvents, "clyde", p, live, true), lb = A.orchestratorTrips(quietEvents, "bonnie", p, live, true);
if (!lc.length || !lc.every((q) => q.leisure)) MOTION.push("no leisure after a quiet spell");
else {
  if (lc[0].t0 < 1001 + A.QUIET - 1e-9) MOTION.push("they left for the bar before " + A.QUIET + " quiet seconds");
  if (!lb.length || Math.abs(lc[0].t0 - lb[0].t0) > 1e-9) MOTION.push("Clyde and Bonnie did not leave together");
  const bar = p.rooms.bar, spot = lc[0].back[lc[0].back.length - 1];
  if (!(spot[0] > bar.x && spot[0] < bar.x + bar.w && spot[1] > bar.y && spot[1] < bar.y + bar.d)) MOTION.push("the leisure walk does not end in the bar");
  if (!lc.some((q) => q.go.some((pt) => Math.hypot(pt[0] - p.rooms["worker-1"].inner[0], pt[1] - p.rooms["worker-1"].inner[1]) < 1e-9))) MOTION.push("they never looked into a workshop");
}
if (A.orchestratorTrips(quietEvents, "clyde", p, live).length) MOTION.push("leisure without being asked for");
// an idle worker goes to the bar after the quiet, its own work first; a busy one never does
const idleW = A.workerTrips(quietEvents, "worker-1", p, live, true), busyW = A.workerTrips(quietEvents, "worker-1", p, live, false);
if (busyW.length !== 1) MOTION.push("a busy worker got " + busyW.length + " trips");
const leisureW = idleW.filter((q) => q.leisure);
if (idleW.length < 2 || !leisureW.length) MOTION.push("an idle worker never went to the bar");
else {
  if (leisureW[0].t0 < A.tripEnd(idleW[0]) - 1e-9 || leisureW[0].t0 < 1001 + A.QUIET - 1e-9) MOTION.push("the worker left for the bar too early");
  const bar = p.rooms.bar, spot = leisureW[0].back[leisureW[0].back.length - 1];
  if (!(spot[0] > bar.x && spot[0] < bar.x + bar.w && spot[1] > bar.y && spot[1] < bar.y + bar.d)) MOTION.push("the worker's bar spot is outside the bar");
  if (leisureW.some((q) => q.go.some((pt) => Math.hypot(pt[0] - p.rooms["worker-2"].inner[0], pt[1] - p.rooms["worker-2"].inner[1]) < 1e-9))) MOTION.push("a worker toured another workshop");
}
if (A.workerTrips([], "worker-2", p, live, true).length === 0) MOTION.push("a worker with nothing ever recorded never went to the bar");
if (new Set(p.bayRooms.map((r) => p.barSpots[r.id].join())).size !== p.bayRooms.length) MOTION.push("two workers share a spot at the bar");
for (const r of p.bayRooms) { const sp = p.barSpots[r.id], route = p.route(r.id, p.homes[r.id], "bar", sp); for (let i = 1; i < route.length; i++) for (let t = 0; t <= 1; t += 0.05) { const x = route[i - 1][0] + (route[i][0] - route[i - 1][0]) * t, y = route[i - 1][1] + (route[i][1] - route[i - 1][1]) * t; for (const f of p.furniture) if (f.room.id === "bar" && x > f.box[0] - 0.25 && x < f.box[0] + f.box[2] + 0.25 && y > f.box[1] - 0.25 && y < f.box[1] + f.box[3] + 0.25) { MOTION.push(r.id + " walks through the " + f.family + " in the bar"); t = 2; } } }
const busy = A.orchestratorTrips([...quietEvents, ev(1100, "clyde", "check", { target: "worker-1", reason: "brief" })], "clyde", p, live, true), job = busy.find((q) => !q.leisure);
if (!job) MOTION.push("the check was lost among the leisure walks");
else {
  const before = busy.filter((q) => q.leisure && q.t0 < job.t0), last = before[before.length - 1];
  if (last && job.t0 < A.tripEnd(last) - 1e-9) MOTION.push("a check started before the walk Clyde was on ended: he would jump");
  if (last && Math.hypot(job.go[0][0] - last.back[last.back.length - 1][0], job.go[0][1] - last.back[last.back.length - 1][1]) > 1e-9) MOTION.push("a check did not start where the leisure walk ended");
}
// 8. the header: working only while the run is live, waiting and failed shown only when there are some, the link neutral until something runs
const crewOf = (r) => r.crew, mk = (status, ...doing) => ({ status, crew: doing.map((d) => ({ name: "x", doing: d })) });
const counts = A.crewCounts([mk("running", "using Edit", "idle", "waiting for approval", "failed"), mk("done", "using Read", "finished")], crewOf);
if (counts.working !== 1 || counts.waiting !== 1 || counts.failed !== 1 || counts.idle !== 3) MOTION.push("crew counts were " + JSON.stringify(counts));
if (A.crewCounts([mk("done", "using Edit")], crewOf).working !== 0) MOTION.push("someone is working in a finished run");
if (A.countsText({ working: 2, waiting: 0, failed: 0, idle: 5 }) !== "2 working \u00b7 5 idle") MOTION.push("counts text: " + A.countsText({ working: 2, waiting: 0, failed: 0, idle: 5 }));
if (A.countsText({ working: 1, waiting: 2, failed: 1, idle: 0 }) !== "1 working \u00b7 2 waiting \u00b7 1 failed \u00b7 0 idle") MOTION.push("counts text with waiting and failed");
if (A.linkState(false, [mk("running")]) !== "down" || A.linkState(true, []) !== "standby" || A.linkState(true, [mk("done")]) !== "standby" || A.linkState(true, [mk("running")]) !== "live") MOTION.push("link states are wrong");
// 10. furniture faces into its room: the pictures face down-right, so a piece on the north wall is mirrored to face down-left and a piece on the west wall keeps its picture
{
  const q = A.plan(layoutFor(3)), bay = q.rooms["worker-1"], wallN = { room: bay, box: [bay.x + 3, bay.y + 0.3, 1.5, 1] }, wallW = { room: bay, box: [bay.x + 0.3, bay.y + 3.5, 1, 1.5] };
  if (!A.facesDownLeft(wallN) || A.facesDownLeft(wallW)) MOTION.push("north-wall pieces are mirrored and west-wall pieces keep their picture");
  if (A.facesDownLeft({ room: bay, box: wallN.box, flip: false }) || !A.facesDownLeft({ room: bay, box: wallW.box, flip: true })) MOTION.push("an explicit facing wins");
  const sofas = q.furniture.filter((f) => f.family === "sofa");
  if (sofas.length !== 2 || sofas.filter((f) => A.facesDownLeft(f)).length !== 1) MOTION.push("one bar sofa faces down-left from the north wall, the other faces down-right from the west wall");
  const bar = q.furniture.find((f) => f.family === "bar");
  if (!A.facesDownLeft(bar)) MOTION.push("the bar counter on the north wall faces the room");
}
// 9. what waits on the user: a pending request (never ages out), a worker whose last event is a failure, a failed run; not what recovered, was dismissed or is days old
const ne = (events) => (id) => events[id] || [], nowT = 10 * 24 * 3600;
const nrun = (id, status, asks) => ({ id, status, asks: asks || [], started: nowT - 500 });
const rowsOf = (runs, events, dismissed) => A.needsYou(runs, ne(events), nowT, dismissed || []);
let rows = rowsOf([nrun("r1", "running", [{ id: "a1", who: "worker-1", tool: "Bash", t: nowT - 90 }])], { r1: [] });
if (rows.length !== 1 || rows[0].kind !== "approval" || rows[0].text !== "worker-1 wants to use Bash" || rows[0].since !== nowT - 90) MOTION.push("approval row: " + JSON.stringify(rows));
if (rowsOf([nrun("r1", "awaiting_approval", [{ id: "a1", who: "w", tool: "Edit", t: 1 }])], { r1: [] }).length !== 1) MOTION.push("a pending request must never age out");
rows = rowsOf([nrun("r1", "running")], { r1: [{ t: nowT - 60, who: "worker-2", kind: "started" }, { t: nowT - 30, who: "worker-2", kind: "failed" }] });
if (rows.length !== 1 || rows[0].text !== "worker-2 failed" || rows[0].kind !== "failure") MOTION.push("failed worker row: " + JSON.stringify(rows));
rows = rowsOf([nrun("r1", "running")], { r1: [{ t: nowT - 30, who: "worker-3", kind: "tool_error", tool: "Bash" }, { t: nowT - 10, who: "worker-3", kind: "tool_use", tool: "Read" }] });
if (rows.length) MOTION.push("a worker that went on after a tool error is still listed");
rows = rowsOf([nrun("r1", "running")], { r1: [{ t: nowT - 30, who: "worker-3", kind: "tool_error", tool: "Bash" }, { t: nowT - 20, who: "worker-3", kind: "check" }] });
if (rows.length !== 1 || rows[0].text !== "worker-3: Bash failed") MOTION.push("a tool error that is the last thing recorded: " + JSON.stringify(rows));
rows = rowsOf([nrun("r1", "failed")], { r1: [{ t: nowT - 5, who: "clyde", kind: "status" }] });
if (rows.length !== 1 || rows[0].text !== "the run failed") MOTION.push("failed run row: " + JSON.stringify(rows));
if (rowsOf([nrun("r1", "running")], { r1: [{ t: nowT - 4 * 24 * 3600, who: "worker-1", kind: "failed" }] }).length) MOTION.push("a failure older than 3 days is still listed");
const failedOnce = { r1: [{ t: nowT - 30, who: "worker-2", kind: "failed" }] }, key = rowsOf([nrun("r1", "running")], failedOnce)[0].key;
if (rowsOf([nrun("r1", "running")], failedOnce, [key]).length) MOTION.push("a dismissed row came back");
if (rowsOf([nrun("r1", "done")], { r1: [] }).length) MOTION.push("rows with nothing waiting");
const order = rowsOf([nrun("r1", "running", [{ id: "a", who: "w", tool: "Edit", t: nowT - 10 }])], { r1: [{ t: nowT - 100, who: "worker-2", kind: "failed" }] });
if (order.length !== 2 || order[0].kind !== "failure") MOTION.push("the longest-waiting row goes first");
if (A.ageText(5) !== "5s" || A.ageText(125) !== "2m" || A.ageText(7300) !== "2h" || A.ageText(200000) !== "2d") MOTION.push("age text");
console.log(JSON.stringify({ layout: LAYOUT, motion: MOTION }));
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class StationScene(unittest.TestCase):
    def _run(self, *flags: str) -> dict[str, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            code, harness = Path(tmp) / "page_blocks.js", Path(tmp) / "harness.js"
            code.write_text(_block("geometry") + _block("motion") + _block("status"), encoding="utf-8")
            harness.write_text(HARNESS, encoding="utf-8")
            done = subprocess.run(["node", str(harness), str(code), *flags], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_nothing_blocks_a_walkway_every_hallway_line_is_on_a_corridor_and_the_corridors_connect(self):
        self.assertEqual(self._run()["layout"], [])

    def test_the_crew_move_only_on_a_record_and_never_jump(self):
        self.assertEqual(self._run()["motion"], [])

    def test_with_reduced_motion_the_crew_appear_at_the_spot_instead_of_walking(self):
        self.assertEqual(self._run("reduced")["motion"], [])


if __name__ == "__main__":
    unittest.main()
