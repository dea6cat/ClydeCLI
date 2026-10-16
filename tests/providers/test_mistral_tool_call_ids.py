"""Mistral rejects a tool call id that is not exactly nine letters and digits. cardShuffle (and /model) can move a
conversation to Mistral after another provider wrote its history, so ids like toolu_01A… must be rewritten on the way out."""
from __future__ import annotations

import re
import unittest

from src.providers.openai_compat import OpenAICompatProvider
from src.providers.types import Conversation, Message, ToolCall, ToolResult

NINE = re.compile(r"[A-Za-z0-9]{9}")


def _conversation(*ids: str) -> Conversation:
    c = Conversation("sys", [Message.user("go")])
    c.append(Message.assistant(text="", tool_calls=[ToolCall(id=i, name="Read", arguments={"file_path": "x"}) for i in ids]))
    c.append(Message.results([ToolResult(i, "ok") for i in ids]))
    return c


def _ids(provider_name: str, *ids: str) -> tuple[list[str], list[str]]:
    out = OpenAICompatProvider(provider_name, "http://localhost/v1", "KEY")._messages(_conversation(*ids))
    calls = [tc["id"] for m in out for tc in m.get("tool_calls", [])]
    results = [m["tool_call_id"] for m in out if m["role"] == "tool"]
    return calls, results


class TestMistralToolCallIds(unittest.TestCase):
    def test_a_foreign_id_becomes_nine_letters_and_digits_and_still_pairs_with_its_result(self):
        calls, results = _ids("mistral", "toolu_01A09q90qw90lq917835lq9", "call_abc-123")
        self.assertTrue(all(NINE.fullmatch(i) for i in calls), calls)
        self.assertEqual(calls, results)
        self.assertEqual(len(set(calls)), 2)

    def test_two_ids_that_share_their_first_characters_stay_distinct(self):
        calls, _ = _ids("mistral", "call_abc12345a", "call_abc12345b")
        self.assertNotEqual(calls[0], calls[1])

    def test_an_id_that_is_already_valid_is_left_alone(self):
        self.assertEqual(_ids("mistral", "aBc123XyZ")[0], ["aBc123XyZ"])

    def test_the_rewrite_is_the_same_every_time(self):
        self.assertEqual(_ids("mistral", "toolu_01A")[0], _ids("mistral", "toolu_01A")[0])

    def test_other_providers_keep_their_ids(self):
        self.assertEqual(_ids("openai", "toolu_01A09q90qw90lq917835lq9")[0], ["toolu_01A09q90qw90lq917835lq9"])


if __name__ == "__main__":
    unittest.main()
