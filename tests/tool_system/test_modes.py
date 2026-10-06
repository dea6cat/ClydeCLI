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


class TestHoldAsksBeforeEveryEdit(ModeCase):
    """With confirm_edits (the REPL's hold mode) every file change asks, whatever the file; code files included."""

    def setUp(self) -> None:
        super().setUp()
        self.ctx.confirm_edits = True

    def write(self, name: str, content: str = "x"):
        return self.registry.dispatch(ToolCall(name="Write", input={"file_path": str(self.root / name), "content": content}), self.ctx)

    def test_a_code_file_asks_and_is_written_only_after_a_yes(self):
        result = self.write("a.py", "x = 1")
        self.assertFalse(result.is_error)
        self.assertEqual(self.asked, ["Write wants to change a.py"])
        self.assertEqual((self.root / "a.py").read_text(), "x = 1")

    def test_a_no_leaves_the_file_alone(self):
        self.ctx.permission_handler = lambda tool, message, suggestion: (self.asked.append(message) or False, False)
        result = self.write("a.py")
        self.assertTrue(result.is_error)
        self.assertFalse((self.root / "a.py").exists())

    def test_edit_asks_too(self):
        target = self.root / "b.py"
        target.write_text("old")
        from src.tool_system.tools.read import FileReadTool  # noqa: F401  (Edit needs the file read first)
        self.registry.dispatch(ToolCall(name="Read", input={"file_path": str(target)}), self.ctx)
        self.asked.clear()                                   # reading a plain file did not ask
        self.registry.dispatch(ToolCall(name="Edit", input={"file_path": str(target), "old_string": "old", "new_string": "new"}), self.ctx)
        self.assertEqual(self.asked, ["Edit wants to change b.py"])
        self.assertEqual(target.read_text(), "new")

    def test_without_anyone_to_ask_it_is_denied(self):
        self.ctx.permission_handler = None                   # print mode in hold
        result = self.write("a.py")
        self.assertTrue(result.is_error)
        self.assertFalse((self.root / "a.py").exists())

    def test_a_saved_allow_rule_skips_the_question(self):
        self.ctx.permission_rules = {"allow": ["Write(a.py)"], "deny": []}
        self.assertFalse(self.write("a.py").is_error)
        self.assertEqual(self.asked, [])
        self.write("other.py")                               # a different file still asks
        self.assertEqual(self.asked, ["Write wants to change other.py"])

    def test_all_in_and_the_default_context_do_not_ask(self):
        self.ctx.auto_approve = True
        self.write("a.py")
        self.ctx.auto_approve = False
        self.ctx.confirm_edits = False                       # what library callers get
        self.write("b.py")
        self.assertEqual(self.asked, [])
        self.assertTrue((self.root / "a.py").exists() and (self.root / "b.py").exists())

    def test_plan_mode_still_refuses_and_reads_still_do_not_ask(self):
        self.ctx.plan_mode = True
        self.assertIn("Reading the table", self.write("a.py").output["error"])
        self.ctx.plan_mode = False
        (self.root / "c.txt").write_text("hi")
        self.registry.dispatch(ToolCall(name="Read", input={"file_path": str(self.root / "c.txt")}), self.ctx)
        self.assertEqual(self.asked, [])


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
