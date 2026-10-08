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

import base64
import collections
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from src import activity
from src.config import clyde_home
from src.providers import keys
from src.agent.session import Session
from src.bonny import artifacts, attachments, automations, pins, projects, providers, theme
from src.bonny.page import PAGE
from src.providers import model_ref
from src.providers.card_shuffle import record_vote
from src.run_control import RunControl
from src.tool_system.tools.web_search import WebSearchTool

MAX_BODY = 1_000_000
MAX_PROMPT = 100_000
MAX_EVENTS = 5000          # older events are dropped; a client that fell this far behind reloads its view
POLL_SECONDS = 20
STOP_GRACE_S = 2.0         # an idle SIGINT this soon after a stop is the stop racing the end of a turn, not a quit
_ID = re.compile(r"^[\w-]{1,80}$")
# A previewed file is untrusted: it runs in an opaque origin (sandbox), can't make requests, and scripts are off unless asked for.
_ARTIFACT_CSP = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; connect-src 'none'; form-action 'none'"
_ARTIFACT_CSP_SCRIPTS = "sandbox allow-scripts; default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; connect-src 'none'; form-action 'none'"
_CSP = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'"


_SEARCH_RULE = (
    "This turn is a Search question. Answer it from the numbered web results below, not from memory alone. Cite a result right after "
    "the claim it supports, as a link with its number, like [1](https://example.com/page), and number only the results you cite, "
    "in the order you first cite them. Do not write a Sources list; the page adds one from your links. Use only these URLs, or "
    "pages you open yourself; never invent a URL. If the results don't answer the question, say so plainly. When the question "
    "is about this conversation or needs no sources, answer it directly."
)


def search_context(results: list[dict], error: str | None) -> str:
    """The system-prompt block for a Search turn: the rule plus the numbered results, or why there are none."""
    if error or not results:
        return f"{_SEARCH_RULE}\n\nThe web search {('failed: ' + error) if error else 'found nothing'}. Answer from what you know and say the answer is unsourced."
    rows = [f"[{i}] {r['title']}\n    {r['url']}\n    {r['snippet']}" for i, r in enumerate(results, 1)]
    return f"{_SEARCH_RULE}\n\nWeb results:\n" + "\n".join(rows)


STATIC = Path(__file__).parent / "static"
FONTS = {"bricolage-grotesque.woff2", "jetbrains-mono.woff2"}   # the only static files served; the site's fonts, under the OFL
FEEDBACK_FILE = "answer_feedback.jsonl"


def record_feedback(session_id: str, model: str, question: str, vote: int) -> None:
    """Append a thumbs up (+1) or down (-1) on an answer to ~/.clyde/answer_feedback.jsonl. Keeps a hash of the question, never its
    text or the answer, and nothing leaves the machine."""
    line = {"ts": time.time(), "session": session_id, "model": model, "prompt": hashlib.sha256(question.encode()).hexdigest()[:16], "vote": vote}
    path = clyde_home() / FEEDBACK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


