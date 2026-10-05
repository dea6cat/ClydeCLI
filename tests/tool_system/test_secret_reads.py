"""Secret files (.env, keys, .ssh, credentials) reach the model only after a yes, even in all-in mode."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall


class TestSecretReads(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        (self.ws / ".env").write_text("TOKEN=s3cret\n")
        (self.ws / "notes.txt").write_text("hello\n")
        self.home = Path(tempfile.mkdtemp())
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = build_default_registry(include_user_tools=False)
        self.ctx = ToolContext(workspace_root=self.ws)
        self.asked: list[str] = []
        self.ctx.permission_handler = lambda tool, msg, rule: (self.asked.append(msg), (False, False))[1]

    def read(self, name):
        return self.registry.dispatch(ToolCall(name="Read", input={"file_path": str(self.ws / name)}, tool_use_id="t"), self.ctx)

    def test_reading_a_secret_asks_and_a_no_keeps_it_out(self):
        result = self.read(".env")
        self.assertTrue(result.is_error)
        self.assertNotIn("s3cret", json.dumps(result.output))
        self.assertIn("secret file", self.asked[0])

    def test_ordinary_files_and_all_in_mode(self):
        self.assertFalse(self.read("notes.txt").is_error)
        self.assertEqual(self.asked, [])
        self.ctx.auto_approve = True                     # all in still asks for secrets
        self.read(".env")
        self.assertEqual(len(self.asked), 1)

    def test_rules_cover_read(self):
        self.ctx.permission_rules = {"allow": ["Read(.env)"], "deny": []}
        self.assertIn("s3cret", json.dumps(self.read(".env").output))   # an allow rule is a standing yes
        self.ctx.permission_rules = {"allow": [], "deny": ["Read(notes.txt)"]}
        self.assertIn("deny rule", json.dumps(self.read("notes.txt").output))
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()
