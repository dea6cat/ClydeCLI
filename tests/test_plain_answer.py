"""Permission answers in the user's own words: only a plain yes allows; anything else holds the action and reaches Clyde."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from src import plain_answer
from src.runtime.run_control import RunControl
from tests.fakes import FakeProvider, reply


class TestIsPlainYes(unittest.TestCase):
    def test_the_model_reads_only_the_reply(self):
        provider = FakeProvider(reply("YES"))
        self.assertEqual(plain_answer.is_plain_yes(provider, "m", "sure, go ahead"), (True, ""))
        self.assertIn("Reply: sure, go ahead", str(provider.requests[0]))

    def test_anything_but_yes_is_no(self):
        for answer in ("OTHER", "Yes, but only the old ones", ""):
            self.assertFalse(plain_answer.is_plain_yes(FakeProvider(reply(answer)), "m", "x")[0], answer)

    def test_reasoning_written_before_the_verdict_is_skipped(self):
        self.assertTrue(plain_answer.is_plain_yes(FakeProvider(reply("<think>they agree</think>\nYes.")), "m", "dale")[0])

    def test_an_error_or_a_slow_model_is_no(self):
        yes, why = plain_answer.is_plain_yes(FakeProvider(RuntimeError("down")), "m", "ok")
        self.assertFalse(yes)
        self.assertIn("down", why)
        slow = MagicMock()
        with patch("src.providers.base.stream_with_retry", side_effect=lambda *a, **k: time.sleep(1)), \
             patch.object(plain_answer, "TIMEOUT_S", 0.05):
            yes, why = plain_answer.is_plain_yes(slow, "m", "ok")
        self.assertFalse(yes)
        self.assertIn("within", why)


class TestTerminalPrompt(unittest.TestCase):
    def _repl(self):
        from src.repl import ClydeREPL
        repl = object.__new__(ClydeREPL)
        repl.console = MagicMock()
        repl.control = RunControl()
        repl.provider, repl.model = FakeProvider(), "m"
        return repl

    def _ask(self, repl, typed, verdict=(True, "")):
        with patch("builtins.input", return_value=typed), patch("src.plain_answer.is_plain_yes", return_value=verdict) as check:
            allowed, _ = repl._ask_permission("Run ls", None)
        return allowed, check

    def test_listed_keys_never_ask_the_model(self):
        for typed, want in (("y", True), ("", True), ("n", False), ("no", False)):
            allowed, check = self._ask(self._repl(), typed)
            self.assertEqual(allowed, want, typed)
            check.assert_not_called()

    def test_a_plain_yes_in_words_allows(self):
        repl = self._repl()
        allowed, check = self._ask(repl, "sure, go ahead")
        self.assertTrue(allowed)
        self.assertEqual(check.call_args.args[-1], "sure, go ahead")
        self.assertIsNone(repl.control.take_steer())

    def test_anything_else_holds_the_action_and_steers_clyde(self):
        repl = self._repl()
        allowed, _ = self._ask(repl, "no, edit the copy in src/ instead", verdict=(False, ""))
        self.assertFalse(allowed)
        self.assertEqual(repl.control.take_steer(), "no, edit the copy in src/ instead")

    def test_a_stray_letter_is_denied_without_a_model_call(self):
        allowed, check = self._ask(self._repl(), "x")
        self.assertFalse(allowed)
        check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
