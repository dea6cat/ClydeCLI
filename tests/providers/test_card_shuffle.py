"""cardShuffle: tier decks, per-turn dealing, and falling back to the next card."""

from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch

from src.config import clyde_home
from src.providers import card_shuffle
from src.providers.base import ProviderError, _Cancelled
from src.providers import laya_client
from src.providers.card_shuffle import (PROMOTE_MIN_TURNS, CardShuffle, Verdict, deck, difficulty_verdict, laya_report, rank,
                                        record_vote, split_council, turn_tool_calls)
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

    def test_an_empty_reply_deals_the_next_card(self):
        self.ollama._responses = [reply("", usage={"input_tokens": 5, "output_tokens": 9})]
        self.anthropic._responses = [reply("real")]
        response = self._stream(Conversation("sys", [Message.user("hi")]))
        self.assertEqual(response.message.text, "real")
        self.assertEqual(self.deals, [LOCAL, HAIKU])
        self.assertEqual(self.card.spent[0][0], LOCAL)

    def test_a_tool_call_without_text_is_not_empty(self):
        self.ollama._responses = [reply(None, tool_calls=[("Read", {})])]
        self._stream(Conversation("sys", [Message.user("hi")]))
        self.assertEqual(self.deals, [LOCAL])

    def test_when_every_card_is_empty_the_last_empty_reply_comes_back(self):
        self.ollama._responses = [reply("")]
        self.anthropic._responses = [reply(""), reply("")]
        response = self._stream(Conversation("sys", [Message.user("hi")]))
        self.assertEqual(response.message.text, "")

    def test_a_rate_limited_card_sits_out_later_turns_until_its_cooldown_ends(self):
        clock = [0.0]
        self.card._now = lambda: clock[0]
        self.ollama._responses = [ProviderError("ollama", "slow down", retryable=True, status=429), reply("later")]
        self.anthropic._responses = [reply("one"), reply("two")]
        self._stream(Conversation("sys", [Message.user("hi")]))
        self.deals.clear()
        self._stream(Conversation("sys", [Message.user("again")]))
        self.assertEqual(self.deals, [HAIKU])
        clock[0] = 91.0
        self.ollama._responses = [reply("back")]
        self._stream(Conversation("sys", [Message.user("third")]))
        self.assertEqual(self.deals[-1], LOCAL)

    def test_the_provider_retry_after_sets_the_bench_length(self):
        clock = [0.0]
        self.card._now = lambda: clock[0]
        self.ollama._responses = [ProviderError("ollama", "slow", retryable=True, status=429, retry_after=300), reply("back")]
        self.anthropic._responses = [reply("one"), reply("two")]
        self._stream(Conversation("sys", [Message.user("hi")]))
        clock[0] = 200.0                      # past the 90 s default, inside the 300 s ask
        self._stream(Conversation("sys", [Message.user("again")]))
        self.assertEqual(self.deals, [LOCAL, HAIKU, HAIKU])

    def test_out_of_credit_benches_every_model_of_that_provider_not_just_the_card(self):
        self.anthropic._responses = [ProviderError("anthropic", "HTTP 402 out of credits", status=402)]
        self.ollama._responses = [reply("local answer")]
        response = self._stream(Conversation("sys", [Message.user("hi")]), "high-roller")
        self.assertEqual(response.message.text, "local answer")
        self.assertEqual(self.deals, [OPUS, LOCAL])   # HAIKU, on the same dry account, was never tried
        self.assertFalse(self.card._ready(HAIKU, self.card._now()))

    def test_an_answer_full_of_leaked_special_tokens_is_not_an_answer(self):
        junk = "<|open|>toolsernels tunneledlevant direct.<|open|><|close|>partial <|open|>away"
        self.ollama._responses = [reply(junk)]
        self.anthropic._responses = [reply("a real answer")]
        response = self._stream(Conversation("sys", [Message.user("hi")]))
        self.assertEqual(response.message.text, "a real answer")
        self.assertEqual(self.deals, [LOCAL, HAIKU])

    def test_one_stray_token_pair_in_a_real_answer_is_kept(self):
        self.ollama._responses = [reply("The cast is <|x|> in this syntax")]
        response = self._stream(Conversation("sys", [Message.user("hi")]))
        self.assertIn("cast is", response.message.text)

    def test_a_plain_error_is_not_benched_past_its_turn(self):
        self.ollama._responses = [ProviderError("ollama", "boom"), reply("ok")]
        self.anthropic._responses = [reply("saved")]
        self._stream(Conversation("sys", [Message.user("hi")]))
        self._stream(Conversation("sys", [Message.user("again")]))
        self.assertEqual(self.deals, [LOCAL, HAIKU, LOCAL])

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


