"""A cloud model checks a weak reply from a small local model; its correction replaces the reply.

A reply is weak when it is empty, shows a pretend tool call or leaked special tokens (the model degenerated), or
Laya rates how well it answers the request below WEAK_BELOW. That threshold is a first guess: Laya's scores sit in
a narrow band and nobody has measured this one against real turns yet, so every score is traced as a `cloud_review`
event and the threshold can be tuned from them, the way Laya's difficulty is.

Nothing leaves the machine unless a cloud provider is connected and the user said yes this session; the prompt names
the model and what is sent, and is asked once. CLYDE_CLOUD_REVIEW=off turns the whole thing off. A failed review
never breaks the turn: the local reply stands.
"""
from __future__ import annotations

import os
import re
from dataclasses import replace
from typing import Any, Callable

from ..providers import laya_client
from ..providers.card_shuffle import _LEAKED_MIN, _LEAKED_TOKENS, CardShuffle
from ..tool_system.registry import ToolRegistry
from . import trace

WEAK_BELOW = 1.3   # of 3; a guess, to tune from the traced scores
_LOCAL = {"ollama", "lmstudio", CardShuffle.name}
_PRETEND_CALL = re.compile(r"\[TOOL_[A-Z_]+\]|<tool_call>|<function=")
_FIT = {"type": "score", "instructions": "How well does `reply` answer `request`?",
        "criteria": ["Wrong or unrelated", "Partly right, with gaps or mistakes", "Mostly right", "Correct and complete"]}
_REVIEW = ("A small local model answered the user's request below. Check the answer. If it is correct and complete, "
           "reply with exactly OK. Otherwise reply with the corrected answer only, written as the final answer to the "
           "user, with no commentary about the original.\n\nRequest:\n{request}\n\nLocal model's answer:\n{reply}")
_CHARS = 6000   # of the request and of the reply sent out


def weak_reason(request: str, reply: str, ask: Callable[[Any, dict], dict | None] = laya_client.ask) -> str:
    """Why this reply looks weak, or "" when it looks fine. Laya is asked last, and only about replies that pass the plain checks."""
    if not reply.strip():
        return "empty reply"
    if _PRETEND_CALL.search(reply):
        return "pretend tool call"
    if len(_LEAKED_TOKENS.findall(reply)) >= _LEAKED_MIN:
        return "leaked special tokens"
    answers = ask({"request": request[-2000:], "reply": reply[-2000:]}, {"fit": _FIT})
    score = float(answers["fit"]["score"]) if answers else None
    trace.record("cloud_review", question="fit", score=None if score is None else round(score, 2), weak=score is not None and score < WEAK_BELOW)
    return f"laya fit {score:.1f}/3" if score is not None and score < WEAK_BELOW else ""


def review_reply(request: str, reply: str, context: Any, *, ask: Callable[[Any, dict], dict | None] = laya_client.ask,
                 registry: dict | None = None) -> str | None:
    """The corrected reply (labelled with the model that wrote it), or None to keep the local one."""
    if os.environ.get("CLYDE_CLOUD_REVIEW") == "off" or context.cloud_review_ok is False:
        return None
    why = weak_reason(request, reply, ask)
    if not why:
        return None
    try:
        from ..providers import build_registry, keys, pick_default_model, resolve
        keys.load_into_env()
        reg = registry if registry is not None else build_registry()
        ref = pick_default_model({name: p for name, p in reg.items() if name not in _LOCAL})
        resolved = resolve(reg, ref) if ref else None
        if resolved is None:
            return None   # no cloud model connected
        provider, model = resolved
        if context.cloud_review_ok is None:
            if context.permission_handler is None:
                return None
            allowed, _ = context.permission_handler(
                "CloudReview", f"The local reply looks weak ({why}). Send your request and that reply to {ref} for a check? "
                               "This is asked once per session.", None)
            context.cloud_review_ok = bool(allowed)
            if not allowed:
                return None
        from .agent_loop import run_agent_loop
        from .conversation import Conversation
        conversation = Conversation()
        conversation.add_user_message(_REVIEW.format(request=request[-_CHARS:], reply=reply[-_CHARS:]))
        sub = replace(context, read_file_fingerprints={}, todos=[])
        sub.permission_handler, sub.ask_user = (lambda *a: (False, False)), None
        text = run_agent_loop(conversation, provider, model, ToolRegistry([]), sub, max_turns=1).response_text.strip()
    except Exception as e:   # a provider error, a missing key: the local reply stands
        trace.record("cloud_review", question="review", error=f"{type(e).__name__}: {e}")
        return None
    corrected = text and text.rstrip(".").upper() != "OK"
    trace.record("cloud_review", question="review", reason=why, model=ref, corrected=bool(corrected))
    return f"{text}\n\n(corrected by {ref}; the local reply looked weak: {why})" if corrected else None
