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

import hashlib
import json
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, Iterable

from .. import activity
from ..agent import trace
from ..config import clyde_home
from . import laya_client
from .base import ProviderError, ProviderResponse, _Cancelled
from .model_eval import load_results
from .types import Conversation, Role

NAME = "cardShuffle"
TIERS = ("high-roller", "house", "free", "small")
LOCAL = ("ollama", "lmstudio")

# Council: `cardShuffle:<tier> council` asks the tier's top models the same question at once, Laya picks the best answer.
COUNCIL = "council"
COUNCIL_SIZE = 4
TOOL_MARKUP = "<tool_call>"   # tools are off in a council, but some models still write a call as text; that is not an answer
COUNCIL_DEADLINE_S = 90     # ponytail: one fixed deadline; make it adaptive if slow providers are common
COUNCIL_READING_DEADLINE_S = 240   # members that read the repo before answering need longer
COUNCIL_LAYA_WAIT_S = 60    # a council turn waits this long for Laya to finish loading; ranking is its point
REPLY_CHARS = 4000          # of each answer shown to Laya
VOTES_FILE = "council_votes.jsonl"
_JUDGE = "Which reply answers `request` most correctly and helpfully?"

STUCK_AFTER = 6     # tool calls in a turn before Laya first looks for a loop
STUCK_EVERY = 3     # tool rounds between looks
STUCK_AT = 0.8      # ponytail: from one replayed loop (0.95) vs normal progress (0.38); tune from traces
_STUCK = {"type": "noul", "instructions": "Is the agent repeating the same tool calls in `recent_tool_calls`, "
                                          "with the same or empty results, without making progress?"}
# Cooldowns, after freellmapi's benching: later turns skip a card that hit a quota, for the provider's Retry-After when it
# gave one (capped at an hour), else these lengths.
RATE_LIMIT_BENCH_S = 90        # 429
OUT_OF_CREDIT_BENCH_S = 3600   # 402
EMPTY_BENCH_S = 600            # a model that answered nothing
# Special tokens that leaked into the text ("<|open|>…<|close|>"): the model degenerated, and that is not an answer.
_LEAKED_TOKENS = re.compile(r"<\|[^|>\s]{1,24}\|>")
_LEAKED_MIN = 2
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


def split_council(model: str) -> tuple[str, bool]:
    """("high-roller", True) for "high-roller council"; any other string comes back unchanged and False."""
    words = model.split()
    return (words[0], True) if len(words) == 2 and words[1] == COUNCIL else (model, False)


def rank(ask: Callable[[object, dict], dict | None], request: str, answers: dict[str, str]) -> dict[str, float] | None:
    """Laya's chance that each answer (keyed by model ref) is the best one, or None when Laya can't say.
    Laya favours some option slots, so it is asked once per rotation of the options and the chances are averaged."""
    refs = list(answers)
    k = len(refs)
    labels = [chr(ord("a") + i) for i in range(k)]
    question = {"type": "choice", "instructions": _JUDGE, "criteria": {l: answers[r][:REPLY_CHARS] for l, r in zip(labels, refs)}}
    got = ask({"request": request[-4000:]}, {f"r{i}": dict(question, option_order=[(j + i) % k for j in range(k)]) for i in range(k)})
    if not got:
        return None
    try:
        return {r: sum(a["probabilities"][l] for a in got.values()) / k for l, r in zip(labels, refs)}
    except (KeyError, TypeError):
        return None