class Prompt(collections.namedtuple("Prompt", "text search mode files auto", defaults=((), None))):
    """A queued message: Search turns get the sourcing rules, each turn runs in the mode it was sent with, `files` are
    the attachments (already taken from the upload store) that go with it, and `auto` names the automation that sent it."""


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
        self.attachments = attachments.Store()
        self._writes: dict[str, tuple[str, str]] = {}   # tool call id -> (tool, path) for file writes still in flight
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
                item = self.control.prompts.get()
            except KeyboardInterrupt:
                if time.monotonic() - self.stopped_at < STOP_GRACE_S:
                    continue
                return
            if item is None:
                return
            self._turn(item if isinstance(item, Prompt) else Prompt(item, False, None))

    def _turn(self, prompt: Prompt) -> None:
        repl, text = self.repl, prompt.text
        if prompt.auto:
            self.new_session()                         # every automation run is a session of its own
        message, images = attachments.apply_to_turn(repl, text, list(prompt.files))
        repl.direct_stream = prompt.search   # Computer mode always has its tools; only Search takes the quick tool-free path
        if prompt.mode:
            repl._set_mode(prompt.mode)
        self._stop_requested = False
        self.control.busy = True
        self.events.emit("turn_start", text=text, files=[{"name": f.name, "kind": f.kind} for f in prompt.files])
        if images and repl._reads_images() is False:
            self.events.emit("notice", message=f"{model_ref(repl.provider, repl.model)} can't read images, so it gets your words but not the picture. Switch the model to include it.")
        chunks: list[str] = []   # in stream mode chat() leaves last_result unset, so the answer is what streamed

        def on_text(chunk: str) -> None:
            chunks.append(chunk)
            self.events.emit("text", text=chunk)

        repl.on_text_hook = on_text
        self._writes.clear()
        repl.on_event_hook = self._on_tool
        try:
            repl.system_extra = self._search(text or "attached files") if prompt.search else None
            repl.chat(message)
        except KeyboardInterrupt:
            self._stop_requested = True
        finally:
            repl.system_extra = None
            self.control.busy = False
        if self._stop_requested:
            self.events.emit("turn_end", stopped=True)
            return
        if repl.last_error:
            self.events.emit("error", message=str(repl.last_error))
        self.events.emit("turn_end", stopped=False, ok=repl.last_error is None, answer="".join(chunks), council=self.council())

    def _on_tool(self, ev: Any) -> None:
        """Tell the page about each tool call, and about every file a write or edit actually changed."""
        self.events.emit("tool", **_tool_event(ev))
        if ev.kind == "tool_use":
            field = artifacts.EDIT_TOOLS.get(str(ev.tool_name).lower())
            raw = (ev.tool_input or {}).get(field) if field else None
            if isinstance(raw, str) and raw.strip():
                self._writes[ev.tool_use_id] = (ev.tool_name, raw)
        elif not ev.is_error and ev.tool_use_id in self._writes:
            tool, raw = self._writes.pop(ev.tool_use_id)
            path = Path(raw).expanduser()
            path = path if path.is_absolute() else Path(self.repl.tool_context.workspace_root) / path
            self.events.emit("artifact", path=str(path), name=path.name, tool=tool, **dict(zip(("filetype", "group"), artifacts.classify(path))))   # not "kind": the event's own kind is "artifact"

    def artifact_rows(self) -> list[dict]:
        return artifacts.collect(Session.list_recent(str(self.repl.tool_context.workspace_root)), session_title)

    def find_artifact(self, path: str) -> dict | None:
        return artifacts.find(path, self.artifact_rows())

    def _search(self, question: str) -> str:
        """Search the web for a Search turn and return the system-prompt block that carries the results. The user chose Search,
        so this runs the read-only tool directly (no permission card) and is shown to the page like any tool call."""
        query = " ".join(question.split())[:300]
        call = uuid.uuid4().hex[:8]
        self.events.emit("tool", phase="start", call=call, tool="WebSearch", summary=query)
        activity.set("searching the web")
        results: list[dict] = []
        error = None
        try:
            results = WebSearchTool().run({"query": query, "num": 6}, self.repl.tool_context).output["results"]
        except Exception as e:   # blocked, offline, timed out: the turn still runs, unsourced, and says why
            error = str(e) or type(e).__name__
        self.events.emit("tool", phase="end", call=call, tool="WebSearch", error=error is not None,
                         summary=error or f"{len(results)} results", **({"results": [{"title": r["title"], "url": r["url"]} for r in results]} if results else {}))
        return search_context(results, error)

    # -- automations ---------------------------------------------------------------------------------
    @property
    def project(self) -> str:
        return str(self.repl.tool_context.workspace_root)

    def fire(self, row: dict) -> None:
        """Queue an automation's prompt. Read-only (plan mode) unless it was made with edits allowed: nobody is there to answer a card."""
        self.control.queue(Prompt(row["prompt"], False, "all_in" if row.get("edits") else "plan", (), row["id"]))
        self.events.emit("automation", automation=row["id"], name=row["name"])

    def tick(self, now: datetime.datetime) -> None:
        for row in automations.due(self.project, now):
            automations.mark_ran(row["id"], now)
            self.fire(row)

    def start_scheduler(self, every: float = 20.0) -> None:
        def loop() -> None:
            while True:
                time.sleep(every)
                try:
                    self.tick(datetime.datetime.now())
                except Exception as e:   # a bad file must not stop the clock; the page shows nothing, the log shows why
                    self.events.emit("notice", message=f"Automations couldn't check the schedule: {e}")

        threading.Thread(target=loop, name="bonny-automations", daemon=True).start()

    def council(self) -> dict | None:
        return getattr(self.repl.provider, "last_council", None)

    def state(self) -> dict:
        repl = self.repl
        return {"busy": self.control.busy, "queued": self.control.prompts.qsize(), "model": model_ref(repl.provider, repl.model),
                "mode": repl.mode, "session": repl.session.session_id, "cwd": str(repl.tool_context.workspace_root),
                "council": self.council(), "event": self.events.last(), "activity": activity.get()}

    def models(self) -> list[str]:
        """What the model picker offers: cardShuffle's tiers (and their council forms), then every model that passed /eval."""
        from src.providers.model_eval import load_results

        card = self.repl.registry.get("cardShuffle")
        tiers = [f"cardShuffle:{m}" for m in card.list_models()] if card is not None else []
        graded = sorted(ref for ref, r in load_results().items() if r.get("passed") and not ref.startswith("cardShuffle:"))
        return tiers + graded

    # -- sessions ------------------------------------------------------------------------------------
    def sessions(self) -> list[dict]:
        found = Session.list_recent(str(self.repl.tool_context.workspace_root))
        pinned = pins.load()
        rows = [{"id": s.session_id, "title": session_title(s), "updated": s.updated_at, "messages": len(s.conversation.messages),
                 "pinned": s.session_id in pinned} for s in found]
        return sorted(rows, key=lambda r: pinned.index(r["id"]) if r["pinned"] else len(pinned))   # stable: pinned first, newest pin first, the rest as before

    def messages(self, session_id: str) -> list[dict] | None:
        from src.repl.core import _message_text

        session = self.repl.session if session_id == self.repl.session.session_id else Session.load(session_id)
        if session is None:
            return None
        out = []
        for i, m in enumerate(session.conversation.messages):
            if m.role not in ("user", "assistant") or not (text := _message_text(m)):
                continue
            row: dict = {"i": i, "role": m.role, "text": text}
            if m.role == "user":
                row["text"], row["files"] = attachments.split(text)
                row["images"] = sum(1 for b in (m.content if isinstance(m.content, list) else []) if getattr(b, "type", None) == "image")
            out.append(row)
        return out

    def session_image(self, session_id: str, index: int, n: int) -> tuple[bytes, str] | None:
        """The n-th picture attached to message `index` of a session, for the thumbnails in the thread."""
        session = self.repl.session if session_id == self.repl.session.session_id else Session.load(session_id)
        try:
            blocks = [b for b in session.conversation.messages[index].content if getattr(b, "type", None) == "image"] if session else []
            block = blocks[n]
            media = block.media_type if block.media_type in attachments.IMAGE_TYPES.values() else None
            return (base64.b64decode(block.data), media) if media else None
        except (IndexError, TypeError, ValueError, AttributeError):
            return None

    def open_session(self, session_id: str) -> bool:
        session = Session.load(session_id)
        if session is None:
            return False
        self.repl._switch_session(session)
        self.events.emit("session", session=session_id)
        return True

    def delete_session(self, session_id: str) -> bool:
        """Move a saved session to the archive folder (restorable with `clyde sessions unarchive`, or Undo here). Deleting the
        open session opens a fresh one. False when there is no such saved session."""
        if not Session.archive(session_id):
            return False
        if session_id == self.repl.session.session_id:
            self.new_session()
        return True

    def set_project(self, path: Path) -> None:
        """Work in another folder: tools, permissions and new sessions follow it, and a fresh session opens there. The caller has
        checked that nothing is running."""
        # ponytail: MCP servers and hooks were loaded for the folder Bonny started in; restart Bonny to pick up a new project's own
        os.chdir(path)
        context = self.repl.tool_context
        context.workspace_root = context.cwd = path
        context.permission_context.workspace_root = path
        projects.remember(path)
        self.new_session()

    def new_session(self) -> None:
        self.repl._switch_session(Session.create(self.repl.provider_name, self.repl.model))
        self.events.emit("session", session=self.repl.session.session_id)