COUNCIL_EVALS = {f"{n}:m": {"passed": True, "strength": st} for n, st in (("a", 5), ("b", 4), ("c", 3), ("d", 2), ("e", 1))}


def _prefers(ref_to_p: dict[str, float], texts: dict[str, str]):
    """A fake Laya that gives each answer the chance listed for its text, whatever slot it sits in."""
    def ask(state, questions):
        out = {}
        for name, q in questions.items():
            order = q.get("option_order") or range(len(q["criteria"]))
            labels = list(q["criteria"])
            out[name] = {"probabilities": {labels[i]: ref_to_p[texts[q["criteria"][labels[i]]]] for i in order}}
        return out
    return ask


class TestCouncil(unittest.TestCase):
    def setUp(self):
        patcher = patch("src.providers.card_shuffle.load_results", return_value=COUNCIL_EVALS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.providers = {n: FakeProvider(reply(f"answer {n}", usage={"input_tokens": 1, "output_tokens": 1}), name=n) for n in "abcde"}
        self.texts = {f"answer {n}": f"{n}:m" for n in "abcde"}
        self.deals: list[str] = []

    def _card(self, ask) -> CardShuffle:
        card = CardShuffle(self.providers, ask=ask, verdict=Verdict([]))
        card.on_deal = lambda ref, why: self.deals.append(f"{ref} | {why}")
        return card

    def _run(self, card: CardShuffle, model: str = "high-roller council"):
        shown: list[str] = []
        response = card.stream(Conversation("sys", [Message.user("what is 2+2?")]), model, (), shown.append)
        return response, shown

    def test_split_council_reads_a_trailing_council_word_only(self):
        self.assertEqual(split_council("high-roller council"), ("high-roller", True))
        self.assertEqual(split_council("high-roller"), ("high-roller", False))
        self.assertEqual(split_council("high-roller extra"), ("high-roller extra", False))

    def test_the_council_forms_are_listed_as_models(self):
        self.assertIn("high-roller council", self._card(lambda *a: None).list_models())

    def test_the_top_four_answer_and_the_best_rated_wins(self):
        chances = {"a:m": 0.1, "b:m": 0.2, "c:m": 0.6, "d:m": 0.1}
        card = self._card(_prefers(chances, self.texts))
        response, shown = self._run(card)
        self.assertEqual(response.message.text, "answer c")
        self.assertEqual(shown, ["answer c"])
        self.assertEqual(card.dealt, "c:m")
        self.assertEqual([a["ref"] for a in card.last_council["answers"]], ["a:m", "b:m", "c:m", "d:m"])   # e is not in the top four
        self.assertEqual(self.providers["e"].requests, [])
        self.assertAlmostEqual(card.last_council["answers"][2]["p"], 0.6)
        self.assertTrue(card.last_council["ranked"])
        self.assertIn("council, 4 of 4 answered · 60% best", self.deals[0])

    def test_models_get_no_tools_and_every_call_is_spent(self):
        card = self._card(_prefers({r: 0.25 for r in self.texts.values()}, self.texts))
        self._run(card)
        self.assertTrue(all(p.requests[0]["tools"] == () for n, p in self.providers.items() if n != "e"))
        self.assertEqual(sorted(ref for ref, _ in card.spent), ["a:m", "b:m", "c:m", "d:m"])

    def test_without_laya_the_strongest_answer_comes_back_unranked(self):
        card = self._card(lambda *a: None)
        response, _ = self._run(card)
        self.assertEqual(response.message.text, "answer a")
        self.assertFalse(card.last_council["ranked"])
        self.assertIn("unranked", self.deals[0])

    def test_a_failing_or_empty_model_does_not_block_the_others(self):
        self.providers["a"]._responses = [ProviderError("a", "boom")]
        self.providers["b"]._responses = [reply("")]
        card = self._card(_prefers({"c:m": 0.7, "d:m": 0.2, "e:m": 0.1}, self.texts))
        response, _ = self._run(card)
        self.assertEqual(response.message.text, "answer c")
        failed = card.last_council["failed"]
        self.assertIn("boom", failed["a:m"])
        self.assertEqual(failed["b:m"], "returned no answer")

    def test_members_read_the_repo_when_the_repl_gives_them_a_way_to(self):
        seen: list[tuple[str, str]] = []

        def investigate(provider, model, cancel):
            seen.append((provider.name, model))
            return reply(f"read answer {provider.name}")

        card = self._card(lambda *a: None)
        card.investigate = investigate
        response, _ = self._run(card)
        self.assertEqual(sorted(seen), [("a", "m"), ("b", "m"), ("c", "m"), ("d", "m")])
        self.assertEqual(response.message.text, "read answer a")
        self.assertTrue(all(p.requests == [] for p in self.providers.values()))   # no tool-less stream() calls

    def test_a_tool_call_written_as_text_is_not_an_answer(self):
        self.providers["a"]._responses = [reply("Let me look. <tool_call>Bash <arg_key>command</arg_key><arg_value>ls</arg_value></tool_call>")]
        card = self._card(_prefers({"b:m": 0.7, "c:m": 0.2, "d:m": 0.1}, self.texts))
        self._run(card)
        self.assertEqual(card.last_council["failed"]["a:m"], "returned no answer")
        self.assertNotIn("a:m", [a["ref"] for a in card.last_council["answers"]])

    def test_a_model_past_the_deadline_is_dropped(self):
        class Stuck(FakeProvider):
            def stream(self, conversation, model, tools, on_text, *, cancel=None, **kw):
                cancel.wait(5)
                raise _Cancelled()

        self.providers["a"] = Stuck(name="a")
        card = self._card(lambda *a: None)
        with patch.object(card_shuffle, "COUNCIL_DEADLINE_S", 0.3):
            response, _ = self._run(card)
        self.assertEqual(response.message.text, "answer b")
        self.assertEqual(card.last_council["failed"], {"a:m": "missed the deadline"})

    def test_every_model_failing_raises(self):
        for n in "abcd":
            self.providers[n]._responses = [ProviderError(n, "down")]
        with self.assertRaises(ProviderError):
            self._run(self._card(lambda *a: None))

    def test_a_cancelled_turn_raises_cancelled(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(_Cancelled):
            self._card(lambda *a: None).stream(Conversation("sys", [Message.user("hi")]), "high-roller council", (), lambda _: None, cancel=cancel)

    def test_one_available_model_is_dealt_normally(self):
        only_a = {"a:m": COUNCIL_EVALS["a:m"]}
        with patch("src.providers.card_shuffle.load_results", return_value=only_a):
            card = self._card(lambda *a: None)
            response, _ = self._run(card)
        self.assertEqual(response.message.text, "answer a")
        self.assertIsNone(card.last_council)

    def test_plain_tiers_are_untouched(self):
        card = self._card(lambda *a: None)
        response, _ = self._run(card, "high-roller")
        self.assertEqual(response.message.text, "answer a")
        self.assertIsNone(card.last_council)
        self.assertEqual([len(p.requests) for p in self.providers.values()], [1, 0, 0, 0, 0])


class TestRank(unittest.TestCase):
    def test_every_answer_takes_the_first_slot_once_so_slot_bias_averages_out(self):
        seen: list[dict] = []

        def slot_zero_fan(state, questions):
            seen.extend(questions.values())
            return {n: {"probabilities": {list(q["criteria"])[q["option_order"][0]]: 1.0,
                                          **{l: 0.0 for i, l in enumerate(q["criteria"]) if i != q["option_order"][0]}}}
                    for n, q in questions.items()}

        chances = rank(slot_zero_fan, "q", {"x": "one", "y": "two", "z": "three"})
        self.assertEqual(sorted(q["option_order"][0] for q in seen), [0, 1, 2])
        self.assertEqual({r: round(p, 3) for r, p in chances.items()}, {"x": 0.333, "y": 0.333, "z": 0.333})

    def test_none_when_laya_cannot_answer_or_answers_oddly(self):
        self.assertIsNone(rank(lambda *a: None, "q", {"x": "1", "y": "2"}))
        self.assertIsNone(rank(lambda *a: {"r0": {}}, "q", {"x": "1", "y": "2"}))


class TestVotes(unittest.TestCase):
    COUNCIL = {"tier": "house", "request": "hi", "answers": [{"ref": "a:m", "text": "t", "p": 0.4}]}

    def test_a_vote_is_appended_locally_without_the_prompt_text(self):
        record_vote(self.COUNCIL, "a:m", -1)
        record_vote(self.COUNCIL, "a:m", 1)
        lines = [json.loads(l) for l in (clyde_home() / "council_votes.jsonl").read_text().splitlines()]
        self.assertEqual([l["vote"] for l in lines[-2:]], [-1, 1])
        self.assertEqual(lines[-1]["ref"], "a:m")
        self.assertNotIn("hi", json.dumps(lines[-1]).replace("high", ""))

    def test_an_unknown_answer_or_bad_vote_is_refused(self):
        with self.assertRaises(ValueError):
            record_vote(self.COUNCIL, "z:m", 1)
        with self.assertRaises(ValueError):
            record_vote(self.COUNCIL, "a:m", 5)
