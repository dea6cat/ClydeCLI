"""Hugging Face source: GGUF quantizations from a repo listing, offered at the best fit (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers import huggingface
from src.providers.fit import GB

TREE = [
    {"type": "directory", "path": "BF16", "size": 0},
    {"type": "file", "path": "README.md", "size": 900},
    {"type": "file", "path": "Coder-7B-Q4_K_M.gguf", "size": 5 * GB},
    {"type": "file", "path": "Coder-7B-Q8_0.gguf", "size": 8 * GB},
    {"type": "file", "path": "Coder-7B-IQ2_XS.gguf", "size": 2 * GB},
    {"type": "file", "path": "mmproj-Coder-7B-F16.gguf", "size": 1 * GB},
    {"type": "file", "path": "Coder-7B-F16-00001-of-00002.gguf", "size": 7 * GB},
    {"type": "file", "path": "Coder-7B-draft-Q8_0.gguf", "size": 1 * GB},
    {"type": "file", "path": "Coder-7B-noMTP-Q4_K_M.gguf", "size": 6 * GB},
]


class TestHuggingFace(unittest.TestCase):
    def test_quants_skip_projectors_drafts_split_files_and_folders(self):
        # Q4_K_M has two files; the larger (6 GB noMTP) is reported, never the smaller.
        self.assertEqual(sorted(huggingface._quants(TREE)), [("IQ2_XS", 2 * GB), ("Q4_K_M", 6 * GB), ("Q8_0", 8 * GB)])

    def test_search_offers_each_repo_at_its_best_fitting_quant(self):
        def fake_get(url, **_):
            if "/tree/" in url:
                return TREE if "fits" in url else [{"type": "file", "path": "Big-F16.gguf", "size": 60 * GB}]
            return [{"id": "u/fits", "downloads": 10}, {"id": "u/huge", "downloads": 99}]
        with patch.object(huggingface, "get_json", side_effect=fake_get):
            offers = huggingface.search("coder", 12 * GB)
        self.assertEqual([(o.pull_tag, o.rating) for o in offers], [("hf.co/u/fits:Q8_0", "balance")])

    def test_repos_whose_chat_template_has_no_tools_are_dropped_unknown_templates_stay(self):
        listing = [
            {"id": "u/tools", "downloads": 3, "gguf": {"chat_template": "{% if tools %}{{ tools }}{% endif %}"}},
            {"id": "u/chatonly", "downloads": 2, "gguf": {"chat_template": "{{ messages }}"}},
            {"id": "u/unknown", "downloads": 1, "gguf": {}},
        ]
        urls = []

        def fake_get(url, **_):
            urls.append(url)
            return [{"type": "file", "path": "M-Q4_K_M.gguf", "size": GB}] if "/tree/" in url else listing
        with patch.object(huggingface, "get_json", side_effect=fake_get):
            offers = huggingface.search("", 12 * GB)
        self.assertEqual([o.name for o in offers], ["u/tools", "u/unknown"])
        self.assertIn("expand%5B%5D=gguf", urls[0])

    def test_mlx_template_lives_under_the_tokenizer_config(self):
        self.assertTrue(huggingface._lacks_tools({"config": {"tokenizer_config": {"chat_template": "hi"}}}, "mlx"))
        self.assertFalse(huggingface._lacks_tools({"config": {"tokenizer_config": {"chat_template": "x tool_call y"}}}, "mlx"))
        self.assertFalse(huggingface._lacks_tools({"config": {}}, "mlx"))


if __name__ == "__main__":
    unittest.main()
