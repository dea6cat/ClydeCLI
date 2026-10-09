"""Discover's pool: reading the two catalogs, the day's cache, and the offline fallback."""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from src import plugin_catalog, plugins
from tests.test_plugins import PluginHomeCase

OFFICIAL = {"plugins": [
    {"name": "local", "description": "in the repo", "category": "dev", "source": "./plugins/local"},
    {"name": "external", "description": "own repo", "source": {"source": "url", "url": "https://github.com/o/e.git"}},
    {"name": "nested", "description": "folder of a repo", "source": {"source": "git-subdir", "url": "https://github.com/o/n.git", "path": "plugins/x"}},
    {"name": "odd", "source": {"source": "npm", "package": "x"}},
    {"description": "no name"},
]}
CURSOR = {"plugins": [{"name": "teaching", "source": "teaching", "description": "Skill mapping"}]}


class TestParse(unittest.TestCase):
    def test_the_three_kinds_of_source_and_what_is_left_out(self) -> None:
        got = plugin_catalog.parse("Anthropic", "anthropics/claude-plugins-official", OFFICIAL)
        self.assertEqual([(e.name, e.url, e.subdir) for e in got], [
            ("local", "https://github.com/anthropics/claude-plugins-official.git", "plugins/local"),
            ("external", "https://github.com/o/e.git", ""),
            ("nested", "https://github.com/o/n.git", "plugins/x")])

    def test_narrow_matches_every_word_across_fields(self) -> None:
        pool = plugin_catalog.parse("Anthropic", "a/b", OFFICIAL)
        self.assertEqual([e.name for e in plugin_catalog.narrow(pool, "own repo")], ["external"])
        self.assertEqual([e.name for e in plugin_catalog.narrow(pool, "DEV anthropic")], ["local"])


class TestEntries(PluginHomeCase):
    def _fetch(self, repo, path):
        return OFFICIAL if "anthropics" in repo else CURSOR

    def test_pools_both_repos_then_serves_the_cache_for_a_day(self) -> None:
        with patch.object(plugin_catalog, "_fetch", side_effect=self._fetch) as fetch:
            pool, note = plugin_catalog.entries()
            self.assertEqual((len(pool), note), (4, ""))
            self.assertEqual({e.origin for e in pool}, {"Anthropic", "Cursor"})
            plugin_catalog.entries()
            self.assertEqual(fetch.call_count, 2)   # the second call came from the cache

    def test_offline_keeps_the_saved_pool_and_says_so(self) -> None:
        with patch.object(plugin_catalog, "_fetch", side_effect=self._fetch):
            plugin_catalog.entries()
        saved = json.loads(plugin_catalog._cache_path().read_text())
        saved["fetched"] = time.time() - 2 * plugin_catalog.TTL_S
        plugin_catalog._cache_path().write_text(json.dumps(saved))
        with patch.object(plugin_catalog, "_fetch", side_effect=OSError("offline")):
            pool, note = plugin_catalog.entries()
        self.assertEqual(len(pool), 4)
        self.assertIn("could not reach Anthropic, Cursor", note)

    def test_offline_with_nothing_saved_is_an_empty_pool_with_a_reason(self) -> None:
        with patch.object(plugin_catalog, "_fetch", side_effect=OSError("offline")):
            self.assertEqual(plugin_catalog.entries(), ([], "could not reach Anthropic, Cursor"))


class TestSubdirInstall(PluginHomeCase):
    def test_install_takes_a_folder_of_the_source_and_refuses_one_outside_it(self) -> None:
        from tests.test_plugins import make_plugin
        repo = self.home / "repo"
        make_plugin(repo / "plugins", "inner")
        plugin = plugins.install(str(repo), "plugins/inner")
        self.assertEqual(plugin.name, "inner")
        self.assertTrue((plugins.plugins_dir() / "inner" / "skills").is_dir())
        with self.assertRaises(ValueError):
            plugins.install(str(repo), "../outside")
        with self.assertRaises(ValueError):
            plugins.install(str(repo), "plugins/missing")


if __name__ == "__main__":
    unittest.main()
