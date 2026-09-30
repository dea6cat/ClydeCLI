"""Tests for `clyde plugin install|list|remove|enable|disable`."""

from __future__ import annotations

import io
import json
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


class TestPluginImport(unittest.TestCase):
    """`clyde plugin import` over a fake ~/.claude plugin index."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._home = patch.object(Path, "home", return_value=self.home)
        self._home.start()
        cache = self.home / ".claude" / "plugins" / "cache"
        on = make_plugin(cache / "mkt", "alpha", manifest_dir=".claude-plugin")
        off = make_plugin(cache / "mkt", "beta", manifest_dir=".claude-plugin")
        legacy = make_plugin(cache / "other", "legacy", manifest_dir=".claude-plugin")
        (legacy / ".claude-plugin" / "plugin.json").rename(legacy / "plugin.json")  # older root-manifest layout
        (legacy / ".claude-plugin").rmdir()
        bare = cache / "mkt" / "lsp-only"
        (bare / ".claude-plugin").mkdir(parents=True)
        (bare / ".claude-plugin" / "plugin.json").write_text('{"name": "lsp-only"}')
        nomanifest = cache / "mkt" / "readme-only"
        nomanifest.mkdir()
        index = {"version": 2, "plugins": {f"{p.name}@m": [{"installPath": str(p)}] for p in (on, off, legacy, bare, nomanifest)}}
        (self.home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(index))
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"beta@m": False}}))
        self.out = io.StringIO()
        self.console = Console(file=self.out, width=200)

    def tearDown(self) -> None:
        self._home.stop()
        self._tmp.cleanup()

    def test_finds_every_plugin_with_its_state(self) -> None:
        found = {(f.plugin.name if f.plugin else f.source.name): f for f in plugins.find_foreign()}
        self.assertEqual(set(found), {"alpha", "beta", "legacy", "lsp-only", "readme-only"})
        self.assertTrue(found["alpha"].enabled_there)
        self.assertFalse(found["beta"].enabled_there)
        self.assertEqual(found["legacy"].reason, "")
        self.assertIn("nothing ClydeCLI can load", found["lsp-only"].reason)
        self.assertEqual(found["readme-only"].reason, "no plugin manifest")

    def test_each_yes_copies_and_enables(self) -> None:
        answers = iter([True, False, True])  # alpha, beta, legacy
        with patch("rich.prompt.Confirm.ask", side_effect=lambda *a, **k: next(answers)) as ask:
            self.assertEqual(handle_plugin(self.console, "import", None), 0)
        self.assertEqual([c.kwargs["default"] for c in ask.call_args_list], [True, False, True])
        self.assertTrue(plugins.is_enabled("alpha") and plugins.is_enabled("legacy"))
        self.assertFalse((plugins.plugins_dir() / "beta").exists())
        self.assertTrue((plugins.plugins_dir() / "alpha" / "tools" / "echo.py").is_file())
        text = self.out.getvalue()
        self.assertIn("(disabled in Claude Code)", text)
        self.assertIn("readme-only skipped: no plugin manifest", text)
        # already-imported plugins are not offered again
        self.assertNotIn("alpha", {f.plugin.name for f in plugins.find_foreign() if f.plugin})

    def test_yes_flag_never_imports(self) -> None:
        with patch("rich.prompt.Confirm.ask", side_effect=AssertionError("prompted")):
            self.assertEqual(handle_plugin(self.console, "import", None, assume_yes=True), 0)
        self.assertFalse(plugins.plugins_dir().exists() and any(plugins.plugins_dir().iterdir()))
        self.assertIn("3 plugin(s) from other agents can be imported", self.out.getvalue())
