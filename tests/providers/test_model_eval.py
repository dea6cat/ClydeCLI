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

    def test_passing_models_play_the_hand_for_strength(self):
        from src.providers.model_eval import HAND
        hand = [reply(tool_calls=[("read_file", {"path": "README.md"})]),
                reply(tool_calls=[("read_file", {"path": "config/app.toml"})]),
                reply(tool_calls=[("read_file", {"path": "./env/PORT"})]),
                reply(tool_calls=[("submit", {"answer": "8431"})]),
                reply(tool_calls=[("submit", {"answer": "Line 5."})]),   # wrong: "line 5." isn't "5"
                reply(tool_calls=[("submit", {"answer": "1.9.2"})]),
                reply("4")]                                               # answered without submit
        provider = GOOD()
        provider._responses += hand
        score = evaluate(provider, "m", "good:m")
        self.assertEqual(score.strength, 2)
        self.assertEqual(len(HAND), 4)
        self.assertEqual(provider.requests[4]["conversation"].messages[-1].tool_results[0].content, "8431\n")

    def test_a_failing_model_plays_no_hand(self):
        self.assertIsNone(evaluate(FakeProvider(reply("42")), "m", "fake:m").strength)

    def test_evaluate_all_ranks_passing_models_first(self):
        seen = []
        scores = evaluate_all([(FakeProvider(reply("no")), "m", "bad:m"), (GOOD(), "m", "good:m")], on_done=lambda s: seen.append(s.ref))
        self.assertEqual([s.ref for s in scores], ["good:m", "bad:m"])
        self.assertEqual(sorted(seen), ["bad:m", "good:m"])


if __name__ == "__main__":
    unittest.main()


class TestEvalResults(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        self._tmp = tempfile.TemporaryDirectory()
        self._home = patch.object(Path, "home", return_value=Path(self._tmp.name))
        self._home.start()

    def tearDown(self):
        self._home.stop()
        self._tmp.cleanup()

    def test_kinds_separate_broken_models_from_transient_errors(self):
        from src.providers.model_eval import ModelScore
        kinds = {e: ModelScore("x", error=e).kind for e in (
            "[openrouter] HTTP 402 — requires more credits, or fewer max_tokens",
            "[openrouter] HTTP 429 — rate limited",
            "[openrouter] HTTP 404 — No endpoints found that support tool use",
            "answered without calling the tool",
            "[nvidia] HTTP 404 — Function 'x': Not found for account")}
        self.assertEqual(list(kinds.values()), ["transient", "transient", "tools", "tools", "unavailable"])

    def test_saved_results_hide_only_models_that_do_not_work(self):
        from src.providers.model_eval import ModelScore, hidden_refs, load_results, save_results
        save_results([ModelScore("a:ok", tool_call=True, round_trip=True),
                      ModelScore("a:notools", error="answered without calling the tool"),
                      ModelScore("a:broke", error="[x] HTTP 402 — requires more credits")])
        self.assertEqual(hidden_refs(), {"a:notools"})
        save_results([ModelScore("a:notools", tool_call=True, round_trip=True)])  # a later pass un-hides it
        self.assertEqual(hidden_refs(), set())
        self.assertTrue(load_results()["a:ok"]["passed"])


class TestModelsListing(unittest.TestCase):
    def test_batch_variants_are_not_chat_models(self):
        from src.providers.openai_compat import _is_chat_model
        self.assertFalse(_is_chat_model("openai/gpt-5.4:batch"))
        self.assertTrue(_is_chat_model("openai/gpt-5.4"))

    def test_models_hides_failed_ones_unless_all(self):
        import io
        from unittest.mock import patch
        from rich.console import Console
        from src.repl.core import ClydeREPL

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.console = Console(file=io.StringIO(), width=120)
        provider = FakeProvider(name="p", models=("good", "bad"))
        repl.registry, repl.provider, repl.model = {"p": provider}, provider, "good"
        with patch("src.repl.core.hidden_refs", return_value={"p:bad"}):
            repl._show_models("")
            out = repl.console.file.getvalue()
            self.assertIn("p:good", out)
            self.assertNotIn("p:bad", out)
            self.assertIn("1 model(s) hidden", out)
            repl.console.file = io.StringIO()
            repl._show_models("all")
            self.assertIn("p:bad", repl.console.file.getvalue())
