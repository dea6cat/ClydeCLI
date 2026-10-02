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
card. It also scores every request's difficulty. That score starts in shadow mode (shown on the
deal line and traced, not acted on) and is promoted into house on its own once traced turns show
it separates easy turns from hard ones; from then on harder requests start house on stronger cards.
"""
from __future__ import annotations

import json
import statistics
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
LAYA_WAIT = 30      # seconds a turn waits, once per session, for Laya to finish its cold load
# Promotion: split the shadow-scored turns at their median score; the harder half must take clearly
# more tool rounds. Laya's scores sit in a narrow band (about 1.3 to 1.9 of 3), so the test is relative.
# ponytail: one fixed bar; revisit with more traced turns
PROMOTE_MIN_TURNS = 10      # in each half
PROMOTE_RATIO = 1.5         # harder half's average rounds over the easier half's
PROMOTE_MIN_GAP = 1.0       # and at least this many rounds more
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
    """Refs weakest to strongest by the share of /eval's hand they solved; among equals the faster
    model ranks higher. Results from before the hand had 8 tasks count out of 4 until /eval runs
    again; models evaluated before any hand count as 0."""
    def key(ref: str) -> tuple[float, float]:
        r = results[ref]
        return (r.get("strength") or 0) / (r.get("hand") or 4), r.get("tokens_per_s") or 0.0
    return sorted(results, key=key)


def deck(tier: str, results: dict[str, dict], mode: str = "hold", difficulty: float | None = None) -> list[str]:
    """The order a tier deals in: first card first, then the fallbacks. For house, `difficulty` (0 to 1,
    how hard this request is relative to past ones) moves the first card from the middle toward the
    strongest; None keeps the middle card."""
    ranked = by_strength(results)
    if tier == "small":
        return ranked
    if tier == "free":
        ranked = [r for r in ranked if r.partition(":")[0] in LOCAL]
    if tier == "house" and mode != "plan" and ranked:
        # The starting card, then stronger ones, then weaker ones.
        mid = len(ranked) // 2 if difficulty is None else round(difficulty * (len(ranked) - 1))
        return ranked[mid:] + ranked[:mid][::-1]
    return ranked[::-1]


class CardShuffle:
    """Deals each user turn to a real provider from the registry it is given."""

    name = NAME

    def __init__(self, registry: dict, ask: Callable[[object, dict], dict | None] = laya_client.ask,
                 wait: Callable[[float], bool] | None = None, verdict: "Verdict | None" = None) -> None:
        self.registry = registry
        self.ask = ask
        # The real Laya needs a cold load; an injected ask (tests) answers at once.
        self.wait = wait if wait is not None else (laya_client.wait_ready if ask is laya_client.ask else (lambda _t: True))
        self._waited = False
        self._verdict = verdict                 # None: read from traced turns on first use
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
        score = self._difficulty(request)
        verdict = self.verdict()
        acts = score is not None and tier == "house" and self.mode != "plan" and verdict.promoted
        relative = verdict.relative(score) if acts and score is not None else None
        self._deck, self._burned = deck(tier, self._candidates(), self.mode, relative), set()
        if score is not None:
            trace.record("laya", question="difficulty", score=round(score, 2), acted=acts, tier=tier)
        note = "" if score is None else f" · laya difficulty {score:.1f}/3" + ("" if acts else " (shadow)")
        return self._deal(tier + note)

    def verdict(self) -> "Verdict":
        if self._verdict is None:
            self._verdict = difficulty_verdict(_traced_lines())
        return self._verdict

    def _difficulty(self, request: str) -> float | None:
        """Laya's difficulty score (0 to 3) for this request, on every tier; None without Laya.
        The first turn of a session waits for Laya's cold load, so Laya actually gets to answer."""
        if not request.strip():
            return None
        if not self._waited:
            self._waited = True
            self.wait(LAYA_WAIT)
        answers = self.ask({"request": request[-4000:], "mode": self.mode}, {"difficulty": _DIFFICULTY})
        return float(answers["difficulty"]["score"]) if answers else None

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


