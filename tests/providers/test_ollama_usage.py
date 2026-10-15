"""Ollama usage keeps the token counts and, when reported, the prefill, decode and load times in milliseconds.
Run: `python -m unittest tests.providers.test_ollama_usage`.
"""
import unittest

from src.agent.agent_loop import _add_usage
from src.providers.ollama import _usage


class OllamaUsage(unittest.TestCase):
    def test_tokens_and_timings(self):
        got = _usage({"prompt_eval_count": 3000, "eval_count": 120, "prompt_eval_duration": 4_500_000_000,
                      "eval_duration": 6_000_000_000, "load_duration": 250_000_000, "total_duration": 11_000_000_000})
        self.assertEqual(got, {"input_tokens": 3000, "output_tokens": 120,
                               "prefill_ms": 4500, "decode_ms": 6000, "load_ms": 250})

    def test_no_timings_leaves_the_old_shape(self):
        self.assertEqual(_usage({"prompt_eval_count": 5, "eval_count": 2}), {"input_tokens": 5, "output_tokens": 2})

    def test_nothing_reported_is_none(self):
        self.assertIsNone(_usage({}))

    def test_timings_sum_across_turns_like_tokens(self):
        total = {"input_tokens": 0, "output_tokens": 0}
        for ms in (100, 300):
            _add_usage(total, {"input_tokens": 1, "output_tokens": 1, "prefill_ms": ms})
        self.assertEqual(total["prefill_ms"], 400)


if __name__ == "__main__":
    unittest.main()
