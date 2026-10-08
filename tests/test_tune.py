"""clyde tune: the verdict rules, the timing maths and model choice, against fakes (no Ollama is started)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src import tune
from src.providers.base import ProviderError

GB = 2 ** 30


def _result(memory_gb: float, gen_tps: float) -> tune.Result:
    return tune.Result(int(memory_gb * GB), 500.0, gen_tps)


class VerdictTests(unittest.TestCase):
    def test_recommends_a_real_saving_without_a_slowdown(self):
        ok, why = tune.verdict(_result(4.7, 41), _result(4.2, 39.8))
        self.assertTrue(ok)
        self.assertIn("MB", why)

    def test_rejects_a_saving_too_small_to_matter(self):
        ok, why = tune.verdict(_result(4.30, 41), _result(4.25, 41))
        self.assertFalse(ok)
        self.assertIn("only", why)

    def test_rejects_a_big_slowdown_even_with_a_saving(self):
        ok, why = tune.verdict(_result(8.0, 40), _result(6.0, 30))
        self.assertFalse(ok)
        self.assertIn("slower", why)

    def test_rejects_when_memory_does_not_drop(self):
        self.assertFalse(tune.verdict(_result(4.0, 40), _result(4.0, 40))[0])

    def test_rejects_a_run_with_no_reading(self):
        self.assertFalse(tune.verdict(_result(4.0, 40), tune.Result(0, 0.0, 0.0))[0])


class MeasureTests(unittest.TestCase):
    def test_reads_speed_from_ollama_timings_and_memory_from_ps(self):
        timed = {"prompt_eval_count": 1000, "prompt_eval_duration": 2_000_000_000,
                 "eval_count": 128, "eval_duration": 4_000_000_000}
        with patch.object(tune, "post_json", side_effect=[{}, timed]) as post, \
                patch.object(tune, "get_json", return_value={"models": [{"name": "m", "size": 5 * GB}]}):
            result = tune.measure("http://h", "m", 8192)
        self.assertEqual(result, tune.Result(5 * GB, 500.0, 32.0))
        warm, real = (c.args[1] for c in post.call_args_list)
        self.assertNotEqual(warm["prompt"], real["prompt"])   # else the timed run is served from the prompt cache
        self.assertEqual(real["options"]["num_ctx"], 8192)

    def test_missing_timings_are_zero_not_an_error(self):
        with patch.object(tune, "post_json", return_value={}), patch.object(tune, "get_json", return_value={}):
            self.assertEqual(tune.measure("http://h", "m", 4096), tune.Result(0, 0.0, 0.0))


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


if __name__ == "__main__":
    unittest.main()
