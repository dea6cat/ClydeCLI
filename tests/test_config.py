"""Tests for config.json handling, the legacy migration, and the API-key store."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import (
    get_config_path,
    get_default_config,
    get_default_model,
    load_config,
    save_config,
    set_default_model,
)
from src.providers import keys

_KEY_VARS = {env: "" for env in keys.PROVIDER_KEY_ENV.values()}


class _TempHome(unittest.TestCase):
    """Runs each test with a throwaway HOME and no provider keys in the environment."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._patches = [patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, _KEY_VARS)]
        for p in self._patches:
            p.start()
        for env in _KEY_VARS:
            os.environ.pop(env, None)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def write_config(self, data: dict) -> None:
        get_config_path().write_text(json.dumps(data))


class TestConfigFile(_TempHome):
    def test_config_path_under_home(self):
        self.assertEqual(get_config_path(), self.home / ".clyde" / "config.json")
        self.assertTrue((self.home / ".clyde").is_dir())

    def test_default_config(self):
        config = get_default_config()
        self.assertIsNone(config["model"])
        self.assertTrue(config["session"]["auto_save"])
        self.assertNotIn("providers", config)

    def test_load_creates_default(self):
        self.assertEqual(load_config(), get_default_config())
        self.assertTrue(get_config_path().exists())

    def test_save_load_roundtrip_and_permissions(self):
        save_config({"model": "openai:gpt-5.4", "session": {"auto_save": False}})
        self.assertEqual(load_config()["model"], "openai:gpt-5.4")
        if os.name != "nt":
            self.assertEqual(get_config_path().stat().st_mode & 0o777, 0o600)

    def test_default_model_get_set(self):
        self.assertIsNone(get_default_model())
        set_default_model("anthropic:claude-sonnet-4-6")
        self.assertEqual(get_default_model(), "anthropic:claude-sonnet-4-6")
        set_default_model(None)
        self.assertIsNone(get_default_model())


class TestLegacyMigration(_TempHome):
    def _legacy(self, **overrides):
        data = {
            "default_provider": "openai",
            "providers": {
                "openai": {"api_key": base64.b64encode(b"sk-openai").decode(), "default_model": "gpt-5.4",
                           "base_url": "https://api.openai.com/v1"},
                "glm": {"api_key": base64.b64encode(b"glm-key").decode(), "default_model": "zai/glm-5"},
                "anthropic": {"api_key": "", "default_model": "claude-sonnet-4-6"},
            },
            "session": {"auto_save": True, "max_history": 50},
        }
        data.update(overrides)
        return data

    def test_keys_move_to_keys_file_decoded(self):
        self.write_config(self._legacy())
        load_config()
        saved = json.loads(keys.keys_file().read_text())
        self.assertEqual(saved, {"openai": "sk-openai", "glm": "glm-key"})
        if os.name != "nt":
            self.assertEqual(keys.keys_file().stat().st_mode & 0o777, 0o600)

    def test_default_model_and_layout_migrated(self):
        self.write_config(self._legacy())
        config = load_config()
        self.assertEqual(config["model"], "openai:gpt-5.4")
        self.assertNotIn("providers", config)
        self.assertNotIn("default_provider", config)
        self.assertEqual(config["session"]["max_history"], 50)
        self.assertNotIn("providers", json.loads(get_config_path().read_text()))

    def test_litellm_prefix_stripped(self):
        self.write_config(self._legacy(default_provider="glm"))
        self.assertEqual(load_config()["model"], "glm:glm-5")

    def test_existing_saved_key_is_not_overwritten(self):
        keys.connect("openai", "sk-newer")
        self.write_config(self._legacy())
        load_config()
        self.assertEqual(json.loads(keys.keys_file().read_text())["openai"], "sk-newer")

    def test_plain_text_legacy_key_kept(self):
        self.write_config(self._legacy(providers={"openai": {"api_key": "sk-plain!", "default_model": "gpt-5.4"}}))
        load_config()
        self.assertEqual(json.loads(keys.keys_file().read_text())["openai"], "sk-plain!")


class TestMigrationSafety(TestLegacyMigration):
    def test_original_config_is_backed_up(self):
        self.write_config(self._legacy())
        original = get_config_path().read_text()
        load_config()
        backup = get_config_path().with_name("config.json.bak")
        self.assertEqual(backup.read_text(), original)
        if os.name != "nt":
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_corrupt_keys_file_blocks_migration_without_loss(self):
        keys.keys_file().parent.mkdir(parents=True, exist_ok=True)
        keys.keys_file().write_text("{not json")
        self.write_config(self._legacy())
        config = load_config()
        self.assertIn("providers", config)                       # left untouched
        self.assertEqual(keys.keys_file().read_text(), "{not json")


class TestKeyStore(_TempHome):
    def test_corrupt_keys_file_is_never_overwritten(self):
        keys.keys_file().parent.mkdir(parents=True, exist_ok=True)
        keys.keys_file().write_text("{half written")
        with self.assertRaises(keys.KeysFileError):
            keys.connect("openai", "sk-x")
        self.assertEqual(keys.keys_file().read_text(), "{half written")
        keys.load_into_env()   # warns, doesn't raise

    def test_new_keys_file_is_private(self):
        keys.connect("openai", "sk-x")
        if os.name != "nt":
            self.assertEqual(keys.keys_file().stat().st_mode & 0o777, 0o600)
            self.assertEqual(keys.keys_file().parent.stat().st_mode & 0o777, 0o700)

    def test_connect_sets_env_and_persists(self):
        keys.connect("deepseek", "ds-key")
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "ds-key")
        self.assertEqual(json.loads(keys.keys_file().read_text()), {"deepseek": "ds-key"})

    def test_shell_key_wins_over_saved(self):
        keys.connect("openai", "saved")
        os.environ["OPENAI_API_KEY"] = "from-shell"
        keys.load_into_env()
        self.assertEqual(os.environ["OPENAI_API_KEY"], "from-shell")

    def test_load_into_env_fills_missing(self):
        keys.connect("mistral", "m-key")
        os.environ.pop("MISTRAL_API_KEY")
        keys.load_into_env()
        self.assertEqual(os.environ["MISTRAL_API_KEY"], "m-key")

    def test_disconnect(self):
        keys.connect("cerebras", "c-key")
        self.assertTrue(keys.disconnect("cerebras"))
        self.assertNotIn("CEREBRAS_API_KEY", os.environ)
        self.assertFalse(keys.disconnect("cerebras"))

    def test_mask(self):
        self.assertEqual(keys.mask("sk-1234567890"), "sk-1…7890")
        self.assertEqual(keys.mask("short"), "•••••")


if __name__ == "__main__":
    unittest.main()
