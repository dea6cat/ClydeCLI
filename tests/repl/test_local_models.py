"""/models local: nothing is pulled or loaded without an informed yes."""

from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest.mock import patch

from rich.console import Console

from src.providers.fit import GB, Offer
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
    def _runner(self, offer, ollama_up: bool, lms: bool):
        repl = _Repl()
        repl.registry = {"ollama": _Ollama(ollama_up)}
        with patch.object(local_models, "_lms", return_value="/bin/lms" if lms else None):
            return local_models._runner(repl, offer)

    def test_each_model_goes_to_the_app_that_runs_it(self):
        self.assertEqual(self._runner(MLX, ollama_up=True, lms=True), "lmstudio")    # MLX: LM Studio only
        self.assertIsNone(self._runner(MLX, ollama_up=True, lms=False))
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

    def test_mlx_installs_lm_studio_as_a_cask(self):
        self._which({"brew"})
        self._patch(local_models, "_start_lmstudio", return_value=True)
        with patch.object(local_models.Confirm, "ask", return_value=True), \
                patch.object(local_models, "_runner", return_value="lmstudio"):
            self.assertEqual(local_models._set_up_runner(self.repl, MLX), "lmstudio")
        self.assertEqual(self.run.call_args.args[0], ["brew", "install", "--cask", "lm-studio"])

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
