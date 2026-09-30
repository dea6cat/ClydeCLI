"""Esc cancels a running turn like Ctrl+C; arrow keys don't; the terminal is restored."""

from __future__ import annotations

import os
import select
import sys
import time
import unittest

CHILD = r'''
import sys, time, termios
sys.path.insert(0, %r)
from src.repl.esc import EscWatcher
before = termios.tcgetattr(0)
try:
    with EscWatcher().active():
        print("waiting", flush=True)
        time.sleep(8)
    print("finished", flush=True)
except KeyboardInterrupt:
    print("cancelled", flush=True)
after = termios.tcgetattr(0)
m = ~termios.PENDIN
print("restored" if after[:3] == before[:3] and after[3] & m == before[3] & m else "broken", flush=True)
'''


@unittest.skipUnless(os.name == "posix", "needs a pseudo-terminal")
class TestEscCancels(unittest.TestCase):
    def _run(self, keys: list[bytes]) -> str:
        import pty
        import subprocess

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        fd, child_tty = pty.openpty()
        proc = subprocess.Popen([sys.executable, "-c", CHILD % root], stdin=child_tty, stdout=child_tty,
                                stderr=child_tty, start_new_session=True)
        os.close(child_tty)
        out = b""

        def pump(seconds: float) -> None:
            nonlocal out
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([fd], [], [], 0.05)
                if ready:
                    try:
                        out += os.read(fd, 4096)
                    except OSError:
                        return

        pump(1.5)
        for key in keys:
            os.write(fd, key)
            pump(0.8)
        pump(1.0)
        proc.kill()
        proc.wait()
        os.close(fd)
        return out.decode(errors="replace")

    def test_lone_esc_cancels_and_restores_the_terminal(self):
        out = self._run([b"\x1b[A", b"\x1b"])  # an arrow key first: it must not cancel
        self.assertIn("cancelled", out)
        self.assertIn("restored", out)


class TestPermissionPromptShowsKeys(unittest.TestCase):
    def test_y_and_n_are_visible_and_accepted(self):
        import io
        from pathlib import Path
        from unittest.mock import patch
        from rich.console import Console
        from src.repl.core import ClydeREPL
        from src.tool_system.context import ToolContext

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.console = Console(file=io.StringIO(), width=100)
        repl._current_status = None
        repl.tool_context = ToolContext(workspace_root=Path.cwd())
        with patch("builtins.input", return_value="n") as ask:
            allowed, _ = repl._handle_permission_request("Bash", "Run shell command: rm x", "Bash(rm:*)")
        self.assertFalse(allowed)
        shown = repl.console.file.getvalue()
        for part in ("y  yes", "a  yes, and don't ask again for Bash(rm:*)", "n  no"):
            self.assertIn(part, shown)
        self.assertIn("[y/a/n]", ask.call_args.args[0])


class TestSpinnerResumesAfterPrompt(unittest.TestCase):
    def test_permission_prompt_pauses_then_restarts_the_spinner(self):
        import io
        from pathlib import Path
        from unittest.mock import patch
        from rich.console import Console
        from src.repl.core import ClydeREPL
        from src.tool_system.context import ToolContext

        calls = []

        class FakeStatus:
            def stop(self):
                calls.append("stop")

            def start(self):
                calls.append("start")

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.console = Console(file=io.StringIO(), width=100)
        repl._current_status = FakeStatus()
        repl.tool_context = ToolContext(workspace_root=Path.cwd())
        with patch("builtins.input", side_effect=lambda _prompt: calls.append("input") or "y"):
            allowed, _ = repl._handle_permission_request("Bash", "Run shell command: ls", None)
        self.assertTrue(allowed)
        self.assertEqual(calls, ["stop", "input", "start"])
