"""cardShuffle: tier decks, per-turn dealing, and falling back to the next card."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers.base import ProviderError
from src.providers.card_shuffle import CardShuffle, deck
from src.providers.types import Conversation, Message, ToolResult
from tests.fakes import FakeProvider, reply

OPUS, HAIKU, LOCAL = "anthropic:claude-opus-4-5", "anthropic:claude-haiku-4-5", "ollama:qwen3:8b"
EVALS = {OPUS: {"passed": True, "strength": 4}, HAIKU: {"passed": True, "strength": 2},
         LOCAL: {"passed": True, "strength": 1}, "anthropic:broken": {"passed": False}, "cardShuffle:house": {"passed": True}}
RANKED = {ref: EVALS[ref] for ref in (HAIKU, LOCAL, OPUS)}


class TestDeck(unittest.TestCase):
    def test_tiers_order_by_eval_strength(self):
        self.assertEqual(deck("high-roller", RANKED), [OPUS, HAIKU, LOCAL])
        self.assertEqual(deck("small", RANKED), [LOCAL, HAIKU, OPUS])
        self.assertEqual(deck("free", RANKED), [LOCAL])

    def test_ties_go_to_the_faster_model(self):
        tied = {"a:slow": {"strength": 3, "tokens_per_s": 20}, "b:fast": {"strength": 3, "tokens_per_s": 90}}
        self.assertEqual(deck("high-roller", tied), ["b:fast", "a:slow"])

    def test_house_deals_the_middle_card_unless_planning(self):
        self.assertEqual(deck("house", RANKED, "hold"), [HAIKU, OPUS, LOCAL])
        self.assertEqual(deck("house", RANKED, "plan"), [OPUS, HAIKU, LOCAL])


class TestDealing(unittest.TestCase):
    def setUp(self):
        patcher = patch("src.providers.card_shuffle.load_results", return_value=EVALS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.anthropic = FakeProvider(name="anthropic")
        self.ollama = FakeProvider(name="ollama")
        self.deals: list[str] = []
        self.card = CardShuffle({"anthropic": self.anthropic, "ollama": self.ollama})
        self.card.on_deal = lambda ref, why: self.deals.append(ref)

    def _stream(self, conv: Conversation, tier: str = "small"):
        return self.card.stream(conv, tier, (), lambda _: None)

    def test_only_eval_passed_models_are_dealt(self):
        self.assertEqual(sorted(self.card._candidates()), sorted([OPUS, HAIKU, LOCAL]))

    def test_new_turn_deals_and_tool_rounds_keep_the_card(self):
        self.ollama._responses = [reply("one"), reply("two")]
        conv = Conversation("sys", [Message.user("hi")])
        self._stream(conv)
        conv.messages += [Message.assistant(tool_calls=[]), Message.results([ToolResult("t1", "ok")])]
        self._stream(conv)
        self.assertEqual(self.deals, [LOCAL])
        self.assertEqual([r["model"] for r in self.ollama.requests], ["qwen3:8b", "qwen3:8b"])

    def test_any_error_falls_back_to_the_next_card(self):
        self.ollama._responses = [ProviderError("ollama", "boom")]
        self.anthropic._responses = [reply("saved", usage={"input_tokens": 3, "output_tokens": 1})]
        response = self._stream(Conversation("sys", [Message.user("hi")]))
        self.assertEqual(response.message.text, "saved")
        self.assertEqual(self.deals, [LOCAL, HAIKU])
        self.assertEqual(self.card.spent, [(HAIKU, {"input_tokens": 3, "output_tokens": 1})])

    def test_spent_deck_raises_the_last_error(self):
        self.ollama._responses = [ProviderError("ollama", "boom")]
        self.anthropic._responses = [ProviderError("anthropic", "a"), ProviderError("anthropic", "b")]
        with self.assertRaises(ProviderError):
            self._stream(Conversation("sys", [Message.user("hi")]))

    def test_redeal_moves_to_the_next_card_until_the_deck_is_spent(self):
        self.card.shuffle("high-roller")
        self.assertTrue(self.card.redeal("stuck"))
        self.assertTrue(self.card.redeal("stuck"))
        self.assertFalse(self.card.redeal("stuck"))
        self.assertEqual(self.deals, [OPUS, HAIKU, LOCAL])


if __name__ == "__main__":
    unittest.main()
