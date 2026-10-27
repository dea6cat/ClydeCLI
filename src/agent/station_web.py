"""`clyde station web`: the station in a browser, on localhost, read from the run files (agent/runs.py).

    GET  /                the page, once the one-time launch link has been opened (it carries the API token)
    GET  /api/state       the active runs as station.snapshot() shows them (?run=<id> for one)
    GET  /api/runs        every run, newest first
    GET  /api/events      ?run=<id>&after=<n>: waits up to 25 s for events past n, then answers (the stream is a long poll)
    POST /api/answer      {run, id, allow}: answer a worker's pending request, as `clyde station approve` does
    POST /api/order       {run, task}: ask the live run for one more worker doing `task` (Clyde hands it over; the run records it)

Any web page the user visits can try to talk to a localhost port, so, as Bonnie does: it binds 127.0.0.1, checks the Host
and Origin headers, hands the page only to the browser that opened the one-time link Clyde printed (an HttpOnly,
SameSite=Strict cookie in exchange), and wants the API token (in that page) on every API call as well as the cookie.
Event rows carry paths and commands, so nothing is served without both.
"""
from __future__ import annotations

import hmac
import http.cookies
import json
import re
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.agent import station
from src.agent.station_page import PAGE
from src.agent.runs import Run

DEFAULT_PORT = 8765   # not 8080: that one is Bonnie's
MAX_BODY = 64 * 1024
LONG_POLL_S = 25
_POLL_STEP_S = 0.4
ART = Path(__file__).parent / "station_art"
_ART_PATH = re.compile(r"/assets/([a-z0-9\-]+\.png)")   # the only paths that are served, so no `..` can reach elsewhere
_PAGE_EVENTS = 500   # at most this many rows in one /api/events answer
_CSP = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'none'; frame-ancestors 'none'"


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
            if "Cache-Control" not in (extra or {}):
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
            elif url.path.startswith("/assets/"):
                self._asset(url.path)
            elif not url.path.startswith("/api/"):
                self._json(404, {"error": "not found"})
            elif self._guard(api=True):
                self._api(url.path, query)

        def _asset(self, path: str) -> None:
            """A picture of the station, served only to the browser that opened the link, only from the station_art folder."""
            if not self._guard(api=False):
                return
            if not self._has_session():
                self._json(403, {"error": "open the link `clyde station web` printed"})
                return
            match = _ART_PATH.fullmatch(path)
            file = ART / match[1] if match else None
            if file is None or not file.is_file():
                self._json(404, {"error": "not found"})
                return
            self._send(200, file.read_bytes(), "image/png", {"Cache-Control": "private, max-age=3600"})

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
            if url.path not in ("/api/answer", "/api/order"):
                self._json(404, {"error": "not found"})
                return
            if not self._guard(api=True):
                return
            data = self._body()
            if data is None:
                return
            run = Run.open(str(data.get("run", "")))
            if url.path == "/api/order":
                if run is None or not isinstance(data.get("task"), str):
                    self._json(400, {"error": "need a run and a task"})
                    return
                try:
                    self._json(200, {"ok": True, "id": run.order(data["task"])})
                except ValueError as e:
                    self._json(409, {"error": str(e)})
                return
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
