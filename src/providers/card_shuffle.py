"""cardShuffle: a virtual provider whose models are tiers. Each user turn is dealt to a real model
that passed /eval; a failing or stuck model is swapped for the next card in the deck.

Tiers (models):
  high-roller  strongest first
  house        by mode: reading the table (plan) gets the strongest, other modes the middle card
  free         local models only (Ollama, LM Studio), strongest first
  small        weakest first, for quick and cheap turns

Strength is how many of /eval's hard tasks a model solved; ties go to the faster model.

Laya (the bundled decision model) watches each turn: every few tool rounds it judges whether the
dealt model is repeating itself without progress, and a confident yes hands the turn to the next
card. For house it also scores the request's difficulty, in shadow mode: shown on the deal line
and traced, not yet acted on.
"""
from __future__ import annotations

import json
from typing import Callable, Iterable

from ..agent import trace
from . import laya_client
from .base import ProviderError, ProviderResponse, _Cancelled
from .model_eval import load_results
from .types import Conversation, Role

NAME = "cardShuffle"
TIERS = ("high-roller", "house", "free", "small")
LOCAL = ("ollama", "lmstudio")

STUCK_AFTER = 6     # tool calls in a turn before Laya first looks for a loop
STUCK_EVERY = 3     # tool rounds between looks
STUCK_AT = 0.8      # ponytail: from one replayed loop (0.95) vs normal progress (0.38); tune from traces
_STUCK = {"type": "noul", "instructions": "Is the agent repeating the same tool calls in `recent_tool_calls`, "
                                          "with the same or empty results, without making progress?"}
_DIFFICULTY = {"type": "score", "instructions": "How hard is `request` for an AI coding agent working in the user's repository?",
               "criteria": ["Trivial: a greeting, a quick question, or a one-line lookup or change",
                            "Simple: a small, well-specified change confined to one file",
                            "Moderate: a multi-step change, a bug investigation, or work across a few files",
                            "Hard: a design decision, a subtle bug, or a large refactor across many files"]}


def _this_turn(conversation: Conversation) -> list:
    """The messages since the last user message."""
    start = max((i for i, m in enumerate(conversation.messages)
                 if m.role == Role.USER and not m.tool_results), default=-1) + 1
    return conversation.messages[start:]


def turn_tool_calls(conversation: Conversation) -> list[str]:
    """This turn's tool calls as short "Tool args -> result" lines."""
    turn = _this_turn(conversation)
    results = {r.tool_call_id: r.content for m in turn for r in m.tool_results}
    return [f"{c.name} {json.dumps(c.arguments, ensure_ascii=False)[:120]} -> {results.get(c.id, '')[:80]}"
            for m in turn for c in m.tool_calls]


def by_strength(results: dict[str, dict]) -> list[str]:
    """Refs weakest to strongest; among equals the faster model ranks higher. Models evaluated
    before the hard tasks existed count as strength 0 until /eval runs again."""
    def key(ref: str) -> tuple[int, float]:
        r = results[ref]
        return r.get("strength") or 0, r.get("tokens_per_s") or 0.0
    return sorted(results, key=key)


def deck(tier: str, results: dict[str, dict], mode: str = "hold") -> list[str]:
    """The order a tier deals in: first card first, then the fallbacks."""
    ranked = by_strength(results)
    if tier == "small":
        return ranked
    if tier == "free":
        ranked = [r for r in ranked if r.partition(":")[0] in LOCAL]
    if tier == "house" and mode != "plan" and ranked:
        # The middle card, then stronger ones, then weaker ones.
        mid = len(ranked) // 2
        return ranked[mid:] + ranked[:mid][::-1]
    return ranked[::-1]


