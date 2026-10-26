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
vm.runInContext(code + "\nthis.__api = { plan, bounds, family, workerTrips, orchestratorTrips, walkerState, tripState, tripEnd };", ctx);
const A = ctx.__api, fails = [];
const FAMILIES = ["read", "write", "shell", "web", "mcp", "other"];
const bay = (i) => ({ id: "worker-" + i, kind: "bay", members: [], objects: FAMILIES.map((f) => ({ family: f, tools: [f], used: 0, asked: 0, allowed: 0, denied: 0, failed: 0, last: null })) });
const layoutFor = (n) => ({ rooms: [{ id: "deck", kind: "deck", members: [], objects: [{ family: "approvals", asked: 0, allowed: 0, denied: 0, pending: 0 }, { family: "ledger", usd: 0, unpriced: 0 }] },
  ...Array.from({ length: n }, (_, i) => bay(i + 1)), { id: "outbox", kind: "outbox", state: "empty" }], hallways: [] });
const inside = (r, x, y, e) => x > r.x - e && x < r.x + r.w + e && y > r.y - e && y < r.y + r.d + e;
const overlap = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0.01 && Math.min(a.y + a.d, b.y + b.d) - Math.max(a.y, b.y) > 0.01;
const boxOf = (b) => ({ x: b[0], y: b[1], w: b[2], d: b[3] });
const propBox = (p) => p[0] === "bookcase" ? { x: p[1], y: p[2], w: 0.9, d: p[3] || 3.4 } : { x: p[1] - 0.45, y: p[2] - 0.45, w: 0.9, d: 0.9 };
const LAYOUT = [], MOTION = [];
for (const n of [1, 2, 3, 5]) {
  const p = A.plan(layoutFor(n)), tag = "n=" + n + ": ";
  const solids = [...p.furniture.map((f) => ({ what: f.family + " in " + f.room.id, ...boxOf(f.box) })), ...p.props.map((q) => ({ what: q[0] + " near " + q[1].toFixed(1) + "," + q[2].toFixed(1), ...propBox(q) }))];
  // 1. every path a person can take is clear of every solid
  const paths = [];
  for (const r of p.bayRooms) {
    paths.push(["door to worker in " + r.id, [[r.x + p.BW / 2, r.y], p.homes[r.id]]]);
    for (const f of FAMILIES) paths.push([r.id + " to " + f, [p.homes[r.id], p.stands[r.id + ":" + f]]]);
    paths.push([r.id + " check spot", [p.homes[r.id], p.checkStands[r.id]]]);
    for (const who of ["clyde", "bonnie"]) paths.push([who + " to " + r.id, p.route("deck", p.homes[who], r.id, p.checkStands[r.id])]);
  }
  for (const who of ["clyde", "bonnie"]) paths.push([who + " to the outbox", p.route("deck", p.homes[who], "outbox", p.checkStands.outbox)]);
  paths.push(["master to clyde", [p.homes.master, p.homes.clyde]], ["advisor to clyde", [p.homes.advisor, p.homes.clyde]]);
  for (const [name, pts] of paths) for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    for (let t = 0; t <= len; t += 0.15) {
      const x = a[0] + (b[0] - a[0]) * t / len, y = a[1] + (b[1] - a[1]) * t / len;
      for (const s of solids) if (inside(s, x, y, 0.25)) { LAYOUT.push(tag + name + " passes through " + s.what); break; }
    }
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
  for (const r of p.bayRooms) if (!p.corridors.some((c) => Math.abs(c.x - (r.x + p.BW / 2 - 1)) < 1e-6 && c.w === 2 && Math.abs(c.y + c.d - r.y) < 1e-6)) LAYOUT.push(tag + "no corridor ends at the door of " + r.id);
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
const door = [p.rooms["worker-1"].x + p.BW / 2, p.rooms["worker-1"].y];
if (clyde.length && !clyde[0].go.some((q) => Math.hypot(q[0] - door[0], q[1] - door[1]) < 2.5)) MOTION.push("Clyde's walk to worker-1 does not pass its door");
const homeAgain = A.walkerState(clyde, p.homes.clyde, 1500);
if (Math.hypot(homeAgain.pos[0] - p.homes.clyde[0], homeAgain.pos[1] - p.homes.clyde[1]) > 1e-6) MOTION.push("Clyde did not end at home");
const landed = A.orchestratorTrips([ev(1005, "user", "landed", { outbox: "/x" })], "clyde", p, live);
const end = landed.length ? landed[0].go[landed[0].go.length - 1] : [0, 0];
if (landed.length !== 1 || Math.hypot(end[0] - p.checkStands.outbox[0], end[1] - p.checkStands.outbox[1]) > 1e-6) MOTION.push("landing did not send Clyde to the outbox");
console.log(JSON.stringify({ layout: LAYOUT, motion: MOTION }));
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class StationScene(unittest.TestCase):
    def _run(self, *flags: str) -> dict[str, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            code, harness = Path(tmp) / "page_blocks.js", Path(tmp) / "harness.js"
            code.write_text(_block("geometry") + _block("motion"), encoding="utf-8")
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
