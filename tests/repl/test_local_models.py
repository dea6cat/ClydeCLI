"""/models local: nothing is pulled or loaded without an informed yes."""

from __future__ import annotations

import unittest
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from rich.console import Console

from src.providers.fit import GB, Offer
from src.providers.huggingface import Details
from src.repl import local_models

HARD = Offer("big", "big:30b", 10 * GB, "hard", 1, "est. Q4", "ollama")
RELAX = Offer("small", "small:3b", 2 * GB, "relax", 1, "est. Q4", "ollama")
GGUF = Offer("u/coder", "hf.co/u/coder:Q4_K_M", 5 * GB, "balance", 1, "Q4_K_M", "hf")
MLX = Offer("mlx-community/Coder-4bit", "https://huggingface.co/mlx-community/Coder-4bit", 4 * GB, "relax", 1, "MLX 4-bit", "mlx")


class _Ollama:
    def __init__(self, up: bool):
        self.up = up

    def is_available(self):
        return self.up


class _Repl:
    def __init__(self):
        self.console = Console(record=True, width=160)
        self.registry = {}

    class _esc:
        paused = staticmethod(nullcontext)


class TestConfirm(unittest.TestCase):
    def setUp(self):
        self.repl = _Repl()
        for name, value in (("disk_free_bytes", 50 * GB), ("free_now_bytes", 4 * GB)):
            patcher = patch.object(local_models.fit, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_hard_models_default_to_no_and_say_why(self):
        with patch.object(local_models.Confirm, "ask", return_value=False) as ask:
            self.assertFalse(local_models._confirm(self.repl, HARD, 12 * GB, "Apple M3 Pro"))
        self.assertFalse(ask.call_args.kwargs["default"])
        shown = self.repl.console.export_text()
        self.assertIn("barely fits", shown)
        self.assertIn("close apps to free", shown)   # 11.5 GB loaded vs 4 GB free right now

    def test_the_cost_is_a_table_of_labelled_rows(self):
        with patch.object(local_models.Confirm, "ask", return_value=True):
            local_models._confirm(self.repl, RELAX, 12 * GB, "Apple M3 Pro")
        shown = self.repl.console.export_text()
        for title in ("WHAT", "DETAIL"):
            self.assertIn(title, shown)
        for row in ("download", "when run", "speed", "quality", "means"):
            self.assertRegex(shown, rf"(?m)^\s*{row}\s+\S")                  # each fact starts its own row, label then detail
        self.assertIn("2.0 GB", shown)
        self.assertIn("relax", shown)

    def test_easy_models_default_to_yes(self):
        with patch.object(local_models.Confirm, "ask", return_value=True) as ask:
            self.assertTrue(local_models._confirm(self.repl, RELAX, 12 * GB, "Apple M3 Pro"))
        self.assertTrue(ask.call_args.kwargs["default"])

    def test_a_download_bigger_than_the_free_disk_is_refused_without_asking(self):
        with patch.object(local_models.fit, "disk_free_bytes", return_value=5 * GB), \
                patch.object(local_models.Confirm, "ask") as ask:
            self.assertFalse(local_models._confirm(self.repl, HARD, 12 * GB, "Apple M3 Pro"))
        ask.assert_not_called()
        self.assertIn("Not enough disk", self.repl.console.export_text())

    def test_declining_pulls_nothing(self):
        with patch.object(local_models, "SOURCES", {"ollama": lambda q, b: [HARD]}), \
                patch.object(local_models, "pick", return_value="0"), \
                patch.object(local_models.Confirm, "ask", return_value=False), \
                patch.object(local_models, "_runner", return_value="ollama"), \
                patch.object(local_models, "_pull_ollama") as pull_ollama, \
                patch.object(local_models, "_get_lmstudio") as get_lmstudio:
            local_models.show(self.repl, " ollama coder")
        pull_ollama.assert_not_called()
        get_lmstudio.assert_not_called()

    def _searched(self, arg: str) -> dict[str, str]:
        """Which sources show() searched for `arg`, and with what query."""
        seen: dict[str, str] = {}
        sources = {name: (lambda q, b, name=name: seen.__setitem__(name, q) or []) for name in ("ollama", "hf")}
        with patch.object(local_models, "SOURCES", sources):
            local_models.show(self.repl, arg)
        return seen

    def test_bare_command_searches_both_sources_with_no_query(self):
        self.assertEqual(self._searched(""), {"ollama": "", "hf": ""})

    def test_bare_command_adds_mlx_only_on_apple_silicon(self):
        seen: list[str] = []
        sources = {n: (lambda q, b, n=n: seen.append(n) or []) for n in ("ollama", "hf", "mlx")}
        for chip, expected in (("Apple M3 Pro", ["ollama", "hf", "mlx"]), ("", ["ollama", "hf"])):
            seen.clear()
            with patch.object(local_models, "SOURCES", sources), patch.object(local_models.fit, "chip", return_value=chip):
                local_models.show(self.repl, "")
            self.assertEqual(sorted(seen), sorted(expected))

    def test_words_search_both_and_a_source_name_narrows_to_it(self):
        self.assertEqual(self._searched(" qwen coder"), {"ollama": "qwen coder", "hf": "qwen coder"})
        self.assertEqual(self._searched(" hf qwen"), {"hf": "qwen"})


class TestRouting(unittest.TestCase):
    def _runner(self, offer, ollama_up: bool, lms: bool, apple: bool = True):
        repl = _Repl()
        repl.registry = {"ollama": _Ollama(ollama_up), **({"omlx": object()} if apple else {})}
        with patch.object(local_models, "_lms", return_value="/bin/lms" if lms else None):
            return local_models._runner(repl, offer)

    def test_each_model_goes_to_the_app_that_runs_it(self):
        self.assertEqual(self._runner(MLX, ollama_up=False, lms=False), "omlx")      # MLX: oMLX, which installs itself
        self.assertIsNone(self._runner(MLX, ollama_up=True, lms=True, apple=False))  # ... and only on Apple Silicon
        self.assertEqual(self._runner(GGUF, ollama_up=True, lms=True), "ollama")     # GGUF: Ollama first
        self.assertEqual(self._runner(GGUF, ollama_up=False, lms=True), "lmstudio")  # ... else LM Studio
        self.assertIsNone(self._runner(HARD, ollama_up=False, lms=True))             # ollama.com: Ollama only

    def test_lm_studio_downloads_exactly_the_rated_variant(self):
        self.assertEqual(local_models.lms_target(GGUF), ("https://huggingface.co/u/coder@Q4_K_M", "--gguf"))
        self.assertEqual(local_models.lms_target(MLX), ("https://huggingface.co/mlx-community/Coder-4bit", "--mlx"))


if __name__ == "__main__":
    unittest.main()


class _FakeOllama:
    name = "ollama"

    def __init__(self, sizes):
        self.sizes, self.deleted = sizes, []

    def is_available(self):
        return True

    def installed(self):
        return dict(self.sizes)

    def delete_model(self, name):
        self.deleted.append(name)


class _FakeLMStudio:
    name = "lmstudio"

    def __init__(self, entries):
        self.entries = entries

    def downloaded(self):
        return self.entries


class TestPurge(unittest.TestCase):
    def setUp(self):
        self.repl = _Repl()
        self.ollama = _FakeOllama({"qwen3:8b": 5 * GB, "llama3:8b": 4 * GB})
        self.repl.registry = {"ollama": self.ollama, "lmstudio": _FakeLMStudio([])}
        self.repl.provider, self.repl.model = self.ollama, "llama3:8b"

    def _purge(self, arg, answer=True):
        with patch.object(local_models.Confirm, "ask", return_value=answer) as ask:
            local_models.purge(self.repl, arg)
        return ask

    def test_no_name_deletes_every_model(self):
        self._purge("")
        self.assertEqual(sorted(self.ollama.deleted), ["llama3:8b", "qwen3:8b"])
        self.assertIn("active model", self.repl.console.export_text())

    def test_a_name_deletes_only_matches(self):
        self._purge(" QWEN")
        self.assertEqual(self.ollama.deleted, ["qwen3:8b"])

    def test_declining_deletes_nothing_and_defaults_to_no(self):
        ask = self._purge("", answer=False)
        self.assertEqual(self.ollama.deleted, [])
        self.assertFalse(ask.call_args.kwargs["default"])

    def test_no_match_asks_nothing(self):
        ask = self._purge("mistral")
        ask.assert_not_called()
        self.assertIn("No local model matches", self.repl.console.export_text())

    def test_lmstudio_files_are_removed_and_unlocatable_models_skipped(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "pub" / "repo").mkdir(parents=True)
            (root / "pub" / "repo" / "m.gguf").write_text("x")
            self.repl.registry["lmstudio"] = _FakeLMStudio([
                {"modelKey": "repo", "path": "pub/repo", "sizeBytes": GB},
                {"modelKey": "alias", "path": "qwen/alias", "sizeBytes": GB},
                {"modelKey": "escape", "path": "../outside", "sizeBytes": GB},
            ])
            with patch("src.providers.lmstudio.MODELS_DIR", root):
                self._purge("lmstudio")
            self.assertFalse((root / "pub" / "repo").exists())
        shown = self.repl.console.export_text()
        self.assertIn("Deleted lmstudio:repo", shown)
        self.assertEqual(shown.count("skipped"), 2)


class TestSetUpRunner(unittest.TestCase):
    """A missing Ollama or LM Studio is installed only after a yes, then the download goes on."""

    def setUp(self):
        self.repl = _Repl()
        self.repl.registry = {"ollama": _Ollama(False)}
        self.run = self._patch(local_models.subprocess, "run", return_value=type("Done", (), {"returncode": 0})())
        self._patch(local_models.sys, "platform", "darwin")
        self._patch(local_models, "_lms", return_value=None)

    def _patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs) if args or kwargs else patch.object(target, name)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _which(self, installed):
        return self._patch(local_models.shutil, "which", side_effect=lambda exe: f"/bin/{exe}" if exe in installed else None)

    def test_declining_installs_nothing(self):
        self._which({"brew"})
        with patch.object(local_models.Confirm, "ask", return_value=False) as ask:
            self.assertIsNone(local_models._set_up_runner(self.repl, RELAX))
        self.run.assert_not_called()
        self.assertFalse(ask.call_args.kwargs["default"])
        self.assertIn("brew install ollama", ask.call_args.args[0])
        self.assertIn("need Ollama", self.repl.console.export_text())

    def test_yes_installs_starts_and_returns_the_runner(self):
        self._which({"brew"})
        up = self._patch(local_models, "_start_ollama", return_value=True)
        with patch.object(local_models.Confirm, "ask", return_value=True), \
                patch.object(local_models, "_runner", return_value="ollama"):
            self.assertEqual(local_models._set_up_runner(self.repl, RELAX), "ollama")
        self.assertEqual(self.run.call_args.args[0], ["brew", "install", "ollama"])
        up.assert_called_once()

    def test_a_failed_install_stops_there(self):
        self._which({"brew"})
        self.run.return_value.returncode = 1
        up = self._patch(local_models, "_start_ollama")
        with patch.object(local_models.Confirm, "ask", return_value=True):
            self.assertIsNone(local_models._set_up_runner(self.repl, RELAX))
        up.assert_not_called()
        self.assertIn("failed", self.repl.console.export_text())

    def test_installed_but_not_running_only_starts_it(self):
        self._which({"ollama"})
        up = self._patch(local_models, "_start_ollama", return_value=True)
        with patch.object(local_models.Confirm, "ask", return_value=True) as ask, \
                patch.object(local_models, "_runner", return_value="ollama"):
            self.assertEqual(local_models._set_up_runner(self.repl, RELAX), "ollama")
        self.run.assert_not_called()
        self.assertIn("ollama serve", ask.call_args.args[0])
        up.assert_called_once()

    def test_mlx_without_omlx_installs_nothing_else(self):
        self._which({"brew"})
        with patch.object(local_models.Confirm, "ask") as ask:
            self.assertIsNone(local_models._set_up_runner(self.repl, MLX))
        ask.assert_not_called()
        self.run.assert_not_called()

    def test_no_way_to_install_asks_nothing(self):
        self._which(set())   # no brew
        with patch.object(local_models.Confirm, "ask") as ask:
            self.assertIsNone(local_models._set_up_runner(self.repl, RELAX))
        ask.assert_not_called()
        self.run.assert_not_called()
        self.assertIn("need Ollama", self.repl.console.export_text())

    def test_show_sets_up_a_missing_runner_then_downloads(self):
        with patch.object(local_models.fit, "chip", return_value="Apple M3"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"ollama": lambda q, b: [RELAX]}), \
                patch.object(local_models, "pick", return_value="0"), \
                patch.object(local_models, "_runner", return_value=None), \
                patch.object(local_models, "_set_up_runner", return_value="ollama") as setup, \
                patch.object(local_models, "_confirm", return_value=True), \
                patch.object(local_models, "_pull_ollama") as pull:
            local_models.show(self.repl, " ollama")
        setup.assert_called_once()
        pull.assert_called_once()


