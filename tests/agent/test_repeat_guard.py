"""A model that sends the same failing call again and again is told to change approach, then stopped."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent.agent_loop import run_agent_loop
from src.agent.conversation import Conversation
from src.agent.repeat_guard import RepeatGuard
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply


class TestRepeatGuardRules(unittest.TestCase):
    def _run(self, guard, calls):
        """Ask the guard about each (call, result) pair in turn; return the refusals it gave."""
        out = []
        for name, args, result in calls:
            note = guard.refusal(name, args)
            out.append(note)
            if note is None:
                guard.record(name, args, result)
        return out

    def test_the_third_identical_call_with_the_same_result_is_refused(self):
        notes = self._run(RepeatGuard(), [("Map", {"action": "query"}, "err")] * 3)
        self.assertEqual([n is None for n in notes], [True, True, False])
        self.assertIn("3 times in a row", notes[2])

    def test_a_changed_result_is_not_a_repeat(self):
        notes = self._run(RepeatGuard(), [("Bash", {"command": "ls"}, "a"), ("Bash", {"command": "ls"}, "b"), ("Bash", {"command": "ls"}, "b")])
        self.assertEqual(notes, [None, None, None])

    def test_different_arguments_are_not_a_repeat(self):
        notes = self._run(RepeatGuard(), [("Read", {"file_path": f"f{i}"}, "err") for i in range(4)])
        self.assertEqual(notes, [None] * 4)

    def test_a_polled_task_is_never_refused(self):
        notes = self._run(RepeatGuard(), [("TaskOutput", {"task_id": "1"}, "running")] * 5)
        self.assertEqual(notes, [None] * 5)

    def test_two_refusals_in_a_row_mean_stuck_and_a_run_call_resets_it(self):
        guard = RepeatGuard()
        self._run(guard, [("Map", {"action": "query"}, "err")] * 3)
        self.assertFalse(guard.stuck)
        self.assertIsNotNone(guard.refusal("Map", {"action": "query"}))
        self.assertTrue(guard.stuck)
        guard.record("Read", {"file_path": "x"}, "ok")
        self.assertFalse(guard.stuck)


class TestRepeatGuardInTheLoop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.context = ToolContext(workspace_root=Path(self.temp_dir.name))

    def test_a_model_repeating_a_failing_read_is_refused_then_stopped(self):
        missing = {"file_path": str(Path(self.temp_dir.name) / "nope.txt")}
        provider = FakeProvider(*[reply(tool_calls=[("Read", missing, f"id{i}")]) for i in range(4)])
        conversation = Conversation()
        conversation.add_user_message("read nope.txt")

        result = run_agent_loop(conversation=conversation, provider=provider, model="fake-model",
                                tool_registry=build_default_registry(), tool_context=self.context, verbose=False)

        self.assertTrue(result.response_text.startswith("Stopped:"), result.response_text)
        self.assertIn("Read", result.response_text)
        self.assertEqual(len(provider.requests), 4)   # the fifth scripted call was never needed
        texts = [str(m.content) for m in conversation.messages]
        self.assertEqual(sum("exact Read call" in t for t in texts), 2)   # the third and fourth were refused, not run


if __name__ == "__main__":
    unittest.main()
