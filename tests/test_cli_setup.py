"""Tests for `clyde setup` onboarding and `clyde hooks import`."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src.cli import handle_hooks_import, handle_setup
from src.providers import keys

_KEY_VARS = {env: "" for env in keys.PROVIDER_KEY_ENV.values()}


class TestSetup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._patches = [patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, _KEY_VARS)]
        for p in self._patches:
            p.start()
        cursor = self.home / ".cursor" / "hooks.json"
        cursor.parent.mkdir()
        cursor.write_text(json.dumps({"version": 1, "hooks": {"beforeShellExecution": [{"command": "audit.sh"}]}}))
        self.settings = self.home / ".clyde" / "settings.json"
        self.out = io.StringIO()
        self.console = Console(file=self.out, width=200)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def test_hooks_import_needs_a_yes(self):
        with patch("rich.prompt.Confirm.ask", return_value=False):
            handle_hooks_import(self.console)
        self.assertIn("audit.sh", self.out.getvalue())
        self.assertFalse(self.settings.exists())

    def test_hooks_import_copies_after_yes(self):
        with patch("rich.prompt.Confirm.ask", return_value=True):
            self.assertEqual(handle_hooks_import(self.console), 0)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"], "Bash")
        self.assertIn("Imported 1 hook", self.out.getvalue())

    def test_setup_yes_never_imports_hooks_or_prompts(self):
        with patch("rich.prompt.Confirm.ask", side_effect=AssertionError("prompted")), \
             patch("rich.prompt.Prompt.ask", side_effect=AssertionError("prompted")), \
             patch("src.providers.build_registry", return_value={}):
            self.assertEqual(handle_setup(self.console, assume_yes=True), 0)
        self.assertFalse(self.settings.exists())
        self.assertIn("clyde hooks import", self.out.getvalue())
        self.assertIn("ClydeCLI is ready", self.out.getvalue())


if __name__ == "__main__":
    unittest.main()
