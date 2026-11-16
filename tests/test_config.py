"""Tests for config.json handling, the legacy migration, and the API-key store."""

from __future__ import annotations

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
