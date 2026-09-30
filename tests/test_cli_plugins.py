"""Tests for `clyde plugin install|list|remove|enable|disable`."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src import plugins
from src.cli import handle_plugin
from tests.test_plugins import make_plugin


class TestPluginCli(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._home = patch.object(Path, "home", return_value=self.home)
        self._home.start()
        self.src = make_plugin(self.home / "src")
        self.out = io.StringIO()
        self.console = Console(file=self.out, width=200)

    def tearDown(self) -> None:
        self._home.stop()
        self._tmp.cleanup()

    def test_install_shows_contents_and_needs_a_yes(self) -> None:
        with patch("rich.prompt.Confirm.ask", return_value=False):
            self.assertEqual(handle_plugin(self.console, "install", str(self.src)), 0)
        text = self.out.getvalue()
        for part in ("echo.py", "greet", "PreToolUse [Bash]", "MCP server fake"):
            self.assertIn(part, text)
        self.assertFalse(plugins.is_enabled("sample"))

    def test_install_enables_after_yes(self) -> None:
        with patch("rich.prompt.Confirm.ask", return_value=True):
            handle_plugin(self.console, "install", str(self.src))
        self.assertTrue(plugins.is_enabled("sample"))

    def test_yes_flag_never_enables_or_prompts(self) -> None:
        with patch("rich.prompt.Confirm.ask", side_effect=AssertionError("prompted")):
            self.assertEqual(handle_plugin(self.console, "install", str(self.src), assume_yes=True), 0)
        self.assertTrue((plugins.plugins_dir() / "sample").is_dir())
        self.assertFalse(plugins.is_enabled("sample"))

    def test_enable_disable_list_remove(self) -> None:
        with patch("rich.prompt.Confirm.ask", return_value=False):
            handle_plugin(self.console, "install", str(self.src))
        self.assertEqual(handle_plugin(self.console, "enable", "sample"), 0)
        self.assertTrue(plugins.is_enabled("sample"))
        handle_plugin(self.console, "list", None)
        self.assertIn("sample 1.0.0  enabled", self.out.getvalue())
        self.assertEqual(handle_plugin(self.console, "disable", "sample"), 0)
        self.assertFalse(plugins.is_enabled("sample"))
        self.assertEqual(handle_plugin(self.console, "remove", "sample"), 0)
        self.assertFalse((plugins.plugins_dir() / "sample").exists())

    def test_unknown_plugin_and_bad_source_fail(self) -> None:
        self.assertEqual(handle_plugin(self.console, "enable", "nope"), 1)
        self.assertEqual(handle_plugin(self.console, "remove", "nope"), 1)
        self.assertEqual(handle_plugin(self.console, "install", str(self.home / "missing")), 1)
        self.assertFalse((self.home / ".clyde" / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
