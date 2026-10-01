"""Modes: hold (asks), reading the table (plan only), all in (asks only before major moves)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall


class ModeCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.asked: list[str] = []
        self.ctx = ToolContext(workspace_root=self.root)
        self.ctx.permission_handler = lambda tool, message, suggestion: (self.asked.append(message) or True, False)
        self.registry = build_default_registry()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def bash(self, command: str):
        return self.registry.dispatch(ToolCall(name="Bash", input={"command": command}), self.ctx)


class TestReadingTheTable(ModeCase):
    def test_changes_are_refused_reads_are_not(self):
        self.ctx.plan_mode = True
        target = self.root / "x.txt"
        wrote = self.registry.dispatch(ToolCall(name="Write", input={"file_path": str(target), "content": "x"}), self.ctx)
        self.assertTrue(wrote.is_error)
        self.assertIn("Reading the table", wrote.output["error"])
        self.assertFalse(target.exists())
        self.assertTrue(self.bash("touch y").is_error)
        self.assertFalse(self.bash("ls").is_error)
        self.assertEqual(self.asked, [])


class TestAllIn(ModeCase):
    def test_ordinary_commands_run_without_asking(self):
        self.ctx.auto_approve = True
        self.assertFalse(self.bash("touch made.txt").is_error)
        self.assertTrue((self.root / "made.txt").exists())
        self.assertEqual(self.asked, [])

    def test_major_moves_still_ask(self):
        self.ctx.auto_approve = True
        (self.root / "build").mkdir()
        self.bash("rm -rf build")
        self.bash("git push origin main")
        self.assertEqual(len(self.asked), 2, self.asked)
        # Writing outside the project is refused outright, in every mode.
        from src.tool_system.errors import ToolPermissionError
        outside = Path(tempfile.gettempdir()) / "clyde-all-in-outside.txt"
        with self.assertRaises(ToolPermissionError):
            self.registry.dispatch(ToolCall(name="Write", input={"file_path": str(outside), "content": "x"}), self.ctx)
        self.assertFalse(outside.exists())

    def test_deny_rules_still_win(self):
        self.ctx.auto_approve = True
        self.ctx.permission_rules = {"allow": [], "deny": ["Bash(touch:*)"]}
        self.assertTrue(self.bash("touch nope").is_error)


class TestCycling(unittest.TestCase):
    def test_shift_tab_order_and_exit_plan_mode_returns_to_hold(self):
        from src.repl.core import ClydeREPL

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.tool_context = ToolContext(workspace_root=Path.cwd())
        seen = [repl.mode]
        for _ in range(3):
            repl._cycle_mode()
            seen.append(repl.mode)
        self.assertEqual(seen, ["hold", "plan", "all_in", "hold"])
        repl._set_mode("plan")
        build_default_registry().dispatch(ToolCall(name="ExitPlanMode", input={}), repl.tool_context)
        self.assertEqual(repl.mode, "hold")


if __name__ == "__main__":
    unittest.main()