_Q4 = Offer("u/m", "hf.co/u/m:Q4_K_M", 5 * GB, "balance", 5, "Q4_K_M", "hf")
_Q8 = Offer("u/m", "hf.co/u/m:Q8_0", 8 * GB, "balance", 5, "Q8_0", "hf")
_F16 = Offer("u/m", "hf.co/u/m:F16", 30 * GB, "too large", 5, "F16", "hf")
_MLX4 = Offer("mlx-community/m-4bit", "https://huggingface.co/mlx-community/m-4bit", 4 * GB, "relax", 2, "MLX 4-bit", "mlx")


class TestDownloadOptions(unittest.TestCase):
    """A model row opens a second picker with every quantization and format of that model."""

    def setUp(self):
        self.row = Offer("u/m", _Q8.pull_tag, 8 * GB, "balance", 5, "Q8_0", "hf", options=(_Q4, _Q8, _F16, _MLX4))

    def _show(self, *rest, runner="ollama", details=None, opened=None):
        """Run /models local with the picker answering "0" (the model row), then `rest` in turn."""
        repl = _Repl()
        with patch.object(local_models.fit, "chip", return_value="Apple M3 Pro"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"hf": lambda q, b: [self.row]}), \
                patch.object(local_models, "hidden_refs", return_value=set()), \
                patch.object(local_models.huggingface, "details", return_value=details), \
                patch.object(local_models.huggingface, "gguf_offer", return_value=opened), \
                patch.object(local_models, "pick", side_effect=["0", *rest]) as pick, \
                patch.object(local_models, "_runner", return_value=runner), \
                patch.object(local_models, "_confirm", return_value=True) as confirm, \
                patch.object(local_models, "_pull_ollama") as pull, \
                patch.object(local_models, "_get_lmstudio") as lms:
            local_models.show(repl, " hf")
        self.repl = repl
        return repl, pick, confirm, pull, lms

    def _details(self, **over):
        updated = (datetime.now(timezone.utc) - timedelta(days=13)).isoformat()
        base = dict(author="IFM", original="", downloads=35214, likes=76, updated=updated, params=8_999_178_240, arch="k2-horizon",
                    context=524288, license="apache-2.0", summary="A dense open-weights model tuned for long documents.",
                    tools=True, vision=False, reasoning=False, related=(("IFM/K2-0.9B-GGUF", 25809, 97),))
        return Details(**{**base, **over})

    def test_the_page_shows_the_numbers_description_specs_and_capabilities(self):
        repl, *_ = self._show("0", details=self._details())
        text = repl.console.export_text()
        for expected in ("u/m", "35K", "76", "13 days ago", "apache-2.0", "A dense open-weights model tuned for long documents.",
                         "9.0B", "k2-horizon", "512K", "GGUF", "MLX", "Tool use ✓", "Vision –", "Reasoning –"):
            self.assertIn(expected, text)

    def test_unknown_capabilities_are_marked_unknown_not_absent(self):
        repl, *_ = self._show("0", details=self._details(tools=None, params=None, context=None, summary=""))
        self.assertIn("Tool use ?", repl.console.export_text())

    def test_the_options_picker_ends_with_other_models_by_the_same_author(self):
        _, pick, *_ = self._show("0", details=self._details())
        args, _ = pick.call_args_list[1]
        more = [c for c in args[2] if c.value.startswith("more:")]
        self.assertEqual([(c.value, c.label) for c in more], [("more:IFM/K2-0.9B-GGUF", "IFM/K2-0.9B-GGUF")])
        self.assertIn("more from IFM", more[0].hint)
        self.assertIn("26K", more[0].hint)
        self.assertEqual(args[2][-1].value, "more:IFM/K2-0.9B-GGUF")

    def test_choosing_another_model_opens_its_page_and_downloads_from_there(self):
        small = Offer("IFM/K2-0.9B-GGUF", "hf.co/IFM/K2-0.9B-GGUF:Q8_0", 1 * GB, "relax", 9, "Q8_0", "hf",
                      options=(Offer("IFM/K2-0.9B-GGUF", "hf.co/IFM/K2-0.9B-GGUF:Q4_K_M", GB // 2, "relax", 9, "Q4_K_M", "hf"),
                               Offer("IFM/K2-0.9B-GGUF", "hf.co/IFM/K2-0.9B-GGUF:Q8_0", 1 * GB, "relax", 9, "Q8_0", "hf")))
        _, pick, _, pull, _ = self._show("more:IFM/K2-0.9B-GGUF", "0", details=self._details(), opened=small)
        self.assertEqual(pull.call_args.args[1].pull_tag, "hf.co/IFM/K2-0.9B-GGUF:Q4_K_M")
        self.assertIn("IFM/K2-0.9B-GGUF", pick.call_args_list[2].args[1])

    def test_another_model_with_nothing_that_fits_says_so_and_stays_on_the_current_page(self):
        repl, _, _, pull, _ = self._show("more:IFM/K2-0.9B-GGUF", "0", details=self._details(), opened=None)
        text = repl.console.export_text()
        self.assertIn("Nothing from IFM/K2-0.9B-GGUF fits", text)
        self.assertEqual(pull.call_args.args[1].pull_tag, _Q4.pull_tag)

    def test_without_details_the_options_picker_still_works_and_no_page_is_printed(self):
        repl, pick, _, pull, _ = self._show("0", details=None)
        self.assertEqual(pull.call_args.args[1].pull_tag, _Q4.pull_tag)
        self.assertNotIn("PARAMS", repl.console.export_text())

    def test_a_single_download_with_nothing_related_goes_straight_to_confirm(self):
        self.row = replace(self.row, options=())
        _, pick, confirm, pull, _ = self._show(details=self._details(related=()))
        self.assertEqual(pick.call_count, 1)
        confirm.assert_called_once()

    def test_a_row_is_named_after_the_original_model_and_says_who_it_comes_from(self):
        row = replace(self.row, name="lmstudio-community/K2-7B-GGUF", model="IFM/K2-7B")
        header, (choice,) = local_models._table([row], "Apple M3 Pro", 200)
        self.assertEqual(choice.label, "IFM/K2-7B")
        self.assertEqual(choice.hint.index("lmstudio-community"), header[1].index("VIA"))   # the publisher sits in the VIA column
        (plain,) = local_models._choices([self.row], "Apple M3 Pro")
        self.assertEqual(plain.label, "u/m")
        self.assertNotIn("lmstudio-community", plain.hint)

    def test_the_page_is_titled_with_the_original_model_and_names_the_repo_it_downloads_from(self):
        repl, pick, *_ = self._show("0", details=self._details(original="IFM/K2-7B"))
        text = repl.console.export_text()
        self.assertIn("IFM/K2-7B", text)
        self.assertIn("via u/m", text)
        self.assertIn("IFM/K2-7B", pick.call_args_list[1].args[1])

    def test_the_search_is_a_table_with_labelled_aligned_columns(self):
        slow = Offer("big/Model-70B-GGUF", "hf.co/big/Model-70B-GGUF:Q4_K_M", 40 * GB, "hard", 1_500_000, "Q4_K_M", "hf")
        header, rows = local_models._table([self.row, slow], "Apple M3 Pro", 200)
        self.assertEqual(header[0], "MODEL")
        for label in ("FIT", "FORMAT", "SIZE", "TOK/S", "PULLS", "QUANT", "OPTIONS"):
            self.assertIn(label, header[1])
        first, second = rows
        self.assertEqual((first.label, second.label), ("u/m", "big/Model-70B-GGUF"))
        for cell in ("balance", "GGUF", "8.0 GB", "5", "Q8_0", "4"):
            self.assertIn(cell, first.hint)
        self.assertIn("(slow)", second.hint)
        self.assertIn("1.5M", second.hint)
        self.assertEqual(first.hint.index("balance"), header[1].index("FIT"))        # each title sits over its column's cells
        self.assertEqual(second.hint.index("hard"), header[1].index("FIT"))
        self.assertEqual(first.hint.index("GGUF"), header[1].index("FORMAT"))
        self.assertEqual(second.hint.index("1.5M"), header[1].index("PULLS"))
        self.assertEqual(len(first.hint), len(second.hint))

    def test_a_narrow_terminal_drops_the_right_hand_columns_instead_of_wrapping(self):
        wide_header, _ = local_models._table([self.row], "Apple M3 Pro", 200)
        narrow_header, narrow_rows = local_models._table([self.row], "Apple M3 Pro", 70)
        self.assertIn("VIA", wide_header[1])
        self.assertNotIn("VIA", narrow_header[1])
        self.assertIn("FIT", narrow_header[1])
        self.assertLessEqual(len(narrow_rows[0].label) + len(narrow_rows[0].hint) + 8, 70)

    def test_the_search_picker_gets_the_table_header(self):
        _, pick, *_ = self._show("0", details=None)
        self.assertEqual(pick.call_args_list[0].kwargs["header"][0], "MODEL")

    def test_the_model_row_says_how_many_options_it_has(self):
        (row,) = local_models._choices([self.row], "Apple M3 Pro")
        self.assertEqual(row.hint.split()[-1], "4")      # the OPTIONS cell; this row has no "via" after it

    def test_the_chosen_option_is_what_gets_confirmed_and_downloaded(self):
        _, _, confirm, pull, _ = self._show("0")
        self.assertEqual(confirm.call_args.args[1].pull_tag, _Q4.pull_tag)
        self.assertEqual(pull.call_args.args[1].pull_tag, _Q4.pull_tag)

    def test_the_option_picker_names_format_quant_size_fit_and_marks_the_recommendation(self):
        _, pick, _, _, _ = self._show("0")
        args, kwargs = pick.call_args_list[1]
        labels = {c.value: c for c in args[2]}
        self.assertIn("u/m", args[1])
        self.assertEqual(kwargs["current"], "1")    # the row's own pick, the Q8_0 option
        self.assertIn("GGUF", labels["0"].label)
        self.assertIn("Q4_K_M", labels["0"].label)
        self.assertIn("recommended", labels["1"].label)
        self.assertIn("5.0 GB", labels["0"].hint)
        self.assertIn("too large", labels["2"].hint)
        self.assertIn("MLX", labels["3"].label)

    def test_the_options_picker_is_a_table_with_titles_over_aligned_columns_and_the_related_rows_inside_it(self):
        _, pick, *_ = self._show("0", details=self._details())
        args, kwargs = pick.call_args_list[1]
        title, columns = kwargs["header"]
        self.assertEqual(title, "OPTION")
        for name in ("FIT", "SIZE", "TOK/S", "QUALITY", "FROM"):
            self.assertIn(name, columns)
        rows = {c.value: c for c in args[2]}
        self.assertEqual(rows["0"].hint.index("balance"), columns.index("FIT"))          # Q4_K_M
        self.assertEqual(rows["2"].hint.index("too large"), columns.index("FIT"))        # F16
        self.assertEqual(rows["0"].hint.index("5.0 GB"), columns.index("SIZE"))
        self.assertEqual(rows["0"].hint.index("u/m"), columns.index("FROM"))             # the repo the download comes from
        self.assertEqual(rows["more:IFM/K2-0.9B-GGUF"].hint.index("more from IFM"), columns.index("FROM"))
        self.assertEqual(len({len(c.hint) for c in args[2]}), 1)                         # every row padded to the same width

    def test_a_narrow_terminal_drops_the_options_tables_right_hand_columns(self):
        repl = _Repl()
        repl.console = Console(record=True, width=60)
        with patch.object(local_models.fit, "chip", return_value="Apple M3 Pro"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models.huggingface, "details", return_value=None), \
                patch.object(local_models, "pick", return_value=None) as pick:
            local_models._choose_option(repl, self.row, "Apple M3 Pro")
        columns = pick.call_args.kwargs["header"][1]
        self.assertIn("FIT", columns)
        self.assertNotIn("FROM", columns)

    def test_a_too_large_option_is_refused_and_nothing_downloads(self):
        repl, _, confirm, pull, lms = self._show("2")
        confirm.assert_not_called()
        pull.assert_not_called()
        lms.assert_not_called()
        self.assertIn("Too large: u/m F16 is 30.0 GB", repl.console.export_text())

    def test_cancelling_the_option_picker_downloads_nothing(self):
        _, _, confirm, pull, _ = self._show(None)
        confirm.assert_not_called()
        pull.assert_not_called()

    def test_an_mlx_option_is_downloaded_through_the_app_that_runs_it(self):
        _, _, _, pull, lms = self._show("3", runner="lmstudio")
        pull.assert_not_called()
        self.assertEqual(lms.call_args.args[1].pull_tag, _MLX4.pull_tag)

    def test_a_row_without_options_skips_the_second_picker(self):
        repl = _Repl()
        with patch.object(local_models.fit, "chip", return_value="Apple M3 Pro"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"ollama": lambda q, b: [RELAX]}), \
                patch.object(local_models, "hidden_refs", return_value=set()), \
                patch.object(local_models, "pick", return_value="0") as pick, \
                patch.object(local_models, "_runner", return_value="ollama"), \
                patch.object(local_models, "_confirm", return_value=False):
            local_models.show(repl, " ollama")
        self.assertEqual(pick.call_count, 1)


