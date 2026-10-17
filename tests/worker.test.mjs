// Run: node --test tests/worker.test.mjs
// The Worker's validation and counting, with D1 stood in for by an in-memory SQLite (D1 is SQLite) running worker/schema.sql.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { handle, valid, rowsFor } from "../worker/src/index.js";

const SCHEMA_SQL = readFileSync(new URL("../worker/schema.sql", import.meta.url), "utf8");
const ID = "a".repeat(32);
const NOW = new Date("2026-10-20T10:00:00Z");

function fakeD1() {
  const db = new DatabaseSync(":memory:");
  db.exec(SCHEMA_SQL);
  const prepare = (sql) => {
    const statement = db.prepare(sql);
    return { bind: (...args) => ({ _run: () => statement.run(...args), run: async () => ({ meta: { changes: Number(statement.run(...args).changes) } }) }) };
  };
  return { db, prepare, batch: async (statements) => statements.forEach((s) => s._run()) };
}

const common = (extra = {}) => ({ v: "0.5.8", id: ID, os: "darwin", arch: "arm64", py: "3.14", ram_gb: 16, day: "2026-10-20", ...extra });
const run = (extra = {}) => ({ event: "run", surface: "repl", outcome: "done", turns: 3, tool_calls: 5, tool_errors: 1, ...common(), ...extra });
const post = (body, headers = {}) => new Request("https://t.example/", { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body), headers });
const env = () => ({ DB: fakeD1(), SALT: "test-salt" });
const rows = (e) => e.DB.db.prepare("SELECT event, field, value, n, total FROM counts ORDER BY event, field, value").all().map((r) => ({ ...r }));

test("valid accepts what the client sends", () => {
  assert.ok(valid(run()));
  assert.ok(valid({ event: "bonnie_start", ...common() }));
  assert.ok(valid({ event: "bonnie_use", feature: "theme", ...common() }));
  assert.ok(valid({ event: "tune", outcome: "applied", memory_saved_pct: "5-15", ...common() }));
});

test("valid refuses anything off schema", () => {
  const bad = [
    run({ prompt: "hello" }), run({ outcome: "exploded" }), run({ turns: -1 }), run({ turns: 1.5 }), run({ turns: 1e9 }),
    run({ v: "x" }), run({ id: "short" }), run({ os: "plan9" }), run({ ram_gb: 12 }), run({ py: "2.7" }), run({ day: "yesterday" }),
    { event: "nope", ...common() }, { event: "_common", ...common() }, { event: "bonnie_use", feature: "../etc", ...common() },
    { ...run(), id: undefined }, null, [], "run", { event: "provider_error", provider: "ollama", kind: "http_5xx", extra: true, ...common() },
  ];
  for (const event of bad) assert.equal(valid(event), false, JSON.stringify(event));
});

test("rowsFor counts words and flags by value and counts by sum", () => {
  const key = (row) => row.join("|");
  assert.deepEqual(rowsFor(run(), "2026-10-20").map(key).sort(), [
    ["2026-10-20", "run", "_n", "", 0], ["2026-10-20", "run", "surface", "repl", 0], ["2026-10-20", "run", "outcome", "done", 0],
    ["2026-10-20", "run", "turns", "", 3], ["2026-10-20", "run", "tool_calls", "", 5], ["2026-10-20", "run", "tool_errors", "", 1],
  ].map(key).sort());
});

test("a good batch is counted and answered 204", async () => {
  const e = env();
  const response = await handle(post({ events: [run(), run({ turns: 7 }), { event: "bonnie_use", feature: "prompt", ...common() }] }), e, NOW);
  assert.equal(response.status, 204);
  const all = rows(e);
  const get = (event, field, value = "") => all.find((r) => r.event === event && r.field === field && r.value === value);
  assert.equal(get("run", "_n").n, 2);
  assert.equal(get("run", "turns").total, 10);
  assert.equal(get("run", "outcome", "done").n, 2);
  assert.equal(get("bonnie_use", "feature", "prompt").n, 1);
  assert.equal(get("_install", "active").n, 1);
  assert.equal(get("_install", "os", "darwin").n, 1);
});

test("an install is counted once a day, events every time", async () => {
  const e = env();
  await handle(post({ events: [run()] }), e, NOW);
  await handle(post({ events: [run()] }), e, NOW);
  const all = rows(e);
  assert.equal(all.find((r) => r.event === "_install" && r.field === "active").n, 1);
  assert.equal(all.find((r) => r.event === "run" && r.field === "_n").n, 2);
  await handle(post({ events: [run()] }), e, new Date("2026-10-21T10:00:00Z"));
  assert.deepEqual(e.DB.db.prepare("SELECT day, n FROM counts WHERE event = '_install' AND field = 'active' ORDER BY day").all().map((r) => ({ ...r })),
    [{ day: "2026-10-20", n: 1 }, { day: "2026-10-21", n: 1 }]);
  assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS c FROM visitors").get().c, 2);
});

test("one bad event refuses the whole batch and writes nothing", async () => {
  const e = env();
  const response = await handle(post({ events: [run(), run({ outcome: "exploded" })] }), e, NOW);
  assert.equal(response.status, 400);
  assert.deepEqual(rows(e), []);
  assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS c FROM visitors").get().c, 0);
});

test("other bad requests", async () => {
  const e = env();
  assert.equal((await handle(post("{not json"), e, NOW)).status, 400);
  assert.equal((await handle(post({ events: [] }), e, NOW)).status, 400);
  assert.equal((await handle(post({ events: "x" }), e, NOW)).status, 400);
  assert.equal((await handle(post({ events: [run(), run({ id: "b".repeat(32) })] }), e, NOW)).status, 400);
  assert.equal((await handle(post({ events: Array(1001).fill(run()) }), e, NOW)).status, 400);
  assert.equal((await handle(post("x".repeat(300_000)), e, NOW)).status, 413);
  assert.equal((await handle(new Request("https://t.example/", { method: "PUT", body: "{}" }), e, NOW)).status, 405);
  assert.equal((await handle(new Request("https://t.example/"), e, NOW)).status, 200);
  assert.equal((await handle(post({ events: [run()] }), { DB: e.DB }, NOW)).status, 500);
  assert.deepEqual(rows(e), []);
});

test("neither the install id nor anything but a hash is stored", async () => {
  const e = env();
  await handle(post({ events: [run()] }), e, NOW);
  const dump = JSON.stringify([e.DB.db.prepare("SELECT * FROM counts").all(), e.DB.db.prepare("SELECT * FROM visitors").all()]);
  assert.ok(!dump.includes(ID));
  const hash = e.DB.db.prepare("SELECT h FROM visitors").get().h;
  assert.match(hash, /^[0-9a-f]{64}$/);
});

test("visitor hashes older than two days are deleted", async () => {
  const e = env();
  e.DB.db.prepare("INSERT INTO visitors (day, h) VALUES ('2026-10-10', 'old'), ('2026-10-19', 'recent')").run();
  await handle(post({ events: [run()] }), e, NOW);
  const days = e.DB.db.prepare("SELECT day FROM visitors ORDER BY day").all().map((r) => r.day);
  assert.deepEqual(days, ["2026-10-19", "2026-10-20"]);
});
