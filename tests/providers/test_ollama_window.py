from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers import ollama
from src.providers.ollama import MODEL_RAM_FRACTION, OllamaProvider

GB = 1024 ** 3


def _window(ram_gb: float, weights_gb: float, kv_kb_per_token: int, trained: int, free_gb: float = 0, loaded_gb: float = 0) -> tuple[int, int]:
    """(window, bytes weights + cache would take) for a model on a machine with ram_gb of RAM, free_gb of it free
    (0: unreadable) and loaded_gb already held by this model in Ollama."""
    provider = OllamaProvider()
    with patch.object(ollama, "_total_ram_bytes", return_value=int(ram_gb * GB)), \
            patch.object(ollama, "_available_ram_bytes", return_value=int(free_gb * GB)), \
            patch.object(provider, "_loaded_bytes", return_value=int(loaded_gb * GB)), \
            patch.object(ollama, "_kv_bytes_per_token", return_value=kv_kb_per_token * 1024), \
            patch.object(provider, "_weight_bytes", return_value=int(weights_gb * GB)), \
            patch.object(provider, "_show", return_value={"model_info": {"x.context_length": trained}}):
        window = provider._compute_ctx("m")
    return window, int(weights_gb * GB) + window * kv_kb_per_token * 1024


class WindowSizingTests(unittest.TestCase):
    def test_a_long_context_model_on_an_18_gb_mac_stays_under_the_ram_cap(self):
        # qwen3:4b: this window was 68,608 tokens, 11.75 GB in all, and panicked the machine
        window, total = _window(18, 2.33, 144, 262_144)
        self.assertLessEqual(total, 18 * GB * MODEL_RAM_FRACTION)
        self.assertLess(window, 40_000)
        self.assertGreater(window, 16_000)

    def test_a_small_cache_model_still_gets_its_whole_trained_window(self):
        self.assertEqual(_window(18, 3.37, 36, 32_768)[0], 32_768)

    def test_a_model_larger_than_the_cap_is_not_pinned_below_the_floor(self):
        self.assertEqual(_window(8, 4.9, 144, 262_144)[0], ollama.CTX_FLOOR)

    def test_memory_that_other_apps_hold_shrinks_the_window(self):
        # this Mac had 7.0 GB free at idle (Xcode, browsers, editors): the same model gets a window that leaves 3 GB free
        busy, total = _window(18, 2.33, 144, 262_144, free_gb=7.0)
        self.assertLess(busy, _window(18, 2.33, 144, 262_144)[0])
        self.assertLessEqual(total, (7.0 - 3.0) * GB + 0.5 * GB)

    def test_a_model_already_loaded_does_not_shrink_its_own_window(self):
        idle = _window(18, 2.33, 144, 262_144, free_gb=7.0)[0]
        self.assertEqual(_window(18, 2.33, 144, 262_144, free_gb=2.5, loaded_gb=4.5)[0], idle)

    def test_free_memory_never_grows_a_window_past_the_ram_cap(self):
        self.assertEqual(_window(18, 2.33, 144, 262_144, free_gb=17.0)[0], _window(18, 2.33, 144, 262_144)[0])

    def test_more_ram_gives_a_longer_window(self):
        self.assertGreater(_window(64, 2.33, 144, 262_144)[0], _window(18, 2.33, 144, 262_144)[0])


if __name__ == "__main__":
    unittest.main()