class TestResultOrder(unittest.TestCase):
    """Heavily compressed quants go below usable ones; slow rows go last among the rest."""

    def _search(self, offers):
        repl = _Repl()
        with patch.object(local_models.fit, "chip", return_value="Apple M3 Pro"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"hf": lambda q, b: offers}), \
                patch.object(local_models, "hidden_refs", return_value=set()), \
                patch.object(local_models.huggingface, "details", return_value=None), \
                patch.object(local_models, "pick", return_value=None) as pick:
            local_models.show(repl, " hf")
        return [c.label for c in pick.call_args.args[2]], repl.console.export_text()

    def test_a_two_bit_quant_does_not_outrank_a_usable_one_even_when_it_is_faster(self):
        official = Offer("lmstudio-community/Big-14B-GGUF", "hf.co/lmstudio-community/Big-14B-GGUF:Q4_K_M", 7 * GB, "balance", 9, "Q4_K_M", "hf")   # ~slow
        squeezed = Offer("x/Big-14B-DASHQ-Q2-GGUF", "hf.co/x/Big-14B-DASHQ-Q2-GGUF:IQ2_M", 4 * GB, "relax", 99, "IQ2_M", "hf")                   # fast, lossy
        fast = Offer("y/Small-3B-GGUF", "hf.co/y/Small-3B-GGUF:Q4_K_M", 2 * GB, "relax", 1, "Q4_K_M", "hf")
        labels, text = self._search([squeezed, official, fast])
        self.assertEqual(labels, ["y/Small-3B-GGUF", "lmstudio-community/Big-14B-GGUF", "x/Big-14B-DASHQ-Q2-GGUF"])
        self.assertIn("1 listed last: a 2-bit or lower quantization", text)

    def test_nothing_is_said_when_no_row_is_that_compressed(self):
        _, text = self._search([Offer("y/Small-3B-GGUF", "hf.co/y/Small-3B-GGUF:Q4_K_M", 2 * GB, "relax", 1, "Q4_K_M", "hf")])
        self.assertNotIn("2-bit", text)


