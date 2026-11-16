"""Ollama's /api/show answer is cached; a failed call is not, so the next call asks again."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers import ollama
from src.providers.base import ProviderError


class TestShowCache(unittest.TestCase):
    def test_a_failure_is_not_remembered_but_an_answer_is(self):
        provider = ollama.OllamaProvider()
        answers = [ProviderError("ollama", "timed out"), {"capabilities": ["vision"]}]
        with patch.object(ollama, "post_json", side_effect=answers) as call:
            self.assertEqual(provider._show("m"), {})
            self.assertEqual(provider._show("m"), {"capabilities": ["vision"]})
            self.assertEqual(provider._show("m"), {"capabilities": ["vision"]})
        self.assertEqual(call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
