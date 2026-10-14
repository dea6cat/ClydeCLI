"""Ollama maps a reasoning level to the `think` field, gated on model capability.
Run: `python -m unittest tests.providers.test_reasoning_ollama`.
"""
import os
import sys
import unittest
from unittest.mock import patch


from src.providers.ollama import OllamaProvider  # noqa: E402


def _prov(caps):
    p = OllamaProvider()
    p._show = lambda model: {"capabilities": caps}     # bypass network
    return p


class ThinkValue(unittest.TestCase):
    def test_capable_model_reports_supported(self):
        self.assertTrue(_prov(["completion", "tools", "thinking"]).supports_reasoning("qwen3.5:9b"))
        self.assertFalse(_prov(["completion", "tools"]).supports_reasoning("llama3:8b"))

    def test_none_reasoning_omits_think(self):
        self.assertIsNone(_prov(["thinking"])._think_value("qwen3.5:9b", None))

    def test_off_on(self):
        p = _prov(["thinking"])
        self.assertIs(p._think_value("qwen3.5:9b", "off"), False)
        self.assertIs(p._think_value("qwen3.5:9b", "on"), True)

    def test_level_is_boolean_true_for_ordinary_model(self):
        self.assertIs(_prov(["thinking"])._think_value("qwen3.5:9b", "high"), True)

    def test_level_is_native_string_for_gpt_oss(self):
        self.assertEqual(_prov(["thinking"])._think_value("gpt-oss:20b", "high"), "high")

    def test_noncapable_model_never_gets_think(self):
        p = _prov(["completion", "tools"])
        for lvl in ("off", "on", "low", "medium", "high", None):
            self.assertIsNone(p._think_value("llama3:8b", lvl))


if __name__ == "__main__":
    unittest.main()


class TestGpuLayers(unittest.TestCase):
    def _layers(self, share):
        p = OllamaProvider()
        p._show_cache["m"] = {"model_info": {"llama.block_count": 31}}
        with patch.object(p, "_weight_bytes", return_value=8 * 1024 ** 3), patch("src.providers.fit.gpu_share", return_value=share):
            return p._gpu_layers("m")

    def test_all_layers_when_the_gpu_holds_the_model_a_share_when_part_and_none_without_a_gpu(self):
        self.assertEqual(self._layers(1.0), 32)
        self.assertEqual(self._layers(0.5), 16)
        self.assertIsNone(self._layers(None))