class TestSpeedFloor(unittest.TestCase):
    def test_slow_models_are_listed_last_with_the_rest_in_order(self):
        repl = _Repl()
        fast = Offer("fast", "fast:3b", 2 * GB, "relax", 1, "est. Q4", "ollama")
        slow = Offer("slow", "slow:70b", 40 * GB, "hard", 9, "est. Q4", "ollama")
        fast2 = Offer("fast2", "fast2:7b", 4 * GB, "relax", 1, "est. Q4", "ollama")
        with patch.object(local_models.fit, "chip", return_value="Apple M3 Pro"), \
                patch.object(local_models.fit, "budget_bytes", return_value=48 * GB), \
                patch.object(local_models, "SOURCES", {"ollama": lambda q, b: [slow, fast, fast2]}), \
                patch.object(local_models, "hidden_refs", return_value=set()), \
                patch.object(local_models, "pick", return_value=None) as pick:
            local_models.show(repl, " ollama")
        self.assertEqual([c.label for c in pick.call_args.args[2]], ["fast", "fast2", "slow"])
        self.assertIn("(slow)", pick.call_args.args[2][2].hint)
        self.assertIn("1 listed last", repl.console.export_text())


class TestLmStudioToolWarning(unittest.TestCase):
    def _show(self, runner):
        repl = _Repl()
        with patch.object(local_models.fit, "chip", return_value="Apple M3"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"hf": lambda q, b: [GGUF]}), \
                patch.object(local_models, "pick", return_value="0"), \
                patch.object(local_models, "_runner", return_value=runner), \
                patch.object(local_models, "_confirm", return_value=False):
            local_models.show(repl, " hf")
        return repl.console.export_text()

    def test_an_lm_studio_download_warns_that_tool_use_is_unconfirmed(self):
        self.assertIn("Tool use isn't confirmed", self._show("lmstudio"))

    def test_an_ollama_download_does_not(self):
        self.assertNotIn("Tool use isn't confirmed", self._show("ollama"))


