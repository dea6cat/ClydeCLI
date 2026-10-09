"""LM Studio: picked up when installed, models from the server or `lms ls`, server started on use."""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from src.providers import lmstudio
from src.providers.base import ProviderError

LS = json.dumps([{"type": "llm", "modelKey": "qwen/qwen3.5-9b"}, {"type": "embedding", "modelKey": "nomic-embed"},
                 {"type": "llm", "modelKey": "google/gemma-3-4b"}])


def _done(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout, "")


class TestLMStudio(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = lmstudio.LMStudioProvider()

    def test_not_available_without_lms_or_server(self):
        with patch.object(lmstudio, "_lms", return_value=None), patch.object(self.provider, "_server_up", return_value=False):
            self.assertFalse(self.provider.is_available())

    def test_lists_downloaded_llms_when_the_server_is_down(self):
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), \
             patch.object(self.provider, "_server_up", return_value=False), \
             patch("subprocess.run", return_value=_done(LS)) as run:
            self.assertTrue(self.provider.is_available())
            self.assertEqual(self.provider._fetch_models(), ["google/gemma-3-4b", "qwen/qwen3.5-9b"])
        self.assertEqual(run.call_args.args[0], ["/bin/lms", "ls", "--json"])

    def test_lists_from_the_server_when_it_runs(self):
        with patch.object(self.provider, "_server_up", return_value=True), \
             patch("src.providers.openai_compat.get_json", return_value={"data": [{"id": "qwen/qwen3.5-9b"}]}):
            self.assertEqual(self.provider._fetch_models(), ["qwen/qwen3.5-9b"])

    def test_stream_starts_the_server_first(self):
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), \
             patch.object(self.provider, "_server_up", side_effect=[False, True]), \
             patch.object(self.provider, "ensure_loaded") as load, \
             patch("subprocess.run", return_value=_done()) as run, \
             patch("src.providers.openai_compat.OpenAICompatProvider.stream", return_value="reply") as parent:
            self.assertEqual(self.provider.stream(None, "m", (), lambda _c: None), "reply")
        self.assertEqual(run.call_args.args[0], ["/bin/lms", "server", "start"])
        load.assert_called_once_with("m")
        parent.assert_called_once()

    def test_stream_without_lm_studio_is_a_clear_error(self):
        with patch.object(lmstudio, "_lms", return_value=None), patch.object(self.provider, "_server_up", return_value=False):
            with self.assertRaisesRegex(ProviderError, "isn't running"):
                self.provider.stream(None, "m", (), lambda _c: None)

    def test_uses_a_placeholder_key(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("LMSTUDIO_API_KEY", None)
            self.assertEqual(self.provider.api_key, "lm-studio")


if __name__ == "__main__":
    unittest.main()


class TestLMStudioContext(unittest.TestCase):
    def test_context_comes_from_lms_ps_or_a_safe_default(self):
        provider = lmstudio.LMStudioProvider()
        ps = json.dumps([{"modelKey": "qwen/qwen3.5-9b", "contextLength": 47872}])
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), patch("subprocess.run", return_value=_done(ps)):
            self.assertEqual(provider.context_window("qwen/qwen3.5-9b"), 47872)
            self.assertEqual(provider.context_window("not-loaded"), lmstudio.UNLOADED_CONTEXT)


class TestLMStudioUnload(unittest.TestCase):
    def test_unload_runs_lms_unload_for_the_model(self):
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), patch("subprocess.run", return_value=_done()) as run:
            lmstudio.LMStudioProvider().unload("qwen/qwen3.5-9b")
        self.assertEqual(run.call_args.args[0], ["/bin/lms", "unload", "qwen/qwen3.5-9b"])

    def test_unload_without_lms_does_nothing(self):
        with patch.object(lmstudio, "_lms", return_value=None), patch("subprocess.run") as run:
            lmstudio.LMStudioProvider().unload("x")
        run.assert_not_called()


class TestLMStudioEstimate(unittest.TestCase):
    def test_estimate_reads_the_total_memory_line(self):
        out = "Model: m\nEstimated GPU Memory:   6.02 GiB\nEstimated Total Memory: 6.02 GiB\nConfidence: LOW\n"
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), patch("subprocess.run", return_value=_done(out)) as run:
            self.assertEqual(lmstudio.LMStudioProvider().estimate("m"), int(6.02 * 1024 ** 3))
        self.assertEqual(run.call_args.args[0], ["/bin/lms", "load", "m", "--estimate-only", "-y"])

    def test_the_estimate_is_found_when_lms_prints_it_on_stderr(self):
        done = subprocess.CompletedProcess([], 0, "", "Estimated Total Memory: 512.00 MiB\n")
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), patch("subprocess.run", return_value=done):
            self.assertEqual(lmstudio.LMStudioProvider().estimate("m"), 512 * 1024 ** 2)

    def test_an_unreadable_estimate_is_none(self):
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), patch("subprocess.run", return_value=_done("nope")):
            self.assertIsNone(lmstudio.LMStudioProvider().estimate("m"))


