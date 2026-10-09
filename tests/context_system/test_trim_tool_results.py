from __future__ import annotations

import unittest

from src.agent.conversation import Conversation
from src.context_system.microcompact import CLEARED_MESSAGE, trim_old_tool_results


def _conversation(results: int, size: int = 4000) -> Conversation:
    convo = Conversation()
    for i in range(results):
        convo.add_user_message(f"step {i}")
        convo.add_tool_result_message(f"id{i}", "x" * size)
    return convo


def _contents(convo: Conversation) -> list[str]:
    return [b.content for m in convo.messages if isinstance(m.content, list) for b in m.content if b.type == "tool_result"]


class TestTrimOldToolResults(unittest.TestCase):
    def test_a_conversation_under_half_the_window_is_left_alone(self):
        convo = _conversation(6)
        self.assertEqual(trim_old_tool_results(convo, window=1_000_000), 0)
        self.assertNotIn(CLEARED_MESSAGE, _contents(convo))

    def test_past_half_the_window_old_results_are_cleared_and_the_newest_kept(self):
        convo = _conversation(8)
        self.assertEqual(trim_old_tool_results(convo, window=4000), 4)
        results = _contents(convo)
        self.assertEqual(results[:4], [CLEARED_MESSAGE] * 4)
        self.assertEqual(results[4:], ["x" * 4000] * 4)

    def test_short_results_are_not_worth_clearing(self):
        convo = _conversation(8, size=100)
        self.assertEqual(trim_old_tool_results(convo, window=100), 0)

    def test_running_it_again_clears_nothing_more(self):
        convo = _conversation(8)
        trim_old_tool_results(convo, window=4000)
        self.assertEqual(trim_old_tool_results(convo, window=4000), 0)


if __name__ == "__main__":
    unittest.main()
