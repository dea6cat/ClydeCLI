"""clyde tune end to end against fakes: the run loop, the unload prompt, grading, the server wrapper and the questions.
No Ollama is started; every network and process boundary is replaced."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from src import tune, tune_profile
from src.providers.base import ProviderError
from src.tune import Quality, Result
from src.tune_profile import Profile

GB = 2 ** 30
CODING = Profile(("coding",), "context")
SAME = Quality(1, 2, ("def merge(a, b): ...",), True)


@contextmanager
def _fake_serve(env):
    yield "http://fake"


class _Private:
    """Stands in for OllamaProvider on the throwaway server."""

    def __init__(self, host=None):
        self.host = host

    def installed(self):
        return {"m:1": 2 * GB}

    def context_window(self, model):
        return 8192

    def trained_context(self, model):
        return 8192


class RunTests(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        self.console = Console(file=self.out, width=200)
        self._home = tempfile.TemporaryDirectory()
        self.home = Path(self._home.name)

    def tearDown(self):
        self._home.cleanup()

    def _run(self, perfs, qualities=None, profile=CODING, **kwargs):
        qualities = qualities or [SAME] * len(perfs)
        with patch.object(tune.shutil, "which", return_value="/usr/bin/ollama"), \
                patch.object(tune_profile, "clyde_home", return_value=self.home), \
                patch.object(tune_profile, "load", return_value=profile), \
                patch.object(tune, "local", return_value=MagicMock(is_available=lambda: False)), \
                patch.object(tune, "OllamaProvider", _Private), \
                patch.object(tune, "_generate"), \
                patch.object(tune, "measure", side_effect=list(perfs)), \
                patch.object(tune, "grade", side_effect=list(qualities)):
            return tune.run(self.console, serve=_fake_serve, **kwargs)

    def test_recommends_the_cheaper_cache_and_saves_the_choice(self):
        code = self._run([Result(4 * GB, 500, 40), Result(4 * GB, 500, 40), Result(int(3.4 * GB), 500, 40)])
        self.assertEqual(code, 0)
        self.assertIn("Recommended: flash + q8_0 KV", self.out.getvalue())
        saved = json.loads((self.home / "tune.json").read_text())
        self.assertEqual(saved["result"]["env"]["OLLAMA_KV_CACHE_TYPE"], "q8_0")
        self.assertEqual(saved["result"]["model"], "m:1")

    def test_keeps_the_current_setup_when_nothing_is_a_real_gain(self):
        code = self._run([Result(4 * GB, 500, 40), Result(4 * GB, 500, 40), Result(int(3.95 * GB), 500, 40)])
        self.assertEqual(code, 0)
        self.assertIn("Keep your current setup", self.out.getvalue())

    def test_a_candidate_that_loses_recall_is_not_chosen(self):
        lost = Quality(1, 2, SAME.answers, False)
        code = self._run([Result(4 * GB, 500, 40), Result(4 * GB, 500, 40), Result(3 * GB, 500, 40)], [SAME, SAME, lost])
        self.assertEqual(code, 0)
        text = self.out.getvalue()
        self.assertIn("lost long-context recall", text)
        self.assertIn("Keep your current setup", text)

    def test_a_provider_error_is_reported_not_raised(self):
        with patch.object(tune.shutil, "which", return_value="/usr/bin/ollama"), \
                patch.object(tune_profile, "load", return_value=CODING), \
                patch.object(tune, "local", return_value=MagicMock(is_available=lambda: False)), \
                patch.object(tune, "OllamaProvider", _Private), \
                patch.object(tune, "_generate", side_effect=ProviderError("ollama", "boom")):
            self.assertEqual(tune.run(self.console, serve=_fake_serve), 1)
        self.assertIn("boom", self.out.getvalue())

    def test_without_ollama_it_says_so(self):
        with patch.object(tune.shutil, "which", return_value=None):
            self.assertEqual(tune.run(self.console), 1)
        self.assertIn("not installed", self.out.getvalue())

    def test_asking_without_a_terminal_is_a_clear_error(self):
        with patch.object(tune.shutil, "which", return_value="/usr/bin/ollama"), \
                patch.object(tune_profile, "load", return_value=None), \
                patch.object(tune_profile, "ask", side_effect=EOFError):
            self.assertEqual(tune.run(self.console), 1)
        self.assertIn("terminal", self.out.getvalue())

    def test_reask_ignores_the_saved_profile(self):
        with patch.object(tune.shutil, "which", return_value="/usr/bin/ollama"), \
                patch.object(tune_profile, "load", return_value=CODING) as load, \
                patch.object(tune_profile, "ask", side_effect=EOFError) as ask:
            tune.run(self.console, reask=True)
        load.assert_not_called()
        ask.assert_called_once()


class UnloadTests(unittest.TestCase):
    def setUp(self):
        self.console = Console(file=io.StringIO(), width=200)

    def _provider(self, available=True):
        return MagicMock(host="http://h", is_available=lambda: available)

    def test_nothing_to_unload_when_the_server_is_down_or_empty(self):
        self.assertTrue(tune.unload_loaded(self.console, self._provider(False)))
        with patch.object(tune, "get_json", return_value={"models": []}):
            self.assertTrue(tune.unload_loaded(self.console, self._provider()))

    def test_a_yes_unloads_every_loaded_model_and_leaves_the_server_running(self):
        with patch.object(tune, "get_json", return_value={"models": [{"name": "a"}, {"model": "b"}]}), \
                patch.object(tune.Confirm, "ask", return_value=True), patch.object(tune, "post_json") as post:
            self.assertTrue(tune.unload_loaded(self.console, self._provider()))
        self.assertEqual([c.args[1] for c in post.call_args_list], [{"model": "a", "keep_alive": 0}, {"model": "b", "keep_alive": 0}])
        self.assertIn("keeps running", self.console.file.getvalue())

    def test_a_no_changes_nothing(self):
        with patch.object(tune, "get_json", return_value={"models": [{"name": "a"}]}), \
                patch.object(tune.Confirm, "ask", return_value=False), patch.object(tune, "post_json") as post:
            self.assertFalse(tune.unload_loaded(self.console, self._provider()))
        post.assert_not_called()


class GradeTests(unittest.TestCase):
    def test_haystack_buries_the_fact_in_the_middle_and_asks_for_it(self):
        text = tune._haystack(2000)
        self.assertEqual(text.count(tune._NEEDLE), 1)
        self.assertTrue(text.rstrip().endswith("Answer with the passcode only."))
        before = text.index(tune._NEEDLE)
        self.assertTrue(len(text) * 0.3 < before < len(text) * 0.7)

    def test_grade_collects_the_eval_the_greedy_answers_and_the_recall(self):
        score = MagicMock(passed=True, strength=3)
        replies = iter(["a", "b", "c", "d", f"it is {tune._NEEDLE}"])
        with patch.object(tune, "OllamaProvider") as provider, patch.object(tune.model_eval, "evaluate", return_value=score), \
                patch.object(tune, "_greedy", side_effect=lambda *a: next(replies)):
            quality = tune.grade("http://h", "m", 8192, 1000)
        provider.return_value.pin_context.assert_called_once_with("m", 8192)
        self.assertEqual(quality, Quality(1, 3, ("a", "b", "c", "d"), True))

    def test_a_missing_fact_is_recorded_as_not_recalled(self):
        score = MagicMock(passed=False, strength=None)
        with patch.object(tune, "OllamaProvider"), patch.object(tune.model_eval, "evaluate", return_value=score), \
                patch.object(tune, "_greedy", return_value="I don't know"):
            quality = tune.grade("http://h", "m", 8192, 1000)
        self.assertEqual((quality.passes, quality.strength, quality.recalled), (0, 0, False))

    def test_greedy_asks_for_a_repeatable_reply(self):
        with patch.object(tune, "post_json", return_value={"response": "x"}) as post:
            self.assertEqual(tune._greedy("http://h", "m", 4096, "p", 20), "x")
        options = post.call_args.args[1]["options"]
        self.assertEqual((options["temperature"], options["seed"], options["num_ctx"]), (0, 1, 4096))


class ServeTests(unittest.TestCase):
    def test_serve_runs_ollama_on_a_private_port_with_the_settings_and_stops_it(self):
        proc = MagicMock(poll=lambda: None)
        with patch.dict(tune.os.environ, {"OLLAMA_HOST": "0.0.0.0:1", "OLLAMA_KV_CACHE_TYPE": "q4_0", "OLLAMA_MODELS": "/m"}), \
                patch.object(tune.subprocess, "Popen", return_value=proc) as popen, \
                patch.object(tune, "get_json", return_value={"version": "x"}):
            with tune._serve(tune.FLASH) as host:
                env = popen.call_args.kwargs["env"]
        self.assertTrue(host.startswith("http://127.0.0.1:"))
        self.assertEqual(env["OLLAMA_FLASH_ATTENTION"], "1")
        self.assertNotIn("OLLAMA_KV_CACHE_TYPE", env)   # the user's own setting must not leak into the test
        self.assertEqual(env["OLLAMA_MODELS"], "/m")
        self.assertTrue(env["OLLAMA_HOST"].startswith("127.0.0.1:") and env["OLLAMA_HOST"] != "0.0.0.0:1")
        proc.terminate.assert_called_once()

    def test_a_server_that_never_comes_up_is_an_error_and_is_still_stopped(self):
        proc = MagicMock(poll=lambda: 1)
        with patch.object(tune.subprocess, "Popen", return_value=proc), \
                patch.object(tune, "get_json", side_effect=ProviderError("ollama", "down")):
            with self.assertRaises(ProviderError):
                with tune._serve({}):
                    pass
        proc.terminate.assert_called_once()


    def test_a_server_that_ignores_terminate_is_killed(self):
        proc = MagicMock(poll=lambda: None)
        proc.wait.side_effect = tune.subprocess.TimeoutExpired("ollama", 10)
        with patch.object(tune.subprocess, "Popen", return_value=proc), patch.object(tune, "get_json", return_value={}):
            with tune._serve({}):
                pass
        proc.kill.assert_called_once()


class OfferInterruptTests(unittest.TestCase):
    def test_an_interrupted_prompt_means_no_and_never_runs_the_tune(self):
        console = Console(file=io.StringIO(), width=200)
        for error in (EOFError, KeyboardInterrupt):
            with patch.object(tune.shutil, "which", return_value="/usr/bin/ollama"), \
                    patch.object(tune.Confirm, "ask", side_effect=error), patch.object(tune, "run") as run:
                tune.offer(console, model="m:1")
            run.assert_not_called()
        self.assertIn("clyde tune", console.file.getvalue())


class ShowTests(unittest.TestCase):
    def test_the_table_names_the_chosen_row_the_baseline_and_why_others_were_dropped(self):
        out = io.StringIO()
        base = tune.Row(tune.Candidate("default", {}, 8192), Result(4 * GB, 0, 40), SAME)
        best = tune.Row(tune.Candidate("flash + q8_0 KV", tune.kv("q8_0"), 8192), Result(3 * GB, 0, 40), SAME)
        bad = tune.Row(tune.Candidate("flash + q4_0 KV", tune.kv("q4_0"), 8192), Result(2 * GB, 0, 30), None, "12% slower")
        tune._show(Console(file=out, width=200), [base, best, bad], best)
        text = out.getvalue()
        for word in ("baseline", "chosen", "12% slower", "100% alike"):
            self.assertIn(word, text)


class AskTests(unittest.TestCase):
    def _ask(self, uses, priority, headroom):
        with tempfile.TemporaryDirectory() as home, patch.object(tune_profile, "clyde_home", return_value=Path(home)), \
                patch.object(tune_profile.Prompt, "ask", return_value=uses), \
                patch.object(tune_profile.IntPrompt, "ask", side_effect=[priority, headroom]):
            profile = tune_profile.ask(Console(file=io.StringIO()))
            return profile, tune_profile.load()

    def test_several_uses_a_priority_and_headroom_become_a_saved_profile(self):
        profile, loaded = self._ask("1, 3", 2, 6)
        self.assertEqual(profile, Profile(("coding", "research"), "context", 6))
        self.assertEqual(loaded, profile)

    def test_junk_or_empty_answers_fall_back_to_chat(self):
        profile, _ = self._ask("x 99", 1, -3)
        self.assertEqual((profile.uses, profile.headroom_gb), (("chat",), 0))


if __name__ == "__main__":
    unittest.main()
