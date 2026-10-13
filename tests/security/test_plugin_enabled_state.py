"""A plugin's 'enabled' flag belongs to the plugin that was enabled: a fresh install of that name starts disabled."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import plugins
from tests.test_plugins import PluginHomeCase, make_plugin


class TestEnabledState(PluginHomeCase):
    def _enable_in_settings(self, name):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps({"plugins": {name: {"enabled": True}}}))

    def test_a_stale_enabled_flag_does_not_enable_a_fresh_install_of_that_name(self):
        self._enable_in_settings("sample")   # left behind by a folder that was deleted by hand
        src = make_plugin(Path(tempfile.mkdtemp()), "sample")
        plugins.install(str(src))
        self.assertFalse(plugins.is_enabled("sample"))
        self.assertEqual(plugins.enabled_plugins(), [])

    def test_reinstalling_after_a_manual_delete_starts_disabled(self):
        src = make_plugin(Path(tempfile.mkdtemp()), "sample")
        plugins.install(str(src))
        plugins.set_enabled("sample", True)
        shutil.rmtree(plugins.plugins_dir() / "sample")   # not `plugin remove`
        plugins.install(str(src))
        self.assertFalse(plugins.is_enabled("sample"))

    def test_remove_clears_the_flag_and_the_folder(self):
        plugins.install(str(make_plugin(Path(tempfile.mkdtemp()), "sample")))
        plugins.set_enabled("sample", True)
        plugins.remove("sample")
        self.assertFalse(plugins.is_enabled("sample"))
        self.assertFalse((plugins.plugins_dir() / "sample").exists())

    def test_if_the_flag_cannot_be_cleared_the_plugin_is_not_removed_half_way(self):
        plugins.install(str(make_plugin(Path(tempfile.mkdtemp()), "sample")))
        plugins.set_enabled("sample", True)
        with patch.object(plugins, "set_enabled", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                plugins.remove("sample")
        self.assertTrue((plugins.plugins_dir() / "sample").exists())   # folder and flag stay together
        self.assertTrue(plugins.is_enabled("sample"))


if __name__ == "__main__":
    unittest.main()