class CardShuffle:
    """Deals each user turn to a real provider from the registry it is given."""

    name = NAME

    def __init__(self, registry: dict, ask: Callable[[object, dict], dict | None] = laya_client.ask) -> None:
        self.registry = registry
        self.ask = ask
        self.mode = "hold"                      # the REPL keeps this in step with Shift+Tab
        self.on_deal: Callable[[str, str], None] | None = None
        self.dealt: str | None = None
        self.spent: list[tuple[str, dict]] = []  # (ref, usage) per real call, drained by the REPL for /cost
        self._deck: list[str] = []
        self._burned: set[str] = set()

    def is_available(self) -> bool:
        return bool(self._candidates(check=False))

    def list_models(self) -> list[str]:
        return list(TIERS)

    def _candidates(self, check: bool = True) -> dict[str, dict]:
        """Eval results of the models that passed /eval (and, with check, whose provider is connected now)."""
        out = {}
        for ref, r in load_results().items():
            if not r.get("passed") or ref.startswith(f"{NAME}:"):
                continue
            if check:
                provider = self.registry.get(ref.partition(":")[0])
                try:
                    if provider is None or not provider.is_available():
                        continue
                except Exception:
                    continue
            out[ref] = r
        return out

    def _deal(self, why: str) -> str:
        card = next((r for r in self._deck if r not in self._burned), None)
        if card is None:
            raise ProviderError(NAME, "no model left to deal: every candidate failed or none passed /eval "
                                      "(run /eval, then try again)")
        self.dealt = card
        if self.on_deal is not None:
            self.on_deal(card, why)
        return card

    def shuffle(self, tier: str, request: str = "") -> str:
        """Build this turn's deck and deal its first card."""
        if tier not in TIERS:
            raise ProviderError(NAME, f"unknown tier '{tier}' (one of {', '.join(TIERS)})")
        self._deck, self._burned = deck(tier, self._candidates(), self.mode), set()
        return self._deal(tier + self._shadow_difficulty(tier, request))

    def _shadow_difficulty(self, tier: str, request: str) -> str:
        """Laya's difficulty score for a house turn, traced and returned for the deal line; not acted on."""
        answers = self.ask({"request": request[-4000:], "mode": self.mode}, {"difficulty": _DIFFICULTY}) \
            if tier == "house" and request.strip() else None
        if not answers:
            return ""
        d = answers["difficulty"]
        trace.record("laya", question="difficulty", score=round(d["score"], 2), confidence=round(d["confidence"], 2),
                     acted=False)
        return f" · laya difficulty {d['score']:.1f}/3 (shadow)"

    def _stuck(self, conversation: Conversation) -> float | None:
        """Laya's probability that this turn is looping, checked every STUCK_EVERY rounds once the
        turn has STUCK_AFTER tool calls; None between checks or without Laya."""
        calls = turn_tool_calls(conversation)
        rounds = sum(1 for m in _this_turn(conversation) if m.tool_results)
        if len(calls) < STUCK_AFTER or rounds % STUCK_EVERY:
            return None
        answers = self.ask({"recent_tool_calls": calls[-8:]}, {"stuck": _STUCK})
        if not answers:
            return None
        p = float(answers["stuck"]["noul"])
        trace.record("laya", question="stuck", noul=round(p, 2), acted=p >= STUCK_AT, model=self.dealt)
        return p

    def redeal(self, why: str) -> bool:
        """Burn the dealt card and deal the next one; False when the deck is spent."""
        if self.dealt is not None:
            self._burned.add(self.dealt)
        try:
            self._deal(why)
        except ProviderError:
            return False
        return True

    def stream(self, conversation: Conversation, model: str, tools, on_text, *, cancel=None,
               reasoning=None, on_thinking=None) -> ProviderResponse:
        last = conversation.messages[-1] if conversation.messages else None
        if self.dealt is None or last is None or not last.tool_results:
            self.shuffle(model, (last.text or "") if last is not None else "")   # a fresh user message opens a new turn
        elif (p := self._stuck(conversation)) is not None and p >= STUCK_AT:
            self.redeal(f"{self.dealt} looked stuck (laya {p:.2f})")
        while True:
            provider_name, _, real_model = self.dealt.partition(":")
            try:
                response = self.registry[provider_name].stream(
                    conversation, real_model, tools, on_text, cancel=cancel, reasoning=reasoning, on_thinking=on_thinking)
            except _Cancelled:
                raise
            except Exception as e:
                if (cancel is not None and cancel.is_set()) or not self.redeal(f"{self.dealt} failed: {str(e)[:80]}"):
                    raise
                continue
            if response.usage:
                self.spent.append((self.dealt, response.usage))
            return response


def laya_report(lines: Iterable[str]) -> str:
    """How Laya's judgments lined up with how turns ended, from trace JSON lines (one session's
    lines in order, sessions one after another): the evidence for tuning STUCK_AT, and for
    promoting difficulty out of shadow mode."""
    stuck: list[tuple[float, bool, bool]] = []      # (noul, re-dealt, turn ran out of rounds anyway)
    difficulty: list[tuple[float, int, bool]] = []  # (score, tool rounds, ran out)
    pending: list[dict] = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("event")
        if kind == "turn":
            pending = []
        elif kind == "laya":
            pending.append(event)
        elif kind == "turn_end":
            ran_out, rounds = bool(event.get("ran_out")), int(event.get("rounds") or 0)
            for e in pending:
                if e.get("question") == "stuck":
                    stuck.append((float(e.get("noul", 0)), bool(e.get("acted")), ran_out))
                elif e.get("question") == "difficulty":
                    difficulty.append((float(e.get("score", 0)), rounds, ran_out))
            pending = []
    out = [f"Stuck checks (re-deal at {STUCK_AT:.2f})   checks  re-dealt  turn ran out anyway"]
    for label, low, high in (("below 0.50", 0.0, 0.5), (f"0.50 to {STUCK_AT:.2f}", 0.5, STUCK_AT), (f"{STUCK_AT:.2f} and up", STUCK_AT, 1.01)):
        band = [s for s in stuck if low <= s[0] < high]
        out.append(f"  {label:32}{len(band):>6}  {sum(s[1] for s in band):>8}  {sum(s[2] for s in band):>19}")
    out.append("  Loops that ran out under the threshold argue for lowering it; re-dealt turns that"
               " ran out anyway, or many re-deals, argue for raising it.")
    out.append("\nDifficulty (shadow)   turns  avg tool rounds  ran out")
    for label, low, high in (("0 to 1", 0, 1), ("1 to 2", 1, 2), ("2 to 3", 2, 3.01)):
        band = [d for d in difficulty if low <= d[0] < high]
        avg = f"{sum(d[1] for d in band) / len(band):.1f}" if band else "-"
        out.append(f"  {label:20}{len(band):>6}  {avg:>15}  {sum(d[2] for d in band):>7}")
    out.append("  Promote it into house once harder bands clearly take more rounds.")
    return "\n".join(out)
