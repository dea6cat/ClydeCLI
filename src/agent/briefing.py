"""Request briefing: Clyde grills the user with clarifying questions until a request is complete.

A briefing session turns a vague user request into a well-formed spec by asking
targeted follow-up questions one at a time. Clyde uses its own model (no tools)
to ask the questions and to decide when the spec is complete. When it is, Clyde
synthesizes a structured spec and offers to hand it to the orchestration system
(master/advisor/worker roles over discovered harnesses).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from src.config import clyde_home
from src.providers.base import stream_with_retry
from src.providers.types import Conversation, Message

MAX_QUESTIONS = 10
MAX_ANSWER_CHARS = 4000


def briefing_dir() -> Path:
    return clyde_home() / "briefing"


@dataclass(frozen=True)
class BriefingState:
    """Where a briefing session is: initial, questioning, or complete."""
    initial_request: str
    questions_asked: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    spec: str | None = None
    complete: bool = False


# System prompt that puts Clyde into briefing mode: ask questions, never tools.
BRIEFING_SYSTEM = """You are Clyde in briefing mode. Your job is to turn the user's request into a complete,
well-formed spec before anything is built or run. Do not execute tools. Do not write code.
Ask one clarifying question at a time, focused on the biggest remaining gap: what the request
is for, who it is for, where it runs, what data it touches, what success looks like, and any
constraints (budget, timeline, security, models, platforms). Keep questions short and concrete.
When the spec is complete, summarize it as a structured brief and end with the word READY on its
own line."""

BRIEFING_CONTINUE = """You are mid-briefing. The user has answered your last question. Ask the next most important
clarifying question, or if the spec is now complete, summarize it as a structured brief and end with
the word READY on its own line."""

BRIEFING_SYNTHESIZE = """Turn this briefing into a single well-formed spec. Include: goal, inputs, outputs, constraints,
success criteria, and any open decisions. Answer with only the spec, no preamble."""


def _model_text(provider: Any, model: str, prompt: str) -> str:
    request = Conversation(system_prompt=BRIEFING_SYSTEM, messages=[Message.user(prompt)])
    return stream_with_retry(provider, request, model, (), lambda _c: None, reasoning="off").message.text or ""


def _transcript(state: BriefingState) -> str:
    lines: list[str] = [f"Original request: {state.initial_request}"]
    for i, q in enumerate(state.questions_asked):
        lines.append(f"Q: {q}")
        if i < len(state.answers):
            lines.append(f"A: {state.answers[i]}")
    return "\n".join(lines)


def _is_ready(text: str) -> bool:
    return "READY" in (line.strip() for line in text.splitlines())


def synthesize_spec(provider: Any, model: str, state: BriefingState) -> str:
    """Produce the final well-formed spec from a completed briefing."""
    text = _model_text(provider, model, f"{BRIEFING_SYNTHESIZE}\n\nBriefing:\n{_transcript(state)}")
    return "\n".join(line for line in text.splitlines() if line.strip() != "READY").strip()   # the marker is for us, not the spec


def start_briefing(initial_request: str) -> BriefingState:
    """Create a new briefing session for `initial_request`."""
    return BriefingState(initial_request=initial_request)


def ask_next_question(provider: Any, model: str, state: BriefingState) -> tuple[str, BriefingState]:
    """Ask the next clarifying question. Returns (question, updated state); when Clyde says the spec is complete,
    the first item is the synthesized spec and the state is complete. After MAX_QUESTIONS the spec is written from
    what is known, so a briefing always ends."""
    prompt = BRIEFING_CONTINUE if state.questions_asked else BRIEFING_SYSTEM
    text = "" if len(state.questions_asked) >= MAX_QUESTIONS else _model_text(provider, model, f"{prompt}\n\nBriefing so far:\n{_transcript(state)}")
    if len(state.questions_asked) >= MAX_QUESTIONS or _is_ready(text):
        spec = synthesize_spec(provider, model, state)
        return spec, replace(state, spec=spec, complete=True)
    question = "\n".join(line for line in text.splitlines() if line.strip() != "READY").strip()
    return question, replace(state, questions_asked=[*state.questions_asked, question])


def record_answer(state: BriefingState, answer: str) -> BriefingState:
    """Record the user's answer to the last question."""
    if not state.questions_asked or len(state.answers) >= len(state.questions_asked):
        return state
    return replace(state, answers=[*state.answers, answer[:MAX_ANSWER_CHARS]])


def parse_briefing_args(args: str) -> str | None:
    """Extract the initial request from /brief args; None when empty."""
    args = args.strip()
    return args or None


# --- File persistence for multi-turn briefing sessions ---

def _state_path(session_id: str | None = None) -> Path:
    folder = briefing_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (f"{session_id}.json" if session_id else "current.json")


def save_state(state: BriefingState, session_id: str | None = None) -> Path:
    """Persist a briefing state to disk. Returns the path written."""
    path = _state_path(session_id)
    data = {
        "initial_request": state.initial_request,
        "questions_asked": state.questions_asked,
        "answers": state.answers,
        "spec": state.spec,
        "complete": state.complete,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_state(session_id: str | None = None) -> BriefingState | None:
    """Load a briefing state from disk, or None if none exists."""
    path = _state_path(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BriefingState(
            initial_request=data.get("initial_request", ""),
            questions_asked=data.get("questions_asked", []),
            answers=data.get("answers", []),
            spec=data.get("spec"),
            complete=data.get("complete", False),
        )
    except (json.JSONDecodeError, OSError):
        return None


def clear_state(session_id: str | None = None) -> None:
    """Remove a persisted briefing state."""
    path = _state_path(session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
