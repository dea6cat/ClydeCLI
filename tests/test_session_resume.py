"""Session auto-save and /resume recovery, against a temp home and workspace (never ~/.clyde)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.agent import Session
from src.providers.convert import to_canonical
from src.repl import ClydeREPL
from tests.fakes import FakeProvider, reply


class _TempHomeAndWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name).resolve()
        self.home = root / "home"
        self.workspace = root / "work"
        self.home.mkdir()
        self.workspace.mkdir()
        self._old_cwd = os.getcwd()
        os.chdir(self.workspace)
        home = patch("pathlib.Path.home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _save(self, session_id: str, updated_at: str, prompt: str, cwd: Path | None = None) -> Session:
        session = Session(session_id=session_id, provider="glm", model="glm-4.5", cwd=str(cwd or self.workspace))
        session.conversation.add_user_message(prompt)
        session.conversation.add_assistant_message(f"answer to {prompt}")
        session.save()
        path = self.home / ".clyde" / "sessions" / f"{session_id}.json"
        data = json.loads(path.read_text())
        data["updated_at"] = updated_at
        path.write_text(json.dumps(data))
        return session

    def _repl(self, *responses, **kwargs) -> tuple[ClydeREPL, FakeProvider]:
        provider = FakeProvider(*responses, name="glm", models=("glm-4.5",))
        with patch("src.repl.core.build_registry", return_value={"glm": provider}), \
                patch("src.repl.core.keys.load_into_env"):
            repl = ClydeREPL(model="glm:glm-4.5", **kwargs)
        repl.console.print = Mock()
        return repl, provider

    def _printed(self, repl: ClydeREPL) -> str:
        return "\n".join(str(a[0]) for a, _k in repl.console.print.call_args_list if a)


class TestSessionListing(_TempHomeAndWorkspace):
    def test_lists_this_workspace_newest_first_and_skips_broken_files(self):
        self._save("old", "2026-01-01T10:00:00", "first")
        self._save("new", "2026-01-02T10:00:00", "second")
        self._save("elsewhere", "2026-01-03T10:00:00", "other", cwd=self.home)
        (self.home / ".clyde" / "sessions" / "broken.json").write_text("{not json")

        ids = [s.session_id for s in Session.list_recent(str(self.workspace))]

        self.assertEqual(ids, ["new", "old"])

    def test_restored_tool_history_is_valid_for_providers(self):
        session = Session(session_id="tools", provider="glm", model="glm-4.5")
        repl, _ = self._repl(
            reply("Looking.", tool_calls=[("Glob", {"pattern": "*.py"}, "call_1")]),
            reply("No Python files."),
        )
        repl.session = session
        repl.command_context.conversation = session.conversation
        repl.chat("list the python files in this folder")

        loaded = Session.load("tools")
        canonical = to_canonical(loaded.conversation, "")

        calls = [c for m in canonical.messages for c in m.tool_calls]
        results = [r for m in canonical.messages for r in m.tool_results]
        self.assertEqual([c.id for c in calls], ["call_1"])
        self.assertEqual([r.tool_call_id for r in results], ["call_1"])


class TestResumeCommand(_TempHomeAndWorkspace):
    def test_chat_autosaves_the_session(self):
        repl, _ = self._repl(reply("Hi."))

        repl.chat("hello there")

        loaded = Session.load(repl.session.session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.conversation.messages), 2)
        self.assertEqual(loaded.cwd, str(self.workspace))

    def test_auto_save_can_be_turned_off(self):
        config = self.home / ".clyde" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"model": None, "session": {"auto_save": False}}))
        repl, _ = self._repl(reply("Hi."))

        repl.chat("hello there")

        self.assertIsNone(Session.load(repl.session.session_id))

    def test_picker_lists_sessions_and_resumes_the_chosen_one(self):
        self._save("old", "2026-01-01T10:00:00", "fix the parser")
        self._save("new", "2026-01-02T10:00:00", "write the docs")
        repl, _ = self._repl()

        with patch("builtins.input", return_value="2"):
            repl.handle_command("/resume")

        printed = self._printed(repl)
        self.assertLess(printed.index("write the docs"), printed.index("fix the parser"))
        self.assertIn("2026-01-02 10:00", printed)
        self.assertEqual(repl.session.session_id, "old")
        self.assertIs(repl.command_context.conversation, repl.session.conversation)
        self.assertIn("Resumed session old", printed)
        self.assertIn("You: fix the parser", printed)

    def test_picker_cancel_keeps_current_session(self):
        self._save("old", "2026-01-01T10:00:00", "fix the parser")
        repl, _ = self._repl()
        current = repl.session

        with patch("builtins.input", return_value=""):
            repl.handle_command("/resume")

        self.assertIs(repl.session, current)

    def test_resume_by_id_then_next_turn_replays_history(self):
        self._save("abc", "2026-01-01T10:00:00", "remember the number 7")
        repl, provider = self._repl(reply("It was 7."))

        repl.handle_command("/resume abc")
        repl.chat("what was the number?")

        texts = [m.text for m in provider.requests[0]["conversation"].messages]
        self.assertIn("remember the number 7", texts)
        self.assertEqual(len(Session.load("abc").conversation.messages), 4)

    def test_continue_resumes_the_most_recent_session(self):
        self._save("old", "2026-01-01T10:00:00", "one")
        self._save("new", "2026-01-02T10:00:00", "two")
        repl, _ = self._repl(continue_last=True)
        repl.prompt_session.prompt = Mock(side_effect=EOFError)

        repl.run()

        self.assertEqual(repl.session.session_id, "new")

    def test_resume_without_sessions_says_so(self):
        repl, _ = self._repl()

        repl.handle_command("/resume")

        self.assertIn("No saved sessions", self._printed(repl))


class TestCliFlags(unittest.TestCase):
    def _main(self, *argv):
        from src import cli
        with patch.object(sys, "argv", ["clyde", *argv]), patch.object(cli, "start_repl", return_value=0) as start:
            cli.main()
        return start.call_args.kwargs

    def test_continue_and_resume_flags(self):
        self.assertTrue(self._main("-c")["continue_last"])
        self.assertEqual(self._main("--resume")["resume"], "")
        self.assertEqual(self._main("--resume", "abc")["resume"], "abc")
        self.assertIsNone(self._main()["resume"])


if __name__ == "__main__":
    unittest.main()