def record_vote(council: dict, ref: str, vote: int) -> None:
    """Append one up (+1) or down (-1) vote on a council answer to ~/.clyde/council_votes.jsonl. Votes stay on this machine."""
    answer = next((a for a in council["answers"] if a["ref"] == ref), None)
    if answer is None or vote not in (1, -1):
        raise ValueError(f"no answer {ref!r} in this council, or vote is not +1/-1")
    line = {"ts": time.time(), "prompt": hashlib.sha256(council["request"].encode()).hexdigest()[:16], "tier": council["tier"],
            "ref": ref, "p": answer["p"], "vote": vote}
    path = clyde_home() / VOTES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


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
        self._benched: dict[str, float] = {}    # ref -> monotonic time its cooldown ends; outlives the turn
        self._now: Callable[[], float] = time.monotonic
        # Set by the REPL: (provider, model, cancel) -> a council member's answer after reading the repo with read-only tools.
        # Without it, members answer from the prompt alone, tools off.
        self.investigate: Callable[[object, str, threading.Event], ProviderResponse] | None = None
        self.last_council: dict | None = None   # the latest council turn's answers and scores, for UIs; the REPL ignores it

    def is_available(self) -> bool:
        return bool(self._candidates(check=False))

    def list_models(self) -> list[str]:
        return [*TIERS, *(f"{t} {COUNCIL}" for t in TIERS)]

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

    def _ready(self, ref: str, now: float) -> bool:
        """Not benched itself, nor through its provider (an account that is out of credit is out for every model on it)."""
        return self._benched.get(ref, 0.0) <= now and self._benched.get(ref.partition(":")[0], 0.0) <= now

    def _deal(self, why: str) -> str:
        now = self._now()
        card = next((r for r in self._deck if r not in self._burned and self._ready(r, now)), None)
        if card is None:
            raise ProviderError(NAME, "no model left to deal: every candidate failed or none passed /eval "
                                      "(run /eval, then try again)")
        self.dealt = card
        activity.set(f"waiting for {card}")
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

    def _await_laya(self) -> None:
        """The first Laya question of a session waits for its cold load, so Laya actually gets to answer."""
        if not self._waited:
            self._waited = True
            activity.set(f"waiting up to {LAYA_WAIT}s for Laya to load")
            self.wait(LAYA_WAIT)

    def _difficulty(self, request: str) -> float | None:
        """Laya's difficulty score (0 to 3) for this request, on every tier; None without Laya.
        The first turn of a session waits for Laya's cold load, so Laya actually gets to answer."""
        if not request.strip():
            return None
        self._await_laya()
        activity.set("asking Laya how hard this is")
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

    def redeal(self, why: str, bench_s: float = 0.0, whole_provider: bool = False) -> bool:
        """Burn the dealt card and deal the next one; False when the deck is spent.
        bench_s keeps the card out of later turns' deals for that long (it is still burned for this turn);
        whole_provider benches every model of its provider, for a failure that belongs to the account."""
        if self.dealt is not None:
            self._burned.add(self.dealt)
            if bench_s:
                self._benched[self.dealt.partition(":")[0] if whole_provider else self.dealt] = self._now() + bench_s
        try:
            self._deal(why)
        except ProviderError:
            return False
        return True

    def _council(self, conversation: Conversation, tier: str, request: str, on_text, cancel, reasoning) -> ProviderResponse | None:
        """Ask the tier's top models at once (reading the repo with read-only tools when the REPL set `investigate`, else tools off), and return the answer Laya rates best; None when fewer than two
        models are available (the turn is then dealt normally). The scored answers are left in `last_council`."""
        if tier not in TIERS:
            raise ProviderError(NAME, f"unknown tier '{tier}' (one of {', '.join(TIERS)})")
        now = self._now()
        roster = [r for r in deck(tier, self._candidates(), self.mode) if self._ready(r, now)][:COUNCIL_SIZE]
        if len(roster) < 2:
            return None
        stop = threading.Event()   # ends the models still running when the deadline passes or the user cancels

        def ask_one(ref: str) -> ProviderResponse:
            name, _, real = ref.partition(":")
            if self.investigate is not None:
                return self.investigate(self.registry[name], real, stop)
            return self.registry[name].stream(conversation, real, (), lambda _: None, cancel=stop, reasoning=reasoning)

        pool = ThreadPoolExecutor(len(roster))
        pending = {pool.submit(ask_one, ref): ref for ref in roster}
        answers: dict[str, ProviderResponse] = {}
        failed: dict[str, str] = {}
        deadline = self._now() + (COUNCIL_DEADLINE_S if self.investigate is None else COUNCIL_READING_DEADLINE_S)
        while pending and self._now() < deadline and not (cancel is not None and cancel.is_set()):
            activity.set(f"council: {len(answers) + len(failed)} of {len(roster)} models have answered")
            done, _ = wait(pending, timeout=0.2)
            for future in done:
                ref = pending.pop(future)
                try:
                    response = future.result()
                except Exception as e:
                    failed[ref] = str(e)[:80]
                    if bench := _bench_for(e):
                        self._benched[ref] = self._now() + bench
                    continue
                if response.usage:
                    self.spent.append((ref, response.usage))
                text = response.message.text or ""
                if text.strip() and not response.message.tool_calls and TOOL_MARKUP not in text:
                    answers[ref] = response
                else:
                    failed[ref] = "returned no answer"
        stop.set()
        pool.shutdown(wait=False, cancel_futures=True)
        if cancel is not None and cancel.is_set():
            raise _Cancelled()
        failed.update({ref: "missed the deadline" for ref in pending.values()})
        if not answers:
            raise ProviderError(NAME, "council: no model answered (" + "; ".join(f"{r}: {why}" for r, why in failed.items()) + ")")
        order = [r for r in roster if r in answers]
        activity.set(f"waiting up to {COUNCIL_LAYA_WAIT_S}s for Laya to load")
        self.wait(COUNCIL_LAYA_WAIT_S)
        activity.set("asking Laya which answer is best")
        chances = rank(self.ask, request, {r: answers[r].message.text for r in order}) if len(order) > 1 else None
        winner = max(order, key=lambda r: chances[r]) if chances else order[0]
        self.last_council = {"tier": tier, "request": request, "ranked": chances is not None, "failed": failed,
                             "answers": [{"ref": r, "text": answers[r].message.text, "p": chances[r] if chances else None} for r in order]}
        self.dealt = winner
        if self.on_deal is not None:
            self.on_deal(winner, f"council, {len(order)} of {len(roster)} answered · " + (f"{chances[winner]:.0%} best" if chances else "unranked"))
        on_text(answers[winner].message.text)
        return answers[winner]

    def stream(self, conversation: Conversation, model: str, tools, on_text, *, cancel=None,
               reasoning=None, on_thinking=None) -> ProviderResponse:
        last = conversation.messages[-1] if conversation.messages else None
        tier, council = split_council(model)
        fresh = self.dealt is None or last is None or not last.tool_results   # a fresh user message opens a new turn
        request = (last.text or "") if last is not None else ""
        self.last_council = None
        if council and fresh and (response := self._council(conversation, tier, request, on_text, cancel, reasoning)) is not None:
            return response
        if fresh:
            self.shuffle(tier, request)
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
                if (cancel is not None and cancel.is_set()) or not self.redeal(f"{self.dealt} failed: {str(e)[:80]}", _bench_for(e), getattr(e, "status", None) == 402):
                    raise
                continue
            if response.usage:
                self.spent.append((self.dealt, response.usage))
            empty = not (response.message.text or "").strip() and not response.message.tool_calls
            garbled = len(_LEAKED_TOKENS.findall(response.message.text or "")) >= _LEAKED_MIN
            if (empty or garbled) and not (cancel is not None and cancel.is_set()) \
                    and self.redeal(f"{self.dealt} returned {'garbled text' if garbled else 'no answer'}", EMPTY_BENCH_S):
                continue
            return response


def _bench_for(error: Exception) -> float:
    """How long a failed card sits out later turns: a spent quota stays spent, a rate limit clears in minutes."""
    asked = getattr(error, "retry_after", None)
    if asked:
        return min(asked, OUT_OF_CREDIT_BENCH_S)
    status = getattr(error, "status", None)
    return {429: RATE_LIMIT_BENCH_S, 402: OUT_OF_CREDIT_BENCH_S}.get(status, 0.0)


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
