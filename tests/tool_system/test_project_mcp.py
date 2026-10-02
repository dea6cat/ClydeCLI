"""Project .mcp.json: servers a repository ships start only after a yes for that exact entry."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.mcp_client import (_expand_vars, describe_server, project_approval, project_servers,
                                        set_project_approval)


class TestProjectServers(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.repo = Path(tempfile.mkdtemp()).resolve()
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = {"command": "npx", "args": ["-y", "docs-server", "--root", "${PROJECT_ROOT:-.}"], "env": {"TOKEN": "${DOCS_TOKEN}"}}
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"docs": self.cfg}}))

    def test_reads_the_projects_servers(self):
        self.assertEqual(project_servers(self.repo), {"docs": self.cfg})
        self.assertEqual(project_servers(self.home), {})

    def test_variables_expand_like_claude_code(self):
        with patch.dict(os.environ, {"DOCS_TOKEN": "t0k"}, clear=False):
            os.environ.pop("PROJECT_ROOT", None)
            self.assertEqual(_expand_vars(self.cfg), {"command": "npx", "args": ["-y", "docs-server", "--root", "."],
                                                      "env": {"TOKEN": "t0k"}})
        self.assertEqual(_expand_vars("${CLYDE_SURELY_UNSET_VAR}"), "${CLYDE_SURELY_UNSET_VAR}")

    def test_an_approval_covers_only_that_exact_entry(self):
        self.assertIsNone(project_approval(self.repo, "docs", self.cfg))
        set_project_approval(self.repo, "docs", self.cfg, True)
        self.assertTrue(project_approval(self.repo, "docs", self.cfg))
        changed = {**self.cfg, "command": "curl"}
        self.assertIsNone(project_approval(self.repo, "docs", changed))      # a changed entry asks again
        set_project_approval(self.repo, "docs", changed, False)
        self.assertFalse(project_approval(self.repo, "docs", changed))

    def test_description_never_shows_secret_values(self):
        line = describe_server({"command": "x", "env": {"TOKEN": "s3cret"}})
        self.assertIn("env: TOKEN", line)
        self.assertNotIn("s3cret", line)
        self.assertNotIn("abc", describe_server({"url": "https://h/mcp", "headers": {"Authorization": "Bearer abc"}}))


class TestReplPrompt(unittest.TestCase):
    """The REPL asks once per new or changed entry, remembers the answer, and never asks when headless."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.repo = Path(tempfile.mkdtemp()).resolve()
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "docs": {"command": "docs-server"}, "mine": {"command": "repo-version"}}}))

    def _servers(self, answers, headless=False, taken=frozenset({"mine"})):
        from rich.console import Console
        from src.repl.core import ClydeREPL

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.console, repl.headless = Console(file=open(os.devnull, "w")), headless
        with patch("rich.prompt.Confirm.ask", side_effect=answers) as ask:
            got = repl._project_mcp_servers(self.repo, set(taken))
        return got, ask.call_count

    def test_yes_starts_it_no_is_remembered_and_your_settings_win(self):
        got, asked = self._servers([True])
        self.assertEqual((got, asked), ({"docs": {"command": "docs-server"}}, 1))   # "mine" is yours: not asked
        self.assertEqual(self._servers([])[1], 0)                                   # answered: not asked again
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"docs": {"command": "changed"}}}))
        got, asked = self._servers([False])
        self.assertEqual((got, asked), ({}, 1))
        self.assertEqual(self._servers([])[0], {})                                  # the no is remembered

    def test_headless_never_asks_and_skips_unanswered_entries(self):
        got, asked = self._servers([], headless=True)
        self.assertEqual((got, asked), ({}, 0))


if __name__ == "__main__":
    unittest.main()
