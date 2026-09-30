"""Grade models on what a coding agent needs: a correct tool call and a round trip back to text.

Each model gets two short requests: "call add_numbers(17, 25)", then the tool result 42 with the
expectation that the reply says 42. Results carry latency and output speed when usage is reported.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from .base import ProviderError, stream_with_retry
from .toolspec import ToolSpec
from .types import Conversation, Message, ToolResult

EVAL_TOOL = ToolSpec(
    "add_numbers",
    "Add two integers and return their sum.",
    {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
)
SYSTEM = "You are being tested. Follow the instructions exactly and keep replies short."
ASK = "Use the add_numbers tool to add 17 and 25. Call the tool; do not answer in text first."
# ponytail: one fixed probe; add harder tasks (multi-step edits, like 2B's --test) if this stops separating models
WORKERS = 4


@dataclass
class ModelScore:
    ref: str
    tool_call: bool = False
    round_trip: bool = False
    latency_s: float | None = None     # time to the first reply (the tool call)
    tokens_per_s: float | None = None  # output tokens per second over both replies, when reported
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.tool_call and self.round_trip


def _as_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def evaluate(provider: Any, model: str, ref: str) -> ModelScore:
    score = ModelScore(ref)
    convo = Conversation(SYSTEM, [Message.user(ASK)])
    out_tokens, spent = 0, 0.0
    try:
        started = time.monotonic()
        first = stream_with_retry(provider, convo, model, (EVAL_TOOL,), lambda _chunk: None, retries=0)
        score.latency_s = spent = time.monotonic() - started
        out_tokens += (first.usage or {}).get("output_tokens", 0) or 0
        call = next((c for c in first.message.tool_calls if c.name == EVAL_TOOL.name), None)
        if call is None:
            score.error = "answered without calling the tool"
            return score
        args = call.arguments or {}
        score.tool_call = {_as_int(args.get("a")), _as_int(args.get("b"))} == {17, 25}
        if not score.tool_call:
            score.error = f"called the tool with {args}"
            return score
        convo.append(first.message)
        convo.append(Message.results([ToolResult(call.id, "42")]))
        started = time.monotonic()
        second = stream_with_retry(provider, convo, model, (EVAL_TOOL,), lambda _chunk: None, retries=0)
        spent += time.monotonic() - started
        out_tokens += (second.usage or {}).get("output_tokens", 0) or 0
        score.round_trip = "42" in (second.message.text or "")
        if not score.round_trip:
            score.error = "did not use the tool result in its answer"
    except ProviderError as e:
        score.error = str(e).splitlines()[0][:160]
    except Exception as e:  # a broken adapter or network must not stop the other models
        score.error = f"{type(e).__name__}: {e}"[:160]
    if out_tokens and spent:
        score.tokens_per_s = out_tokens / spent
    return score


def evaluate_all(targets: list[tuple[Any, str, str]], on_done: Callable[[ModelScore], None] | None = None) -> list[ModelScore]:
    """Evaluate (provider, model, ref) targets, WORKERS at a time; local Ollama models run one by one."""
    local = [t for t in targets if getattr(t[0], "name", "") == "ollama"]
    remote = [t for t in targets if t not in local]

    def run(target: tuple[Any, str, str]) -> ModelScore:
        score = evaluate(*target)
        if on_done:
            on_done(score)
        return score

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        remote_scores = list(pool.map(run, remote))
    scores = [run(t) for t in local] + remote_scores
    return sorted(scores, key=lambda s: (not s.passed, not s.tool_call, s.latency_s or 1e9))
