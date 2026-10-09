"""/plugins: the Installed, Errors and Stats tabs and the keys that drive them."""

from __future__ import annotations

import unittest

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from src import plugin_screen, plugins
from tests.test_plugins import PluginHomeCase, make_plugin

LEFT, RIGHT, DOWN, ESC = "\x1b[D", "\x1b[C", "\x1b[B", "\x1b"


def _text(fragments) -> str:
    return "".join(t for _, t in fragments)


class TestPluginScreen(PluginHomeCase):
    def test_installed_tab_lists_state_and_what_each_plugin_adds(self) -> None:
        self.installed_sample()
        shown = _text(plugin_screen.render(0, 0, 0, 8, [], ""))
        self.assertIn("sample 1.0.0", shown)
        self.assertIn("disabled · 1 skills, 1 tools, 1 hooks, 1 MCP servers", shown)
        plugins.set_enabled("sample", True)
        self.assertIn("enabled ·", _text(plugin_screen.render(0, 0, 0, 8, [], "")))

    def test_errors_tab_gathers_bad_manifests_startup_warnings_and_unreadable_parts(self) -> None:
        root = self.installed_sample()
        (plugins.plugins_dir() / "broken").mkdir()
        (root / ".mcp.json").write_text("{not json")
        loaded = [plugins.Loaded(plugins.read_manifest(root), warnings=["plugin 'sample': tool X skipped"])]
        found = "\n".join(plugin_screen.errors(loaded))
        self.assertIn("no plugin manifest", found)
        self.assertIn("tool X skipped", found)
        self.assertIn("sample: MCP servers unreadable", found)

    def test_a_clean_install_has_no_errors(self) -> None:
        self.installed_sample()
        self.assertEqual(plugin_screen.errors([]), [])
        self.assertIn("No errors.", _text(plugin_screen.render(1, 0, 0, 8, [], "")))

    def test_stats_count_only_enabled_plugins(self) -> None:
        make_plugin(plugins.plugins_dir(), "one")
        make_plugin(plugins.plugins_dir(), "two")
        plugins.set_enabled("one", True)
        lines = plugin_screen.stats()
        self.assertEqual(lines[0], "2 installed, 1 enabled")
        self.assertIn("1 skills, 1 tools, 1 hooks, 1 MCP servers", lines[1])
        self.assertEqual([line.strip().split(":")[0] for line in lines[2:]], ["one"])

    def test_space_toggles_the_highlighted_plugin_and_arrows_switch_tabs(self) -> None:
        make_plugin(plugins.plugins_dir(), "one")
        make_plugin(plugins.plugins_dir(), "two")
        with create_pipe_input() as pipe:
            pipe.send_text(DOWN + " " + RIGHT + LEFT + ESC)
            plugin_screen.show([], input=pipe, output=DummyOutput())
        self.assertEqual((plugins.is_enabled("one"), plugins.is_enabled("two")), (False, True))


if __name__ == "__main__":
    unittest.main()
