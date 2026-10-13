"""Leaving plan mode needs a yes, and the plan goes only to this session's plan file."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.plan_mode import EnterPlanModeTool, ExitPlanModeTool


class TestExitPlanMode(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / ".git" / "hooks").mkdir(parents=True)
        self.plan_file = self.root / ".clyde" / "plans" / "s1.md"
        self.ctx = ToolContext(workspace_root=self.root, plan_file=self.plan_file)
        self.registry = ToolRegistry([EnterPlanModeTool(), ExitPlanModeTool()])
        self.asked: list[str] = []

    def _handler(self, answer):
        def handler(tool_name, message, suggestion):
            self.asked.append(tool_name)
            return answer, False
        self.ctx.permission_handler = handler

    def _exit(self, **extra):
        return self.registry.dispatch(ToolCall(name="ExitPlanMode", input={"plan": "PLAN", **extra}), self.ctx)

    def test_a_plan_path_other_than_the_session_plan_file_is_rejected(self):
        hook = self.root / ".git" / "hooks" / "pre-commit"
        self.ctx.plan_mode = True
        with self.assertRaises(ToolInputError):
            ExitPlanModeTool().run({"plan": "#!/bin/sh\ntouch pwned\n", "planFilePath": str(hook)}, self.ctx)
        self.assertFalse(hook.exists())
        self.assertTrue(self.ctx.plan_mode)

    def test_the_session_plan_file_is_still_written(self):
        self.ctx.plan_mode = True
        ExitPlanModeTool().run({"plan": "PLAN", "planFilePath": str(self.plan_file)}, self.ctx)
        self.assertEqual(self.plan_file.read_text(), "PLAN")
        self.assertFalse(self.ctx.plan_mode)

    def test_leaving_plan_mode_asks_and_a_no_keeps_plan_mode_and_writes_nothing(self):
        self._handler(False)
        self.registry.dispatch(ToolCall(name="EnterPlanMode", input={}), self.ctx)
        result = self._exit()
        self.assertEqual(self.asked, ["ExitPlanMode"])
        self.assertTrue(result.is_error)
        self.assertTrue(self.ctx.plan_mode)
        self.assertFalse(self.plan_file.exists())

    def test_with_no_one_to_ask_plan_mode_cannot_be_left(self):
        self.ctx.permission_handler = None
        self.registry.dispatch(ToolCall(name="EnterPlanMode", input={}), self.ctx)
        self.assertTrue(self._exit().is_error)
        self.assertTrue(self.ctx.plan_mode)

    def test_a_yes_leaves_plan_mode_and_saves_the_plan(self):
        self._handler(True)
        self.registry.dispatch(ToolCall(name="EnterPlanMode", input={}), self.ctx)
        result = self._exit()
        self.assertFalse(result.is_error)
        self.assertFalse(self.ctx.plan_mode)
        self.assertEqual(self.plan_file.read_text(), "PLAN")


if __name__ == "__main__":
    unittest.main()