def _traced_lines() -> list[str]:
    """Every traced session's lines, oldest session first."""
    try:
        files = sorted(trace.traces_dir().glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        return [line for p in files for line in p.read_text(encoding="utf-8", errors="replace").splitlines()]
    except OSError:
        return []


def _judgments(lines: Iterable[str]) -> tuple[list[tuple[float, bool, bool]], list[tuple[float, int, bool, bool]]]:
    """(stuck, difficulty) judgments lined up with how their turn ended: stuck as (noul, re-dealt,
    ran out), difficulty as (score, tool rounds, ran out, acted). Turns that never ended are skipped."""
    stuck: list[tuple[float, bool, bool]] = []
    difficulty: list[tuple[float, int, bool, bool]] = []
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
                    difficulty.append((float(e.get("score", 0)), rounds, ran_out, bool(e.get("acted"))))
            pending = []
    return stuck, difficulty


class Verdict:
    """Whether Laya's difficulty score has earned a say in house, from shadow-scored turns only (turns
    it already steered would bias the evidence), plus where a new score falls among the past ones."""

    def __init__(self, shadow: list[tuple[float, int]]) -> None:
        self.scores = sorted(s for s, _ in shadow)
        self.median = statistics.median(self.scores) if self.scores else 0.0
        easy = [r for s, r in shadow if s < self.median]
        hard = [r for s, r in shadow if s >= self.median]
        self.easy_n, self.hard_n = len(easy), len(hard)
        self.easy_rounds = sum(easy) / len(easy) if easy else 0.0
        self.hard_rounds = sum(hard) / len(hard) if hard else 0.0
        self.promoted = (min(self.easy_n, self.hard_n) >= PROMOTE_MIN_TURNS
                         and self.hard_rounds >= self.easy_rounds * PROMOTE_RATIO
                         and self.hard_rounds - self.easy_rounds >= PROMOTE_MIN_GAP)

    def relative(self, score: float) -> float:
        """0 to 1: the share of past shadow scores below this one."""
        if not self.scores:
            return 0.5
        below = sum(1 for s in self.scores if s < score)
        return below / len(self.scores)

    def summary(self) -> str:
        rounds = (f"the harder half took {self.hard_rounds:.1f} tool rounds on average, the easier half "
                  f"{self.easy_rounds:.1f}") if self.easy_n and self.hard_n else "no scored turns have finished yet"
        if self.promoted:
            return f"Difficulty acts in house: {rounds}, so harder requests start on stronger cards."
        need = max(0, PROMOTE_MIN_TURNS - min(self.easy_n, self.hard_n))
        wait = (f"needs {need} more scored turn(s) in the smaller half" if need else
                f"needs the harder half to take at least {PROMOTE_RATIO:g}x and {PROMOTE_MIN_GAP:g} more rounds")
        return f"Difficulty stays in shadow: {rounds}; it {wait}."


def difficulty_verdict(lines: Iterable[str]) -> Verdict:
    _, difficulty = _judgments(lines)
    return Verdict([(score, rounds) for score, rounds, _, acted in difficulty if not acted])


def laya_report(lines: Iterable[str]) -> str:
    """How Laya's judgments lined up with how turns ended, from trace JSON lines (one session's
    lines in order, sessions one after another): the evidence for tuning STUCK_AT, and the
    verdict on promoting difficulty into house."""
    lines = list(lines)
    stuck, difficulty = _judgments(lines)
    out = [f"Stuck checks (re-deal at {STUCK_AT:.2f})   checks  re-dealt  turn ran out anyway"]
    for label, low, high in (("below 0.50", 0.0, 0.5), (f"0.50 to {STUCK_AT:.2f}", 0.5, STUCK_AT), (f"{STUCK_AT:.2f} and up", STUCK_AT, 1.01)):
        band = [s for s in stuck if low <= s[0] < high]
        out.append(f"  {label:32}{len(band):>6}  {sum(s[1] for s in band):>8}  {sum(s[2] for s in band):>19}")
    out.append("  Loops that ran out under the threshold argue for lowering it; re-dealt turns that"
               " ran out anyway, or many re-deals, argue for raising it.")
    verdict = difficulty_verdict(lines)
    shadow = [d for d in difficulty if not d[3]]
    out.append(f"\nDifficulty (shadow turns, split at score {verdict.median:.2f})   turns  avg tool rounds  ran out")
    for label, half in (("easier half", [d for d in shadow if d[0] < verdict.median]),
                        ("harder half", [d for d in shadow if d[0] >= verdict.median])):
        avg = f"{sum(d[1] for d in half) / len(half):.1f}" if half else "-"
        out.append(f"  {label:40}{len(half):>6}  {avg:>15}  {sum(d[2] for d in half):>7}")
    acted = len(difficulty) - len(shadow)
    if acted:
        out.append(f"  {acted} house turn(s) were steered by it.")
    out.append("  " + verdict.summary())
    return "\n".join(out)