class TestFailedEvalHidden(unittest.TestCase):
    def test_a_model_that_failed_eval_is_not_listed_again(self):
        repl = _Repl()
        with patch.object(local_models.fit, "chip", return_value="Apple M3"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"ollama": lambda q, b: [RELAX, HARD]}), \
                patch.object(local_models, "hidden_refs", return_value={"ollama:small:3b"}), \
                patch.object(local_models, "pick", return_value=None) as pick:
            local_models.show(repl, " ollama")
        self.assertEqual([c.label for c in pick.call_args.args[2]], ["big"])
        self.assertIn("1 hidden", repl.console.export_text())


    def test_a_failed_hugging_face_offer_is_hidden_whatever_the_case(self):
        repl = _Repl()
        hf = Offer("Q", "hf.co/Bart/Qwen3-GGUF:Q4_K_M", 5 * GB, "relax", 1, "Q4_K_M", "hf")
        with patch.object(local_models.fit, "chip", return_value="Apple M3"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"hf": lambda q, b: [hf]}), \
                patch.object(local_models, "hidden_refs", return_value={"ollama:hf.co/bart/qwen3-gguf:q4_k_m"}), \
                patch.object(local_models, "pick", return_value=None) as pick:
            local_models.show(repl, " hf")
        pick.assert_not_called()


    def test_a_failed_lm_studio_model_is_hidden_by_its_folder_not_its_key(self):
        class _LMStudio:
            def downloaded(self):
                return [{"modelKey": "coder-4bit", "path": "mlx-community/Coder-4bit"},
                        {"modelKey": "coder-q4", "path": "u/Coder/Coder.Q4_K_M.gguf"},
                        {"modelKey": "other", "path": "x/Other"}]
        repl = _Repl()
        repl.registry["lmstudio"] = _LMStudio()
        other_quant = Offer("u/coder", "hf.co/u/coder:Q8_0", 5 * GB, "balance", 1, "Q8_0", "hf")
        with patch.object(local_models.fit, "chip", return_value="Apple M3"), \
                patch.object(local_models.fit, "budget_bytes", return_value=12 * GB), \
                patch.object(local_models, "SOURCES", {"hf": lambda q, b: [GGUF, other_quant, MLX]}), \
                patch.object(local_models, "hidden_refs", return_value={"lmstudio:coder-4bit", "lmstudio:coder-q4"}), \
                patch.object(local_models, "pick", return_value=None) as pick:
            local_models.show(repl, " hf")
        self.assertEqual([c.label for c in pick.call_args.args[2]], ["u/coder"])
        self.assertIn("2 hidden", repl.console.export_text())


