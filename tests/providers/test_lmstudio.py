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
             patch("subprocess.run", return_value=_done()) as run, \
             patch("src.providers.openai_compat.OpenAICompatProvider.stream", return_value="reply") as parent:
            self.assertEqual(self.provider.stream(None, "m", (), lambda _c: None), "reply")
        self.assertEqual(run.call_args.args[0], ["/bin/lms", "server", "start"])
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
