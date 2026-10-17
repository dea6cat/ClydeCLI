// Cloudflare Worker that receives Clyde's and Bonnie's opt-in telemetry and keeps daily counters in D1.
// It re-checks every event against schema.json (generated from src/telemetry.py), writes no address, header or
// install id, and refuses a whole batch if any event is off-schema.
import schema from "../schema.json" with { type: "json" };

const MAX_BODY = 256 * 1024;
const MAX_EVENTS = 1000;
const MAX_INT = 10_000_000;
const VERSION = /^\d{1,3}\.\d{1,3}\.\d{1,3}([.+-][0-9A-Za-z.+-]{0,20})?$/;
const PYTHON = /^3\.\d{1,2}$/;
const INSTALL_ID = /^[0-9a-f]{32}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

const isText = (value) => typeof value === "string";

function fieldOk(rule, value) {
  if (Array.isArray(rule)) return rule.includes(value);
  if (rule === "bool") return typeof value === "boolean";
  return Number.isInteger(value) && value >= 0 && value <= MAX_INT;
}

/** True when `event` is one the client could have sent: known name, known fields, allowed values, well-formed common fields. */
export function valid(event) {
  if (!event || typeof event !== "object" || Array.isArray(event)) return false;
  const rules = schema[event.event];
  if (!rules || event.event === "_common") return false;
  const { event: _name, v, id, os, arch, py, ram_gb: ram, day, ...fields } = event;
  const common = schema._common;
  const commonOk = isText(v) && VERSION.test(v) && isText(id) && INSTALL_ID.test(id) && common.os.includes(os) && common.arch.includes(arch) &&
    isText(py) && PYTHON.test(py) && common.ram_gb.includes(ram) && isText(day) && DAY.test(day);
  return commonOk && Object.entries(fields).every(([name, value]) => name in rules && fieldOk(rules[name], value));
}

const UPSERT = "INSERT INTO counts (day, event, field, value, n, total) VALUES (?, ?, ?, ?, 1, ?) " +
  "ON CONFLICT (day, event, field, value) DO UPDATE SET n = n + 1, total = total + excluded.total";

/** The counter rows one event adds to: a total, plus each word or flag it carries, plus the sum of each count. */
export function rowsFor(event, day) {
  const rules = schema[event.event];
  const rows = [[day, event.event, "_n", "", 0]];
  for (const [name, rule] of Object.entries(rules)) {
    if (!(name in event)) continue;
    const value = event[name];
    rows.push(Array.isArray(rule) || rule === "bool" ? [day, event.event, name, String(value), 0] : [day, event.event, name, "", value]);
  }
  return rows;
}

async function dailyHash(salt, day, id) {
  const bytes = new TextEncoder().encode(`${salt}:${day}:${id}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const reply = (status, text = null) => new Response(text, { status, headers: { "Cache-Control": "no-store" } });

/** The request handler. `now` is injectable so tests can pin the day. */
export async function handle(request, env, now = new Date()) {
  if (request.method === "GET") return reply(200, "clyde telemetry receiver\n");
  if (request.method !== "POST") return reply(405);
  if (!env.SALT) return reply(500, "not configured");
  if (Number(request.headers.get("content-length") || 0) > MAX_BODY) return reply(413);

  const text = await request.text();
  if (text.length > MAX_BODY) return reply(413);
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return reply(400, "not json");
  }
  const events = body && body.events;
  if (!Array.isArray(events) || events.length === 0 || events.length > MAX_EVENTS) return reply(400, "bad batch");
  if (!events.every(valid)) return reply(400, "off schema");
  const id = events[0].id;
  if (!events.every((event) => event.id === id)) return reply(400, "mixed installs");

  const day = now.toISOString().slice(0, 10);
  const oldest = new Date(now.getTime() - 2 * 86_400_000).toISOString().slice(0, 10);
  const hash = await dailyHash(env.SALT, day, id);
  const statements = [env.DB.prepare("DELETE FROM visitors WHERE day < ?").bind(oldest)];
  const first = await env.DB.prepare("INSERT OR IGNORE INTO visitors (day, h) VALUES (?, ?)").bind(day, hash).run();
  if (first.meta.changes === 1) {
    const { v, os, arch, py, ram_gb: ram } = events[0];
    for (const [name, value] of [["active", ""], ["v", v], ["os", os], ["arch", arch], ["py", py], ["ram_gb", String(ram)]]) {
      statements.push(env.DB.prepare(UPSERT).bind(day, "_install", name, value, 0));
    }
  }
  for (const event of events) {
    for (const row of rowsFor(event, day)) statements.push(env.DB.prepare(UPSERT).bind(...row));
  }
  await env.DB.batch(statements);
  return reply(204);
}

export default { fetch: (request, env) => handle(request, env) };
