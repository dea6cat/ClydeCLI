"""cardShuffle: tier decks, per-turn dealing, and falling back to the next card."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.providers.base import ProviderError
from src.providers import laya_client
from src.providers.card_shuffle import (PROMOTE_MIN_TURNS, CardShuffle, Verdict, deck, difficulty_verdict, laya_report,
                                        turn_tool_calls)
from src.providers.types import Conversation, Message, ToolCall, ToolResult
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

    def test_old_four_task_scores_and_new_eight_task_scores_compare_by_share(self):
        mixed = {"old:full": {"strength": 4}, "new:most": {"strength": 7, "hand": 8}, "new:half": {"strength": 4, "hand": 8}}
        self.assertEqual(deck("high-roller", mixed), ["old:full", "new:most", "new:half"])

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
        self.card = CardShuffle({"anthropic": self.anthropic, "ollama": self.ollama}, ask=lambda *a: None, verdict=Verdict([]))
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


def _looping_turn(rounds: int) -> Conversation:
    conv = Conversation("sys", [Message.user("find onError")])
    for i in range(rounds):
        call = ToolCall(f"c{i}", "Grep", {"pattern": "onError"})
        conv.messages += [Message.assistant(tool_calls=[call]), Message.results([ToolResult(f"c{i}", "0 files")])]
    return conv


class TestLaya(unittest.TestCase):
    def setUp(self):
        patcher = patch("src.providers.card_shuffle.load_results", return_value=EVALS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.anthropic, self.ollama = FakeProvider(name="anthropic"), FakeProvider(name="ollama")
        self.asked: list[dict] = []
        self.stuck = 0.9

        def ask(state, questions):
            self.asked.append(state)
            if "stuck" in questions:
                return {"stuck": {"noul": self.stuck}}
            return {"difficulty": {"score": self.score, "confidence": 0.3}}
        self.score = 2.6
        self.waits: list[float] = []
        self.shadow = Verdict([])
        self.card = CardShuffle({"anthropic": self.anthropic, "ollama": self.ollama}, ask=ask,
                                wait=lambda t: self.waits.append(t) or True, verdict=self.shadow)
        self.deals: list[str] = []
        self.card.on_deal = lambda ref, why: self.deals.append(f"{ref} | {why}")

    def test_a_confident_loop_hands_the_turn_to_the_next_card(self):
        self.ollama._responses = [reply("first")]
        self.card.stream(Conversation("sys", [Message.user("find onError")]), "small", (), lambda _: None)
        self.anthropic._responses = [reply("fresh eyes")]
        self.card.stream(_looping_turn(6), "small", (), lambda _: None)
        self.assertEqual([d.split(" | ")[0] for d in self.deals], [LOCAL, HAIKU])
        self.assertIn("looked stuck (laya 0.90)", self.deals[-1])
        self.assertIn("Grep", self.asked[-1]["recent_tool_calls"][0])

    def test_an_unsure_answer_keeps_the_card(self):
        self.stuck = 0.5
        self.ollama._responses = [reply("first"), reply("still going")]
        self.card.stream(Conversation("sys", [Message.user("find onError")]), "small", (), lambda _: None)
        self.card.stream(_looping_turn(6), "small", (), lambda _: None)
        self.assertEqual(len(self.deals), 1)

    def test_laya_only_looks_after_enough_calls_and_every_few_rounds(self):
        self.card.dealt = LOCAL
        self.assertIsNone(self.card._stuck(_looping_turn(5)))     # fewer than STUCK_AFTER calls
        self.assertIsNone(self.card._stuck(_looping_turn(7)))     # not a STUCK_EVERY round
        self.assertEqual(self.card._stuck(_looping_turn(9)), 0.9)

    def test_in_shadow_difficulty_is_shown_on_every_tier_but_does_not_change_the_deal(self):
        self.card.mode = "hold"
        self.card.shuffle("house", "redesign the auth system")
        self.assertEqual(self.card.dealt, HAIKU)                  # the middle card, as without Laya
        self.assertIn("laya difficulty 2.6/3 (shadow)", self.deals[-1])
        self.card.shuffle("small", "hi")
        self.assertEqual(self.card.dealt, LOCAL)
        self.assertIn("(shadow)", self.deals[-1])                 # scored on small too, for evidence

    def test_the_first_turn_waits_once_for_laya_to_load(self):
        self.card.shuffle("small", "one")
        self.card.shuffle("small", "two")
        self.assertEqual(self.waits, [30])

    def test_once_promoted_house_starts_harder_requests_on_stronger_cards(self):
        self.card._verdict = _promoted()                          # past scores 1.3 (easy) and 1.8 (hard)
        self.score = 1.9                                          # harder than every past request
        self.card.shuffle("house", "redesign the provider layer")
        self.assertEqual(self.card.dealt, OPUS)
        self.assertNotIn("(shadow)", self.deals[-1])
        self.score = 1.2                                          # easier than every past request
        self.card.shuffle("house", "hi")
        self.assertEqual(self.card.dealt, LOCAL)
        self.card.mode = "plan"
        self.card.shuffle("house", "hi")
        self.assertEqual(self.card.dealt, OPUS)                   # planning still gets the strongest
        self.card.mode = "hold"
        self.card.shuffle("small", "redesign the provider layer")
        self.assertEqual(self.card.dealt, LOCAL)                  # only house acts on it

    def test_turn_tool_calls_cover_only_this_turn(self):
        conv = _looping_turn(2)
        conv.messages += [Message.assistant(text="done"), Message.user("next task")]
        self.assertEqual(turn_tool_calls(conv), [])
        self.assertEqual(turn_tool_calls(_looping_turn(2))[0], 'Grep {"pattern": "onError"} -> 0 files')


def _turns(n: int, score: float, rounds: int, acted: bool = False) -> list[dict]:
    return [e for _ in range(n) for e in ({"event": "turn"}, {"event": "laya", "question": "difficulty", "score": score, "acted": acted},
                                          {"event": "turn_end", "ran_out": False, "rounds": rounds})]


def _promoted() -> Verdict:
    import json
    return difficulty_verdict(json.dumps(e) for e in _turns(PROMOTE_MIN_TURNS, 1.3, 2) + _turns(PROMOTE_MIN_TURNS, 1.8, 6))


class TestVerdict(unittest.TestCase):
    def verdict(self, events):
        import json
        return difficulty_verdict(json.dumps(e) for e in events)

    def test_promotes_once_harder_scored_turns_clearly_take_more_rounds(self):
        v = _promoted()
        self.assertTrue(v.promoted)
        self.assertIn("acts in house", v.summary())

    def test_stays_in_shadow_without_enough_turns_or_a_clear_gap(self):
        few = self.verdict(_turns(PROMOTE_MIN_TURNS - 1, 1.3, 2) + _turns(PROMOTE_MIN_TURNS, 1.8, 6))
        self.assertFalse(few.promoted)
        self.assertIn("needs 1 more scored turn", few.summary())
        close = self.verdict(_turns(PROMOTE_MIN_TURNS, 1.3, 4) + _turns(PROMOTE_MIN_TURNS, 1.8, 5))
        self.assertFalse(close.promoted)
        self.assertFalse(self.verdict([]).promoted)

    def test_turns_it_already_steered_are_not_evidence(self):
        v = self.verdict(_turns(PROMOTE_MIN_TURNS, 1.3, 2) + _turns(PROMOTE_MIN_TURNS, 1.8, 6, acted=True))
        self.assertFalse(v.promoted)

    def test_a_new_score_is_placed_among_past_scores(self):
        v = _promoted()
        self.assertEqual((v.relative(1.0), v.relative(1.5), v.relative(2.0)), (0.0, 0.5, 1.0))


class TestLayaReport(unittest.TestCase):
    def test_lines_up_judgments_with_how_each_turn_ended(self):
        import json
        events = [
            {"event": "turn"}, {"event": "laya", "question": "stuck", "noul": 0.9, "acted": True},
            {"event": "turn_end", "ran_out": False, "rounds": 9},
            {"event": "turn"}, {"event": "laya", "question": "stuck", "noul": 0.6, "acted": False},
            {"event": "turn_end", "ran_out": True, "rounds": 20},
            {"event": "turn"}, {"event": "laya", "question": "difficulty", "score": 2.4},
            {"event": "turn_end", "ran_out": False, "rounds": 7},
            {"event": "turn"}, {"event": "laya", "question": "stuck", "noul": 0.95},   # never ended: ignored
            {"event": "turn"}, {"event": "turn_end", "ran_out": False, "rounds": 1},
        ]
        report = laya_report([json.dumps(e) for e in events] + ["not json"])
        rows = {line.split()[0] + line.split()[1]: line.split()[-3:] for line in report.splitlines()
                if line.startswith("  ") and line.split()[-1].isdigit()}
        self.assertEqual(rows["0.50to"], ["1", "0", "1"])        # one loop slipped under the threshold
        self.assertEqual(rows["0.80and"], ["1", "1", "0"])       # one re-deal, and that turn finished
        self.assertEqual(rows["harderhalf"], ["1", "7.0", "0"])  # difficulty 2.4 took 7 rounds
        self.assertIn("stays in shadow", report)


class TestLayaClient(unittest.TestCase):
    def test_without_a_loaded_model_there_is_no_answer(self):
        with patch.object(laya_client, "_router", None):
            self.assertIsNone(laya_client.ask({"request": "hi"}, {}))

    def test_waiting_without_downloaded_weights_returns_at_once(self):
        with patch.object(laya_client, "cached", return_value=False), patch.object(laya_client, "_thread", None), \
                patch.object(laya_client, "_router", None):
            self.assertFalse(laya_client.wait_ready(30))

    def test_nothing_loads_when_the_weights_are_not_downloaded(self):
        with patch.object(laya_client, "cached", return_value=False), patch.object(laya_client, "_thread", None), \
                patch.object(laya_client, "_router", None), patch.object(laya_client, "_error", ""):
            laya_client.warm()
            self.assertIsNone(laya_client._thread)
            self.assertEqual(laya_client.status(), "not downloaded")


if __name__ == "__main__":
    unittest.main()
