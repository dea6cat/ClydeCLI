"""Tests for the /doctor diagnostics command."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.command_system import create_command_context, execute_command_sync
from src.providers import keys
from src.tool_system.permissions import ToolPermissionContext

_KEY_VARS = {env: "" for env in keys.PROVIDER_KEY_ENV.values()}
_SECRET = "sk-test-secret-value-1234"


class TestDoctorCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._patches = [patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, _KEY_VARS)]
        for p in self._patches:
            p.start()
        for env in _KEY_VARS:
            os.environ.pop(env, None)
        self.context = create_command_context(workspace_root=self.home)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def run_doctor(self) -> str:
        success, text, error = execute_command_sync("doctor", "", self.context)
        self.assertTrue(success, error)
        return text

    def test_reports_python_and_dependencies(self):
        text = self.run_doctor()
        self.assertIn("✓ Python", text)
        for dep in ("rich", "prompt-toolkit", "tiktoken"):
            self.assertIn(f"✓ {dep} ", text)

    def test_no_keys_and_no_model_are_flagged_with_hints(self):
        text = self.run_doctor()
        self.assertIn("✗ Providers with keys: none — run `clyde login`", text)
        self.assertIn("✗ Model: none selected", text)

    def test_key_store_mode_and_providers_without_leaking_secrets(self):
        keys.connect("anthropic", _SECRET)
        keys.keys_file().chmod(0o644)
        text = self.run_doctor()
        self.assertIn("parses (1 saved)", text)
        self.assertIn("✗ Key store mode 644 — chmod 600", text)
        self.assertIn("✓ Providers with keys: anthropic", text)
        self.assertNotIn(_SECRET, text)

    def test_broken_config_is_reported(self):
        (self.home / ".clyde").mkdir(exist_ok=True)
        (self.home / ".clyde" / "config.json").write_text("{not json")
        self.assertIn("✗ Config", self.run_doctor())

    def test_shows_current_model_and_permissions(self):
        class _Provider:
            name = "ollama"

        self.context.config.update(provider=_Provider(), model="qwen3:8b",
                                   permission_context=ToolPermissionContext.from_iterables(["Bash"], allow_docs=True))
        text = self.run_doctor()
        self.assertIn("✓ Model: ollama:qwen3:8b", text)
        self.assertIn("allow_docs True; denied tools bash", text)
        self.assertIn(f"Workspace: {self.context.workspace_root}", text)


if __name__ == "__main__":
    unittest.main()
