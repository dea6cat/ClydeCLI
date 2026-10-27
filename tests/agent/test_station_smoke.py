"""The station page's own code, run in Node against a stub DOM: it loads, draws the whole page for a run, and animates the crew without an error.
Caught by this and nothing else: a helper deleted by mistake leaves a blank page while every other test still passes."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.agent.station_page import PAGE

HARNESS = r"""
const vm = require("vm"), fs = require("fs");
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.style = { setProperty() {}, removeProperty() {} }; this.dataset = {}; this.className = ""; this.hidden = false; this.textContent = ""; this.title = "";
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false }; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k]; } append(...c) { this.children.push(...c); } appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...c) { this.children = c; } addEventListener() {} removeEventListener() {} setPointerCapture() {} remove() {} focus() {}
  querySelector() { return new El("q"); } querySelectorAll() { return []; } getBoundingClientRect() { return { left: 0, top: 0, width: 1000, height: 500, right: 1000, bottom: 500 }; }
  get lastChild() { return this.children[this.children.length - 1]; }
}
const document = { getElementById: () => new El("id"), createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t), createTextNode: (t) => { const e = new El("#text"); e.textContent = t; return e; },
  body: new El("body"), documentElement: new El("html"), addEventListener() {}, querySelectorAll: () => [] };
const ctx = { document, window: { matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() {} }, localStorage: { getItem: () => null, setItem() {} },
  fetch: () => Promise.reject(new Error("no network in the smoke test")), setInterval() {}, setTimeout() {}, requestAnimationFrame() {}, Image: class { set src(v) {} },
  performance: { now: () => 0 }, Date, JSON, Math, console, parseInt, parseFloat, Number, String, Array, Object, Set, Map, Promise, Error, RegExp };
ctx.globalThis = ctx;
vm.createContext(ctx);
const code = fs.readFileSync(process.argv[2], "utf8"), n = +process.argv[3];
const smoke = `
function countNodes(e) { return 1 + e.children.reduce((a, c) => a + (c && c.children ? countNodes(c) : 0), 0); }
const FAMILIES = ["read", "write", "shell", "web", "mcp", "other"];
const bay = (i) => ({ id: "worker-" + i, kind: "bay", members: [], objects: FAMILIES.map((f) => ({ family: f, tools: [f], used: 3, asked: 1, allowed: 1, denied: 0, failed: 0, last: Date.now() / 1000 })) });
const layout = { rooms: [{ id: "deck", kind: "deck", members: [{ name: "bonnie", doing: "idle" }, { name: "master", doing: "idle" }, { name: "advisor", doing: "idle" }], objects: [{ family: "approvals", asked: 1, allowed: 1, denied: 0, pending: 1 }, { family: "ledger", usd: 0.5, unpriced: 0 }] },
  ...Array.from({ length: ${n} }, (_, i) => bay(i + 1)), { id: "outbox", kind: "outbox", state: "landed" }],
  hallways: [{ id: "task:worker-1", kind: "task", state: "lit", from: "deck", to: "worker-1", count: 2 }, { id: "landing", kind: "landing", state: "waiting", from: "deck", to: "outbox", count: 1 }, { id: "review", kind: "review", state: "dark", from: "advisor", to: "master", count: 0 }] };
const crew = [{ name: "master", model: "m", doing: "idle" }, { name: "advisor", model: "a", doing: "idle" }, ...Array.from({ length: ${n} }, (_, i) => ({ name: "worker-" + (i + 1), model: "x", doing: i % 3 === 0 ? "using Edit" : i % 3 === 1 ? "waiting for approval" : "failed" }))];
const run = { id: "r1", task: "smoke", status: "running", started: 1, clyde: "watching the workers", crew, asks: [{ id: "a1", who: "worker-1", tool: "Bash", message: "ls", t: 5 }], spend: { usd: 0, unpriced: 0 }, events: 0, layout };
state.runs = [run];
state.feeds["r1"] = [{ t: 100, who: "worker-1", kind: "tool_use", tool: "Edit" }, { t: 101, who: "worker-2", kind: "failed" }, { t: 102, who: "clyde", kind: "check", target: "worker-1", reason: "brief" }];
draw();
for (const scene of state.scenes) { tickScene(scene, Date.now() / 1000 + 3); tickScene(scene, Date.now() / 1000 + 30); }
return { scenes: state.scenes.length, people: state.scenes[0].people.length, nodes: countNodes($runs) };
`;
try {
  vm.runInContext(code.replace(/^"use strict";/m, "") + "\nthis.__out = (function () {" + smoke + "})();", ctx);
  console.log(JSON.stringify(ctx.__out));
} catch (e) { console.log(JSON.stringify({ error: String((e && e.stack) || e).split("\n").slice(0, 4).join(" | ") })); }
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class StationSmoke(unittest.TestCase):
    def _run(self, workers: int) -> dict:
        script = re.search(r"<script>\n(.*?)</script>", PAGE, re.S)
        self.assertIsNotNone(script)
        with tempfile.TemporaryDirectory() as tmp:
            page, harness = Path(tmp) / "page.js", Path(tmp) / "harness.js"
            page.write_text(script.group(1), encoding="utf-8")
            harness.write_text(HARNESS, encoding="utf-8")
            done = subprocess.run(["node", str(harness), str(page), str(workers)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_the_page_draws_and_animates_for_one_three_and_seven_workers(self):
        for workers in (1, 3, 7):
            out = self._run(workers)
            self.assertNotIn("error", out, f"{workers} workers: {out.get('error')}")
            self.assertEqual(out["scenes"], 1)
            self.assertEqual(out["people"], 4 + workers)   # Clyde, Bonnie, the master, the advisor and each worker
            self.assertGreater(out["nodes"], 300 + 60 * workers)


if __name__ == "__main__":
    unittest.main()
