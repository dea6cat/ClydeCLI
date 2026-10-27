"""Writes that a crash cannot tear: the old file or the new one, never half, and the last good version kept."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import safe_write
from src.safe_write import read_json_safely, write_json_safely, write_safely


class SafeWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_write_lands_whole_flushes_the_file_and_the_folder_and_leaves_nothing_behind(self):
        path = self.dir / "sub" / "a.json"
        with patch("src.safe_write.os.fsync") as fsync:
            write_safely(path, "hello")
        self.assertEqual(path.read_text(), "hello")
        self.assertGreaterEqual(fsync.call_count, 2)   # the file, then the folder that names it
        self.assertEqual([p.name for p in path.parent.iterdir()], ["a.json"])

    def test_a_crash_before_the_swap_keeps_the_old_file_and_cleans_up(self):
        path = self.dir / "a.json"
        path.write_text('{"v": 1}')
        with patch("src.safe_write.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_safely(path, '{"v": 2}')
        self.assertEqual(path.read_text(), '{"v": 1}')
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.json"])

    def test_private_is_owner_only_and_an_ordinary_write_keeps_the_mode_the_file_had(self):
        secret = self.dir / "keys.json"
        write_safely(secret, "{}", private=True)
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        shared = self.dir / "settings.json"
        shared.write_text("{}")
        os.chmod(shared, 0o640)
        write_safely(shared, "{}\n")
        self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o640)

    def test_the_last_good_version_is_kept_and_a_cut_off_file_never_replaces_it(self):
        path = self.dir / "c.json"
        write_json_safely(path, {"v": 1})
        write_json_safely(path, {"v": 2})
        prev = self.dir / "c.json.prev"
        self.assertEqual((json.loads(path.read_text()), json.loads(prev.read_text())), ({"v": 2}, {"v": 1}))
        path.write_text('{"v": 2, "cut')   # a torn write from some other writer
        write_json_safely(path, {"v": 3})
        self.assertEqual(json.loads(prev.read_text()), {"v": 1})   # the good copy was not overwritten with the cut-off one

    def test_reading_falls_back_to_the_last_good_copy_and_raises_when_there_is_none(self):
        path = self.dir / "d.json"
        write_json_safely(path, {"v": 1})
        write_json_safely(path, {"v": 2})
        path.write_text("")   # cut off
        self.assertEqual(read_json_safely(path), {"v": 1})
        path.unlink()
        self.assertEqual(read_json_safely(path), {"v": 1})   # missing too
        (self.dir / "d.json.prev").unlink()
        with self.assertRaises(OSError):
            read_json_safely(path)
        (self.dir / "e.json").write_text("not json")
        with self.assertRaises(ValueError):
            read_json_safely(self.dir / "e.json")

    def test_the_writers_that_matter_use_it(self):
        from src import config, plugins
        from src.agent import runs, session
        from src.bonnie import automations, pins
        from src.providers import keys
        from src.tool_system import hooks, permission_rules
        ours = (safe_write.write_safely, safe_write.write_json_safely)
        for module in (config, runs, session, automations, pins, hooks, permission_rules, plugins, keys):
            self.assertTrue(any(getattr(module, name, None) in ours for name in dir(module)), module.__name__)


class ConfigSurvivesATornWrite(unittest.TestCase):
    def test_a_cut_off_config_falls_back_to_the_last_good_one_instead_of_the_defaults(self):
        from src import config
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with patch.object(config, "get_config_path", return_value=path):
                config.save_config({"default_model": "a:one"})
                config.save_config({"default_model": "a:two"})
                path.write_text('{"default_model": "a:tw')   # the process died halfway through a write
                self.assertEqual(config.load_config().get("default_model"), "a:one")


if __name__ == "__main__":
    unittest.main()
