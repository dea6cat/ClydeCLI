"""clyde tune: the profile rules, gates, candidate list and choice, against fakes (no Ollama is started)."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src import tune, tune_profile
from src.providers.base import ProviderError
from src.tune import Candidate, Quality, Result, Row
from src.tune_profile import Profile

GB = 2 ** 30
CODING = Profile(("coding",), "context")
CHAT = Profile(("chat",), "speed")


def _perf(memory_gb: float, gen_tps: float) -> Result:
    return Result(int(memory_gb * GB), 500.0, gen_tps)


def _row(label: str, memory_gb: float, tps: float, strength: int, ctx: int = 32768, why: str = "") -> Row:
    return Row(Candidate(label, {}, ctx), _perf(memory_gb, tps), Quality(1, strength), why)


class ProfileTests(unittest.TestCase):
    def test_coding_and_research_tolerate_no_quality_drop(self):
        self.assertEqual(Profile(("coding",), "speed").tolerance, 0)
        self.assertEqual(Profile(("chat", "research"), "speed").tolerance, 0)
        self.assertEqual(CHAT.tolerance, 1)

    def test_the_lossy_cache_is_only_for_chat_and_quick_answers(self):
        self.assertTrue(Profile(("chat", "quick"), "speed").allow_q4)
        self.assertFalse(Profile(("chat", "documents"), "speed").allow_q4)

    def test_profile_round_trips_through_the_config_file(self):
        with tempfile.TemporaryDirectory() as home, patch.object(tune_profile, "clyde_home", return_value=Path(home)):
            self.assertIsNone(tune_profile.load())
            tune_profile.save(Profile(("coding", "research"), "context", 6), {"model": "m", "ctx": 8192, "env": {}})
            self.assertEqual(tune_profile.load(), Profile(("coding", "research"), "context", 6))

    def test_numbers_ignores_junk_and_out_of_range(self):
        self.assertEqual(tune_profile._numbers("3, 1 x 9 1", 5), [1, 3])


class CandidateTests(unittest.TestCase):
    def test_q4_is_offered_only_when_the_profile_allows_it(self):
        self.assertFalse(any("q4_0" in c.label for c in tune.candidates(8192, 8192, CODING)))
        self.assertTrue(any("q4_0" in c.label for c in tune.candidates(8192, 8192, CHAT)))

    def test_a_longer_window_is_offered_only_below_the_trained_length(self):
        self.assertFalse(any("window" in c.label for c in tune.candidates(32768, 32768, CODING)))
        longer = [c for c in tune.candidates(16384, 131072, CODING) if "window" in c.label]
        self.assertEqual(len(longer), 1)
        self.assertGreater(longer[0].ctx, 16384)
        self.assertLessEqual(longer[0].ctx, 131072)

    def test_the_baseline_is_first_and_has_no_settings(self):
        first = tune.candidates(8192, 8192, CODING)[0]
        self.assertEqual((first.label, first.env), ("default", {}))


class GateTests(unittest.TestCase):
    def test_more_memory_is_rejected(self):
        self.assertEqual(tune.perf_gate(_perf(4, 40), _perf(4.5, 40), CODING, 0), "uses more memory")

    def test_a_real_slowdown_is_rejected_but_measurement_noise_is_not(self):
        self.assertIn("slower", tune.perf_gate(_perf(4, 40), _perf(4, 30), CODING, 0))
        self.assertIn("slower", tune.perf_gate(_perf(4, 40), _perf(4, 34), CHAT, 0))   # 15%, even for a speed priority
        self.assertEqual(tune.perf_gate(_perf(4, 40), _perf(4, 38), CHAT, 0), "")      # 5% is within the noise floor

    def test_no_headroom_is_rejected(self):
        self.assertIn("free", tune.perf_gate(_perf(12, 40), _perf(12, 40), Profile(("chat",), "speed", 4), 16 * GB))

    def test_a_missing_reading_is_rejected(self):
        self.assertEqual(tune.perf_gate(_perf(4, 40), Result(0, 0.0, 0.0), CODING, 0), "no reading")

    def test_quality_must_hold_for_strict_profiles(self):
        base = Quality(1, 10)
        self.assertEqual(tune.quality_gate(base, Quality(1, 10), CODING), "")
        self.assertEqual(tune.quality_gate(base, Quality(1, 9), CODING), "")   # one task either way is chance
        self.assertIn("dropped", tune.quality_gate(base, Quality(1, 8), CODING))
        self.assertEqual(tune.quality_gate(base, Quality(1, 8), CHAT), "")
        self.assertIn("dropped", tune.quality_gate(base, Quality(1, 7), CHAT))

    def test_drifting_answers_are_rejected_by_how_strict_the_profile_is(self):
        base = Quality(1, 0, ("def merge(a, b): return sorted(a + b)",))
        slight = Quality(1, 0, ("def merge(a, b): return sorted(a + b)  # ok",))
        heavy = Quality(1, 0, ("completely different text",))
        self.assertEqual(tune.quality_gate(base, base, CODING), "")
        self.assertIn("drift", tune.quality_gate(base, heavy, CHAT))
        self.assertEqual(tune.quality_gate(base, slight, CHAT), "")
        self.assertIn("drift", tune.quality_gate(base, slight, CODING))   # strict: 0.95 alike or better

    def test_losing_a_buried_fact_is_rejected_but_never_gained_back_as_a_loss(self):
        self.assertEqual(tune.quality_gate(Quality(1, 0, (), True), Quality(1, 0, (), False), CHAT), "lost long-context recall")
        self.assertEqual(tune.quality_gate(Quality(1, 0, (), False), Quality(1, 0, (), False), CHAT), "")

    def test_identical_answers_are_fully_alike(self):
        self.assertEqual(tune.fidelity(Quality(1, 0, ("a b c",)), Quality(1, 0, ("a b c",))), 1.0)
        self.assertEqual(tune.fidelity(Quality(1, 0), Quality(1, 0)), 1.0)   # no probes recorded

    def test_losing_tool_calling_always_fails(self):
        self.assertEqual(tune.quality_gate(Quality(1, 10), Quality(0, 10), CHAT), "lost tool calling")


class ChooseTests(unittest.TestCase):
    def test_keeps_the_baseline_when_nothing_is_a_real_gain(self):
        rows = [_row("default", 4.0, 40, 10), _row("flash", 3.95, 40.5, 10)]
        self.assertIs(tune.choose(rows, CODING), rows[0])
        self.assertEqual(rows[1].why, "no real gain")

    def test_never_picks_a_row_that_failed_a_gate(self):
        rows = [_row("default", 4.0, 40, 10), _row("tiny", 2.0, 40, 5, why="quality dropped")]
        self.assertIs(tune.choose(rows, CODING), rows[0])

    def test_context_priority_prefers_the_longer_window(self):
        rows = [_row("default", 4.0, 40, 10), _row("saves", 3.0, 40, 10), _row("longer", 3.9, 38, 10, ctx=65536)]
        self.assertEqual(tune.choose(rows, CODING).cand.label, "longer")

    def test_speed_priority_prefers_the_faster_row(self):
        rows = [_row("default", 4.0, 40, 10), _row("saves", 3.0, 40.5, 10), _row("fast", 3.9, 46, 10)]
        self.assertEqual(tune.choose(rows, Profile(("chat",), "speed")).cand.label, "fast")


class OfferTests(unittest.TestCase):
    def setUp(self):
        self.console = Console(file=io.StringIO(), width=200)

    def _offer(self, *, installed=None, confirm=True, which="/usr/bin/ollama", **kwargs):
        provider = type("P", (), {"installed": staticmethod(lambda: installed if isinstance(installed, dict) else (_ for _ in ()).throw(installed))})
        with patch.object(tune.shutil, "which", return_value=which), patch.object(tune, "local", return_value=provider), \
                patch.object(tune.Confirm, "ask", return_value=confirm) as ask, patch.object(tune, "run") as run:
            tune.offer(self.console, **kwargs)
        return ask, run

    def test_never_asks_with_yes_or_without_ollama(self):
        for kwargs in ({"assume_yes": True}, {"which": None}):
            ask, run = self._offer(installed={"m": 1}, **kwargs)
            ask.assert_not_called()
            run.assert_not_called()

    def test_setup_is_silent_when_no_model_is_installed(self):
        ask, run = self._offer(installed={})
        ask.assert_not_called()
        run.assert_not_called()

    def test_setup_points_at_the_command_when_ollama_is_not_running(self):
        ask, run = self._offer(installed=ProviderError("ollama", "down"))
        ask.assert_not_called()
        self.assertIn("clyde tune", self.console.file.getvalue())

    def test_a_yes_runs_the_tune_and_a_no_does_not(self):
        _, run = self._offer(installed={"m": 1}, confirm=True)
        run.assert_called_once_with(self.console, model=None)
        _, run = self._offer(installed={"m": 1}, confirm=False)
        run.assert_not_called()

    def test_after_a_download_it_tunes_that_model_without_listing_installed_ones(self):
        _, run = self._offer(installed=ProviderError("ollama", "down"), model="qwen3:4b")
        run.assert_called_once_with(self.console, model="qwen3:4b")


class ApplyHintTests(unittest.TestCase):
    ENV = tune.kv("q8_0")

    def _hint(self, system, app, ctx=8192):
        with patch.object(tune.platform, "system", return_value=system), patch.object(tune.os.path, "exists", return_value=app):
            return tune.apply_hint(self.ENV, "m:1", ctx, 8192)

    def test_launchctl_is_only_advised_for_the_ollama_app(self):
        self.assertIn("launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0", self._hint("Darwin", True))

    def test_a_cli_ollama_on_a_mac_gets_exports_not_launchctl(self):
        hint = self._hint("Darwin", False)
        self.assertNotIn("launchctl setenv OLLAMA_", hint)
        self.assertIn("export OLLAMA_FLASH_ATTENTION=1", hint)

    def test_linux_gets_systemd_and_a_longer_window_gets_the_clyde_variable(self):
        self.assertIn("systemctl", self._hint("Linux", False))
        self.assertIn("CLYDE_MODEL_CONTEXT_M_1=16384", self._hint("Linux", False, ctx=16384))
        self.assertNotIn("CLYDE_MODEL_CONTEXT", self._hint("Linux", False))


class EvalTests(unittest.TestCase):
    class _Score:
        def __init__(self, passed):
            self.passed = passed

    def test_a_failed_tool_call_gets_one_more_try_on_another_seed(self):
        seeds = []

        def evaluate(provider, model, ref):
            seeds.append(os.environ.get("CLYDE_SAMPLING_SEED"))
            return self._Score(len(seeds) == 2)

        with patch.object(tune.model_eval, "evaluate", side_effect=evaluate):
            self.assertTrue(tune._eval(object(), "m").passed)
        self.assertEqual(seeds, ["1", "2"])

    def test_a_pass_is_not_retried_and_the_seed_is_restored(self):
        with patch.dict(os.environ, {"CLYDE_SAMPLING_SEED": "9"}), \
                patch.object(tune.model_eval, "evaluate", return_value=self._Score(True)) as evaluate:
            tune._eval(object(), "m")
            self.assertEqual(os.environ["CLYDE_SAMPLING_SEED"], "9")
        evaluate.assert_called_once()
        self.assertNotIn("CLYDE_SAMPLING_SEED", os.environ)


class PickModelTests(unittest.TestCase):
    class _Provider:
        def __init__(self, installed):
            self._installed = installed

        def installed(self):
            return self._installed

    def test_defaults_to_the_smallest_installed(self):
        self.assertEqual(tune.pick_model(self._Provider({"big": 9, "small": 2}), None), "small")

    def test_unknown_model_is_an_error(self):
        with self.assertRaises(ProviderError):
            tune.pick_model(self._Provider({"a": 1}), "b")

    def test_nothing_installed_is_an_error(self):
        with self.assertRaises(ProviderError):
            tune.pick_model(self._Provider({}), None)


class MeasureTests(unittest.TestCase):
    def test_keeps_the_faster_run_and_reads_memory_from_ps(self):
        slow = {"prompt_eval_count": 1000, "prompt_eval_duration": 2_000_000_000, "eval_count": 128, "eval_duration": 8_000_000_000}
        fast = {"prompt_eval_count": 1000, "prompt_eval_duration": 2_000_000_000, "eval_count": 128, "eval_duration": 4_000_000_000}
        with patch.object(tune, "post_json", side_effect=[{}, slow, fast]) as post, \
                patch.object(tune, "get_json", return_value={"models": [{"name": "m", "size": 5 * GB}]}):
            result = tune.measure("http://h", "m", 8192)
        self.assertEqual(result, Result(5 * GB, 500.0, 32.0))
        warm, first, second = (c.args[1] for c in post.call_args_list)
        self.assertNotEqual(warm["prompt"], first["prompt"])   # else the timed run is served from the prompt cache
        self.assertNotEqual(first["prompt"], second["prompt"])
        self.assertEqual(second["options"]["num_ctx"], 8192)


if __name__ == "__main__":
    unittest.main()
