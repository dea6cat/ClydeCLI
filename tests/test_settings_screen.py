"""/settings: the four tabs and the keys that drive them."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from src import config, settings_screen
from src import usage_stats as stats

RIGHT, ESC, TAB, DOWN = "\x1b[C", "\x1b", "\t", "\x1b[B"
TODAY = date(2026, 10, 13)
SNAP = settings_screen.Snapshot([("Version", "1.0"), ("Model", "ollama:m")], ["Total cost: free or unpriced"], [("ecc", 3, 120)])
REQS = [stats.Request(TODAY, "ollama:m", stats.Totals(100, 20, 0, 0)), stats.Request(TODAY, "lmstudio:q", stats.Totals(50, 5, 0, 0))]


def _text(fragments) -> str:
    return "".join(t for _, t in fragments)


def _state(**kw):
    return {"tab": 0, "sub": 0, "range": "all", "cursor": 0, "top": 0, "query": "", "note": "", **kw}


class TestSettingsScreen(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        for p in (patch.dict(os.environ, {"XDG_CONFIG_HOME": "", "HOME": home}), patch.object(Path, "home", return_value=Path(home))):
            p.start()
            self.addCleanup(p.stop)

    def test_each_tab_shows_its_content(self):
        shown = lambda **kw: _text(settings_screen.render(_state(**kw), SNAP, REQS, [], TODAY))  # noqa: E731
        self.assertIn("Version:", shown())
        self.assertIn("Auto-save sessions", shown(tab=1))
        self.assertIn("~120 tok/turn", shown(tab=2))
        self.assertIn("Favorite model:", shown(tab=3))
        self.assertIn("ollama:m", shown(tab=3, sub=1))
        self.assertIn("No traced model requests", _text(settings_screen.render(_state(tab=3, sub=1), SNAP, [], [], TODAY)))

    def test_config_search_narrows_the_rows(self):
        self.assertEqual([s.label for s in settings_screen.visible_settings("channel")], ["Update channel"])

    def test_space_changes_the_highlighted_setting_and_saves_it(self):
        with create_pipe_input() as pipe:
            pipe.send_text(RIGHT + " " + ESC)
            settings_screen.show(SNAP, input=pipe, output=DummyOutput(), today=TODAY)
        self.assertIs(config.load_config()["session"]["auto_save"], False)

    def test_typing_on_config_picks_a_setting_to_change(self):
        with create_pipe_input() as pipe:
            pipe.send_text(RIGHT + "chan" + " " + ESC)
            settings_screen.show(SNAP, input=pipe, output=DummyOutput(), today=TODAY)
        self.assertEqual(config.get_update_channel(), "stable")

    def test_stats_keys_flip_the_view_and_range_without_touching_settings(self):
        with create_pipe_input() as pipe:
            pipe.send_text(RIGHT * 3 + TAB + "r" + DOWN + ESC)
            settings_screen.show(SNAP, input=pipe, output=DummyOutput(), today=TODAY)
        self.assertEqual(config.load_config()["session"], {"auto_save": True, "max_history": 100})

    def test_session_usage_prices_each_model_and_reports_the_cache(self):
        lines = settings_screen.session_usage({"ollama:m": {"input_tokens": 10, "output_tokens": 2},
                                               "x:y": {"input_tokens": 100, "cache_read_input_tokens": 300}})
        text = "\n".join(lines)
        self.assertIn("ollama:m: 10 in, 2 out", text)
        self.assertIn("Prompt cache: 73%", text)
        self.assertEqual(settings_screen.session_usage({}), ["No model requests yet in this session."])


if __name__ == "__main__":
    unittest.main()
