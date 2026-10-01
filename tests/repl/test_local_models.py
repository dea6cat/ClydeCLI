"""/models local: nothing is pulled or loaded without an informed yes."""

from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest.mock import patch

from rich.console import Console

from src.providers.fit import GB, Offer
from src.repl import local_models

HARD = Offer("big", "big:30b", 10 * GB, "hard", 1, "est. Q4")
RELAX = Offer("small", "small:3b", 2 * GB, "relax", 1, "est. Q4")


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
                patch.object(local_models.Prompt, "ask", return_value="1"), \
                patch.object(local_models.Confirm, "ask", return_value=False), \
                patch.object(local_models, "pull") as pull:
            local_models.show(self.repl, " ollama coder")
        pull.assert_not_called()

    def _searched(self, arg: str) -> dict[str, str]:
        """Which sources show() searched for `arg`, and with what query."""
        seen: dict[str, str] = {}
        sources = {name: (lambda q, b, name=name: seen.__setitem__(name, q) or []) for name in ("ollama", "hf")}
        with patch.object(local_models, "SOURCES", sources):
            local_models.show(self.repl, arg)
        return seen

    def test_bare_command_searches_both_sources_with_no_query(self):
        self.assertEqual(self._searched(""), {"ollama": "", "hf": ""})

    def test_words_search_both_and_a_source_name_narrows_to_it(self):
        self.assertEqual(self._searched(" qwen coder"), {"ollama": "qwen coder", "hf": "qwen coder"})
        self.assertEqual(self._searched(" hf qwen"), {"hf": "qwen"})


if __name__ == "__main__":
    unittest.main()
