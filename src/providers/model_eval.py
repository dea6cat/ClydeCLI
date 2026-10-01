"""Grade models on what a coding agent needs: a correct tool call and a round trip back to text.

Each model gets two short requests: "call add_numbers(17, 25)", then the tool result 42 with the
expectation that the reply says 42. Results carry latency and output speed when usage is reported.

A model that passes then plays the hand: a few harder tasks graded exactly (chained tool reads,
spotting a bug, version ordering, tracing a Python gotcha). How many it solves is its strength,
which cardShuffle ranks models by.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
WORKERS = 4

SUBMIT_TOOL = ToolSpec(
    "submit",
    "Submit your final answer.",
    {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
)
READ_TOOL = ToolSpec(
    "read_file",
    "Read a file from the project and return its contents.",
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)
_HAND_ROUNDS = 6   # model turns allowed per task (the chained task needs four)


@dataclass(frozen=True)
class HardTask:
    prompt: str
    answer: str
    files: dict[str, str] | None = None   # offered through read_file when set


# ponytail: four fixed tasks; add more (or harder ones) when strong models start tying at 4/4.
HAND = (
    HardTask("Using read_file (start with README.md), find the port the service listens on, "
             "then call submit with just the number.", "8431",
             {"README.md": "Service docs. The listening port is configured in config/app.toml.\n",
              "config/app.toml": "[server]\nport_from = \"env/PORT\"\n",
              "env/PORT": "8431\n"}),
    HardTask("This function should return the last n items of a list, oldest first. Which line has the bug? "
             "Call submit with just the line number.\n\n"
             "1  def last_n(items, n):\n2      \"\"\"Return the last n items, oldest first.\"\"\"\n"
             "3      if n <= 0:\n4          return []\n5      return items[len(items) - n - 1:]", "5"),
    HardTask("Sort these versions from oldest to newest by semantic versioning, then call submit with the third "
             "one: 1.10.0, 1.9.2, 1.2.10, 10.0.0, 1.2.9", "1.9.2"),
    HardTask("What does this Python program print? Call submit with just the output.\n\n"
             "def add(x, acc=[]):\n    acc.append(x)\n    return len(acc)\n\n"
             "print(add(1) + add(2) + add(3, []))", "4"),
)


@dataclass
class ModelScore:
    ref: str
    tool_call: bool = False
    round_trip: bool = False
    latency_s: float | None = None     # time to the first reply (the tool call)
    tokens_per_s: float | None = None  # output tokens per second over both replies, when reported
    strength: int | None = None        # HAND tasks solved; None when the basic check failed
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.tool_call and self.round_trip

    @property
    def kind(self) -> str:
        """Why it failed: "tools" and "unavailable" say the model won't work for ClydeCLI;
        "transient" (credits, rate limits, server errors) says nothing about the model itself."""
        if self.passed:
            return "ok"
        e = self.error.lower()
        if re.search(r"http (402|429|5\d\d)|rate.?limit|credits|timed? ?out|overloaded", e):
            return "transient"
        if "tool" in e and ("support" in e or "endpoint" in e) or not self.tool_call and "without calling" in e:
            return "tools"
        if re.search(r"http 40[0134]|not found|not available|no longer available|no endpoints", e):
            return "unavailable"
        return "answer"

    @property
    def short_note(self) -> str:
        return {"ok": "", "transient": "credits or rate limit", "tools": "no tool calling",
                "unavailable": "not available", "answer": self.error[:40]}[self.kind]


def _as_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _norm(answer: Any) -> str:
    return str(answer).strip().strip("\"'`. ").lower()


def play(provider: Any, model: str, task: HardTask) -> bool:
    """Whether the model submits the task's exact answer within _HAND_ROUNDS turns. Any error loses."""
    tools = (SUBMIT_TOOL, READ_TOOL) if task.files else (SUBMIT_TOOL,)
    convo = Conversation(SYSTEM, [Message.user(task.prompt)])
    try:
        for _ in range(_HAND_ROUNDS):
            reply = stream_with_retry(provider, convo, model, tools, lambda _chunk: None, retries=0)
            calls = reply.message.tool_calls
            submitted = next((c for c in calls if c.name == SUBMIT_TOOL.name), None)
            if submitted is not None:
                return _norm((submitted.arguments or {}).get("answer", "")) == _norm(task.answer)
            if not calls:
                return False
            convo.append(reply.message)
            convo.append(Message.results([
                ToolResult(c.id, (task.files or {}).get(str((c.arguments or {}).get("path", "")).lstrip("./"),
                                                        "No such file.")) for c in calls]))
    except Exception:
        return False
    return False


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
    if score.passed:
        score.strength = sum(play(provider, model, task) for task in HAND)
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
    return sorted(scores, key=lambda s: (not s.passed, not s.tool_call, -(s.strength or 0), s.latency_s or 1e9))


def results_path() -> Path:
    return Path.home() / ".clyde" / "model_evals.json"


def load_results() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(results_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_results(scores: list[ModelScore]) -> None:
    """Merge these results into ~/.clyde/model_evals.json (newest result per model wins)."""
    data = load_results()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for sc in scores:
        data[sc.ref] = {"passed": sc.passed, "kind": sc.kind, "note": sc.error[:200], "at": stamp,
                        "strength": sc.strength, "tokens_per_s": sc.tokens_per_s}
    path = results_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def hidden_refs(results: dict[str, dict[str, Any]] | None = None) -> set[str]:
    """Models whose last evaluation showed they don't work (no tools, or not available)."""
    results = load_results() if results is None else results
    return {ref for ref, r in results.items() if not r.get("passed") and r.get("kind") in ("tools", "unavailable", "answer")}
