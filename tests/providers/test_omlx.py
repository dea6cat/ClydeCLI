"""oMLX: a key only Clyde holds, Clyde's planned window applied before load, the server started with the key in its environment."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.providers import omlx
from src.providers.base import ProviderError

GB = 1024 ** 3


class TestOMLX(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        home = patch.object(omlx, "home", return_value=Path(self.tmp) / "omlx")
        home.start()
        self.addCleanup(home.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("OMLX_API_KEY", None)
        self.provider = omlx.OMLXProvider()

    def test_the_server_key_is_made_once_and_only_the_owner_can_read_it(self):
        key = omlx.server_key()
        self.assertGreaterEqual(len(key), 40)
        self.assertEqual(omlx.server_key(), key)
        self.assertEqual(stat.S_IMODE((Path(self.tmp) / "omlx" / "api_key").stat().st_mode), 0o600)

    def test_requests_carry_the_key_once_omlx_is_installed(self):
        with patch.object(omlx, "_exe", return_value="/bin/omlx"):
            self.assertEqual(self.provider._headers()["Authorization"], f"Bearer {omlx.server_key()}")
        with patch.object(omlx, "_exe", return_value="/bin/omlx"), patch.dict(os.environ, {"OMLX_API_KEY": "mine"}):
            self.assertEqual(self.provider.api_key, "mine")   # a server you run yourself

    def test_the_server_starts_with_the_key_in_its_environment_not_its_command_line(self):
        with patch.object(omlx, "_exe", return_value="/bin/omlx"), \
                patch.object(self.provider, "_server_up", side_effect=[False, True]), \
                patch.object(omlx.subprocess, "Popen") as popen:
            self.provider._ensure_server()
        argv, kwargs = popen.call_args.args[0], popen.call_args.kwargs
        self.assertEqual(argv[:2], ["/bin/omlx", "serve"])
        self.assertIn("safe", argv)
        self.assertNotIn(omlx.server_key(), " ".join(argv))
        self.assertEqual(kwargs["env"]["OMLX_API_KEY"], omlx.server_key())

    def test_not_installed_and_nobody_to_ask_never_installs(self):
        with patch.object(omlx, "_exe", return_value=None), patch.object(self.provider, "_server_up", return_value=False), \
                patch.object(omlx, "install") as install:
            with self.assertRaises(ProviderError):
                self.provider._ensure_server()
        install.assert_not_called()

    def test_your_own_server_is_never_replaced(self):
        with patch.object(self.provider, "_server_up", return_value=False), patch.dict(os.environ, {"OMLX_API_KEY": "mine"}), \
                patch.object(omlx.subprocess, "Popen") as popen:
            with self.assertRaises(ProviderError):
                self.provider._ensure_server()
        popen.assert_not_called()

    def test_the_planned_window_is_set_before_loading_and_only_once(self):
        folder = Path(self.tmp) / "m"
        folder.mkdir()
        (folder / "config.json").write_text(json.dumps({"num_hidden_layers": 36, "num_attention_heads": 32,
                                                         "num_key_value_heads": 8, "head_dim": 128}))
        entry = {"id": "Qwen3-8B-4bit", "model_path": str(folder), "estimated_size": 4 * GB, "model_context_length": 40960,
                 "loaded": False}
        calls = []
        with patch.object(self.provider, "_status", return_value=[entry]), patch.object(omlx, "fixed_window", return_value=None), \
                patch.object(omlx.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(omlx, "post_json", side_effect=lambda url, payload, **kw: calls.append((kw["method"], url, payload))):
            self.provider.ensure_loaded("Qwen3-8B-4bit")
            self.provider.ensure_loaded("Qwen3-8B-4bit")
        (method, url, payload), load = calls
        self.assertEqual((method, url.endswith("/admin/api/models/Qwen3-8B-4bit/settings")), ("PUT", True))
        self.assertTrue(omlx.WINDOW_FLOOR <= payload["max_context_window"] <= omlx.MAX_WINDOW)
        self.assertTrue(load[1].endswith("/v1/models/Qwen3-8B-4bit/load"))

    def test_context_window_is_what_the_server_serves(self):
        with patch.object(omlx, "get_json", return_value={"data": [{"id": "m", "max_model_len": 16384}]}):
            self.assertEqual(self.provider.context_window("m"), 16384)

    def test_lmstudio_models_join_omlx_folders_once_and_omlx_keeps_its_own(self):
        lms, settings = Path(self.tmp) / "lms-models", Path(self.tmp) / "omlx-settings.json"
        lms.mkdir()
        settings.write_text(json.dumps({"server": {"port": 8000}}))
        with patch.object(omlx, "LMSTUDIO_MODELS", lms), patch.object(omlx, "settings_file", return_value=settings):
            self.assertTrue(omlx.adopt_lmstudio_models())
            self.assertFalse(omlx.adopt_lmstudio_models())
        data = json.loads(settings.read_text())
        self.assertEqual(data["server"], {"port": 8000})
        self.assertEqual(data["model"]["model_dirs"], [str(Path.home() / ".omlx" / "models"), str(lms)])

    def test_an_unreadable_omlx_settings_file_is_left_alone(self):
        lms, settings = Path(self.tmp) / "lms-models", Path(self.tmp) / "omlx-settings.json"
        lms.mkdir()
        settings.write_text("{not json")
        with patch.object(omlx, "LMSTUDIO_MODELS", lms), patch.object(omlx, "settings_file", return_value=settings):
            self.assertFalse(omlx.adopt_lmstudio_models())
        self.assertEqual(settings.read_text(), "{not json")

    def test_only_offered_on_apple_silicon(self):
        with patch.object(omlx.sys, "platform", "linux"):
            self.assertFalse(omlx.supported())


if __name__ == "__main__":
    unittest.main()
