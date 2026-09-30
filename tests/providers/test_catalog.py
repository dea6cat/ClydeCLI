"""Tests for the per-model capability catalog (Phase 6.1). Covers prefix matching,
the accessor fallbacks, corrupt-catalog degradation, and the context_budget wiring
(catalog window for known cloud models, per-provider constant otherwise).
Run: `python -m unittest tests.providers.test_catalog`.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


from src.providers import catalog  # noqa: E402


class _Prov:
    def __init__(self, name):
        self.name = name


class CatalogLookup(unittest.TestCase):
    def test_exact_key_matches(self):
        info = catalog.lookup("gpt-4o-mini")
        self.assertIsNotNone(info)
        self.assertEqual(info.context_window, 128000)

    def test_dated_variant_matches_base_prefix(self):
        # gpt-4o-2024-08-06 has no exact key; falls to the 'gpt-4o' prefix.
        info = catalog.lookup("gpt-4o-2024-08-06")
        self.assertIsNotNone(info)
        self.assertEqual(info.context_window, 128000)
        self.assertEqual(info.default_max_tokens, 16384)

    def test_longest_prefix_wins(self):
        # 'gpt-4o-mini-...' must resolve to gpt-4o-mini, not the shorter gpt-4o.
        mini = catalog.lookup("gpt-4o-mini-2024-07-18")
        base = catalog.lookup("gpt-4o-2024-08-06")
        self.assertEqual(mini.default_max_tokens, 16384)
        self.assertEqual(base.default_max_tokens, 16384)
        # 'o1-mini' (128k) is a longer prefix than the bare 'o1' full model (200k),
        # so a reasoning-mini variant must not inherit the larger window.
        self.assertEqual(catalog.lookup("o1-mini-2024-09-12").context_window, 128000)
        self.assertEqual(catalog.lookup("o1-2024-12-17").context_window, 200000)

    def test_case_insensitive(self):
        self.assertEqual(catalog.lookup("GPT-4O"), catalog.lookup("gpt-4o"))

    def test_unknown_model_is_none(self):
        self.assertIsNone(catalog.lookup("some-unknown-model-xyz"))
        self.assertIsNone(catalog.lookup(""))


class CatalogAccessors(unittest.TestCase):
    def test_context_window_fallback(self):
        self.assertEqual(catalog.context_window("gpt-4o"), 128000)
        self.assertIsNone(catalog.context_window("nope-nope"))

    def test_max_tokens_uses_default_when_unknown(self):
        self.assertEqual(catalog.max_tokens("claude-opus-4-8", 4096), 64000)
        self.assertEqual(catalog.max_tokens("nope-nope", 4096), 4096)

    def test_prices_are_optional(self):
        info = catalog.lookup("gpt-4o-2024-08-06")
        self.assertEqual((info.input_per_mtok, info.output_per_mtok, info.cache_read_per_mtok), (2.5, 10.0, 1.25))
        mythos = catalog.lookup("claude-mythos-5-1")
        self.assertEqual(mythos.context_window, 200000)
        self.assertIsNone(mythos.input_per_mtok)

    def test_entry_without_price_fields_still_loads(self):
        real, real_cache = catalog._CATALOG_PATH, catalog._cache
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "catalog.json"
            path.write_text(json.dumps({"models": {"m": {"context_window": 10, "default_max_tokens": 5}}}))
            try:
                catalog._CATALOG_PATH, catalog._cache = path, None
                self.assertEqual(catalog.lookup("m"), catalog.ModelInfo(10, 5))
            finally:
                catalog._CATALOG_PATH, catalog._cache = real, real_cache


class CorruptCatalog(unittest.TestCase):
    def test_bad_json_degrades_to_empty(self):
        real = catalog._CATALOG_PATH
        real_cache = catalog._cache
        try:
            catalog._CATALOG_PATH = real.with_name("does-not-exist.json")
            catalog._cache = None
            self.assertIsNone(catalog.lookup("gpt-4o"))
            self.assertEqual(catalog.max_tokens("gpt-4o", 4096), 4096)
        finally:
            catalog._CATALOG_PATH = real
            catalog._cache = real_cache


if __name__ == "__main__":
    unittest.main()
