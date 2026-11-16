"""The settings store: approvals saved before it existed still match, and an update never overwrites a broken file."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import settings


class TestSettings(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.patch = patch("src.settings.clyde_home", return_value=self.home)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_approval_keys_match_the_ones_already_saved(self) -> None:
        root, allow, cfg = self.home, ["Bash(npm test)", "Read"], {"command": "x", "args": ["1"]}
        old_rules = f"{root.resolve()}::{hashlib.sha256(json.dumps(sorted(allow)).encode()).hexdigest()[:16]}"
        old_mcp = f"{root.resolve()}::srv::{hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]}"
        self.assertEqual(settings.Approvals.key(root, sorted(allow)), old_rules)
        self.assertEqual(settings.Approvals.key(root, cfg, "srv"), old_mcp)

    def test_toml_settings_apply_under_json(self) -> None:
        (self.home / "settings.toml").write_text('[permissions]\ndeny = ["Bash(rm:*)"]\n[mcpServers.a]\ncommand = "toml"\n'
                                                 '[mcpServers.b]\ncommand = "b"\n')
        settings.json_path().write_text(json.dumps({"permissions": {"deny": ["WebFetch"]}, "mcpServers": {"a": {"command": "json"}}}))
        merged = settings.read_json()
        self.assertEqual(merged["permissions"]["deny"], ["Bash(rm:*)", "WebFetch"])
        self.assertEqual(merged["mcpServers"]["a"]["command"], "json")
        self.assertEqual(merged["mcpServers"]["b"]["command"], "b")

    def test_update_writes_owner_only_and_refuses_a_file_that_is_not_an_object(self) -> None:
        settings.update(lambda data: data.setdefault("a", 1) == 1)
        self.assertEqual(json.loads(settings.json_path().read_text()), {"a": 1})
        self.assertEqual(settings.json_path().stat().st_mode & 0o777, 0o600)
        settings.json_path().write_text("[1, 2]")
        with self.assertRaises(ValueError):
            settings.update(lambda data: True)
        self.assertEqual(settings.json_path().read_text(), "[1, 2]")


if __name__ == "__main__":
    unittest.main()
