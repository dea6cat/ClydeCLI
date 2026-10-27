"""Prompt-cache misses read from traced model requests: what was billed again, what it cost, and whether you had been away."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.agent import cache_stats
from src.agent.cache_stats import analyze, describe

PRICE = SimpleNamespace(input_per_mtok=3.0, output_per_mtok=15.0, cache_read_per_mtok=0.3, cache_write_per_mtok=3.75)


def req(second: int, fresh: int, read: int, wrote: int, messages: int, model: str = "m", duration_ms: int = 2000) -> dict:
    return {"event": "model_request", "ts": f"2026-10-27T10:{second // 60:02d}:{second % 60:02d}.000", "provider": "anthropic", "model": model, "messages": messages,
            "duration_ms": duration_ms, "usage": {"input_tokens": fresh, "cache_read_input_tokens": read, "cache_creation_input_tokens": wrote}}


class Misses(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(cache_stats.catalog, "lookup", return_value=PRICE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_cache_that_holds_has_no_misses_and_a_hit_rate(self):
        report = analyze([req(0, 200, 0, 9000, 1), req(10, 300, 9000, 400, 3), req(20, 200, 9400, 300, 5)])
        self.assertEqual((report.requests, report.misses), (3, []))
        self.assertAlmostEqual(report.hit_rate, 18400 / (9200 + 9700 + 9900), places=3)
        self.assertIn("no misses worth naming", "\n".join(describe(report)))

    def test_a_request_that_reads_again_what_the_last_one_had_cached_is_a_miss_priced_by_the_difference(self):
        report = analyze([req(0, 200, 0, 9000, 1), req(10, 9500, 0, 400, 3)])   # nothing read: the start of the prompt changed
        (miss,) = report.misses
        self.assertEqual(miss.missed, 9200)   # min(9200, 9900) - 0
        self.assertAlmostEqual(miss.extra_usd, 9200 * (3.75 - 0.3) / 1e6, places=6)   # billed as a write, not a read
        self.assertLess(miss.idle_s, 20)

    def test_the_idle_gap_is_the_time_between_one_request_ending_and_the_next_starting(self):
        report = analyze([req(0, 200, 0, 9000, 1), req(600, 9300, 0, 100, 3, duration_ms=4000)])   # ten quiet minutes, then a 4 s request
        self.assertEqual(round(report.misses[0].idle_s), 596)
        text = "\n".join(describe(report))
        self.assertIn("1 miss", text)
        self.assertIn("1 after you were away longer than 5 min", text)
        self.assertIn("after 9 min quiet", text)

    def test_noise_other_models_other_conversations_errors_and_uncached_providers_are_not_misses(self):
        self.assertEqual(analyze([req(0, 200, 0, 9000, 1), req(10, 600, 8900, 300, 3)]).misses, [])   # small difference: block granularity
        self.assertEqual(analyze([req(0, 200, 0, 9000, 1, "a"), req(10, 9500, 0, 400, 3, "b")]).misses, [])   # another model starts its own chain
        self.assertEqual(analyze([req(0, 200, 0, 9000, 6), req(10, 9500, 0, 400, 2)]).misses, [])   # a shorter conversation: a compaction or a sub-agent
        bad = req(10, 9500, 0, 400, 3)
        bad["error"] = "boom"
        self.assertEqual(analyze([req(0, 200, 0, 9000, 1), bad]).requests, 1)
        none = analyze([req(0, 9000, 0, 0, 1), req(10, 9500, 0, 0, 3)])   # a provider that never reports caching
        self.assertEqual((none.requests, none.misses, describe(none)), (0, [], []))

    def test_without_a_price_the_miss_is_still_counted_and_the_report_names_the_biggest_three(self):
        with patch.object(cache_stats.catalog, "lookup", return_value=None):
            events = [req(0, 200, 0, 9000, 1)]
            for i in range(5):
                events.append(req(100 * (i + 1), 2000 * (i + 1) + 1000, 0, 100, 3 + 2 * i))
            report = analyze(events)
        self.assertEqual(len(report.misses), 5)
        self.assertIsNone(report.extra_usd)
        lines = describe(report)
        self.assertNotIn("more than a hit", "\n".join(lines))
        self.assertEqual(len([ln for ln in lines if "billed again" in ln]), 3)


class InTheCostCommand(unittest.TestCase):
    def test_cost_shows_the_cache_section_from_the_session_trace(self):
        from src.agent.cost_tracker import CostTracker
        from src.command_system.builtins import cost_command_call
        events = [req(0, 200, 0, 9000, 1), req(600, 9300, 0, 100, 3)]
        tracker = CostTracker()
        tracker.models = {"anthropic:m": {"input_tokens": 9500, "output_tokens": 10}}
        with patch("src.command_system.builtins.trace.read_events", return_value=events), patch.object(cache_stats.catalog, "lookup", return_value=PRICE):
            out = cost_command_call("", SimpleNamespace(cost_tracker=tracker)).value
        self.assertIn("Prompt cache:", out)
        self.assertIn("1 miss", out)
        with patch("src.command_system.builtins.trace.read_events", return_value=[]):
            self.assertNotIn("Prompt cache:", cost_command_call("", SimpleNamespace(cost_tracker=tracker)).value)


if __name__ == "__main__":
    unittest.main()
