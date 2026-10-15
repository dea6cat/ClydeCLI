"""Hugging Face source: GGUF quantizations from a repo listing, offered at the best fit (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers import huggingface
from src.providers.base import ProviderError
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
    def test_a_listing_that_times_out_while_reading_is_an_empty_listing_not_a_crash(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("The read operation timed out")):
            self.assertEqual(huggingface.files("org/repo"), [])
            self.assertEqual(huggingface.offers("gguf", "q", lambda repo: None), [])

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

    def test_search_lists_every_quant_as_an_option_smallest_first_and_flags_the_ones_too_large(self):
        tree = [{"type": "file", "path": "M-Q8_0.gguf", "size": 8 * GB}, {"type": "file", "path": "M-Q4_K_M.gguf", "size": 5 * GB},
                {"type": "file", "path": "M-F16.gguf", "size": 30 * GB}]

        def fake_get(url, **_):
            return tree if "/tree/" in url else [{"id": "u/m", "downloads": 10}]
        with patch.object(huggingface, "get_json", side_effect=fake_get):
            (offer,) = huggingface.search("m", 12 * GB)
        self.assertEqual([(o.note, o.rating) for o in offer.options], [("Q4_K_M", "balance"), ("Q8_0", "balance"), ("F16", "too large")])
        self.assertEqual(offer.pull_tag, "hf.co/u/m:Q8_0")                 # the recommendation is unchanged
        self.assertIn(offer.pull_tag, [o.pull_tag for o in offer.options])

    def test_a_repo_with_one_quant_has_no_extra_options(self):
        def fake_get(url, **_):
            return [{"type": "file", "path": "M-Q4_K_M.gguf", "size": 5 * GB}] if "/tree/" in url else [{"id": "u/m", "downloads": 1}]
        with patch.object(huggingface, "get_json", side_effect=fake_get):
            (offer,) = huggingface.search("m", 12 * GB)
        self.assertEqual(offer.options, ())

    def test_a_speculative_decoding_file_is_not_a_quantization_of_the_model(self):
        tree = [{"type": "file", "path": "Model-Q8_0.gguf", "size": 12 * GB}, {"type": "file", "path": "gemma-4-12B-it-MTP-F16.gguf", "size": 1 * GB},
                {"type": "file", "path": "Model-Q4_K_M.gguf", "size": 7 * GB}, {"type": "file", "path": "Model-draft-Q8_0.gguf", "size": 1 * GB},
                {"type": "file", "path": "Model-noMTP-Q6_K.gguf", "size": 9 * GB}]     # noMTP is the full model without the MTP head: a real quant
        self.assertEqual(sorted(huggingface._quants(tree)), [("Q4_K_M", 7 * GB), ("Q6_K", 9 * GB), ("Q8_0", 12 * GB)])

    def test_a_repo_whose_only_fitting_file_is_a_drafter_is_not_offered(self):
        tree = [{"type": "file", "path": "Model-Q8_0.gguf", "size": 12 * GB}, {"type": "file", "path": "Model-MTP-F16.gguf", "size": 1 * GB}]
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: tree if "/tree/" in url else [{"id": "u/m", "downloads": 9}]):
            self.assertEqual(huggingface.search("m", 12 * GB), [])     # the 12 GB model does not fit and the 1 GB file is not the model

    def test_drafter_repos_are_dropped_from_the_search(self):
        listing = [{"id": "g/gemma-4-12B-it-assistant", "downloads": 9, "config": {"model_type": "gemma4_unified_assistant"}},
                   {"id": "m/gemma-4-12B-it-qat-assistant-4bit", "downloads": 8, "config": {"model_type": "gemma4"}, "tags": ["mlx", "draft-model"]},
                   {"id": "m/gemma-4-12B-it-4bit", "downloads": 7, "config": {"model_type": "gemma4"}, "tags": ["mlx"]}]
        seen = []
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: listing):
            huggingface.offers("mlx", "gemma", lambda repo: seen.append(repo["id"]))
        self.assertEqual(sorted(set(seen)), ["m/gemma-4-12B-it-4bit"])

    def test_the_original_model_is_named_only_when_the_base_model_is_the_same_model_as_the_repo(self):
        def repo(rid, base=None):
            return {"id": rid, **({"cardData": {"base_model": base}} if base else {})}
        cases = [
            (repo("lmstudio-community/Ministral-3-14B-Reasoning-2512-GGUF", "mistralai/Ministral-3-14B-Reasoning-2512"), "mistralai/Ministral-3-14B-Reasoning-2512"),
            (repo("x/K2-7B-GGUF", ["IFM/K2-7B"]), "IFM/K2-7B"),                                       # a list, as some cards write it
            (repo("bartowski/mistralai_Ministral-3-14B-Reasoning-2512-GGUF", "mistralai/Ministral-3-14B-Reasoning-2512"),
             "mistralai/Ministral-3-14B-Reasoning-2512"),                                              # bartowski prefixes the org
            (repo("mlx-community/Ministral-3-14B-Reasoning-2512-4bit", ["mistralai/Ministral-3-14B-Base-2512"]), ""),   # a mislabelled base
            (repo("u/Gemma-12B-coder-GGUF", "google/gemma-12b"), ""),                                  # a fine-tune is not the original
            (repo("a/B-3B-GGUF", "a/B-3B-GGUF"), ""),
            (repo("a/C-3B-GGUF"), ""),
        ]
        self.assertEqual([huggingface.original(r) for r, _ in cases], [want for _, want in cases])

    def test_search_names_the_original_model_on_the_offer(self):
        listing = [{"id": "lmstudio-community/K2-7B-GGUF", "downloads": 5, "cardData": {"base_model": "IFM/K2-7B"}}]
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: [{"type": "file", "path": "M-Q4_K_M.gguf", "size": 5 * GB}] if "/tree/" in url else listing):
            (offer,) = huggingface.search("k2", 12 * GB)
        self.assertEqual((offer.name, offer.model), ("lmstudio-community/K2-7B-GGUF", "IFM/K2-7B"))

    def test_a_models_page_uses_the_original_repos_numbers_and_readme_and_the_quant_repos_specs(self):
        quant = {"id": "lmstudio-community/K2-7B-GGUF", "author": "lmstudio-community", "downloads": 30, "likes": 1,
                 "lastModified": "2026-01-01T00:00:00.000Z", "tags": [], "cardData": {"base_model": "IFM/K2-7B"},
                 "gguf": {"total": 7_000_000_000, "architecture": "k2", "context_length": 8192, "chat_template": "{{ tools }}"}}
        orig = {"id": "IFM/K2-7B", "author": "IFM", "downloads": 74000, "likes": 90, "lastModified": "2026-10-02T00:00:00.000Z",
                "tags": [], "cardData": {"license": "apache-2.0"}}
        texts = []

        def fake_text(url, **_):
            texts.append(url)
            return "# T\n\nThe original model card describes a dense open-weights model for long documents."
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: [] if "author=" in url else orig if "/IFM/K2-7B?" in url else quant), \
                patch.object(huggingface, "get_text", side_effect=fake_text):
            d = huggingface.details("lmstudio-community/K2-7B-GGUF", "gguf")
        self.assertEqual((d.original, d.downloads, d.likes, d.updated, d.license), ("IFM/K2-7B", 74000, 90, "2026-10-02T00:00:00.000Z", "apache-2.0"))
        self.assertEqual((d.params, d.arch, d.context, d.tools), (7_000_000_000, "k2", 8192, True))
        self.assertTrue(any("IFM/K2-7B/raw/main/README.md" in u for u in texts))
        self.assertTrue(d.summary.startswith("The original model card"))

    def test_a_page_without_an_original_keeps_the_repos_own_numbers(self):
        bare = {"id": "u/m", "author": "u", "downloads": 3, "likes": 2, "lastModified": "2026-01-01T00:00:00.000Z", "tags": [], "gguf": {}}
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: [] if "author=" in url else bare), \
                patch.object(huggingface, "get_text", return_value=""):
            d = huggingface.details("u/m", "gguf")
        self.assertEqual((d.original, d.downloads, d.likes), ("", 3, 2))

    def test_search_also_finds_vision_models_and_the_catalog_publishers_untagged_repos(self):
        # Hugging Face tags a vision-language model image-text-to-text, and lmstudio-community's repos often carry no pipeline tag:
        # asking only for text-generation hid both (Ministral 3 14B Reasoning, Gemma 4 12B).
        urls, tree = [], [{"type": "file", "path": "M-Q4_K_M.gguf", "size": 5 * GB}]
        by_query = {"text-generation": [{"id": "x/plain", "downloads": 10}],
                    "image-text-to-text": [{"id": "x/vision", "downloads": 50}],
                    "lmstudio-community": [{"id": "lmstudio-community/M-GGUF", "downloads": 30}, {"id": "x/plain", "downloads": 10}]}

        def fake_get(url, **_):
            if "/tree/" in url:
                return tree
            urls.append(url)
            return next(v for k, v in by_query.items() if k in url)
        with patch.object(huggingface, "get_json", side_effect=fake_get):
            offers = huggingface.search("m", 12 * GB)
        self.assertEqual([o.name for o in offers], ["x/vision", "lmstudio-community/M-GGUF", "x/plain"])   # by downloads, once each
        self.assertTrue(any("pipeline_tag=image-text-to-text" in u for u in urls))
        catalog = [u for u in urls if "author=lmstudio-community" in u]
        self.assertEqual(len(catalog), 1)
        self.assertNotIn("pipeline_tag", catalog[0])

    def test_mlx_search_asks_the_mlx_community_without_a_pipeline_tag_too(self):
        urls = []
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: urls.append(url) or []):
            huggingface.offers("mlx", "m", lambda repo: None)
        self.assertTrue(any("author=mlx-community" in u and "pipeline_tag" not in u for u in urls))

    def test_details_read_the_card_numbers_capabilities_and_other_repos_by_the_author(self):
        info = {"id": "IFM/K2-7B-GGUF", "author": "IFM", "downloads": 35214, "likes": 76, "lastModified": "2026-10-02T13:23:24.000Z",
                "pipeline_tag": "text-generation", "tags": ["gguf", "license:apache-2.0", "reasoning"],
                "cardData": {"license": "apache-2.0"},
                "gguf": {"total": 8999178240, "architecture": "k2-horizon", "context_length": 524288, "chat_template": "{{ tools }}"},
                "siblings": [{"rfilename": "mmproj-F16.gguf"}]}
        readme = ("---\nlicense: mit\n---\n\n# K2\n\n> [!NOTE]\n> a note that is not the description\n\n"
                  "The K2 Horizon 7B model is a **dense** open-weights model, see [the card](http://x), tuned for long documents.\n\n| a | b |")
        others = [{"id": "IFM/K2-7B-GGUF", "downloads": 35214, "likes": 76}, {"id": "IFM/K2-0.9B-GGUF", "downloads": 25809, "likes": 97}]
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: others if "author=" in url else info), \
                patch.object(huggingface, "get_text", return_value=readme):
            d = huggingface.details("IFM/K2-7B-GGUF", "gguf")
        self.assertEqual((d.downloads, d.likes, d.updated, d.params, d.arch, d.context, d.license),
                         (35214, 76, "2026-10-02T13:23:24.000Z", 8999178240, "k2-horizon", 524288, "apache-2.0"))
        self.assertEqual(d.summary, "The K2 Horizon 7B model is a dense open-weights model, see the card, tuned for long documents.")
        self.assertEqual((d.tools, d.vision, d.reasoning), (True, True, True))
        self.assertEqual(d.author, "IFM")
        self.assertEqual(d.related, (("IFM/K2-0.9B-GGUF", 25809, 97),))      # not the repo itself

    def test_details_leave_unknowns_empty_and_a_failed_lookup_is_none(self):
        bare = {"id": "u/m", "author": "u", "downloads": 3, "likes": 0, "tags": [], "gguf": {}}
        with patch.object(huggingface, "get_json", side_effect=lambda url, **_: [] if "author=" in url else bare), \
                patch.object(huggingface, "get_text", side_effect=ProviderError("huggingface", "down")):
            d = huggingface.details("u/m", "gguf")
        self.assertEqual((d.params, d.arch, d.context, d.license, d.summary, d.tools, d.vision, d.reasoning, d.related),
                         (None, "", None, "", "", None, False, False, ()))
        with patch.object(huggingface, "get_json", side_effect=ProviderError("huggingface", "down")):
            self.assertIsNone(huggingface.details("u/m", "gguf"))

    def test_the_description_is_the_first_real_paragraph_and_is_cut_at_a_word(self):
        long = "word " * 120
        self.assertEqual(huggingface._summary("---\na: b\n---\n# T\n\n![badge](x)\n\n<p>html</p>\n\n```\ncode\n```\n\nShort."), "")
        text = huggingface._summary(f"# T\n\n{long}")
        self.assertTrue(len(text) <= 281 and text.endswith("…") and "  " not in text)
        self.assertEqual(huggingface._summary("# T\n\nA real description paragraph that is long enough to count."),
                         "A real description paragraph that is long enough to count.")

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

    def test_a_quant_of_a_base_model_with_an_instruct_sibling_is_dropped(self):
        def repo(name, base):
            return {"id": name, "downloads": 1, "cardData": {"base_model": base}}
        listing = [repo("u/Coder-7B-GGUF", "Qwen/Coder-7B"),                # base: Coder-7B-Instruct exists
                   repo("u/Hybrid-8B-GGUF", "Qwen/Hybrid-8B"),              # no -Instruct sibling: stays
                   repo("u/Coder-7B-Instruct-GGUF", "Qwen/Coder-7B-Instruct"),   # already chat-tuned: not even probed
                   repo("u/Listed-GGUF", ["Org/Listed"])]                   # base_model as a list; no sibling

        def fake_get(url, **_):
            if "/tree/" in url:
                return [{"type": "file", "path": "M-Q4_K_M.gguf", "size": GB}]
            if url.endswith("Qwen/Coder-7B-Instruct") and "tree" not in url:
                return {"id": "Qwen/Coder-7B-Instruct"}
            if "-Instruct" in url:
                raise huggingface.ProviderError("huggingface", "HTTP 401")
            return listing
        with patch.object(huggingface, "get_json", side_effect=fake_get) as get:
            names = [o.name for o in huggingface.search("", 12 * GB)]
        self.assertEqual(sorted(names), ["u/Coder-7B-Instruct-GGUF", "u/Hybrid-8B-GGUF", "u/Listed-GGUF"])
        probed = [c.args[0] for c in get.call_args_list if c.args[0].endswith("-Instruct")]
        self.assertNotIn("https://huggingface.co/api/models/Qwen/Coder-7B-Instruct-Instruct", probed)

    def test_a_repo_is_judged_by_its_gguf_chat_template(self):
        for gguf, expected in (({"chat_template": "hi"}, True), ({"chat_template": "x tool_call y"}, False), ({}, False)):
            with patch.object(huggingface, "get_json", return_value={"gguf": gguf}):
                self.assertEqual(huggingface.repo_lacks_tools("a/b"), expected)
        with patch.object(huggingface, "get_json", side_effect=huggingface.ProviderError("huggingface", "offline")):
            self.assertFalse(huggingface.repo_lacks_tools("a/b"))

    def test_mlx_template_lives_under_the_tokenizer_config(self):
        self.assertTrue(huggingface._lacks_tools({"config": {"tokenizer_config": {"chat_template": "hi"}}}, "mlx"))
        self.assertFalse(huggingface._lacks_tools({"config": {"tokenizer_config": {"chat_template": "x tool_call y"}}}, "mlx"))
        self.assertFalse(huggingface._lacks_tools({"config": {}}, "mlx"))


if __name__ == "__main__":
    unittest.main()
