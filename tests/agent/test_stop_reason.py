"""The loop says why it stopped, so callers need not read its reply text."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent.agent_loop import run_agent_loop
from src.agent.subagent import build_tool_registry
from src.conversation import Conversation
from src.tool_system.context import ToolContext
from tests.fakes import FakeProvider, reply


class TestStopReason(unittest.TestCase):
    def _run(self, *replies):
        conversation = Conversation()
        conversation.add_user_message("go")
        context = ToolContext(workspace_root=Path(tempfile.mkdtemp()))
        return run_agent_loop(conversation, FakeProvider(*replies), "m", build_tool_registry(include_user_tools=False), context)

    def test_an_answer_is_done(self):
        self.assertEqual(self._run(reply("all set")).stop_reason, "done")

    def test_the_same_failing_call_over_and_over_is_a_give_up_not_done(self):
        same = [reply(tool_calls=[("Read", {"file_path": "missing.txt"}, f"t{i}")]) for i in range(12)]
        result = self._run(*same, reply("wrap-up"), reply("wrap-up"))
        self.assertIn(result.stop_reason, ("repeat", "stalled"))
        self.assertFalse(result.ran_out)


if __name__ == "__main__":
    unittest.main()