class TestLMStudioWindow(unittest.TestCase):
    ENTRY = {"modelKey": "m", "sizeBytes": 4 * 1024 ** 3, "maxContextLength": 131072, "path": "x/m"}

    def _folder(self, tmp: str, **cfg) -> str:
        import pathlib
        pathlib.Path(tmp, "config.json").write_text(json.dumps({"num_hidden_layers": 36, "num_attention_heads": 32,
                                                                 "num_key_value_heads": 8, "head_dim": 128, **cfg}))
        return tmp

    def test_kv_bytes_per_token_come_from_the_model_config(self):
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._folder(tmp)
            self.assertEqual(lmstudio.kv_bytes_per_token(pathlib.Path(tmp)), 2 * 36 * 8 * 128 * 2)
        self.assertIsNone(lmstudio.kv_bytes_per_token(None))

    def test_the_window_fits_the_budget_left_after_the_weights(self):
        import pathlib, tempfile
        GB = 1024 ** 3
        with tempfile.TemporaryDirectory() as tmp:
            self._folder(tmp)
            provider = lmstudio.LMStudioProvider()
            with patch.object(provider, "downloaded", return_value=[self.ENTRY]), \
                    patch.object(lmstudio, "model_files", return_value=pathlib.Path(tmp)), \
                    patch.object(lmstudio.fit, "budget_bytes", return_value=12 * GB):
                window = provider.planned_window("m")
                self.assertEqual(window % 1024, 0)
                self.assertTrue(lmstudio.WINDOW_FLOOR <= window <= lmstudio.MAX_WINDOW)
                self.assertLessEqual(window * 147456, (12 * GB - 4 * GB - lmstudio.fit.OVERHEAD) * lmstudio.KV_SHARE)
            with patch.object(provider, "downloaded", return_value=[self.ENTRY]), \
                    patch.object(lmstudio, "model_files", return_value=pathlib.Path(tmp)), \
                    patch.object(lmstudio.fit, "budget_bytes", return_value=5 * GB):
                self.assertEqual(provider.planned_window("m"), lmstudio.WINDOW_FLOOR)   # no room: the floor, never zero

    def test_a_model_without_a_config_gets_the_conservative_window(self):
        provider = lmstudio.LMStudioProvider()
        with patch.object(provider, "downloaded", return_value=[self.ENTRY]), patch.object(lmstudio, "model_files", return_value=None):
            self.assertEqual(provider.planned_window("m"), lmstudio.GGUF_WINDOW)

    def test_an_env_override_wins(self):
        with patch.dict("os.environ", {"CLYDE_CONTEXT_TOKENS": "12000"}):
            self.assertEqual(lmstudio.LMStudioProvider().planned_window("m"), 12000)

    def test_an_unloaded_model_is_loaded_with_the_window_and_one_slot(self):
        provider = lmstudio.LMStudioProvider()
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), patch.object(provider, "_loaded", return_value=False), \
                patch.object(provider, "planned_window", return_value=16384), patch("subprocess.run", return_value=_done()) as run:
            provider.ensure_loaded("m")
            provider.ensure_loaded("m")   # the second call is cached
        self.assertEqual(run.call_args.args[0], ["/bin/lms", "load", "m", "-c", "16384", "--parallel", "1", "--ttl", "3600", "-y"])
        self.assertEqual(run.call_count, 1)

    def test_a_model_already_loaded_is_left_alone(self):
        provider = lmstudio.LMStudioProvider()
        with patch.object(lmstudio, "_lms", return_value="/bin/lms"), patch.object(provider, "_loaded", return_value=True), \
                patch("subprocess.run") as run:
            provider.ensure_loaded("m")
        run.assert_not_called()


class TestLMStudioToolTraining(unittest.TestCase):
    def _lacks(self, entry):
        provider = lmstudio.LMStudioProvider()
        with patch.object(provider, "downloaded", return_value=[entry]):
            return provider.lacks_tool_training("m")

    def test_a_model_marked_untrained_for_tools_is_flagged(self):
        self.assertTrue(self._lacks({"modelKey": "m", "trainedForToolUse": False}))

    def test_a_trained_or_unreported_model_is_not(self):
        self.assertFalse(self._lacks({"modelKey": "m", "trainedForToolUse": True}))
        self.assertFalse(self._lacks({"modelKey": "m"}))
        self.assertFalse(self._lacks({"modelKey": "other", "trainedForToolUse": False}))