class TestTuneAfterDownload(unittest.TestCase):
    def _pull(self, events):
        repl = _Repl()
        repl.registry = {"ollama": type("O", (), {"host": "http://h", "name": "ollama"})()}
        with patch.object(local_models, "post_stream", return_value=events), \
                patch.object(local_models, "_offer_eval"), \
                patch.object(local_models.tune, "offer") as offer:
            local_models._pull_ollama(repl, RELAX)
        return offer

    def test_a_finished_download_offers_to_tune_that_model(self):
        offer = self._pull(['{"status": "success"}'])
        offer.assert_called_once()
        self.assertEqual(offer.call_args.kwargs["model"], "small:3b")

    def test_a_failed_download_offers_nothing(self):
        self._pull(['{"error": "boom"}']).assert_not_called()


class TestStoppedEval(unittest.TestCase):
    def _provider(self):
        return type("P", (), {"name": "lmstudio", "unloaded": [], "unload": lambda self, m: self.unloaded.append(m)})()

    def test_ctrl_c_during_the_offered_eval_unloads_the_model_and_saves_nothing(self):
        repl, provider = _Repl(), self._provider()
        with patch.object(local_models.Confirm, "ask", return_value=True), \
                patch.object(local_models.fit, "free_now_bytes", return_value=20 * GB), \
                patch.object(local_models, "evaluate", side_effect=KeyboardInterrupt), \
                patch.object(local_models, "save_results") as save:
            local_models._offer_eval(repl, provider, "deepseek", RELAX)
        self.assertEqual(provider.unloaded, ["deepseek"])
        save.assert_not_called()
        self.assertIn("Eval stopped", repl.console.export_text())

    def test_a_provider_that_cannot_unload_is_left_alone(self):
        repl = _Repl()
        local_models.stop_eval(repl.console, [(type("O", (), {"name": "ollama"})(), "m")])
        self.assertIn("Eval stopped", repl.console.export_text())

    def test_a_model_that_does_not_fit_the_free_memory_warns_and_defaults_to_no(self):
        repl = _Repl()
        with patch.object(local_models.fit, "free_now_bytes", return_value=3 * GB), \
                patch.object(local_models.Confirm, "ask", return_value=False) as ask:
            local_models._offer_eval(repl, self._provider(), "deepseek", MLX)
        self.assertIn("Not enough free memory", repl.console.export_text())
        self.assertFalse(ask.call_args.kwargs["default"])

    def test_a_model_that_fits_does_not_warn(self):
        repl = _Repl()
        with patch.object(local_models.fit, "free_now_bytes", return_value=20 * GB), \
                patch.object(local_models.Confirm, "ask", return_value=False) as ask:
            local_models._offer_eval(repl, self._provider(), "deepseek", RELAX)
        self.assertNotIn("Not enough", repl.console.export_text())
        self.assertTrue(ask.call_args.kwargs["default"])


