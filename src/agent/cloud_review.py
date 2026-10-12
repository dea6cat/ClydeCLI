"""A cloud model checks a weak reply from a small local model; its correction replaces the reply.

A reply is weak when it is empty, shows a pretend tool call or leaked special tokens (the model degenerated), or is a
short refusal that says the model cannot reach files or run anything (a model that was not trained for tool use does
that instead of calling the tool). These are plain text checks with no model behind them. Laya's fit score was tried as
a trigger and dropped: on real replies it rated a correct "391" at 0.08 and a refusal to read an existing file at 2.1,
so it flagged right answers and passed wrong ones.

Nothing leaves the machine unless a cloud provider is connected and the user said yes this session; the prompt names
the model and what is sent, and is asked once. CLYDE_CLOUD_REVIEW=off turns the whole thing off. A failed review
never breaks the turn: the local reply stands.
"""
from __future__ import annotations

import os
import re
from dataclasses import replace
from typing import Any

from ..providers.card_shuffle import _LEAKED_MIN, _LEAKED_TOKENS, CardShuffle
from ..tool_system.registry import ToolRegistry
from . import trace

_LOCAL = {"ollama", "lmstudio", CardShuffle.name}
_PRETEND_CALL = re.compile(r"\[TOOL_[A-Z_]+\]|<tool_call>|<function=")
# First person only ("I can't run", "I don't have access"), a missing file, or the sandbox excuse: an explanation that
# merely mentions that something cannot access something does not match.
_CANT_REACH = re.compile(
    r"\b(?:i|we)(?:\s+(?:can(?:'|’)?t|cannot|am unable to|do(?:n't| not) have)|(?:'|’)m unable to)\s+(?:\w+\s+){0,2}?(?:access|open|read|run|execute|reach)\b"
    r"|\bsandboxed (?:environment|setup)\b|\bmy sandbox\b"
    r"|\bfile\b[^\n]{0,100}\b(?:doesn(?:'|’)?t|does not|did not|didn(?:'|’)?t) exist\b|\bno such file\b", re.I)
_REFUSAL_CHARS = 800   # a long answer that mentions such a phrase is an explanation, not a refusal
_REVIEW = ("A small local model answered the user's request below. Check the answer. If it is correct and complete, "
           "reply with exactly OK. Otherwise reply with the corrected answer only, written as the final answer to the "
           "user, with no commentary about the original.\n\nRequest:\n{request}\n\nLocal model's answer:\n{reply}")
_CHARS = 6000   # of the request and of the reply sent out


def weak_reason(reply: str) -> str:
    """Why this reply looks weak, or "" when it looks fine."""
    if not reply.strip():
        return "empty reply"
    if _PRETEND_CALL.search(reply):
        return "pretend tool call"
    if len(_LEAKED_TOKENS.findall(reply)) >= _LEAKED_MIN:
        return "leaked special tokens"
    if len(reply) <= _REFUSAL_CHARS and _CANT_REACH.search(reply):
        return "says it cannot reach files or tools"
    return ""


def review_reply(request: str, reply: str, context: Any, *, registry: dict | None = None) -> str | None:
    """The corrected reply (labelled with the model that wrote it), or None to keep the local one."""
    if os.environ.get("CLYDE_CLOUD_REVIEW") == "off" or context.cloud_review_ok is False:
        return None
    why = weak_reason(reply)
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
