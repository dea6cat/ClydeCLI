from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from src import tune_profile
from src.providers import best_fit, fit
from src.providers.fit import GB


def _ranked(repo="bartowski/Qwen3-8B-GGUF", size=5 * GB, **kw):
    model = NS(id="Qwen/Qwen3-8B", downloads=900, license="apache-2.0")
    variant = NS(quant_type="Q4_K_M", file_size_bytes=size)
    base = dict(model=model, artifact_model=NS(id=repo) if repo else None, artifact_variant=variant, gguf_variant=variant,
                quality_score=61.8, benchmark_source="direct", estimated_tok_per_sec=31.6, speed_range_tok_per_sec=(11.1, 63.3),
                speed_confidence="low")
    return NS(**{**base, **kw})


class TestBestFit(unittest.TestCase):
    def setUp(self):
        best_fit._ranked.cache_clear()

    def _search(self, ranked, query="", budget=12 * GB):
        with patch.object(best_fit, "_cache_state", return_value="fresh"), patch.object(best_fit, "_ranked", return_value=tuple(ranked)):
            return best_fit.search(query, budget)

    def test_a_ranked_model_becomes_a_pullable_offer_with_its_details(self):
        (offer,) = self._search([_ranked()])
        self.assertEqual((offer.pull_tag, offer.source, offer.note), ("hf.co/bartowski/Qwen3-8B-GGUF:Q4_K_M", "hf", "Q4_K_M"))
        self.assertEqual(offer.detail, "quality 62 (direct benchmark) · ~32 tok/s (11-63, low confidence) · apache-2.0")

    def test_models_without_a_gguf_repo_or_that_do_not_fit_are_left_out(self):
        self.assertEqual(self._search([_ranked(repo=None), _ranked(size=40 * GB)]), [])

    def test_the_query_filters_by_model_name(self):
        self.assertEqual(len(self._search([_ranked()], "qwen3")), 1)
        self.assertEqual(self._search([_ranked()], "llama"), [])

    def test_a_failed_ranking_gives_no_offers(self):
        with patch.object(best_fit, "_cache_state", return_value="fresh"), patch.object(best_fit, "_ranked", side_effect=OSError("offline")):
            self.assertEqual(best_fit.search("", 12 * GB), [])

    def test_a_cold_cache_starts_the_build_in_the_background_and_returns_nothing(self):
        with patch.object(best_fit, "_cache_state", return_value="none"), patch.object(best_fit, "_build") as build:
            self.assertEqual(best_fit.search("", 12 * GB), [])
        build.assert_called_once()

    def test_a_stale_cache_is_served_while_a_fresh_one_builds(self):
        with patch.object(best_fit, "_cache_state", return_value="stale"), patch.object(best_fit, "_build") as build, \
                patch.object(best_fit, "_ranked", return_value=(_ranked(),)):
            self.assertEqual(len(best_fit.search("", 12 * GB)), 1)
        build.assert_called_once()

    def test_a_fresh_cache_builds_nothing(self):
        with patch.object(best_fit, "_cache_state", return_value="fresh"), patch.object(best_fit, "_build") as build, \
                patch.object(best_fit, "_ranked", return_value=(_ranked(),)):
            best_fit.search("", 12 * GB)
        build.assert_not_called()

    def test_the_build_runs_once_while_it_is_pending(self):
        gate = threading.Event()
        best_fit._builder = None
        with patch.object(best_fit, "_ranked", side_effect=lambda *a: gate.wait(5)):
            best_fit._build(12 * GB, "Apple M3 Pro", "general")
            first = best_fit._builder
            best_fit._build(12 * GB, "Apple M3 Pro", "general")
            self.assertTrue(best_fit.pending())
            self.assertIs(best_fit._builder, first)
            gate.set()
            first.join(5)
        self.assertFalse(best_fit.pending())

    def test_the_machine_handed_to_whichllm_carries_our_budget_and_bandwidth(self):
        with patch.object(fit, "_total_ram_bytes", return_value=18 * GB):
            hardware = best_fit._machine(12 * GB, "Apple M3 Pro")
        gpu = hardware.gpus[0]
        self.assertEqual((gpu.usable_vram_bytes, gpu.memory_bandwidth_gbps, gpu.shared_memory), (12 * GB, 150.0, True))

    def test_the_ranking_profile_follows_the_uses_chosen_at_setup(self):
        for uses, expected in (((), "general"), (("chat",), "general"), (("coding",), "coding"), (("chat", "coding"), "coding")):
            saved = tune_profile.Profile(uses, "speed") if uses else None
            with patch.object(best_fit.tune_profile, "load", return_value=saved):
                self.assertEqual(best_fit._profile(), expected, uses)

    def test_the_profile_reaches_the_ranking(self):
        with patch("whichllm.api.recommend", return_value=[]) as rec:
            best_fit._ranked.cache_clear()
            best_fit._ranked(12 * GB, "Apple M3 Pro", "coding")
        self.assertEqual(rec.call_args.kwargs["profile"], "coding")

    def test_bandwidth_of_a_known_and_an_unknown_chip(self):
        self.assertEqual(fit.bandwidth_gbps("Apple M3 Pro"), 150)
        self.assertIsNone(fit.bandwidth_gbps("Intel Xeon"))


if __name__ == "__main__":
    unittest.main()
