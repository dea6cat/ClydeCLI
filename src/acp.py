"""clyde --acp: speak the Agent Client Protocol (agentclientprotocol.com) on stdio, so editors that
support it (Zed, JetBrains through an adapter) can run Clyde as their agent.

Newline-delimited JSON-RPC 2.0, protocol version 1. Supported: initialize, session/new,
session/prompt and session/cancel; the agent streams session/update (agent_message_chunk,
tool_call, tool_call_update) and asks session/request_permission before anything that needs a yes.
Logs go to stderr, never stdout.

Turns run on the main thread, so session/cancel interrupts them the way Esc does (SIGINT); a reader
thread takes everything coming in and hands responses back to the turn waiting for them.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import sys
import threading
import uuid
from typing import Any, TextIO

PROTOCOL_VERSION = 1
_KINDS = {"read": "read", "edit": "edit", "write": "edit", "notebookedit": "edit", "bash": "execute",
          "grep": "search", "glob": "search", "webfetch": "fetch", "websearch": "fetch"}


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
        from src.providers.base import abort_all_connections

        self.cancelled.set()
        for rid in list(self.replies):                               # a turn waiting on a permission answer
            box = self.replies.pop(rid, None)
            if box is not None:
                box.put({"result": {"outcome": {"outcome": "cancelled"}}})
        abort_all_connections()
        os.kill(os.getpid(), signal.SIGINT)                          # the same path Esc takes

    def serve(self) -> int:
        threading.Thread(target=self._read, name="acp-reader", daemon=True).start()
        while (msg := self.work.get()) is not None:
            handler = getattr(self, "on_" + msg["method"].replace("/", "_"), None)
            if handler is None:
                self.send({"id": msg["id"], "error": {"code": -32601, "message": f"method not found: {msg['method']}"}})
                continue
            try:
                self.send({"id": msg["id"], "result": handler(msg.get("params") or {})})
            except Exception as e:  # report it, keep serving
                self.send({"id": msg["id"], "error": {"code": -32603, "message": str(e) or type(e).__name__}})
        return 0

    # -- agent methods ----------------------------------------------------------------------------
    def on_initialize(self, params: dict) -> dict:
        return {"protocolVersion": PROTOCOL_VERSION, "authMethods": [],
                "agentCapabilities": {"loadSession": False,
                                      "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False}}}

    def on_session_new(self, params: dict) -> dict:
        from rich.console import Console
        from src.repl.core import ClydeREPL

        # ponytail: one working directory per process; editors start one agent process per project
        if params.get("cwd"):
            os.chdir(params["cwd"])
        repl = ClydeREPL(model=self.model, console=Console(stderr=True, soft_wrap=True), headless=True)
        repl.stream = True
        sid = f"sess_{uuid.uuid4().hex[:16]}"
        repl.tool_context.permission_handler = lambda tool, message, rule: self._ask(sid, tool, message)
        repl.tool_context.ask_user = None
        self.sessions[sid] = repl
        return {"sessionId": sid}

    def on_session_prompt(self, params: dict) -> dict:
        sid = params["sessionId"]
        repl = self.sessions[sid]
        text = "\n".join(b.get("text", "") for b in params.get("prompt", []) if b.get("type") == "text").strip()

        def update(u: dict) -> None:
            self.notify("session/update", {"sessionId": sid, "update": u})

        repl.on_text_hook = lambda chunk: update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": chunk}})
        repl.on_event_hook = lambda ev: update(_tool_update(ev))
        self.cancelled.clear()
        try:
            repl.chat(text)
        except KeyboardInterrupt:
            return {"stopReason": "cancelled"}
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
