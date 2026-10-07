"""clyde luv bonny: Clyde as a local web app.

One ClydeREPL runs turns on the main thread, fed from a RunControl queue, exactly as the ACP server does. A
threaded HTTP server on 127.0.0.1 only takes requests from the browser and answers from that state: queue,
steer and stop a run, list and open sessions, read the event feed, answer permission cards and vote on council
answers. The browser polls /api/events (long poll), so no websocket or extra dependency is needed.

Guards, because any web page the user visits can try to talk to a localhost port: the server binds 127.0.0.1,
checks the Host and Origin headers, requires a per-run token (put in the page, sent as X-Bonny-Token) and JSON
bodies, and caps body and prompt size. The token does not protect against other programs on the same machine.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.agent.session import Session
from src.bonny.page import PAGE
from src.providers import model_ref
from src.providers.card_shuffle import record_vote
from src.run_control import RunControl

MAX_BODY = 1_000_000
MAX_PROMPT = 100_000
MAX_EVENTS = 5000          # older events are dropped; a client that fell this far behind reloads its view
POLL_SECONDS = 20
STOP_GRACE_S = 2.0         # an idle SIGINT this soon after a stop is the stop racing the end of a turn, not a quit
_ID = re.compile(r"^[\w-]{1,80}$")
_CSP = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"


class EventLog:
    """Append-only event feed with ids; readers ask for everything after the last id they saw."""

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._first = 1                 # id of _events[0]
        self._cond = threading.Condition()

    def emit(self, kind: str, **data: Any) -> None:
        with self._cond:
            self._events.append({**data, "id": self._first + len(self._events), "kind": kind})   # id and kind are the log's own
            if len(self._events) > MAX_EVENTS:
                del self._events[:len(self._events) - MAX_EVENTS]
                self._first = self._events[0]["id"]
            self._cond.notify_all()

    def last(self) -> int:
        with self._cond:
            return self._first + len(self._events) - 1

    def after(self, last: int, timeout: float = 0.0) -> tuple[list[dict], int]:
        """(events with id > last, the newest id), waiting up to `timeout` seconds when there are none yet."""
        with self._cond:
            if timeout and self._first + len(self._events) - 1 <= last:
                self._cond.wait(timeout)
            events = [e for e in self._events if e["id"] > last]
            return events, (events[-1]["id"] if events else last)


class Bonny:
    """What the web front end drives: the REPL, its run control, the event feed and pending permission cards."""

    def __init__(self, repl: Any) -> None:
        self.repl = repl
        self.control: RunControl = repl.control
        self.events = EventLog()
        self.stopped_at = float("-inf")
        self._stop_requested = False
        self._waiters: dict[str, list] = {}          # permission id -> [Event, allowed]
        self._lock = threading.Lock()
        repl.stream = True                            # text chunks reach on_text_hook as they arrive
        repl.tool_context.output_style_name = "bonny"
        repl.tool_context.permission_handler = self.ask_permission
        repl.tool_context.ask_user = None             # ponytail: no question cards yet; the agent decides without asking

    # -- permission cards --------------------------------------------------------------------------
    def ask_permission(self, tool: str, message: str, rule: str | None) -> tuple[bool, bool]:
        """Runs on the turn's thread: show a card, wait for the browser's answer (or a stop, which denies)."""
        pid = uuid.uuid4().hex[:12]
        waiter = [threading.Event(), False]
        with self._lock:
            self._waiters[pid] = waiter
        self.events.emit("permission", card=pid, tool=tool, message=message)
        waiter[0].wait()
        with self._lock:
            self._waiters.pop(pid, None)
        return waiter[1], False

    def answer_permission(self, pid: str, allow: bool) -> bool:
        with self._lock:
            waiter = self._waiters.get(pid)
        if waiter is None:
            return False
        waiter[1] = allow
        waiter[0].set()
        return True

    def stop(self) -> None:
        self.stopped_at = time.monotonic()
        self._stop_requested = True
        with self._lock:
            waiters = list(self._waiters.values())
        for waiter in waiters:                        # a turn waiting on a card ends as a denial
            waiter[1] = False
            waiter[0].set()
        self.control.stop()

    # -- the turn loop (main thread) -----------------------------------------------------------------
    def run(self) -> None:
        while True:
            try:
                text = self.control.prompts.get()
            except KeyboardInterrupt:
                if time.monotonic() - self.stopped_at < STOP_GRACE_S:
                    continue
                return
            if text is None:
                return
            self._turn(text)

    def _turn(self, text: str) -> None:
        repl = self.repl
        self._stop_requested = False
        self.control.busy = True
        self.events.emit("turn_start", text=text)
        chunks: list[str] = []   # in stream mode chat() leaves last_result unset, so the answer is what streamed

        def on_text(chunk: str) -> None:
            chunks.append(chunk)
            self.events.emit("text", text=chunk)

        repl.on_text_hook = on_text
        repl.on_event_hook = lambda ev: self.events.emit("tool", **_tool_event(ev))
        try:
            repl.chat(text)
        except KeyboardInterrupt:
            self._stop_requested = True
        finally:
            self.control.busy = False
        if self._stop_requested:
            self.events.emit("turn_end", stopped=True)
            return
        if repl.last_error:
            self.events.emit("error", message=str(repl.last_error))
        self.events.emit("turn_end", stopped=False, ok=repl.last_error is None, answer="".join(chunks), council=self.council())

    def council(self) -> dict | None:
        return getattr(self.repl.provider, "last_council", None)

    def state(self) -> dict:
        repl = self.repl
        return {"busy": self.control.busy, "queued": self.control.prompts.qsize(), "model": model_ref(repl.provider, repl.model),
                "mode": repl.mode, "session": repl.session.session_id, "cwd": str(repl.tool_context.workspace_root),
                "council": self.council(), "event": self.events.last()}

    def models(self) -> list[str]:
        """What the model picker offers: cardShuffle's tiers (and their council forms), then every model that passed /eval."""
        from src.providers.model_eval import load_results

        card = self.repl.registry.get("cardShuffle")
        tiers = [f"cardShuffle:{m}" for m in card.list_models()] if card is not None else []
        graded = sorted(ref for ref, r in load_results().items() if r.get("passed") and not ref.startswith("cardShuffle:"))
        return tiers + graded

    # -- sessions ------------------------------------------------------------------------------------
    def sessions(self) -> list[dict]:
        from src.repl.core import _first_prompt

        found = Session.list_recent(str(self.repl.tool_context.workspace_root))
        return [{"id": s.session_id, "title": _first_prompt(s), "updated": s.updated_at, "messages": len(s.conversation.messages)}
                for s in found]

    def messages(self, session_id: str) -> list[dict] | None:
        from src.repl.core import _message_text

        session = self.repl.session if session_id == self.repl.session.session_id else Session.load(session_id)
        if session is None:
            return None
        return [{"role": m.role, "text": text} for m in session.conversation.messages
                if m.role in ("user", "assistant") and (text := _message_text(m))]

    def open_session(self, session_id: str) -> bool:
        session = Session.load(session_id)
        if session is None:
            return False
        self.repl._switch_session(session)
        self.events.emit("session", session=session_id)
        return True

    def new_session(self) -> None:
        self.repl._switch_session(Session.create(self.repl.provider_name, self.repl.model))
        self.events.emit("session", session=self.repl.session.session_id)


