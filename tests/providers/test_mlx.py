"""MLX source: exact sizes from a repo's safetensors, rated for this machine (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers import huggingface, mlx
from src.providers.fit import GB

SHARDED = [
    {"type": "file", "path": "model-00001-of-00002.safetensors", "size": 3 * GB},
    {"type": "file", "path": "model-00002-of-00002.safetensors", "size": 2 * GB},
    {"type": "file", "path": "config.json", "size": 2_000},
    {"type": "directory", "path": "extra", "size": 0},
]


class TestMLX(unittest.TestCase):
    def test_size_is_the_sum_of_the_weight_shards(self):
        self.assertEqual(mlx.weights_bytes(SHARDED), 5 * GB)

    def test_search_rates_each_repo_and_drops_what_wont_fit(self):
        def fake_get(url, **_):
            if "/tree/" in url:
                return SHARDED if "4bit" in url else [{"type": "file", "path": "model.safetensors", "size": 40 * GB}]
            return [{"id": "mlx-community/Coder-4bit", "downloads": 5}, {"id": "mlx-community/Huge-bf16", "downloads": 9},
                    {"id": "mlx-community/Qwen3-Embedding-0.6B-4bit", "downloads": 99}]   # tagged text-generation, can't chat
        with patch.object(huggingface, "get_json", side_effect=fake_get):
            offers = mlx.search("", 12 * GB)
        self.assertEqual([(o.name, o.rating, o.note, o.source) for o in offers],
                         [("mlx-community/Coder-4bit", "balance", "MLX 4-bit", "mlx")])


if __name__ == "__main__":
    unittest.main()
