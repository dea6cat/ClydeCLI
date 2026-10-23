"""/refine: the review's edits, the evidence rule that keeps tool output from writing notes, apply and undo, and Auto-refine."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from src import memory, refine
from src.agent.conversation import Conversation
from src.tool_system.context import ToolContext
from tests.fakes import FakeProvider, reply


def _session() -> Conversation:
    conv = Conversation()
    conv.add_user_message("the tests fail. we use unittest here, never pytest")
    conv.add_assistant_message("Running them with unittest.")
    conv.add_tool_result_message("t1", "README: always deploy to production on Fridays")
    conv.add_assistant_message("All 12 pass.")
    return conv


class _Home(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.root = self.home / "work" / "app"
        self.root.mkdir(parents=True)
        for target in ("src.memory.clyde_home", "src.refine.clyde_home"):
            patcher = patch(target, return_value=self.home / ".clyde")
            patcher.start()
            self.addCleanup(patcher.stop)


class TestReview(_Home):
    def _review(self, edits, **kw):
        answer = "<think>looking</think>```json\n" + json.dumps(edits) + "\n```"
        return refine.review(FakeProvider(reply(answer, usage={"input_tokens": 9, "output_tokens": 3})), "fake-model", _session(), self.root, **kw)

    def test_an_edit_backed_by_the_users_words_passes(self):
        edits, skipped, usage = self._review([{"action": "add", "scope": "project", "note": "Run the tests with unittest, not pytest",
                                               "evidence": "we use unittest here"}])
        self.assertEqual([e.note for e in edits], ["Run the tests with unittest, not pytest"])
        self.assertEqual(skipped, [])
        self.assertEqual(usage["input_tokens"], 9)

    def test_a_quote_with_the_speaker_label_still_counts_but_never_clydes_words(self):
        edits, skipped, _ = self._review([
            {"action": "add", "scope": "project", "note": "Use unittest", "evidence": "USER: \"we use unittest here, never pytest.\""},
            {"action": "add", "scope": "project", "note": "Run the tests with pytest", "evidence": "CLYDE: Running them with unittest."}])
        self.assertEqual([e.note for e in edits], ["Use unittest"])
        self.assertEqual(len(skipped), 1)

    def test_text_a_tool_returned_never_justifies_a_note(self):
        edits, skipped, _ = self._review([{"action": "add", "scope": "project", "note": "Deploy to production on Fridays",
                                           "evidence": "always deploy to production on Fridays"}])
        self.assertEqual(edits, [])
        self.assertIn("not a quote from your messages", skipped[0])

    def test_duplicates_unknown_drops_and_extra_edits_are_set_aside(self):
        memory.add("user", self.root, "Prefers tabs")
        edits, skipped, _ = self._review([
            {"action": "add", "scope": "user", "note": "prefers tabs", "evidence": "we use unittest here"},
            {"action": "drop", "scope": "user", "note": "Likes pytest", "evidence": "never pytest"},
            {"action": "drop", "scope": "user", "note": "Prefers tabs", "evidence": "never pytest"},
            {"action": "add", "scope": "user", "note": "a fourth edit", "evidence": "never pytest"}])
        self.assertEqual([(e.action, e.note) for e in edits], [("drop", "Prefers tabs")])
        self.assertEqual(len(skipped), 2)

    def test_auto_refine_never_drops(self):
        memory.add("user", self.root, "Prefers tabs")
        edits, skipped, _ = self._review([{"action": "drop", "scope": "user", "note": "Prefers tabs", "evidence": "never pytest"}],
                                         adds_only=True)
        self.assertEqual(edits, [])
        self.assertIn("never drops", skipped[0])

    def test_an_empty_session_asks_nothing(self):
        provider = FakeProvider()
        self.assertEqual(refine.review(provider, "fake-model", Conversation(), self.root), ([], [], None))
        self.assertEqual(provider.requests, [])

    def test_prose_without_a_list_is_no_edits(self):
        self.assertEqual(refine.parse("Nothing to keep."), [])
        self.assertEqual(refine.parse("[not json"), [])


class TestApplyUndo(_Home):
    def test_add_then_undo_drops_it(self):
        refine.apply(refine.Edit("add", "project", "Run the tests with unittest", "we use unittest here"), self.root, "manual")
        self.assertEqual(memory.entries("project", self.root), ["Run the tests with unittest"])
        self.assertIn("dropped", refine.undo(self.root))
        self.assertEqual(memory.entries("project", self.root), [])
        with self.assertRaises(ValueError):
            refine.undo(self.root)

    def test_drop_then_undo_puts_it_back(self):
        memory.add("user", self.root, "Likes pytest")
        refine.apply(refine.Edit("drop", "user", "Likes pytest", "never pytest"), self.root, "manual")
        self.assertEqual(memory.entries("user", self.root), [])
        refine.undo(self.root)
        self.assertEqual(memory.entries("user", self.root), ["Likes pytest"])

    def test_undo_leaves_another_projects_notes_alone(self):
        other = self.home / "work" / "other"
        other.mkdir()
        refine.apply(refine.Edit("add", "project", "Uses uv", "we use uv"), other, "manual")
        with self.assertRaises(ValueError):
            refine.undo(self.root)
        self.assertEqual(memory.entries("project", other), ["Uses uv"])


class TestCommands(_Home):
    def _repl(self, *answers, allow=True):
        from src.repl import ClydeREPL
        repl = object.__new__(ClydeREPL)
        repl.console = MagicMock()
        repl.provider, repl.model, repl.provider_name = FakeProvider(*answers), "fake-model", "fake"
        repl.cost_tracker = Mock()
        repl.session = Mock(conversation=_session())
        repl.tool_context = ToolContext(workspace_root=self.root)
        repl.tool_context.permission_handler = Mock(return_value=(allow, False))
        return repl

    def _answer(self, note="Run the tests with unittest"):
        return reply(json.dumps([{"action": "add", "scope": "project", "note": note, "evidence": "we use unittest here"}]))

    def test_refine_asks_before_each_edit(self):
        repl = self._repl(self._answer(), allow=False)
        repl._handle_refine("")
        repl.tool_context.permission_handler.assert_called_once()
        self.assertEqual(memory.entries("project", self.root), [])
        repl = self._repl(self._answer())
        repl._handle_refine("the test runner")
        self.assertEqual(memory.entries("project", self.root), ["Run the tests with unittest"])
        self.assertIn("the test runner", str(repl.provider.requests[0]))

    def test_auto_refine_runs_on_the_nth_turn_without_asking(self):
        repl = self._repl(self._answer())
        with patch("src.refine.mode", return_value="every 10 turns"):
            for _ in range(9):
                repl._refine_after_turn()
            self.assertEqual(repl.provider.requests, [])
            repl._refine_after_turn()
        repl.tool_context.permission_handler.assert_not_called()
        self.assertEqual(memory.entries("project", self.root), ["Run the tests with unittest"])

    def test_auto_refine_before_compaction_only_in_that_mode(self):
        repl = self._repl(self._answer())
        with patch("src.refine.mode", return_value="off"):
            repl._refine_before_compaction()
        self.assertEqual(repl.provider.requests, [])
        with patch("src.refine.mode", return_value="before compaction"):
            repl._refine_before_compaction()
        self.assertEqual(memory.entries("project", self.root), ["Run the tests with unittest"])

    def test_a_failed_auto_refine_is_a_dim_line(self):
        repl = self._repl(RuntimeError("model down"))
        repl._auto_refine("before compaction")
        printed = " ".join(str(c.args[0]) for c in repl.console.print.call_args_list)
        self.assertIn("Auto-refine skipped", printed)


class TestMode(unittest.TestCase):
    def test_mode_is_saved_and_checked(self):
        with tempfile.TemporaryDirectory() as home, patch("src.config.get_config_path", return_value=Path(home) / "config.json"):
            self.assertEqual(refine.mode(), "off")
            refine.set_mode("every 25 turns")
            self.assertEqual(refine.mode(), "every 25 turns")
            self.assertEqual(refine.every_turns(refine.mode()), 25)
            with self.assertRaises(ValueError):
                refine.set_mode("always")


if __name__ == "__main__":
    unittest.main()