def _tool_event(ev: Any) -> dict:
    from src.agent.agent_loop import summarize_tool_result, summarize_tool_use

    if ev.kind == "tool_use":
        return {"phase": "start", "call": ev.tool_use_id, "tool": ev.tool_name, "summary": summarize_tool_use(ev.tool_name, ev.tool_input or {})}
    return {"phase": "end", "call": ev.tool_use_id, "tool": ev.tool_name, "error": bool(ev.is_error),
            "summary": str(summarize_tool_result(ev.tool_name, ev.tool_output) or "")[:500]}


def make_server(bonny: Bonny, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        # -- plumbing --
        def _allowed_hosts(self) -> set[str]:
            port_ = self.server.server_address[1]
            return {f"127.0.0.1:{port_}", f"localhost:{port_}"}

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", _CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _guard(self, api: bool) -> bool:
            """Host and Origin must be this server; API calls also need the token."""
            if self.headers.get("Host", "") not in self._allowed_hosts():
                self._json(403, {"error": "bad host"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin.removeprefix("http://") not in self._allowed_hosts():
                self._json(403, {"error": "bad origin"})
                return False
            if api and not hmac.compare_digest(self.headers.get("X-Bonny-Token", ""), token):
                self._json(403, {"error": "bad token"})
                return False
            return True

        def _body(self) -> dict | None:
            """The JSON object sent with a POST; None after answering an error."""
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json(415, {"error": "send application/json"})
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                self.close_connection = True   # the body is left unread, so this connection can't carry another request
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

        # -- routes --
        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/":
                if self._guard(api=False):
                    self._send(200, PAGE.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8")
                return
            if not url.path.startswith("/api/") or not self._guard(api=True):
                if not url.path.startswith("/api/"):
                    self._json(404, {"error": "not found"})
                return
            query = parse_qs(url.query)
            if url.path == "/api/state":
                self._json(200, bonny.state())
            elif url.path == "/api/models":
                self._json(200, {"models": bonny.models()})
            elif url.path == "/api/sessions":
                self._json(200, {"sessions": bonny.sessions()})
            elif url.path.startswith("/api/sessions/"):
                session_id = url.path.rsplit("/", 1)[1]
                messages = bonny.messages(session_id) if _ID.match(session_id) else None
                self._json(200, {"messages": messages}) if messages is not None else self._json(404, {"error": "no such session"})
            elif url.path == "/api/events":
                try:
                    after = int(query.get("after", ["0"])[0])
                except ValueError:
                    after = 0
                events, last = bonny.events.after(after, POLL_SECONDS)
                self._json(200, {"events": events, "last": last})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if not self._guard(api=True):
                return
            data = self._body()
            if data is None:
                return
            text = data.get("text")
            if path in ("/api/prompt", "/api/steer"):
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROMPT:
                    self._json(400, {"error": f"text must be 1 to {MAX_PROMPT} characters"})
                elif path == "/api/prompt":
                    bonny.control.queue(text.strip())
                    self._json(200, {"queued": bonny.control.prompts.qsize()})
                elif not bonny.control.busy:
                    self._json(409, {"error": "nothing is running; send it as a prompt"})
                else:
                    bonny.control.steer(text.strip())
                    self._json(200, {"steering": True})
            elif path == "/api/stop":
                bonny.stop()
                self._json(200, {"stopped": True})
            elif path == "/api/permission":
                ok = isinstance(data.get("card"), str) and bonny.answer_permission(data["card"], data.get("allow") is True)
                self._json(200, {"ok": True}) if ok else self._json(404, {"error": "no such card"})
            elif path == "/api/vote":
                self._vote(data)
            elif path in ("/api/session/open", "/api/session/new", "/api/mode", "/api/model"):
                self._change(path, data)
            else:
                self._json(404, {"error": "not found"})

        def _vote(self, data: dict) -> None:
            council = bonny.council()
            if council is None:
                self._json(409, {"error": "no council turn to vote on"})
                return
            try:
                record_vote(council, str(data.get("ref")), 1 if data.get("vote") == "up" else -1 if data.get("vote") == "down" else 0)
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except OSError as e:
                self._json(500, {"error": f"couldn't save the vote: {e}"})
            else:
                self._json(200, {"ok": True})

        def _change(self, path: str, data: dict) -> None:
            """Session, mode and model changes: refused while a turn runs, since they act on the live REPL."""
            if bonny.control.busy:
                self._json(409, {"error": "a turn is running; stop it first"})
                return
            if path == "/api/session/new":
                bonny.new_session()
            elif path == "/api/session/open":
                session_id = data.get("id")
                if not isinstance(session_id, str) or not _ID.match(session_id) or not bonny.open_session(session_id):
                    self._json(404, {"error": "no such session"})
                    return
            elif path == "/api/mode":
                if data.get("mode") not in ("hold", "plan", "all_in"):
                    self._json(400, {"error": "mode is hold, plan or all_in"})
                    return
                bonny.repl._set_mode(data["mode"])
            elif not isinstance(data.get("model"), str) or not bonny.repl._switch_model(data["model"]):
                self._json(400, {"error": "that model can't be used right now"})
                return
            self._json(200, bonny.state())

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.token = token   # type: ignore[attr-defined]
    return server


def main(model: str | None = None, port: int = 0, open_browser: bool = True) -> int:
    from rich.console import Console

    from src.repl.core import ClydeREPL

    repl = ClydeREPL(model=model, console=Console(stderr=True, soft_wrap=True), headless=True)
    bonny = Bonny(repl)
    server = make_server(bonny, "127.0.0.1", port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, name="bonny-http", daemon=True).start()
    print(f"Bonny is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        bonny.run()
    finally:
        server.shutdown()
    return 0