def session_title(session: Session) -> str:
    """What the sidebar calls a session: the first thing the user typed, without attachment markers, or the file's name."""
    from src.repl.core import _message_text, _preview

    for message in session.conversation.messages:
        if message.role == "user" and (text := _message_text(message)):
            visible, files = attachments.split(text)
            return _preview(visible or (files[0] if files else "Picture"))
    return "(no prompt)"


def _tool_event(ev: Any) -> dict:
    from src.agent.agent_loop import summarize_tool_result, summarize_tool_use

    if ev.kind == "tool_use":
        url = (ev.tool_input or {}).get("url")
        return {"phase": "start", "call": ev.tool_use_id, "tool": ev.tool_name, "summary": summarize_tool_use(ev.tool_name, ev.tool_input or {}),
                **({"url": url} if isinstance(url, str) else {})}
    out = ev.tool_output if isinstance(ev.tool_output, dict) else {}
    found = [{"title": str(r.get("title", "")), "url": r["url"]} for r in out.get("results", []) if isinstance(r, dict) and isinstance(r.get("url"), str)]
    return {"phase": "end", "call": ev.tool_use_id, "tool": ev.tool_name, "error": bool(ev.is_error),
            "summary": str(summarize_tool_result(ev.tool_name, ev.tool_output) or "")[:500], **({"results": found[:10]} if found else {})}


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionError):   # a closed tab mid-response is not worth a traceback
            super().handle_error(request, client_address)


