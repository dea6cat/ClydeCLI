"""Deferred tools: send only the tools most turns need, and load the rest on request.

Every tool definition is sent with every request: 56 tools were about 9.5k tokens, most of it for tools a
turn never touches. The core tools below are always sent. The others are listed by name in a short index in
the system prompt, and `ToolSearch` loads a tool's definition into the following requests. A tool the model
calls without loading it first still runs (the registry knows every tool) and is loaded from then on.
Setting CLYDE_ALL_TOOLS=1 sends everything, as before.

A small local model does better with a handful of tools than with eighteen, so for local models the core set
shrinks to what the user's prompt asks for: Read, Grep and Glob always, Edit and Write for a change, Bash for
running things, the web tools for a URL or the web. The rest is one ToolSearch away, and a tool the model
calls anyway still runs.
"""
from __future__ import annotations

import os
import re
from typing import Iterable

from .registry import ToolSpec

CORE_TOOLS = frozenset(name.lower() for name in (
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "TodoWrite", "Agent", "Skill",
    "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "SendUserMessage", "StructuredOutput", "ToolSearch", "Remember",
))
LOCAL_BASE = frozenset({"read", "grep", "glob", "toolsearch"})
_INTENTS = (
    (re.compile(r"\b(edit|change|fix|write|create|add|implement|refactor|rename|update|delete|remove|rewrite|replace|patch|migrate)\b", re.I), ("edit", "write")),
    (re.compile(r"\b(run|runs|running|test|tests|build|install|execute|compile|git|commit|lint|format|script|command|terminal|shell|npm|pip|uv|flutter|dart)\b", re.I), ("bash",)),
    (re.compile(r"https?://|\b(web|website|online|internet|latest|documentation|docs)\b", re.I), ("webfetch", "websearch")),
)
_HINT_CHARS = 55
_SENTENCE_END = re.compile(r"(?<!e\.g)(?<!i\.e)\.\s")   # not the dots inside "e.g." and "i.e."


def local_tools(prompt: str) -> frozenset[str]:
    """The tools a small local model gets for this prompt (lowercase names)."""
    return LOCAL_BASE.union(*(tools for pattern, tools in _INTENTS if pattern.search(prompt)))


def is_deferred(name: str, only: frozenset[str] | None = None) -> bool:
    """Whether a tool's definition is left out of requests. `only` replaces the core set (see `local_tools`)."""
    return os.environ.get("CLYDE_ALL_TOOLS") != "1" and name.lower() not in (CORE_TOOLS if only is None else only)


def advertised(specs: Iterable[ToolSpec], loaded: set[str], only: frozenset[str] | None = None) -> list[ToolSpec]:
    """The tools to send with a request: the core ones plus any the model has loaded (lowercase names)."""
    return [s for s in specs if not is_deferred(s.name, only) or s.name.lower() in loaded]


def hint(spec: ToolSpec) -> str:
    """The first sentence of a tool's description, cut short: enough to know whether to load it."""
    first = _SENTENCE_END.split(" ".join(spec.description.split()), maxsplit=1)[0].rstrip(".")
    if len(first) <= _HINT_CHARS:
        return first
    return first[:_HINT_CHARS].rsplit(" ", 1)[0] + "…"   # at a word boundary


def index_prompt(specs: Iterable[ToolSpec], only: frozenset[str] | None = None) -> str:
    """The system-prompt section naming the tools that aren't sent; "" when everything is."""
    rows = [f"- {s.name}: {hint(s)}" for s in specs if is_deferred(s.name, only)]
    if not rows:
        return ""
    return ("## More tools\nThese exist, but their definitions aren't loaded, to save tokens. Before using one, call "
            "ToolSearch with `select:Name` (several: `select:A,B`) or keywords; it is ready on your next step.\n"
            + "\n".join(rows))
