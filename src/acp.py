"""clyde --acp: speak the Agent Client Protocol (agentclientprotocol.com) on stdio, so editors that
support it (Zed, JetBrains through an adapter) can run Clyde as their agent.

Newline-delimited JSON-RPC 2.0, protocol version 1. Supported: initialize, session/new, session/load (a saved session,
its messages replayed), session/prompt, session/cancel, authenticate and session/set_config_option (the model picker and the `/settings` toggles:
select options in the session/new reply); the agent streams session/update (agent_message_chunk,
tool_call, tool_call_update) and asks session/request_permission before anything that needs a yes.
Logs go to stderr, never stdout.

Turns run on the main thread, so session/cancel interrupts them the way Esc does (SIGINT); a reader
thread takes everything coming in and hands responses back to the turn waiting for them.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import uuid
from urllib.parse import unquote, urlparse
from typing import Any, TextIO

PROTOCOL_VERSION = 1
AUTH_REQUIRED = -32000
# Terminal auth: the editor runs `clyde login` in a terminal. Zed adds the args to the agent's own `--acp` command
# (`clyde --acp login`), so cli.py lets a subcommand win over the flag.
AUTH_METHODS = [{"id": "login", "name": "Connect a provider", "type": "terminal", "args": ["login"],
                 "description": "Runs `clyde login` in a terminal: pick a provider and save its key (Ollama and oMLX need none)."}]
_KINDS = {"read": "read", "edit": "edit", "write": "edit", "notebookedit": "edit", "bash": "execute",
          "grep": "search", "glob": "search", "webfetch": "fetch", "websearch": "fetch"}


_LINES = re.compile(r"L(\d+)(?::L?(\d+))?")   # Zed's file mentions end in #L115:116
_SESSION_ID = re.compile(r"[\w.-]+")           # a saved session's file name: no path separators


def _link_text(block: dict) -> str:
    """A `resource_link` (an @-mentioned file) as text. Only the reference goes in, not the contents: the model reads the
    file with its own Read tool, which keeps the permission and secret-file guards an editor-supplied path must not skip."""
    uri = str(block.get("uri", ""))
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return f"[Referenced by the user: {block.get('name') or uri}] {uri}"
    span = _LINES.fullmatch(parsed.fragment)
    where = f", lines {span[1]}-{span[2]}" if span and span[2] else f", line {span[1]}" if span else ""
    return f"[Referenced by the user: {unquote(parsed.path)}{where}. Read it if you need it.]"


def _prompt_text(blocks: list[dict]) -> str:
    """What the model is told: the text blocks, and the files and links the user mentioned, in order."""
    parts = [b.get("text", "") if b.get("type") == "text" else _link_text(b) for b in blocks if b.get("type") in ("text", "resource_link")]
    return "\n".join(p for p in parts if p).strip()


class AuthRequired(Exception):
    """No provider is connected, so there is no model to run: the editor should offer the auth methods."""


class Server:
    def __init__(self, model: str | None = None, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        self.model = model
        self.stdin, self.stdout = stdin or sys.stdin, stdout or sys.stdout
        self.sessions: dict[str, Any] = {}
        self.work: queue.Queue = queue.Queue()      # incoming requests, run in order on the main thread
        self.replies: dict[int, queue.Queue] = {}   # our outgoing request id -> where its response goes
        self.lock = threading.Lock()
        self.next_id = 0
        self.cancelled = threading.Event()
        self.busy = False                           # a prompt turn is running (only then does cancel interrupt)

    # -- transport --------------------------------------------------------------------------------
    def send(self, message: dict) -> None:
        with self.lock:
            self.stdout.write(json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n")
            self.stdout.flush()

    def notify(self, method: str, params: dict) -> None:
        self.send({"method": method, "params": params})

    def request(self, method: str, params: dict) -> dict:
        """Call the client and wait for its result (an error result reads as {})."""
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        box: queue.Queue = queue.Queue(maxsize=1)
        self.replies[rid] = box
        self.send({"id": rid, "method": method, "params": params})
        reply = box.get()
        return reply.get("result") or {}

    def _read(self) -> None:
        for line in self.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "method" not in msg:                                  # a response to one of our requests
                box = self.replies.pop(msg.get("id"), None)
                if box is not None:
                    box.put(msg)
            elif msg["method"] == "session/cancel":
                self._cancel()
            elif "id" in msg:
                self.work.put(msg)
        self.work.put(None)                                          # the client closed stdin

    def _cancel(self) -> None:
        from src.runtime.run_control import interrupt_turn

        self.cancelled.set()
        for rid in list(self.replies):                               # a turn waiting on a permission answer
            box = self.replies.pop(rid, None)
            if box is not None:
                box.put({"result": {"outcome": {"outcome": "cancelled"}}})
        if self.busy:                                                # idle: nothing to interrupt
            interrupt_turn()                                         # the same path Esc takes

    def serve(self) -> int:
        if self.stdin.isatty():
            print("clyde --acp speaks the Agent Client Protocol on stdin/stdout; an editor (e.g. Zed) starts it. "
                  "Ctrl+C to quit.", file=sys.stderr)
        threading.Thread(target=self._read, name="acp-reader", daemon=True).start()
        try:
            return self._loop()
        except KeyboardInterrupt:                                    # Ctrl+C while idle: quit quietly
            return 130

    def _loop(self) -> int:
        while (msg := self.work.get()) is not None:
            handler = getattr(self, "on_" + msg["method"].replace("/", "_"), None)
            if handler is None:
                self.send({"id": msg["id"], "error": {"code": -32601, "message": f"method not found: {msg['method']}"}})
                continue
            try:
                self.send({"id": msg["id"], "result": handler(msg.get("params") or {})})
            except AuthRequired as e:
                self.send({"id": msg["id"], "error": {"code": AUTH_REQUIRED, "message": str(e)}})
            except (Exception, SystemExit) as e:  # report it, keep serving: an exit inside a handler must not leave the editor waiting
                self.send({"id": msg["id"], "error": {"code": -32603, "message": str(e) or type(e).__name__}})
        return 0

    # -- agent methods ----------------------------------------------------------------------------
    def on_initialize(self, params: dict) -> dict:
        return {"protocolVersion": PROTOCOL_VERSION, "authMethods": AUTH_METHODS,
                "agentCapabilities": {"loadSession": True,
                                      "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False}}}

    def on_authenticate(self, params: dict) -> dict:
        return {}   # login happens in the terminal the editor opened; the next session/new sees the saved key

    def _new_repl(self, params: dict) -> Any:
        from rich.console import Console
        from src.providers import usable
        from src.repl.core import ClydeREPL, build_registry

        # before the REPL: with nothing connected it can't resolve a model and exits, which would leave the editor waiting
        if not usable(build_registry()):
            raise AuthRequired("No provider is connected. Run `clyde login`, or start Ollama or oMLX.")

        # ponytail: one working directory per process; editors start one agent process per project
        if params.get("cwd"):
            os.chdir(params["cwd"])
        repl = ClydeREPL(model=self.model, console=Console(stderr=True, soft_wrap=True), headless=True)
        repl.stream = True
        repl.tool_context.ask_user = None
        return repl

    def _register(self, repl: Any) -> str:
        """Hand the session to the editor under Clyde's own session id, so the id still names it after a restart."""
        sid = repl.session.session_id
        repl.tool_context.permission_handler = lambda tool, message, rule: self._ask(sid, tool, message)
        self.sessions[sid] = repl
        return sid

    def on_session_new(self, params: dict) -> dict:
        repl = self._new_repl(params)
        return {"sessionId": self._register(repl), "configOptions": _config_options(repl)}

    def on_session_load(self, params: dict) -> dict:
        """Reopen a saved session and replay its messages, so the editor and the model both have the history."""
        from src.agent.session import Session
        from src.repl.core import _message_text

        wanted = str(params.get("sessionId", ""))
        if not _SESSION_ID.fullmatch(wanted):     # the id names a file in the sessions folder
            raise ValueError(f"not a session id: {wanted!r}")
        saved = Session.load(wanted)
        if saved is None:
            raise ValueError(f"session not found: {wanted}")
        repl = self._new_repl(params)
        repl._switch_session(saved)
        sid = self._register(repl)
        for message in saved.conversation.messages:
            text = _message_text(message)
            kind = {"user": "user_message_chunk", "assistant": "agent_message_chunk"}.get(message.role)
            if text and kind:
                self.notify("session/update", {"sessionId": sid, "update": {"sessionUpdate": kind, "content": {"type": "text", "text": text}}})
        return {"configOptions": _config_options(repl)}

    def on_session_set_config_option(self, params: dict) -> dict:
        from src.ui.settings_screen import settings

        repl, config_id, value = self.sessions[params["sessionId"]], params.get("configId"), str(params.get("value"))
        if config_id == "model":
            if not repl._switch_model(value):
                raise ValueError(f"can't switch to {value}")
            return {"configOptions": _config_options(repl)}
        setting = next((s for s in settings() if _setting_id(s) == config_id), None)
        if setting is None:
            raise ValueError(f"unknown option: {config_id}")
        missing = object()   # None is a real choice for some settings (the context window's default), so it can't mean "not found"
        choice = next((c for c in setting.choices if str(c) == value), missing)
        if choice is missing:
            raise ValueError(f"{setting.label} can't be {value}")
        setting.write(choice)
        return {"configOptions": _config_options(repl)}

    def on_session_prompt(self, params: dict) -> dict:
        sid = params["sessionId"]
        repl = self.sessions[sid]
        text = _prompt_text(params.get("prompt", []))

        def update(u: dict) -> None:
            self.notify("session/update", {"sessionId": sid, "update": u})

        repl.on_text_hook = lambda chunk: update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": chunk}})
        repl.on_event_hook = lambda ev: update(_tool_update(ev))
        self.cancelled.clear()
        self.busy = True
        try:
            repl.chat(text)
        except KeyboardInterrupt:
            return {"stopReason": "cancelled"}
        finally:
            self.busy = False
        if self.cancelled.is_set():
            return {"stopReason": "cancelled"}
        if repl.last_error:
            update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": f"\n\nError: {repl.last_error}"}})
        return {"stopReason": "end_turn"}

    def _ask(self, sid: str, tool: str, message: str) -> tuple[bool, bool]:
        reply = self.request("session/request_permission", {
            "sessionId": sid,
            "toolCall": {"toolCallId": f"perm_{uuid.uuid4().hex[:8]}", "title": message, "kind": _KINDS.get(tool.lower(), "other")},
            "options": [{"optionId": "allow-once", "name": "Allow once", "kind": "allow_once"},
                        {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"}],
        })
        outcome = reply.get("outcome") or {}
        return outcome.get("outcome") == "selected" and outcome.get("optionId") == "allow-once", False


def _model_option(repl: Any) -> dict:
    """The model picker an editor shows (a `select` option in the `model` category): the models of every connected
    provider that /eval hasn't shown to fail, plus the current one."""
    from src.providers import model_ref, usable
    from src.providers.model_eval import hidden_refs

    current, hidden, refs = model_ref(repl.provider, repl.model), hidden_refs(), []
    for name, provider in usable(repl.registry).items():
        try:
            refs += [f"{name}:{m}" for m in provider.list_models()]
        except Exception:   # one provider that can't list its models must not take the picker away
            continue
    shown = [ref for ref in dict.fromkeys(refs) if ref not in hidden or ref == current]
    return {"id": "model", "name": "Model", "category": "model", "type": "select", "currentValue": current,
            "options": [{"value": ref, "name": ref} for ref in (shown if current in shown else [current, *shown])]}


def _setting_id(setting: Any) -> str:
    return "setting_" + re.sub(r"\W+", "_", setting.label.lower()).strip("_")


def _setting_option(setting: Any) -> dict:
    """One of the toggles /settings > Config offers, as a `select` option (works in every client, unlike a boolean one)."""
    name = lambda c: "Default" if c is None else "On" if c is True else "Off" if c is False else str(c)   # noqa: E731
    current = setting.value()
    choices = [current, *(c for c in setting.choices if c != current)] if current not in setting.choices else list(setting.choices)
    return {"id": _setting_id(setting), "name": setting.label, "description": f"Applies {setting.applies}.", "type": "select",
            "currentValue": str(current), "options": [{"value": str(c), "name": name(c)} for c in choices]}


def _config_options(repl: Any) -> list[dict]:
    """Everything the editor can change in a session: the model, then each setting from `/settings` > Config."""
    from src.ui.settings_screen import settings

    return [_model_option(repl), *(_setting_option(s) for s in settings())]


def _tool_update(ev: Any) -> dict:
    """A Clyde tool event as an ACP tool_call (start) or tool_call_update (finish)."""
    from src.agent.agent_loop import summarize_tool_result, summarize_tool_use

    call_id = ev.tool_use_id or ev.tool_name
    if ev.kind == "tool_use":
        summary = summarize_tool_use(ev.tool_name, ev.tool_input or {})
        return {"sessionUpdate": "tool_call", "toolCallId": call_id, "title": f"{ev.tool_name} {summary}".strip(),
                "kind": _KINDS.get(ev.tool_name.lower(), "other"), "status": "in_progress"}
    text = str(summarize_tool_result(ev.tool_name, ev.tool_output) or "")
    return {"sessionUpdate": "tool_call_update", "toolCallId": call_id, "status": "failed" if ev.is_error else "completed",
            "content": [{"type": "content", "content": {"type": "text", "text": text}}]}


def main(model: str | None = None) -> int:
    return Server(model=model).serve()
