"""`clyde station web`: the station in a browser, on localhost, read from the run files (agent/runs.py).

    GET  /                the page, once the one-time launch link has been opened (it carries the API token)
    GET  /api/state       the active runs as station.snapshot() shows them (?run=<id> for one)
    GET  /api/runs        every run, newest first
    GET  /api/events      ?run=<id>&after=<n>: waits up to 25 s for events past n, then answers (the stream is a long poll)
    POST /api/answer      {run, id, allow}: answer a worker's pending request, as `clyde station approve` does

Any web page the user visits can try to talk to a localhost port, so, as Bonnie does: it binds 127.0.0.1, checks the Host
and Origin headers, hands the page only to the browser that opened the one-time link Clyde printed (an HttpOnly,
SameSite=Strict cookie in exchange), and wants the API token (in that page) on every API call as well as the cookie.
Event rows carry paths and commands, so nothing is served without both.
"""
from __future__ import annotations

import hmac
import http.cookies
import json
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.agent import station
from src.agent.runs import Run

DEFAULT_PORT = 8765   # not 8080: that one is Bonnie's
MAX_BODY = 64 * 1024
LONG_POLL_S = 25
_POLL_STEP_S = 0.4
_PAGE_EVENTS = 500   # at most this many rows in one /api/events answer
_CSP = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'none'; frame-ancestors 'none'"

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
main { max-width: 1100px; margin: 0 auto; padding: 20px 16px 48px; }
header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
h1 { font-size: 20px; margin: 0; }
.muted { color: var(--muted); }
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
@media (prefers-reduced-motion: reduce) { .dot { animation: none !important; } }
.card .model { font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
.card .doing { margin-top: 4px; }
.card .rule { margin-top: 6px; font-size: 12px; color: var(--muted); }
.asks { margin-top: 14px; }
.ask { border: 1px solid var(--warn); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.ask pre { margin: 6px 0 8px; white-space: pre-wrap; overflow-wrap: anywhere; font: 12.5px/1.4 ui-monospace, Menlo, monospace; max-height: 160px; overflow: auto; }
button.act { font: inherit; padding: 5px 14px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; margin-right: 8px; }
button.act.allow { border-color: var(--ok); color: var(--ok); }
button.act.deny { border-color: var(--bad); color: var(--bad); }
button.act:focus-visible, .card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.feed { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
.feed h3 { font-size: 13px; margin: 0 0 6px; font-weight: 600; }
.log { font: 12.5px/1.5 ui-monospace, Menlo, monospace; max-height: 260px; overflow: auto; margin: 0; padding: 0; list-style: none; }
.log li { white-space: pre-wrap; overflow-wrap: anywhere; }
.log .t { color: var(--muted); }
.empty { color: var(--muted); padding: 30px 0; text-align: center; }
#status { font-size: 12px; }
</style>
</head>
<body>
<main>
  <header><h1>Clyde station</h1><span class="muted">what the team recorded, live</span><span id="status" class="muted" aria-live="polite"></span></header>
  <div id="runs"></div>
</main>
<script>
"use strict";
const TOKEN = "__TOKEN__";
const state = { runs: [], feeds: {}, filter: {}, polling: {} };
const $runs = document.getElementById("runs");
const $status = document.getElementById("status");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
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

function card(run, member) {
  const button = el("button", "card");
  button.type = "button";
  button.setAttribute("aria-pressed", String(state.filter[run.id] === member.name));
  const who = el("div", "who");
  who.append(el("span", "dot " + dotClass(member.doing)), el("span", "", member.name));
  if (member.kind) who.append(el("span", "chip", member.kind === "cli" ? "agent CLI" : "Clyde"));
  button.append(who, el("div", "model", member.model), el("div", "doing", member.doing));
  if (member.constraint) button.append(el("div", "rule", member.constraint));
  button.addEventListener("click", () => { state.filter[run.id] = state.filter[run.id] === member.name ? null : member.name; draw(); });
  return button;
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
  const box = el("div", "feed");
  const who = state.filter[run.id];
  box.append(el("h3", "", who ? "Events from " + who + " (click its card again for all)" : "Events"));
  const log = el("ul", "log");
  for (const e of (state.feeds[run.id] || []).filter((x) => !who || x.who === who).slice(-200)) {
    const detail = e.tool ? e.tool + (e.input ? " " + e.input : "") : (e.status || e.note || "");
    const line = el("li");
    line.append(el("span", "t", clock(e.t) + " "), document.createTextNode(e.who + " " + e.kind + (detail ? " " + detail : "")));
    log.append(line);
  }
  box.append(log);
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  return box;
}
let lastSignature = "";
function draw() {
  // Rebuild only when something visible changed: a rebuild every few seconds would swap the buttons out from under a click.
  const signature = JSON.stringify([state.runs, Object.keys(state.feeds).map((id) => [id, state.feeds[id].length]), state.filter]);
  if (signature === lastSignature) return;
  lastSignature = signature;
  $runs.replaceChildren();
  if (!state.runs.length) { $runs.append(el("div", "empty", "No runs yet. Start one with /orchestrate in clyde.")); return; }
  for (const run of state.runs) {
    const section = el("section", "run");
    const head = el("div", "run-head");
    const spend = "$" + run.spend.usd.toFixed(4) + (run.spend.unpriced ? " + " + run.spend.unpriced + " unpriced" : "");
    head.append(el("h2", "", run.task || run.id), el("span", "chip " + run.status, run.status.replace("_", " ")), el("span", "chip", spend), el("span", "chip", run.id));
    section.append(head, el("div", "clyde", "Clyde: " + run.clyde));
    const grid = el("div", "grid");
    for (const member of run.crew) grid.append(card(run, member));
    section.append(grid);
    if (run.asks.length) section.append(asks(run));
    section.append(feed(run));
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
refresh();
setInterval(refresh, 5000);   // picks up runs that start after the page opened
</script>
</body>
</html>
"""


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    launch_secret = ""
    token = ""

    def handle_error(self, request: Any, client_address: Any) -> None:
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):   # a closed tab is not news
            super().handle_error(request, client_address)


def make_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)
    launch = [secrets.token_urlsafe(24)]   # the one-time secret in the printed link; "" once used
    sessions: set[str] = set()             # cookie values handed out in exchange for it

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        def _allowed_hosts(self) -> set[str]:
            number = self.server.server_address[1]
            return {f"127.0.0.1:{number}", f"localhost:{number}"}

        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _has_session(self) -> bool:
            jar = http.cookies.SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie", ""))
            except http.cookies.CookieError:
                return False
            morsel = jar.get("station_session")
            return morsel is not None and any(hmac.compare_digest(morsel.value, sid) for sid in sessions)

        def _guard(self, api: bool) -> bool:
            """Host and Origin must be this server; an API call also needs the session cookie and the token."""
            if self.headers.get("Host", "") not in self._allowed_hosts():
                self._json(403, {"error": "bad host"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin.removeprefix("http://") not in self._allowed_hosts():
                self._json(403, {"error": "bad origin"})
                return False
            if api and not (self._has_session() and hmac.compare_digest(self.headers.get("X-Station-Token", ""), token)):
                self._json(403, {"error": "bad token"})
                return False
            return True

        def _body(self) -> dict[str, Any] | None:
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json(415, {"error": "send application/json"})
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                self.close_connection = True   # the body stays unread, so this connection can't carry another request
                self._json(413, {"error": "body too large"})
                return None
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json(400, {"error": "not JSON"})
                return None
            if not isinstance(data, dict):
                self._json(400, {"error": "expected a JSON object"})
                return None
            return data

        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/":
                self._page(query.get("k", [""])[0])
            elif not url.path.startswith("/api/"):
                self._json(404, {"error": "not found"})
            elif self._guard(api=True):
                self._api(url.path, query)

        def _page(self, key: str) -> None:
            if not self._guard(api=False):
                return
            if key:
                if launch[0] and hmac.compare_digest(key, launch[0]):
                    launch[0] = ""   # a link works once
                    sid = secrets.token_urlsafe(24)
                    sessions.add(sid)
                    self._send(302, b"", "text/plain", {"Location": "/", "Set-Cookie": f"station_session={sid}; HttpOnly; SameSite=Strict; Path=/"})
                else:
                    self._json(403, {"error": "this link is wrong or was already used; run `clyde station web` again for a new one"})
                return
            if not self._has_session():
                self._json(403, {"error": "open the link `clyde station web` printed"})
                return
            self._send(200, PAGE.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8")

        def _api(self, path: str, query: dict[str, list[str]]) -> None:
            run_id = query.get("run", [""])[0]
            if path == "/api/state":
                runs = [Run.open(run_id)] if run_id else station.select_runs(None)
                self._json(200, {"runs": [station.snapshot(r) for r in runs if r], "now": time.time()})
            elif path == "/api/runs":
                self._json(200, {"runs": [{"id": r.id, "status": r.state().get("status"), "task": r.state().get("task")} for r in Run.all()]})
            elif path == "/api/events":
                self._events(run_id, query.get("after", ["0"])[0])
            else:
                self._json(404, {"error": "not found"})

        def _events(self, run_id: str, after_text: str) -> None:
            run = Run.open(run_id)
            if run is None or not after_text.isdigit():
                self._json(404 if run is None else 400, {"error": "no such run" if run is None else "after must be a number"})
                return
            after, deadline = int(after_text), time.monotonic() + LONG_POLL_S
            # ponytail: Run.events() re-reads the whole file each step; an index or tail-read if a run's log gets large
            while True:
                events = run.events()
                if len(events) > after or time.monotonic() >= deadline:
                    rows = events[after:after + _PAGE_EVENTS]
                    self._json(200, {"events": rows, "next": after + len(rows)})
                    return
                time.sleep(_POLL_STEP_S)

        def do_POST(self) -> None:
            url = urlparse(self.path)
            if url.path != "/api/answer":
                self._json(404, {"error": "not found"})
                return
            if not self._guard(api=True):
                return
            data = self._body()
            if data is None:
                return
            run = Run.open(str(data.get("run", "")))
            if run is None or not isinstance(data.get("allow"), bool):
                self._json(400, {"error": "need a run and allow: true or false"})
                return
            self._json(200, {"ok": run.answer(str(data.get("id", "")), data["allow"])})

    server = _Server((host, port), Handler)
    server.launch_secret = launch[0]
    server.token = token
    return server


def open_server(port: int | None) -> ThreadingHTTPServer:
    """Bind 127.0.0.1. With no port asked for: 8765, or any free port when something else has it. A port asked for is
    exact, so a taken one raises OSError rather than quietly moving."""
    if port:
        return make_server("127.0.0.1", port)
    try:
        return make_server("127.0.0.1", DEFAULT_PORT)
    except OSError:
        return make_server("127.0.0.1", 0)


def main(port: int | None = None, open_browser: bool = True) -> int:
    try:
        server = open_server(port)
    except OSError as e:
        print(f"Can't use port {port}: {e.strerror or e}. Pick another, for example `clyde station web --port {(port or DEFAULT_PORT) + 1}`.", file=sys.stderr)
        return 1
    url = f"http://localhost:{server.server_address[1]}/?k={server.launch_secret}"   # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="station-http", daemon=True)
    thread.start()
    print(f"The station is up. Open this link once, in your browser: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0
