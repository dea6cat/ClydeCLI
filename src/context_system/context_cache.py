"""Reversible cuts: the full text behind every "...[truncated]" in the context prompt, kept on disk.

The prompt keeps the head of an over-budget section (an instruction file, the README excerpt, git status) and ends it
with a reference; the RetrieveContext tool reads the full text back. Same text, same reference, so the prompt stays
byte-identical across turns and the provider's prompt cache keeps hitting.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from ..config import clyde_home

TTL_SECONDS = 7 * 86_400
_REF = re.compile(r"ctx:([0-9a-f]{16})")


def _dir() -> Path:
    return clyde_home() / "context_cache"


def stash(text: str) -> str:
    """Keep `text` and return its reference (ctx:<16 hex>). Writing a new entry prunes the ones past the TTL."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    path = _dir() / f"{digest}.txt"
    try:
        if path.exists():
            path.touch()   # still in use: keep it past the TTL
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            _prune(path.parent)
            path.write_text(text, encoding="utf-8")
    except OSError:
        pass   # the cut still happens; RetrieveContext says the text is gone
    return f"ctx:{digest}"


def fetch(reference: str) -> str | None:
    """The text kept under `reference`, or None when it is unknown, expired or not a reference."""
    match = _REF.fullmatch(reference.strip())
    if match is None:
        return None
    try:
        return (_dir() / f"{match.group(1)}.txt").read_text(encoding="utf-8")
    except OSError:
        return None


def marker(full: str, shown: str = "") -> str:
    """The tail that ends a cut section: the headings it leaves out, and where its full text is. Without the headings a
    model can't tell the answer it needs was cut, and answers from what it sees (live: 0 of 12 runs on a rule past the cut)."""
    names = _hidden_headings(full, shown)
    hidden = f"not shown: {', '.join(names[:_MAX_HEADINGS])}{f' (+{len(names) - _MAX_HEADINGS} more)' if len(names) > _MAX_HEADINGS else ''}; " if names else ""
    return f'\n...[truncated; {hidden}full text: RetrieveContext(reference="{stash(full)}")]'


def cut(full: str, limit: int) -> str:
    """`full` when it fits `limit` characters, else its head plus the marker, `limit` characters at most."""
    if len(full) <= limit:
        return full
    head = full[:limit]
    for _ in range(4):   # a shorter head can hide one more heading, which lengthens the marker: settle in a few steps
        tail = marker(full, head)
        shorter = full[: max(0, limit - len(tail))]
        if shorter == head:
            break
        head = shorter
    return head.rstrip() + tail


_MAX_HEADINGS = 15
_HEADING = re.compile(r"#{1,6}\s+(.+)")


def _hidden_headings(full: str, shown: str) -> list[str]:
    """Markdown headings of `full` past `shown`, outside code fences, each cut to 48 characters."""
    names, fenced = [], False
    for line in full.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = None if fenced else _HEADING.fullmatch(line.strip())
        if match and line.strip() not in shown:
            names.append(match.group(1).strip()[:48])
    return names


def _prune(folder: Path) -> None:
    cutoff = time.time() - TTL_SECONDS
    for entry in folder.glob("*.txt"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue
