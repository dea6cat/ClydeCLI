"""Machine fit: the memory budget, relax / balance / hard ratings, and the speed estimate."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers.fit import GB, OVERHEAD, Offer, budget_bytes, gpu_share, group, is_slow, model_key, pick, rate, tokens_per_s


class TestBudget(unittest.TestCase):
    def test_apple_wires_two_thirds_up_to_36gb_and_three_quarters_above(self):
        self.assertEqual(budget_bytes(18 * GB, apple=True, wired_limit_mb=0), 12 * GB)
        self.assertEqual(budget_bytes(64 * GB, apple=True, wired_limit_mb=0), 48 * GB)

    def test_a_raised_wired_limit_wins(self):
        self.assertEqual(budget_bytes(18 * GB, apple=True, wired_limit_mb=14 * 1024), 14 * GB)

    def test_other_machines_keep_a_quarter_for_the_os(self):
        self.assertEqual(budget_bytes(32 * GB, apple=False), 24 * GB)


class TestSlow(unittest.TestCase):
    def test_a_model_under_the_floor_is_slow_over_it_or_unknown_is_not(self):
        self.assertTrue(is_slow(40 * GB, "Apple M3 Pro"))    # ~150 GB/s over 40 GB
        self.assertFalse(is_slow(2 * GB, "Apple M3 Pro"))
        self.assertFalse(is_slow(40 * GB, ""))               # unknown chip

    def test_the_floor_can_be_changed_and_a_bad_value_is_ignored(self):
        with patch.dict("os.environ", {"CLYDE_MIN_TOKS": "1000"}):
            self.assertTrue(is_slow(2 * GB, "Apple M3 Pro"))
        with patch.dict("os.environ", {"CLYDE_MIN_TOKS": "fast"}):
            self.assertFalse(is_slow(2 * GB, "Apple M3 Pro"))


class TestGpuShare(unittest.TestCase):
    def test_a_gpu_that_holds_the_model_gives_all_of_it_part_gives_a_share_none_gives_none(self):
        self.assertEqual(gpu_share(8 * GB, 20 * GB), 1.0)
        self.assertAlmostEqual(gpu_share(8 * GB, 4.75 * GB), 0.5)
        self.assertIsNone(gpu_share(0, 20 * GB))
        with patch("src.providers.fit.gpu_budget_bytes", return_value=None):   # no GPU
            self.assertIsNone(gpu_share(8 * GB))


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


class TestGrouping(unittest.TestCase):
    def test_repos_of_one_model_share_a_key_whatever_the_publisher_format_or_quant_tag(self):
        key = model_key("IFM/K2-Horizon-7B-GGUF")
        self.assertEqual(key, "k2-horizon-7b")
        for name in ("abenzerps/K2-Horizon-7B-MLX-4bit", "mlx-community/K2-Horizon-7B-oQ6e", "x/k2_horizon_7b_gguf"):
            self.assertEqual(model_key(name), key)

    def test_a_different_fine_tune_keeps_its_own_key(self):
        self.assertNotEqual(model_key("mlx-community/K2-Horizon-7B-Uno-oQ6e"), model_key("IFM/K2-Horizon-7B-GGUF"))
        self.assertNotEqual(model_key("a/Qwen3-4B-Instruct"), model_key("a/Qwen3-8B-Instruct"))

    def test_grouping_merges_formats_into_the_first_row_and_lists_every_option_once(self):
        q4 = Offer("IFM/K2-Horizon-7B-GGUF", "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M", 5 * GB, "balance", 9, "Q4_K_M", "hf")
        q8 = Offer("IFM/K2-Horizon-7B-GGUF", "hf.co/IFM/K2-Horizon-7B-GGUF:Q8_0", 8 * GB, "hard", 9, "Q8_0", "hf")
        gguf = Offer("IFM/K2-Horizon-7B-GGUF", q4.pull_tag, 5 * GB, "balance", 9, "Q4_K_M", "hf", options=(q4, q8))
        mlx = Offer("abenzerps/K2-Horizon-7B-MLX-4bit", "https://huggingface.co/abenzerps/K2-Horizon-7B-MLX-4bit",
                    4 * GB, "relax", 3, "MLX 4-bit", "mlx")
        other = Offer("u/Other-3B", "hf.co/u/Other-3B:Q4_K_M", 2 * GB, "relax", 1, "Q4_K_M", "hf")
        rows = group([gguf, other, mlx, gguf])
        self.assertEqual([r.name for r in rows], ["IFM/K2-Horizon-7B-GGUF", "u/Other-3B"])
        self.assertEqual(rows[0].pull_tag, q4.pull_tag)
        self.assertEqual([o.pull_tag for o in rows[0].options], [q4.pull_tag, q8.pull_tag, mlx.pull_tag])
        self.assertEqual(rows[1].options, ())

    def test_one_gguf_repo_lists_its_quants_and_other_publishers_do_not_repeat_them(self):
        def repo(name, *quants):
            offers = tuple(Offer(name, f"hf.co/{name}:{q}", (4 + i) * GB, "balance", 5, q, "hf") for i, q in enumerate(quants))
            return Offer(name, offers[0].pull_tag, offers[0].size_bytes, "balance", 5, quants[0], "hf", options=offers)
        top, other = repo("IFM/K2-7B-GGUF", "Q4_K_M", "Q8_0"), repo("bart/K2-7B-GGUF", "Q4_K_M", "IQ1_S", "Q8_0")
        (row,) = group([top, other])
        self.assertEqual([o.name for o in row.options], ["IFM/K2-7B-GGUF"] * 2)

    def test_single_download_repos_add_one_option_per_distinct_quant_most_popular_first(self):
        def mlx(name, note):
            return Offer(name, f"https://huggingface.co/{name}", 5 * GB, "balance", 1, note, "mlx")
        gguf = Offer("IFM/K2-7B-GGUF", "hf.co/IFM/K2-7B-GGUF:Q4_K_M", 5 * GB, "balance", 5, "Q4_K_M", "hf")
        rows = group([gguf, mlx("a/K2-7B-MLX-4bit", "MLX 4-bit"), mlx("mlx-community/K2-7B-4bit", "MLX 4-bit"),
                      mlx("a/K2-7B-oQ6e", "MLX oQ6e")])
        (row,) = rows
        self.assertEqual([(o.name, o.note) for o in row.options],
                         [("IFM/K2-7B-GGUF", "Q4_K_M"), ("a/K2-7B-MLX-4bit", "MLX 4-bit"), ("a/K2-7B-oQ6e", "MLX oQ6e")])

    def test_a_lone_offer_is_left_alone(self):
        solo = Offer("a/B-3B-GGUF", "hf.co/a/B-3B-GGUF:Q4_K_M", 2 * GB, "relax", 1, "Q4_K_M", "hf")
        self.assertEqual(group([solo]), [solo])


if __name__ == "__main__":
    unittest.main()
