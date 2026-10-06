"""Session archive, unarchive and search, against a temp Clyde home (never ~/.clyde)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import Session


class TestSessionArchive(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = patch("src.agent.session.clyde_home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _saved(self, session_id: str, text: str, cwd: str = "/work") -> Session:
        session = Session(session_id=session_id, provider="p", model="m", cwd=cwd)
        session.conversation.add_user_message(text)
        session.save()
        return session

    def test_archive_hides_a_session_and_unarchive_brings_it_back(self):
        self._saved("a1", "hello")
        self.assertTrue(Session.archive("a1"))
        self.assertEqual(Session.list_recent("/work"), [])
        self.assertTrue((self.home / "sessions" / "archive" / "a1.json").is_file())
        self.assertTrue(Session.unarchive("a1"))
        self.assertEqual([s.session_id for s in Session.list_recent("/work")], ["a1"])

    def test_an_unknown_or_unsafe_id_is_refused(self):
        self._saved("a1", "hello")
        for bad in ("nope", "../a1", "a/b", "", ".hidden"):
            self.assertFalse(Session.archive(bad), bad)
        self.assertFalse(Session.unarchive("a1"))          # not archived
        self.assertEqual(len(Session.list_recent("/work")), 1)

    def test_search_finds_the_words_in_this_workspace_only(self):
        self._saved("a1", "please fix the Parser bug in the lexer")
        self._saved("a2", "unrelated chat")
        self._saved("a3", "parser in another project", cwd="/elsewhere")
        found = Session.search("/work", "PARSER")
        self.assertEqual([s.session_id for s, _ in found], ["a1"])
        self.assertIn("Parser bug", found[0][1])
        self.assertEqual(Session.search("/work", "  "), [])

    def test_search_can_look_in_the_archive(self):
        self._saved("a1", "old parser work")
        Session.archive("a1")
        self.assertEqual(Session.search("/work", "parser"), [])
        self.assertEqual([s.session_id for s, _ in Session.search("/work", "parser", archived=True)], ["a1"])


class TestSessionsCli(unittest.TestCase):
    def test_list_search_archive_via_the_command(self):
        import os
        from io import StringIO
        from rich.console import Console
        from src.cli import handle_sessions
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            old = os.getcwd()
            os.chdir(root)
            self.addCleanup(os.chdir, old)
            with patch("src.agent.session.clyde_home", return_value=root / "home"):
                session = Session(session_id="s1", provider="p", model="m", cwd=str(root))
                session.conversation.add_user_message("find the flaky test")
                session.save()
                out = StringIO()
                console = Console(file=out, width=200)
                self.assertEqual(handle_sessions(console, "list", ""), 0)
                self.assertEqual(handle_sessions(console, "search", "flaky"), 0)
                self.assertEqual(handle_sessions(console, "search", "absent"), 1)
                self.assertEqual(handle_sessions(console, "archive", "s1"), 0)
                self.assertEqual(handle_sessions(console, "list", ""), 1)
                self.assertEqual(handle_sessions(console, "archive", ""), 2)
                self.assertEqual(handle_sessions(console, "unarchive", "s1"), 0)
        self.assertIn("s1", out.getvalue())
        self.assertIn("flaky test", out.getvalue())


if __name__ == "__main__":
    unittest.main()
