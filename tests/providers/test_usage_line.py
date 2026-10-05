"""The per-turn usage line: tokens, cost when the model is priced, and the provider's remaining quota."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.providers import base
from src.repl.core import _usage_note


class TestUsageLine(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(base.RATE_LIMITS, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_remaining_quota_comes_from_rate_limit_headers(self):
        base._note_limits(SimpleNamespace(headers={"x-ratelimit-remaining-requests": "812", "X-Ratelimit-Remaining-Tokens": "9000",
                                                   "content-type": "text/event-stream"}), "openai")
        self.assertEqual(base.remaining_quota("openai"), "812 requests left")
        base._note_limits(SimpleNamespace(headers={"anthropic-ratelimit-tokens-remaining": "40000"}), "anthropic")
        self.assertEqual(base.remaining_quota("anthropic"), "40,000 tokens left")
        self.assertEqual(base.remaining_quota("nvidia"), "")              # sent no such headers

    def test_usage_note(self):
        note = _usage_note({"input_tokens": 4120, "output_tokens": 388}, "ollama:qwen3:8b")
        self.assertEqual(note, " · 4.1k in, 388 out")                     # local: no cost, no quota
        base.RATE_LIMITS["openai"] = {"x-ratelimit-remaining-requests": "99"}
        with patch("src.agent.cost_tracker.estimate_usd", return_value=0.0123):
            self.assertEqual(_usage_note({"input_tokens": 10, "output_tokens": 5}, "openai:gpt-x"),
                             " · 10 in, 5 out · $0.012 · 99 requests left")


if __name__ == "__main__":
    unittest.main()
