"""`/status` and `/goal`: what the session is set to, and a goal that rides in the system prompt each turn."""

from __future__ import annotations

from pathlib import Path

MAX_GOAL_CHARS = 500   # the goal is sent every turn, so it is capped; /status shows what is in effect


def clamp_goal(text: str) -> tuple[str, bool]:
    """The goal on one line, cut to MAX_GOAL_CHARS; True when it had to be cut."""
    one_line = " ".join(text.split())
    return one_line[:MAX_GOAL_CHARS], len(one_line) > MAX_GOAL_CHARS


def status_lines(*, version: str, model: str, mode: str, cwd: str | Path, session_id: str, goal: str | None,
                 terse: bool, usage: dict[str, int]) -> list[str]:
    """The `/status` block. `usage` is the session's token totals (input_tokens, output_tokens)."""
    tokens_in, tokens_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    return [
        f"ClydeCLI v{version}",
        f"  model:     {model}",
        f"  mode:      {mode}",
        f"  directory: {cwd}",
        f"  session:   {session_id}",
        f"  goal:      {goal or 'none (set one with /goal TEXT)'}",
        f"  terse:     {'on' if terse else 'off'}",
        f"  tokens:    {tokens_in:,} in, {tokens_out:,} out",
    ]
