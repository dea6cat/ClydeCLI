"""The size of a model in billions of parameters, from what the provider reports or else from its name."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers.model_size import billions, parse_reported
from src.providers.ollama import OllamaProvider


class _Reports:
    def __init__(self, size):
        self._size = size

    def parameter_billions(self, _model):
        return self._size


class TestModelSize(unittest.TestCase):
    def test_a_size_in_the_name_is_read(self):
        for model, want in (("qwen2.5-coder-3b-instruct", 3.0), ("hf.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF:Q8_0", 3.0),
                            ("qwen3:4b", 4.0), ("llama3.2:1b", 1.0), ("gpt-oss:20b", 20.0), ("gemma-3-27b-it", 27.0),
                            ("qwen3:30b-a3b", 30.0), ("ministral-8b-latest", 8.0)):
            with self.subTest(model=model):
                self.assertEqual(billions(object(), model), want)

    def test_a_name_without_a_clear_size_is_unknown(self):
        for model in ("phi-4-mini", "mixtral-8x7b", "qwen2.5", "gpt-4o", "local-model-q8_0"):
            with self.subTest(model=model):
                self.assertIsNone(billions(object(), model))

    def test_what_the_provider_reports_wins_over_the_name(self):
        self.assertEqual(billions(_Reports(7.6), "qwen3:4b"), 7.6)

    def test_a_provider_that_does_not_know_falls_back_to_the_name(self):
        self.assertEqual(billions(_Reports(None), "qwen3:4b"), 4.0)

    def test_reported_sizes(self):
        self.assertEqual(parse_reported("3.09B"), 3.09)
        self.assertAlmostEqual(parse_reported("494.03M"), 0.49403)
        self.assertIsNone(parse_reported("big"))
        self.assertIsNone(parse_reported(None))

    def test_ollama_reads_the_size_from_its_model_info(self):
        provider = OllamaProvider()
        with patch.object(provider, "_show", return_value={"details": {"parameter_size": "3.09B"}}):
            self.assertEqual(provider.parameter_billions("anything"), 3.09)
        with patch.object(provider, "_show", return_value={}):
            self.assertIsNone(provider.parameter_billions("anything"))


if __name__ == "__main__":
    unittest.main()
