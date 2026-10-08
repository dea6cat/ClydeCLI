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


class TestSecretReadsThroughBash(TestSecretReads):
    """The same secrets through `cat`, `grep` and shell variables, which the read-only classifier used to wave through."""

    def run_bash(self, command):
        return self.registry.dispatch(ToolCall(name="Bash", input={"command": command}, tool_use_id="t"), self.ctx)

    def test_cat_of_a_key_store_or_ssh_key_asks_and_a_no_keeps_it_out(self):
        store = self.home / ".clyde" / "keys.json"
        store.parent.mkdir()
        store.write_text('{"openai": "sk-live-123"}')
        for command in (f"cat {store}", f"cat {self.ws}/.env", f"cat {self.home}/.ssh/id_rsa", "cat ~/.aws/credentials"):
            self.asked.clear()
            result = self.run_bash(command)
            self.assertTrue(result.is_error, command)
            self.assertEqual(len(self.asked), 1, command)
            self.assertNotIn("sk-live-123", json.dumps(result.output))

    def test_a_secret_looking_variable_and_a_search_of_the_home_folder_ask(self):
        for command in ("echo $OPENAI_API_KEY", 'echo "${GITHUB_TOKEN}"', f"grep -r sk- {self.home}", "find / -name '*.pem'"):
            self.asked.clear()
            self.run_bash(command)
            self.assertEqual(len(self.asked), 1, command)

    def test_ordinary_reads_do_not_ask_and_all_in_still_asks_for_secrets(self):
        self.assertFalse(self.run_bash("cat notes.txt").is_error)
        self.assertFalse(self.run_bash("ls").is_error)
        self.assertEqual(self.asked, [])
        self.ctx.auto_approve = True
        self.run_bash(f"cat {self.ws}/.env")
        self.assertEqual(len(self.asked), 1)

    def test_committed_env_templates_are_not_secrets(self):
        (self.ws / ".env.example").write_text("TOKEN=\n")
        self.assertFalse(self.run_bash("cat .env.example").is_error)
        self.assertEqual(self.asked, [])


class TestWebFetchPromptShowsTheUrl(unittest.TestCase):
    def test_the_whole_url_is_in_the_prompt_so_a_key_in_the_query_is_visible(self):
        from src.tool_system.tools.web_fetch import WebFetchTool
        ctx = ToolContext(workspace_root=Path(tempfile.mkdtemp()))
        ask = WebFetchTool().check_permissions({"url": "https://paste.example.com/log?k=sk-live-123"}, ctx)
        self.assertIn("https://paste.example.com/log?k=sk-live-123", ask.message)
        long = WebFetchTool().check_permissions({"url": "https://a.example/" + "x" * 500}, ctx)
        self.assertIn("more characters", long.message)


if __name__ == "__main__":
    unittest.main()