def _attachment(name: str) -> str:
    """A Content-Disposition value for a download. A file name is untrusted (Clyde may have written it after reading a hostile page)
    and can hold a quote or a newline, so the plain form is ASCII with those replaced and the real name rides percent-encoded."""
    plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", name)
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


def make_server(bonny: Bonny, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)

    def background_url() -> str | None:
        path = theme.image_path()
        return f"/theme/background?t={token}&v={path.stat().st_mtime_ns}" if path else None

    def theme_payload() -> dict:
        saved, url = theme.load(), background_url()
        return {"theme": saved, "vars": theme.css_vars(saved, url), "image": url is not None, "presets": theme.PRESETS}

    def render_page() -> str:
        saved = theme.load()
        # the user's own CSS goes in last, so nothing after it can be rewritten by it
        return (PAGE.replace("__TOKEN__", token).replace("__SHAPE__", saved["shape"])
                .replace("__THEME__", theme.root_block(theme.css_vars(saved, background_url()))).replace("__CUSTOM__", theme.safe_css(saved["css"])))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        # -- plumbing --
        def _allowed_hosts(self) -> set[str]:
            port_ = self.server.server_address[1]
            return {f"127.0.0.1:{port_}", f"localhost:{port_}"}

        def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store", csp: str = _CSP, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", csp)
            for name, value in (extra or {}).items():
                self.send_header(name, value.replace("\r", " ").replace("\n", " "))   # one stray newline would end the headers and start a body
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
                    self._send(200, render_page().encode(), "text/html; charset=utf-8")
                return
            if url.path.startswith("/static/") or url.path in ("/theme/background", "/artifact/raw", "/session/image"):
                self._asset(url)
                return
            if not url.path.startswith("/api/") or not self._guard(api=True):
                if not url.path.startswith("/api/"):
                    self._json(404, {"error": "not found"})
                return
            query = parse_qs(url.query)
            if url.path == "/api/state":
                self._json(200, bonny.state())
            elif url.path == "/api/theme":
                self._json(200, theme_payload())
            elif url.path == "/api/artifacts":
                self._json(200, {"artifacts": [artifacts.public(r) for r in bonny.artifact_rows()]})
            elif url.path == "/api/artifact":
                self._artifact_preview(query.get("path", [""])[0])
            elif url.path == "/api/automations":
                self._json(200, {"automations": [{**a, "when": automations.describe(a["schedule"])} for a in automations.listing(bonny.project)]})
            elif url.path == "/api/providers":
                self._json(200, providers.listing(bonny.repl.registry))
            elif url.path == "/api/dirs":
                try:
                    self._json(200, projects.browse(query.get("path", [bonny.project])[0]))
                except ValueError as e:
                    self._json(400, {"error": str(e)})
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
            if path == "/api/theme/image":
                self._upload()
                return
            if path == "/api/attachments":
                self._attach()
                return
            data = self._body()
            if data is None:
                return
            text = data.get("text")
            ids = data.get("attachments") or []
            if path in ("/api/prompt", "/api/steer"):
                if not isinstance(text, str) or len(text) > MAX_PROMPT or not (text.strip() or (ids and path == "/api/prompt")):
                    self._json(400, {"error": f"text must be 1 to {MAX_PROMPT} characters"})
                elif path == "/api/prompt":
                    mode = data.get("mode")
                    if mode not in (None, "hold", "plan", "all_in"):
                        self._json(400, {"error": "mode is hold, plan or all_in"})
                        return
                    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                        self._json(400, {"error": "attachments is a list of ids"})
                        return
                    try:
                        files = bonny.attachments.take(ids)
                    except ValueError as e:
                        self._json(400, {"error": str(e)})
                        return
                    bonny.control.queue(Prompt(text.strip(), data.get("search") is True, mode, tuple(files)))
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
            elif path == "/api/theme":
                try:
                    theme.save(data)
                except OSError as e:
                    self._json(500, {"error": f"couldn't save the theme: {e}"})
                else:
                    self._json(200, theme_payload())
            elif path == "/api/theme/image/remove":
                theme.remove_image()
                self._json(200, theme_payload())
            elif path == "/api/artifact/reveal":
                row = bonny.find_artifact(str(data.get("path", "")))
                if row is None or not artifacts.reveal(Path(row["path"])):
                    self._json(404, {"error": "couldn't show that file"})
                else:
                    self._json(200, {"ok": True})
            elif path == "/api/feedback":
                vote = {"up": 1, "down": -1}.get(data.get("vote"))
                question = data.get("question")
                if vote is None or not isinstance(question, str) or len(question) > MAX_PROMPT:
                    self._json(400, {"error": "vote is up or down, and the question is text"})
                    return
                try:
                    state = bonny.state()
                    record_feedback(state["session"], state["model"], question, vote)
                except OSError as e:
                    self._json(500, {"error": f"couldn't save that: {e}"})
                else:
                    self._json(200, {"ok": True})
            elif path in ("/api/session/open", "/api/session/new", "/api/mode", "/api/model"):
                self._change(path, data)
            elif path in ("/api/session/delete", "/api/session/restore"):
                self._trash(path, data)
            elif path == "/api/session/pin":
                self._pin(data)
            elif path == "/api/dirs/create":
                try:
                    self._json(200, {"path": str(projects.make_dir(data.get("parent"), data.get("name")))})
                except ValueError as e:
                    self._json(400, {"error": str(e)})
            elif path == "/api/project":
                self._project(data)
            elif path in ("/api/providers/connect", "/api/providers/disconnect", "/api/providers/custom"):
                self._providers(path.rsplit("/", 1)[1], data)
            elif path.startswith("/api/automation/"):
                self._automation(path.rsplit("/", 1)[1], data)
            else:
                self._json(404, {"error": "not found"})

        def _asset(self, url: Any) -> None:
            """The site's fonts, the user's background image and a previewed artifact. The last two need the token in their address,
            since an <img>, an <iframe> or a CSS url() can't send headers."""
            if not self._guard(api=False):
                return
            if url.path in ("/theme/background", "/artifact/raw", "/session/image") and not hmac.compare_digest(parse_qs(url.query).get("t", [""])[0], token):
                self._json(403, {"error": "bad token"})
                return
            if url.path == "/theme/background":
                path = theme.image_path()
                if path is None:
                    self._json(404, {"error": "no background image"})
                    return
                self._send(200, path.read_bytes(), theme.CONTENT_TYPES[path.suffix[1:]], cache="private, max-age=3600")
                return
            if url.path == "/artifact/raw":
                self._artifact_raw(url)
                return
            if url.path == "/session/image":
                query = parse_qs(url.query)
                try:
                    session_id, index, n = query["session"][0], int(query["i"][0]), int(query["n"][0])
                except (KeyError, ValueError, IndexError):
                    session_id, index, n = "", 0, 0
                found = bonny.session_image(session_id, index, n) if _ID.match(session_id) else None
                if found is None:
                    self._json(404, {"error": "no such picture"})
                else:
                    self._send(200, found[0], found[1], csp=_ARTIFACT_CSP, cache="private, max-age=3600")
                return
            name = url.path.removeprefix("/static/")
            if name not in FONTS:
                self._json(404, {"error": "not found"})
                return
            self._send(200, (STATIC / name).read_bytes(), "font/woff2", cache="public, max-age=86400")

        def _artifact_preview(self, path: str) -> None:
            """What the preview pane needs for one artifact: its details, plus the text for the kinds shown as text."""
            row = bonny.find_artifact(path)
            if row is None:
                self._json(404, {"error": "that file isn't one of Clyde's artifacts"})
                return
            info = artifacts.public(row)
            if row["exists"] and row["kind"] in ("text", "markdown"):
                try:
                    info.update(artifacts.read_text(Path(row["path"])))
                except OSError as e:
                    info["exists"] = False
                    info["error"] = str(e)
            self._json(200, info)

        def _artifact_raw(self, url: Any) -> None:
            """The file's own bytes for an iframe, an image or a download. Always sandboxed; scripts only when asked for."""
            query = parse_qs(url.query)
            row = bonny.find_artifact(query.get("path", [""])[0])
            path = Path(row["path"]) if row else None
            if row is None or path is None or not path.is_file():
                self._json(404, {"error": "no such artifact"})
                return
            if path.stat().st_size > artifacts.MAX_RAW:
                self._json(413, {"error": "that file is too big to preview"})
                return
            kind = row["kind"]
            ctype = ("text/html; charset=utf-8" if kind == "html" else artifacts.IMAGES.get(path.suffix.lower().lstrip("."), "application/octet-stream")
                     if kind == "image" else "text/plain; charset=utf-8" if kind in ("text", "markdown") else "application/octet-stream")
            download = query.get("download") == ["1"] or kind == "other"
            csp = _ARTIFACT_CSP_SCRIPTS if kind == "html" and query.get("scripts") == ["1"] else _ARTIFACT_CSP
            extra = {"Content-Disposition": _attachment(path.name)} if download else None
            self._send(200, path.read_bytes(), ctype, csp=csp, extra=extra)

        def _raw_body(self, limit: int, what: str) -> bytes | None:
            """A raw (not JSON) request body up to `limit` bytes; None after answering an error. The type comes from the bytes."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= limit:
                self.close_connection = True   # the body is left unread
                self._json(413 if length > 0 else 400, {"error": f"send {what} up to {limit // 1_000_000} MB"})
                return None
            return self.rfile.read(length)

        def _attach(self) -> None:
            data = self._raw_body(attachments.MAX_FILE, "a file")
            if data is None:
                return
            try:
                item = bonny.attachments.add(unquote(self.headers.get("X-File-Name", "")), data)
            except ValueError as e:
                self._json(400, {"error": str(e)})
            else:
                self._json(200, item.public())

        def _upload(self) -> None:
            """The background image arrives as the raw request body; its type is read from its bytes, not from the headers."""
            data = self._raw_body(theme.MAX_IMAGE, "an image")
            if data is None:
                return
            try:
                theme.save_image(data)
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except OSError as e:
                self._json(500, {"error": f"couldn't save the image: {e}"})
            else:
                self._json(200, theme_payload())

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

        def _trash(self, path: str, data: dict) -> None:
            """Delete (archive) or restore a saved session. Another session can go while a turn runs; the open one cannot."""
            session_id = data.get("id")
            if not isinstance(session_id, str) or not _ID.match(session_id):
                self._json(404, {"error": "no such session"})
                return
            if path == "/api/session/delete":
                if bonny.control.busy and session_id == bonny.repl.session.session_id:
                    self._json(409, {"error": "Bonny is working in this session. Stop her first."})
                    return
                ok = bonny.delete_session(session_id)
            else:
                ok = Session.unarchive(session_id)
            self._json(200, {"ok": True, "state": bonny.state()}) if ok else self._json(404, {"error": "no such session"})

        def _automation(self, action: str, data: dict) -> None:
            if action == "create":
                try:
                    row = automations.add(bonny.project, data.get("name"), data.get("prompt"), data.get("schedule"), data.get("edits"), datetime.datetime.now())
                except ValueError as e:
                    self._json(400, {"error": str(e)})
                else:
                    self._json(200, {"automation": row})
                return
            automation_id = data.get("id")
            if action not in ("pause", "resume", "delete", "run") or not isinstance(automation_id, str) or not _ID.match(automation_id):
                self._json(400, {"error": "unknown automation action"})
                return
            row = automations.get(bonny.project, automation_id)
            if row is None:
                self._json(404, {"error": "no such automation"})
            elif action == "run":
                bonny.fire(row)
                self._json(200, {"queued": bonny.control.prompts.qsize()})
            else:
                automations.update(bonny.project, automation_id, action)
                self._json(200, {"ok": True})

        def _providers(self, action: str, data: dict) -> None:
            """Connect, disconnect or add a provider. Idle only: it swaps the registry the running turn uses."""
            if bonny.control.busy:
                self._json(409, {"error": "Bonny is working. Stop her, or wait, then try again."})
                return
            try:
                if action == "connect":
                    result = providers.connect(bonny.repl, data.get("provider"), data.get("key"), data.get("extra"))
                elif action == "custom":
                    result = providers.add_custom(bonny.repl, data.get("name"), data.get("protocol"), data.get("base_url"), data.get("key"))
                else:
                    result = providers.disconnect(bonny.repl, data.get("provider"))
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except (OSError, keys.KeysFileError) as e:
                self._json(500, {"error": f"couldn't save the key: {e}"})
            else:
                self._json(200, result)

        def _project(self, data: dict) -> None:
            if bonny.control.busy:
                self._json(409, {"error": "Bonny is working. Stop her, or wait, then try again."})
                return
            try:
                bonny.set_project(projects.choose(data.get("path")))
            except ValueError as e:
                self._json(400, {"error": str(e)})
            else:
                state = bonny.state()
                self._json(200, {**state, "messages": []})

        def _pin(self, data: dict) -> None:
            session_id = data.get("id")
            if not isinstance(session_id, str) or not _ID.match(session_id) or not isinstance(data.get("pinned"), bool):
                self._json(400, {"error": "id and pinned are required"})
                return
            try:
                pins.set_pinned(session_id, data["pinned"])
            except OSError as e:
                self._json(500, {"error": f"couldn't save the pin: {e}"})
            else:
                self._json(200, {"ok": True})

        def _change(self, path: str, data: dict) -> None:
            """Session, mode and model changes: refused while a turn runs, since they act on the live REPL."""
            if bonny.control.busy:
                self._json(409, {"error": "Bonny is working. Stop her, or wait, then try again."})
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
            state = bonny.state()
            self._json(200, {**state, "messages": bonny.messages(state["session"]) or []} if path.startswith("/api/session/") else state)

    server = _Server((host, port), Handler)
    server.token = token   # type: ignore[attr-defined]
    return server


DEFAULT_PORT = 8080


def open_server(bonny: Bonny, port: int | None) -> ThreadingHTTPServer:
    """Bind 127.0.0.1. With no port asked for: 8080, or any free port when something else has it. A port asked for is exact,
    so a taken one raises OSError rather than quietly moving."""
    if port:
        return make_server(bonny, "127.0.0.1", port)
    try:
        return make_server(bonny, "127.0.0.1", DEFAULT_PORT)
    except OSError:
        return make_server(bonny, "127.0.0.1", 0)


def main(model: str | None = None, port: int | None = None, open_browser: bool = True) -> int:
    from rich.console import Console

    from src.repl.core import ClydeREPL

    repl = ClydeREPL(model=model, console=Console(stderr=True, soft_wrap=True), headless=True)
    bonny = Bonny(repl)
    try:
        server = open_server(bonny, port)
    except OSError as e:
        print(f"Can't use port {port}: {e.strerror or e}. Pick another, for example `clyde luv bonny {port + 1}`.", file=sys.stderr)
        return 1
    url = f"http://localhost:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, name="bonny-http", daemon=True).start()
    bonny.start_scheduler()
    projects.remember(Path.cwd())
    moved = f"  (port {DEFAULT_PORT} was taken; `clyde luv bonny PORT` picks one)" if not port and server.server_address[1] != DEFAULT_PORT else ""
    print(f"Bonny is running at {url}  (Ctrl+C to stop){moved}")
    if open_browser:
        webbrowser.open(url)
    try:
        bonny.run()
    finally:
        server.shutdown()
    return 0
