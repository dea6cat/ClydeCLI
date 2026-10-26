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
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)   # tool output can hold secrets: owner only
            _prune(path.parent)
            path.write_text(text, encoding="utf-8")
            path.chmod(0o600)
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


def marker(full: str) -> str:
    """The tail that ends a cut section: where its full text is."""
    return f'\n...[truncated; full text: RetrieveContext(reference="{stash(full)}")]'


def cut(full: str, limit: int) -> str:
    """`full` when it fits `limit` characters, else its head plus the marker, `limit` characters at most."""
    if len(full) <= limit:
        return full
    tail = marker(full)
    return full[: max(0, limit - len(tail))].rstrip() + tail


def clip(text: str, limit: int) -> str:
    """Tool output over `limit` characters: its first and last halves of the budget around a note saying where the
    whole of it is. The end is kept because that is where a failing command says why (a test summary, a traceback)."""
    if len(text) <= limit:
        return text
    note = (f"\n…[{{omitted:,}} characters left out; the whole output: "
            f'RetrieveContext(reference="{stash(text)}")]…\n')
    keep = max(0, limit - len(note) - 12)
    head, tail = text[: keep // 2], text[len(text) - (keep - keep // 2):] if keep else ""
    return head + note.format(omitted=len(text) - len(head) - len(tail)) + tail


def _prune(folder: Path) -> None:
    cutoff = time.time() - TTL_SECONDS
    for entry in folder.glob("*.txt"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue
