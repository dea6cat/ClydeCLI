"""End-to-end harness for the terminal app: a real `clyde` in a pseudo-terminal, talking to a scripted fake model.

Nothing here touches the real machine's setup: every run gets a throwaway HOME (so no keys, sessions, skills or
settings), a PATH without Ollama or LM Studio, and no provider keys in the environment. The only model is the
fake server in this file, added as a custom provider named `fake`.

    server = FakeModel([say("hello")])
    with Terminal(server, tmp) as t:
        t.expect("❯")
        t.send_line("hi")
        t.expect("hello")
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import sys
import tempfile
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[=>()][A-Za-z0-9]?|\r")

UP, DOWN, ENTER, ESC, CTRL_C, CTRL_D, SHIFT_TAB = b"\x1b[A", b"\x1b[B", b"\r", b"\x1b", b"\x03", b"\x04", b"\x1b[Z"


def say(text: str, delay: float = 0, thinking: str = "") -> dict:
    """A scripted reply that is plain text, after `delay` seconds, optionally with reasoning text before it."""
    return {"text": text, "delay": delay, "thinking": thinking}


def fail(status: int, message: str = "scripted error") -> dict:
    """A scripted reply that is an HTTP error."""
    return {"status": status, "message": message}


def call(name: str, **arguments: Any) -> dict:
    """A scripted reply that calls one tool."""
    return {"tool": name, "arguments": arguments}


class FakeModel:
    """An OpenAI-compatible server that answers from a script, one entry per request, and records requests."""

    def __init__(self, script: list[dict] | None = None, models: tuple[str, ...] = ("m", "m2")) -> None:
        self.script = list(script or [])
        self.models = models
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                body = json.dumps({"object": "list", "data": [{"id": m, "object": "model"} for m in outer.models]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                with outer._lock:
                    outer.requests.append(payload)
                    item = outer.script.pop(0) if outer.script else say("(the script has ended)")
                time.sleep(item.get("delay", 0))
                if "status" in item:   # a scripted failure: the HTTP status and a JSON error body
                    body = json.dumps({"error": {"message": item.get("message", "scripted error")}}).encode()
                    self.send_response(item["status"])
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in outer._chunks(item):
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._http.server_address[1]
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

    @staticmethod
    def _chunks(item: dict) -> list[dict]:
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        if "tool" in item:
            call_delta = {"index": 0, "id": "call_1", "type": "function",
                          "function": {"name": item["tool"], "arguments": json.dumps(item["arguments"])}}
            return [{"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [call_delta]}}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}], "usage": usage}]
        chunks = []
        if item.get("thinking"):
            chunks.append({"choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": item["thinking"]}}]})
        if item["text"]:
            chunks.append({"choices": [{"index": 0, "delta": {"role": "assistant", "content": item["text"]}}]})
        return chunks + [{"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}]

    def close(self) -> None:
        """Stop answering and refuse connections (the socket is closed too). Safe to call twice."""
        if not getattr(self, "_closed", False):
            self._closed = True
            self._http.shutdown()
            self._http.server_close()

    def system_prompt(self, n: int = 0) -> str:
        return next(m["content"] for m in self.requests[n]["messages"] if m["role"] == "system")

    def tool_names(self, n: int = 0) -> list[str]:
        return [t["function"]["name"] for t in self.requests[n].get("tools", [])]

    def user_texts(self, n: int = -1) -> list[str]:
        return [m["content"] for m in self.requests[n]["messages"] if m["role"] == "user" and isinstance(m["content"], str)]


def isolated_env(server: FakeModel | None, home: Path, *, with_key: bool = True, settings: dict | None = None) -> dict[str, str]:
    """A process environment with a throwaway HOME where the fake model is the only provider. `settings` is merged
    into ~/.clyde/settings.json (hooks, MCP servers and the like)."""
    home.mkdir(parents=True, exist_ok=True)
    clyde = home / ".clyde"
    clyde.mkdir(exist_ok=True)
    merged = dict(settings or {})
    if server is not None:
        merged["providers"] = {"fake": {"base_url": f"http://127.0.0.1:{server.port}/v1"}}
        if with_key:
            (clyde / "keys.json").write_text(json.dumps({"fake": "test-key"}))
    if merged:
        (clyde / "settings.json").write_text(json.dumps(merged))
    env = {k: v for k, v in os.environ.items()
           if not k.endswith(("_API_KEY", "_API_TOKEN", "_ACCOUNT_ID")) and k != "XDG_CONFIG_HOME"}
    env.update({
        "HOME": str(home), "TERM": "xterm-256color", "PYTHONPATH": str(REPO),
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",     # no Ollama or LM Studio command line tools
        "OLLAMA_HOST": "http://127.0.0.1:1", "OLLAMA_API_BASE": "http://127.0.0.1:1",   # both: the second wins when set
        "CLYDE_NO_MODEL_FETCH": "1",
        "CLYDE_TRACE": "off", "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


class Terminal:
    """`clyde` in a pseudo-terminal. `expect` waits for text in what has been printed so far (ANSI removed)."""

    def __init__(self, server: FakeModel | None, workdir: Path, args: list[str] | None = None, *, home: Path | None = None,
                 env: dict[str, str] | None = None, rows: int = 30, cols: int = 120, with_key: bool = True,
                 settings: dict | None = None, keep_home: bool = False) -> None:
        self.workdir = workdir
        self.keep_home = keep_home or home is not None   # a HOME the test made is the test's to remove
        self.home = home or Path(tempfile.mkdtemp(prefix="clyde-e2e-home-"))
        self.env = env or isolated_env(server, self.home, with_key=with_key, settings=settings)
        self.args = args if args is not None else ["--model", "fake:m"]
        self.buffer = ""
        self._seen = 0
        pid, fd = pty.fork()
        if pid == 0:
            # A test run started with `&` has SIGINT ignored, and so would the app (Python keeps an inherited
            # "ignore"): Ctrl+C would silently do nothing. Restore the defaults a terminal user gets.
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGQUIT, signal.SIG_DFL)
            os.chdir(workdir)
            # SIGUSR1 dumps every thread's Python stack to the terminal, so a wait that times out can show what the app
            # was doing (see expect). Otherwise this is `python -m src.cli`.
            boot = ("import faulthandler, runpy, signal; faulthandler.register(signal.SIGUSR1, all_threads=True); "
                    "runpy.run_module('src.cli', run_name='__main__', alter_sys=True)")
            os.execve(sys.executable, [sys.executable, "-c", boot, *self.args], self.env)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def __enter__(self) -> "Terminal":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _pump(self, wait: float) -> None:
        end = time.monotonic() + wait
        while True:
            ready, _, _ = select.select([self.fd], [], [], max(0.0, min(0.1, end - time.monotonic())))
            if ready:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.buffer += _ANSI.sub("", data.decode("utf-8", errors="replace"))
            if time.monotonic() >= end:
                return

    def expect(self, text: str, timeout: float = 15, *, regex: bool = False, since_last: bool = False) -> str:
        """Wait until `text` appears (after the last match when `since_last`); returns the output so far."""
        pattern = re.compile(text if regex else re.escape(text))
        end = time.monotonic() + timeout
        start = self._seen if since_last else 0
        while time.monotonic() < end:
            found = pattern.search(self.buffer, start)
            if found:
                self._seen = found.end()
                return self.buffer
            self._pump(0.2)
        stacks = ""
        if self.pid:                                  # what was the app doing? its threads' stacks, via SIGUSR1
            before = len(self.buffer)
            try:
                os.kill(self.pid, signal.SIGUSR1)
                self._pump(1.0)
                stacks = "\n--- the app's thread stacks ---\n" + self.buffer[before:][-3500:] + self._terminal_state()
            except OSError:
                pass
        raise AssertionError(f"timed out waiting for {text!r}\n--- screen so far (tail) ---\n{self.buffer[-1500:]}{stacks}")

    def _terminal_state(self) -> str:
        """Which terminal flags and which process group the app has, for a stuck-prompt report."""
        try:
            lflag = termios.tcgetattr(self.fd)[3]
            flags = ", ".join(f"{name}={'on' if lflag & bit else 'off'}" for name, bit in
                              (("ISIG", termios.ISIG), ("ICANON", termios.ICANON), ("ECHO", termios.ECHO)))
            return f"\n--- terminal: {flags}; foreground group {os.tcgetpgrp(self.fd)}, app {self.pid} ---"
        except (OSError, termios.error) as e:
            return f"\n--- terminal state unavailable: {e} ---"

    def absent(self, text: str, wait: float = 1.5) -> None:
        """Assert `text` does not show up in the next `wait` seconds."""
        self._pump(wait)
        assert text not in self.buffer[self._seen:], f"{text!r} appeared\n{self.buffer[-800:]}"

    def send(self, data: bytes | str) -> None:
        """Type `data`. Written in small pieces with the app's output drained in between: a long paste otherwise
        fills the pty while the app is blocked writing its redraws, and both sides wait on each other."""
        raw = data.encode() if isinstance(data, str) else data
        for i in range(0, len(raw), 256):
            os.write(self.fd, raw[i:i + 256])
            self._pump(0.002)

    def paste(self, text: str) -> None:
        """Paste `text` as a terminal does: one bracketed-paste block (the app collapses a big one to a marker)."""
        self.send(b"\x1b[200~" + text.encode() + b"\x1b[201~")

    def send_line(self, text: str) -> None:
        self.send(text.encode() + ENTER)

    def turn_done(self, timeout: float = 30) -> None:
        """Wait for the turn footer ("... 100 in, 10 out") after the last match, then for the prompt to take input."""
        self.expect(r"\d+ in, \d+ out", timeout, regex=True, since_last=True)
        self.ready()

    def ready(self, timeout: float = 15) -> None:
        """Wait until the prompt accepts typing. The screen is redrawn cell by cell, so the chevron is not re-sent
        and cannot be waited for; a marker typed and echoed back can."""
        self._ready_count = getattr(self, "_ready_count", 0) + 1
        marker = f"zq{self._ready_count}qz"
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.send(marker)
            try:
                self.expect(marker, 1.5, since_last=True)
            except AssertionError:
                continue
            self.send(b"\x15")                    # Ctrl+U clears the line again
            self._pump(0.2)
            return
        raise AssertionError(f"the prompt never took input\n{self.buffer[-800:]}")

    def mark(self) -> None:
        """Only look at output from here on."""
        self._pump(0.3)
        self._seen = len(self.buffer)

    def tail(self, n: int = 1200) -> str:
        self._pump(0.3)
        return self.buffer[-n:]

    def wait_exit(self, timeout: float = 10) -> int | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self._pump(0.1)
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                self.pid = 0
                return os.waitstatus_to_exitcode(status)
        return None

    def close(self) -> None:
        """Release the terminal, stop the app and reap it. The pty is closed first: a child that is still writing
        to a full terminal cannot finish exiting until its other end is gone, so waiting for it first deadlocks."""
        fd, self.fd = self.fd, -1
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
            for _ in range(50):                      # up to 5 s, never forever
                try:
                    done, _status = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    break
                if done:
                    break
                time.sleep(0.1)
            self.pid = 0
        if not self.keep_home:
            shutil.rmtree(self.home, ignore_errors=True)


def run_cli(server: FakeModel | None, workdir: Path, args: list[str], *, stdin: str | None = None, timeout: int = 60,
            env_extra: dict[str, str] | None = None) -> tuple[int, str, str]:
    """A non-interactive `clyde ...` run (print mode and the like): (exit code, stdout, stderr)."""
    import subprocess
    home = Path(tempfile.mkdtemp(prefix="clyde-e2e-home-"))
    try:
        env = isolated_env(server, home)
        env.update(env_extra or {})
        done = subprocess.run([sys.executable, "-m", "src.cli", *args], cwd=workdir, env=env, input=stdin,
                              capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    finally:
        shutil.rmtree(home, ignore_errors=True)
