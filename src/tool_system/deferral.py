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
    # The tools a small model never asks ToolSearch for (0 of about 70 trials on two models): when the prompt names the job, send the tool.
    (re.compile(r"\b(remember|memorize|keep in mind|from now on|note that)\b", re.I), ("remember",)),
    (re.compile(r"\b(todos?|to-do|task list|checklist)\b", re.I), ("todowrite",)),
    (re.compile(r"\bplan mode\b|\b(make|give|write|draft) (me )?a plan\b|\bplan before\b", re.I), ("enterplanmode", "exitplanmode")),
    (re.compile(r"\b(remind|reminders?|schedule|scheduled|cron|recurring|every \d+ (seconds?|minutes?|hours?|days?))\b", re.I), ("croncreate", "cronlist", "crondelete")),
    (re.compile(r"\b(ask me|let me (choose|pick)|options to pick|multiple.?choice)\b", re.I), ("askuserquestion",)),
    (re.compile(r"\b(csv|tsv|parquet|xlsx|dataset|data file)\b", re.I), ("data",)),
    (re.compile(r"\b(code ?map|call graph|callers?|callees?|who calls)\b", re.I), ("map",)),
)
VERIFY_PROMPT = """## Check code before you present it
When you write or change code that uses a library, API or version you are not sure of, check it first:
1. Read or Grep the project and the installed package for the real names and signatures.
2. If it can run, run it with Bash: the tests, or a one-line import.
3. If that does not settle it, look up the documentation for that version with WebSearch or WebFetch.
Load a tool with ToolSearch first if it is listed under "More tools". Skip this for code that only uses the language itself.
After checking, say what you checked and what you could not confirm."""
# The descriptions in the index help a model that can read them and distract one that cannot. Qwen2.5-Coder 3B, handed the
# Remember tool, called it 1 time in 6 with the full index (it answered "Remembered: ..." and saved nothing) and 6 in 6
# without; across six routed tools its first-turn calls were 39/60 against 50/60. Qwen3 4B did well with the full index, and
# capable hosted models found hidden tools 89% of the time with it against 55% without. Ollama reports the first as 3.4B and
# the second as 4.0B, so the line sits between them. Two models measured, so move it only with more evidence.
NAMES_ONLY_UP_TO_BILLIONS = 3.7
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


def index_prompt(specs: Iterable[ToolSpec], only: frozenset[str] | None = None, names_only: bool = False) -> str:
    """The system-prompt section naming the tools that aren't sent; "" when everything is. `names_only` drops the
    descriptions (about 400 tokens fewer): see NAMES_ONLY_UP_TO_BILLIONS."""
    deferred = [s for s in specs if is_deferred(s.name, only)]
    if not deferred:
        return ""
    if names_only:
        return ("## More tools\nNot loaded, to save tokens: " + ", ".join(s.name for s in deferred)
                + ". Call ToolSearch with `select:Name` (several: `select:A,B`) before using one.")
    rows = [f"- {s.name}: {hint(s)}" for s in deferred]
    return ("## More tools\nThese exist, but their definitions aren't loaded, to save tokens. Before using one, call "
            "ToolSearch with `select:Name` (several: `select:A,B`) or keywords; it is ready on your next step.\n"
            + "\n".join(rows))
