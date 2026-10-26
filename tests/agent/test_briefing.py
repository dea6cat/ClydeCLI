"""/brief: every question is asked with the earlier answers in front of the model, and an interview always ends."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import briefing
from tests.fakes import FakeProvider, reply


def _prompt(provider: FakeProvider, index: int) -> str:
    return provider.requests[index]["conversation"].messages[0].text


class Briefing(unittest.TestCase):
    def test_the_second_question_sees_the_first_answer(self):
        provider = FakeProvider(reply("Who is it for?"), reply("Which database?"), name="p")
        state = briefing.start_briefing("build a todo app")
        question, state = briefing.ask_next_question(provider, "m", state)
        state = briefing.record_answer(state, "for my team")
        question2, state = briefing.ask_next_question(provider, "m", state)
        self.assertEqual((question, question2), ("Who is it for?", "Which database?"))
        self.assertIn("Q: Who is it for?", _prompt(provider, 1))
        self.assertIn("A: for my team", _prompt(provider, 1))
        self.assertEqual(state.questions_asked, ["Who is it for?", "Which database?"])
        self.assertFalse(state.complete)

    def test_ready_ends_it_with_a_synthesized_spec(self):
        provider = FakeProvider(reply("All clear.\nREADY"), reply("GOAL: a todo app\nREADY"), name="p")
        spec, state = briefing.ask_next_question(provider, "m", briefing.start_briefing("todo app"))
        self.assertEqual((spec, state.spec, state.complete), ("GOAL: a todo app", "GOAL: a todo app", True))

    def test_a_model_that_never_says_ready_is_stopped_at_the_question_cap(self):
        state = briefing.BriefingState("x", questions_asked=[f"q{i}" for i in range(briefing.MAX_QUESTIONS)],
                                       answers=["a"] * briefing.MAX_QUESTIONS)
        provider = FakeProvider(reply("spec from what we know"), name="p")
        _spec, state = briefing.ask_next_question(provider, "m", state)
        self.assertTrue(state.complete)
        self.assertEqual(len(provider.requests), 1)   # only the synthesis, no further question

    def test_an_answer_with_no_open_question_is_ignored_and_state_round_trips(self):
        state = briefing.start_briefing("x")
        self.assertEqual(briefing.record_answer(state, "stray").answers, [])
        with tempfile.TemporaryDirectory() as tmp, patch("src.agent.briefing.clyde_home", return_value=Path(tmp)):
            briefing.save_state(briefing.BriefingState("x", ["q"], ["a"], "spec", True))
            loaded = briefing.load_state()
            self.assertEqual((loaded.questions_asked, loaded.answers, loaded.complete), (["q"], ["a"], True))
            briefing.clear_state()
            self.assertIsNone(briefing.load_state())


if __name__ == "__main__":
    unittest.main()
