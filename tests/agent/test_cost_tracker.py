"""Tests for per-model token tracking, USD estimates and the /cost report.
Run: `python -m unittest tests.agent.test_cost_tracker`.
"""
import unittest

from src.command_system.builtins import cost_command_call
from src.command_system.engine import create_command_context
from src.agent.cost_tracker import CostTracker, estimate_usd


class RecordUsage(unittest.TestCase):
    def test_sums_per_model_and_keeps_units(self):
        t = CostTracker()
        t.record_usage("anthropic", "claude-sonnet-4-6", {"input_tokens": 100, "output_tokens": 10})
        t.record_usage("anthropic", "claude-sonnet-4-6", {"input_tokens": 50, "output_tokens": 5,
                                                         "cache_read_input_tokens": 1000})
        t.record_usage("ollama", "qwen3:8b", {"input_tokens": 7, "output_tokens": 3})
        self.assertEqual(t.models["anthropic:claude-sonnet-4-6"],
                         {"input_tokens": 150, "output_tokens": 15, "cache_read_input_tokens": 1000})
        self.assertEqual(t.models["ollama:qwen3:8b"], {"input_tokens": 7, "output_tokens": 3})
        self.assertEqual(t.total_units, 175)
        self.assertEqual(len(t.events), 3)


class EstimateUsd(unittest.TestCase):
    def test_priced_model_bills_each_token_kind(self):
        # Sonnet: $3 in, $15 out, $0.30 cache read, $3.75 cache write per MTok.
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000}
        self.assertAlmostEqual(estimate_usd("anthropic:claude-sonnet-4-6", usage), 22.05)

    def test_missing_cache_price_falls_back_to_input_price(self):
        # claude-opus-4-8 lists $5/$25 but no cache prices.
        self.assertAlmostEqual(estimate_usd("anthropic:claude-opus-4-8", {"cache_read_input_tokens": 1_000_000}), 5.0)

    def test_sibling_entry_is_not_priced_by_shorter_prefix(self):
        self.assertAlmostEqual(estimate_usd("openai:gpt-4.1-mini", {"input_tokens": 1_000_000}), 0.4)

    def test_local_ollama_is_free_and_unpriced_model_is_unknown(self):
        self.assertEqual(estimate_usd("ollama:qwen3:8b", {"input_tokens": 999}), 0.0)
        self.assertIsNone(estimate_usd("deepseek:deepseek-v4-pro", {"input_tokens": 999}))
        self.assertIsNone(estimate_usd("anthropic:claude-mythos-5-1", {"input_tokens": 999}))


class CostCommand(unittest.TestCase):
    def test_reports_models_prices_and_total(self):
        t = CostTracker()
        t.record_usage("anthropic", "claude-haiku-4-5", {"input_tokens": 1_000_000, "output_tokens": 0})
        t.record_usage("ollama", "llama3", {"input_tokens": 5, "output_tokens": 5})
        t.record_usage("deepseek", "deepseek-v4-pro", {"input_tokens": 5, "output_tokens": 5})
        out = cost_command_call("", create_command_context(workspace_root=".", cost_tracker=t)).value
        self.assertIn("anthropic:claude-haiku-4-5: 1,000,000 in, 0 out — $1.0000", out)
        self.assertIn("ollama:llama3: 5 in, 5 out — $0.0000", out)
        self.assertIn("deepseek:deepseek-v4-pro: 5 in, 5 out — price unknown", out)
        self.assertIn("Estimated total: $1.0000 (excludes models with unknown prices)", out)


if __name__ == "__main__":
    unittest.main()
