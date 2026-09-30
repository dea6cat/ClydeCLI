"""Model evaluation: a correct tool call plus a round trip back to text."""

from __future__ import annotations

import unittest

from src.providers.base import ProviderError
from src.providers.model_eval import evaluate, evaluate_all
from tests.fakes import FakeProvider, reply

GOOD = lambda: FakeProvider(reply(tool_calls=[("add_numbers", {"a": 17, "b": "25"})], usage={"output_tokens": 10}),  # noqa: E731
                            reply("The sum is 42.", usage={"output_tokens": 6}), name="good")


class TestModelEval(unittest.TestCase):
    def test_a_model_that_calls_the_tool_and_uses_the_result_passes(self):
        provider = GOOD()
        score = evaluate(provider, "m", "good:m")
        self.assertTrue(score.passed)
        self.assertIsNotNone(score.latency_s)
        self.assertGreater(score.tokens_per_s, 0)
        second = provider.requests[1]["conversation"]
        self.assertEqual(second.messages[-1].tool_results[0].content, "42")
        self.assertEqual([t.name for t in provider.requests[0]["tools"]], ["add_numbers"])

    def test_answering_in_text_fails_the_tool_call(self):
        score = evaluate(FakeProvider(reply("42")), "m", "fake:m")
        self.assertFalse(score.tool_call)
        self.assertIn("without calling the tool", score.error)

    def test_wrong_arguments_and_ignored_results_fail(self):
        wrong = evaluate(FakeProvider(reply(tool_calls=[("add_numbers", {"a": 1, "b": 2})])), "m", "x:m")
        self.assertFalse(wrong.tool_call)
        ignored = evaluate(FakeProvider(reply(tool_calls=[("add_numbers", {"a": 17, "b": 25})]), reply("done")), "m", "x:m")
        self.assertTrue(ignored.tool_call)
        self.assertFalse(ignored.round_trip)

    def test_errors_are_reported_not_raised(self):
        score = evaluate(FakeProvider(ProviderError("fake", "HTTP 404 — model not found")), "m", "x:m")
        self.assertFalse(score.passed)
        self.assertIn("404", score.error)

    def test_evaluate_all_ranks_passing_models_first(self):
        seen = []
        scores = evaluate_all([(FakeProvider(reply("no")), "m", "bad:m"), (GOOD(), "m", "good:m")], on_done=lambda s: seen.append(s.ref))
        self.assertEqual([s.ref for s in scores], ["good:m", "bad:m"])
        self.assertEqual(sorted(seen), ["bad:m", "good:m"])


if __name__ == "__main__":
    unittest.main()