class TestShortOnMemory(unittest.TestCase):
    def test_it_warns_only_when_the_model_does_not_fit_the_free_memory(self):
        repl = _Repl()
        with patch.object(local_models.fit, "free_now_bytes", return_value=3 * GB):
            self.assertTrue(local_models.short_on_memory(repl.console, 4 * GB, "/eval"))
            self.assertFalse(local_models.short_on_memory(repl.console, 1 * GB, "/eval"))
        self.assertEqual(repl.console.export_text().count("Not enough free memory"), 1)

    def test_an_unreadable_memory_figure_never_warns(self):
        with patch.object(local_models.fit, "free_now_bytes", return_value=None):
            self.assertFalse(local_models.short_on_memory(_Repl().console, 99 * GB, "/eval"))


class TestLoadedBytes(unittest.TestCase):
    def test_the_runtimes_own_estimate_wins_over_the_flat_allowance(self):
        lmstudio = type("L", (), {"estimate": lambda self, m: 6 * GB})()
        self.assertEqual(local_models.loaded_bytes(lmstudio, "m", 4 * GB), 6 * GB)

    def test_without_an_estimate_it_is_the_file_plus_the_allowance(self):
        ollama = type("O", (), {})()
        self.assertEqual(local_models.loaded_bytes(ollama, "m", 4 * GB), 4 * GB + local_models.fit.OVERHEAD)
        unsure = type("L", (), {"estimate": lambda self, m: None})()
        self.assertEqual(local_models.loaded_bytes(unsure, "m", 4 * GB), 4 * GB + local_models.fit.OVERHEAD)


