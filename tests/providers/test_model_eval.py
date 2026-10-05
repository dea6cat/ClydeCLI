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

    def test_a_call_echoed_inside_its_own_arguments_is_unwrapped(self):
        # What Qwen2.5-Coder GGUF sends through Ollama: the whole call as the arguments.
        wrapped = {"name": "add_numbers", "arguments": {"a": 17, "b": 25}}
        score = evaluate(FakeProvider(reply(tool_calls=[("add_numbers", wrapped)]), reply("It is 42.")), "m", "x:m")
        self.assertTrue(score.passed)

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
                reply("4"),                                               # answered without submit
                reply(tool_calls=[("read_file", {"path": "orders.csv"})]),
                reply(tool_calls=[("read_file", {"path": "rates.json"})]),
                reply(tool_calls=[("submit", {"answer": "$257.2"})]),    # same number, written differently
                reply(tool_calls=[("submit", {"answer": "6"})]),          # the late-binding trap
                reply(tool_calls=[("submit", {"answer": "8 hours"})]),    # not just the number
                reply(tool_calls=[("read_file", {"path": "config.yaml"})]),
                reply(tool_calls=[("read_file", {"path": ".env"})]),
                reply(tool_calls=[("read_file", {"path": "overrides/prod.env"})]),
                reply(tool_calls=[("submit", {"answer": "2,500"})]),      # a thousands separator is fine
                reply(tool_calls=[("submit", {"answer": "3"})]),
                reply(tool_calls=[("submit", {"answer": "tuesday"})]),
                reply(tool_calls=[("submit", {"answer": "A, C"})])]       # the logic trap
        provider = GOOD()
        provider._responses += hand
        score = evaluate(provider, "m", "good:m")
        self.assertEqual(score.strength, 5)   # 8431, 1.9.2, $257.2, 2,500, tuesday
        self.assertEqual(len(HAND), 11)
        self.assertEqual(provider.requests[4]["conversation"].messages[-1].tool_results[0].content, "8431\n")

    def test_a_provider_error_mid_hand_scores_nothing_and_keeps_the_earlier_strength(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from src.providers.model_eval import load_results, save_results
        provider = GOOD()
        provider._responses += [reply(tool_calls=[("read_file", {"path": "README.md"})]),
                                ProviderError("openrouter", "HTTP 402 — out of credits", status=402)]
        score = evaluate(provider, "m", "good:m")
        self.assertIsNone(score.strength)
        self.assertIn("provider error", score.note)
        with patch.object(Path, "home", return_value=Path(tempfile.mkdtemp())):
            (Path.home() / ".clyde").mkdir()
            (Path.home() / ".clyde" / "model_evals.json").write_text('{"good:m": {"passed": true, "strength": 3}}')
            save_results([score])
            self.assertEqual(load_results()["good:m"]["strength"], 3)

    def test_a_grade_that_drops_is_reported(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from src.providers.model_eval import HAND, ModelScore, save_results
        with patch.object(Path, "home", return_value=Path(tempfile.mkdtemp())):
            (Path.home() / ".clyde").mkdir()
            (Path.home() / ".clyde" / "model_evals.json").write_text(
                '{"a:m": {"passed": true, "strength": 4, "hand": 4, "at": "2026-09-12T10:00:00+00:00"}}')
            worse = ModelScore("a:m", tool_call=True, round_trip=True, strength=5)            # 5/11 < 4/4
            self.assertEqual(save_results([worse]), [f"a:m: 4/4 → 5/{len(HAND)} since 2026-09-12"])
            self.assertEqual(save_results([ModelScore("a:m", tool_call=True, round_trip=True, strength=7)]), [])

    def test_dot_files_are_found_by_the_hand(self):
        from src.providers.model_eval import _task_path
        self.assertEqual([_task_path(p) for p in (".env", "./.env", "/overrides/prod.env", "./README.md")],
                         [".env", ".env", "overrides/prod.env", "README.md"])

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
