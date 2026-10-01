"""Machine fit: the memory budget, relax / balance / hard ratings, and the speed estimate."""

from __future__ import annotations

import unittest

from src.providers.fit import GB, OVERHEAD, budget_bytes, pick, rate, tokens_per_s


class TestBudget(unittest.TestCase):
    def test_apple_wires_two_thirds_up_to_36gb_and_three_quarters_above(self):
        self.assertEqual(budget_bytes(18 * GB, apple=True, wired_limit_mb=0), 12 * GB)
        self.assertEqual(budget_bytes(64 * GB, apple=True, wired_limit_mb=0), 48 * GB)

    def test_a_raised_wired_limit_wins(self):
        self.assertEqual(budget_bytes(18 * GB, apple=True, wired_limit_mb=14 * 1024), 14 * GB)

    def test_other_machines_keep_a_quarter_for_the_os(self):
        self.assertEqual(budget_bytes(32 * GB, apple=False), 24 * GB)


class TestRating(unittest.TestCase):
    def test_share_of_the_budget_sets_the_rating(self):
        budget = 12 * GB
        self.assertEqual(rate(6 * GB - OVERHEAD, budget), "relax")
        self.assertEqual(rate(int(9.6 * GB) - OVERHEAD, budget), "balance")
        self.assertEqual(rate(12 * GB - OVERHEAD, budget), "hard")
        self.assertIsNone(rate(12 * GB, budget))

    def test_pick_prefers_the_largest_easy_variant_over_a_hard_one(self):
        variants = [("q2", 3 * GB), ("q4", 7 * GB), ("q6", 10 * GB), ("f16", 30 * GB)]
        self.assertEqual(pick(variants, 12 * GB), ("q4", 7 * GB, "balance"))
        self.assertEqual(pick([("q6", 10 * GB)], 12 * GB), ("q6", 10 * GB, "hard"))
        self.assertIsNone(pick([("f16", 30 * GB)], 12 * GB))


class TestSpeed(unittest.TestCase):
    def test_bandwidth_bound_and_moe_reads_only_active_weights(self):
        dense = tokens_per_s(5 * GB, "Apple M3 Pro")
        self.assertEqual(dense, 18)                                  # 150 GB/s × 0.6 / 5 GB
        self.assertEqual(tokens_per_s(5 * GB, "Apple M3 Pro", "Qwen3-30B-A3B"), 180)
        self.assertGreater(tokens_per_s(5 * GB, "Apple M3 Max"), dense)   # longest chip name wins
        self.assertIsNone(tokens_per_s(5 * GB, "Intel Core i7"))


if __name__ == "__main__":
    unittest.main()