class TestQuantHint(unittest.TestCase):
    def test_a_quant_note_gets_its_quality_in_words(self):
        for note, hint in (("Q4_K_M", "good balance"), ("est. Q4", "good balance"), ("MLX 4-bit", "good balance"),
                           ("Q8_0", "near lossless"), ("F16", "lossless"), ("BF16", "lossless"), ("Q2_K", "noticeable loss")):
            self.assertEqual(local_models.fit.quant_hint(note), hint, note)

    def test_iquants_get_their_quality_too(self):
        for note, hint in (("IQ2_M", "noticeable loss"), ("IQ1_S", "heavy loss"), ("IQ3_XS", "some loss"), ("IQ4_XS", "good balance"),
                           ("Q2_K_XL", "noticeable loss")):
            self.assertEqual(local_models.fit.quant_hint(note), hint, note)

    def test_a_note_with_no_quant_gets_no_hint(self):
        self.assertEqual(local_models.fit.quant_hint(""), "")
        self.assertEqual(local_models._quant("instruct"), "instruct")

    def test_the_picker_row_shows_it(self):
        self.assertIn("Q4_K_M (good balance)", local_models._choices([GGUF], "")[0].hint)


class TestOfferDetails(unittest.TestCase):
    def _summary(self, offer):
        repl = _Repl()
        with patch.object(local_models.fit, "disk_free_bytes", return_value=50 * GB), \
                patch.object(local_models.fit, "free_now_bytes", return_value=20 * GB), \
                patch.object(local_models.Confirm, "ask", return_value=False):
            local_models._confirm(repl, offer, 12 * GB, "Apple M3 Pro")
        return repl.console.export_text()

    def test_a_ranked_offer_shows_its_details_and_credits_whichllm(self):
        text = self._summary(Offer("Qwen/Qwen3-8B", "hf.co/r/q:Q4_K_M", 5 * GB, "relax", 1, "Q4_K_M", "hf", "quality 62 (direct benchmark)"))
        self.assertIn("details    quality 62 (direct benchmark)  [ranked by whichllm]", text)

    def test_an_offer_without_details_shows_no_details_line(self):
        self.assertNotIn("details", self._summary(RELAX))
