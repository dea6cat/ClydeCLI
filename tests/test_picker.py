"""The arrow-key picker: filtering, scrolling, rendering, and the real key handling over a pipe."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from rich.console import Console

from src import picker
from src.picker import Choice, narrow, pick, render, scroll

CHOICES = [Choice("a", "alpha", "first"), Choice("b", "beta", "second"), Choice("c", "gamma", "third")]
MANY = [Choice(str(i), f"model-{i}") for i in range(20)]

try:
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
except ImportError:   # the picker falls back to a numbered question without prompt_toolkit
    create_pipe_input = None

DOWN, UP, ENTER, CTRL_C = "\x1b[B", "\x1b[A", "\r", "\x03"


def _drive(keys: str, choices=CHOICES, **kwargs):
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        return pick(Console(file=io.StringIO()), "Pick", choices, input=pipe, output=DummyOutput(), **kwargs)


class TestPureParts(unittest.TestCase):
    def test_narrow_matches_every_word_in_label_hint_or_value(self):
        self.assertEqual([c.value for c in narrow(CHOICES, "BET")], ["b"])
        self.assertEqual([c.value for c in narrow(CHOICES, "a second")], ["b"])   # words may hit different fields
        self.assertEqual(narrow(CHOICES, "zzz"), [])
        self.assertEqual(narrow(CHOICES, ""), CHOICES)

    def test_scroll_keeps_the_cursor_in_the_window(self):
        self.assertEqual(scroll(0, 0, 20, 8), 0)
        self.assertEqual(scroll(0, 9, 20, 8), 2)      # moved past the bottom: window follows
        self.assertEqual(scroll(5, 3, 20, 8), 3)      # moved above the top
        self.assertEqual(scroll(15, 19, 20, 8), 12)   # never scrolls past the end
        self.assertEqual(scroll(4, 1, 3, 8), 0)       # short list: no scrolling

    def test_render_marks_the_cursor_the_current_and_what_is_cut(self):
        text = "".join(t for _, t in render(MANY, cursor=9, top=2, visible=8, title="T", description="D", current="5", query="", hint="H"))
        self.assertIn("↑ 2 more", text)
        self.assertIn("↓ 10 more", text)
        self.assertIn("❯ ", text)
        self.assertRegex(text, r"model-5\s+✔")
        self.assertNotIn("model-1\n", text.replace("model-10", ""))   # row 1 is above the window
        self.assertTrue(text.rstrip().endswith("H"))

    def test_render_shows_the_filter_and_an_empty_result(self):
        text = "".join(t for _, t in render([], 0, 0, 8, title="T", description="", current=None, query="zz", hint="H"))
        self.assertIn("Filter: zz", text)
        self.assertIn("Nothing matches.", text)


@unittest.skipIf(create_pipe_input is None, "prompt_toolkit not installed")
class TestKeys(unittest.TestCase):
    def test_enter_picks_the_first_row_by_default(self):
        self.assertEqual(_drive(ENTER), "a")

    def test_down_and_up_move_the_cursor(self):
        self.assertEqual(_drive(DOWN + DOWN + ENTER), "c")
        self.assertEqual(_drive(DOWN + DOWN + UP + ENTER), "b")

    def test_the_cursor_stops_at_both_ends(self):
        self.assertEqual(_drive(UP + ENTER), "a")
        self.assertEqual(_drive(DOWN * 9 + ENTER), "c")

    def test_the_current_choice_starts_selected(self):
        self.assertEqual(_drive(ENTER, current="b"), "b")

    def test_scrolling_a_long_list_reaches_the_last_row(self):
        self.assertEqual(_drive(DOWN * 19 + ENTER, MANY), "19")

    def test_typing_filters_and_backspace_widens(self):
        self.assertEqual(_drive("gam" + ENTER), "c")
        self.assertEqual(_drive("gx\x7f" + ENTER), "c")      # 'gx' matches nothing; Backspace drops the x

    def test_enter_on_no_match_does_nothing_unless_custom_text_is_allowed(self):
        self.assertEqual(_drive("zzz" + CTRL_C), None)
        self.assertEqual(_drive("my-model" + ENTER, allow_custom=True), "my-model")

    def test_ctrl_c_cancels(self):
        self.assertIsNone(_drive(DOWN + CTRL_C))

    def test_the_esc_watcher_is_paused_while_it_is_open(self):
        from src.repl.esc import WATCHER
        seen = []
        original = WATCHER.stop
        with patch.object(WATCHER, "stop", side_effect=lambda: (seen.append("stopped"), original())[1]):
            _drive(ENTER)
        self.assertEqual(seen, ["stopped"])


class TestWithoutATerminal(unittest.TestCase):
    def test_it_asks_for_a_number_instead(self):
        with patch.object(picker, "_interactive", return_value=False), \
                patch.object(picker.Prompt, "ask", return_value="2"):
            self.assertEqual(pick(Console(file=io.StringIO()), "Pick", CHOICES), "b")

    def test_a_bad_number_or_empty_answer_cancels_but_custom_text_can_pass(self):
        with patch.object(picker, "_interactive", return_value=False):
            for answer, custom, expected in (("9", False, None), ("", False, None), ("mine", False, None), ("mine", True, "mine")):
                with patch.object(picker.Prompt, "ask", return_value=answer):
                    self.assertEqual(pick(Console(file=io.StringIO()), "Pick", CHOICES, allow_custom=custom), expected)

    def test_hints_with_brackets_print_literally(self):
        console = Console(file=io.StringIO(), width=100)
        with patch.object(picker, "_interactive", return_value=False), patch.object(picker.Prompt, "ask", return_value=""):
            pick(console, "Pick", [Choice("x", "label", "fix [bold]this[/bold]")])
        self.assertIn("fix [bold]this[/bold]", console.file.getvalue())

    def test_nothing_to_choose_returns_none(self):
        self.assertIsNone(pick(Console(file=io.StringIO()), "Pick", []))


if __name__ == "__main__":
    unittest.main()
