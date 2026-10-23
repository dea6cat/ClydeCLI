"""Refine: Clyde looks back over the session and proposes a few memory notes to add or drop, so the lessons outlive the chat.

`/refine [focus]` asks the current model, with no tools, to review the conversation since the last compaction and return at most MAX_EDITS
edits, each with a quote from the user's own messages as its evidence. Clyde checks every edit (the quote must really be in a user message,
a dropped note must exist), asks before applying each one, and logs it to ~/.clyde/refine_history.jsonl so `/refine undo` can reverse the
latest. The edits go into the memory notes (src/memory.py), so they ride in the system prompt fenced as data, like any note the user saved.

Auto-refine (/settings) runs the same review before each compaction or every N turns and applies what passes the checks without asking.
Run that way it only adds notes, never drops one, and the evidence rule means text a tool returned (a web page, a file) cannot justify a
note on its own: only something the user said can.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import memory
from src.agent import trace
from src.agent.conversation import Conversation, Message
from src.config import clyde_home
from src.providers.base import stream_with_retry
from src.providers.convert import to_canonical

MAX_EDITS = 3
TRANSCRIPT_CHARS = 40_000   # the latest part of the session the review reads
MODES = ("off", "before compaction", "every 10 turns", "every 25 turns")
HISTORY = "refine_history.jsonl"

SYSTEM_PROMPT = "You review a coding session and keep the assistant's long-term notes useful. You answer with JSON only."

REVIEW_PROMPT = """Below is a coding session between a user and Clyde, a coding agent, then the notes Clyde keeps between sessions.

Propose at most {max_edits} edits to the notes that would help Clyde in future sessions: a preference or correction the user stated, a
fact about the project that took effort to find, a mistake the user had to point out. Also drop a note the session shows is wrong.
Propose nothing when nothing is worth keeping; an empty list is a good answer.

Rules:
- Each note is one plain sentence under {max_chars} characters, written as a fact or a rule ("Run the tests with python -m unittest").
- "scope" is "user" for something about the user that holds in every project, "project" for something about this project.
- "evidence" is a short exact quote, copied word for word from one of the USER messages, that shows the note is right.
- Never repeat a note that is already there. To drop a note, give its exact text.
{focus}
Answer with only a JSON list, no prose:
[{{"action": "add", "scope": "project", "note": "...", "evidence": "..."}}, {{"action": "drop", "scope": "user", "note": "...", "evidence": "..."}}]

=== SESSION ===
{transcript}
=== END SESSION ===

=== NOTES ===
{notes}
=== END NOTES ==="""


@dataclass(frozen=True)
class Edit:
    action: str     # "add" or "drop"
    scope: str      # "user" or "project"
    note: str
    evidence: str


def mode() -> str:
    """The Auto-refine choice from /settings ("off" unless set)."""
    from src.config import load_config
    value = load_config().get("auto_refine")
    return value if value in MODES else "off"


def set_mode(value: str) -> None:
    """Persist the Auto-refine choice. ValueError for anything not in MODES."""
    from src.config import load_config, save_config
    if value not in MODES:
        raise ValueError(f"auto-refine must be one of {', '.join(MODES)}")
    config = load_config()
    config["auto_refine"] = value
    save_config(config)


def every_turns(value: str) -> int | None:
    """N for an "every N turns" mode, else None."""
    match = re.fullmatch(r"every (\d+) turns", value)
    return int(match.group(1)) if match else None


def _block_text(block: Any) -> str:
    kind = getattr(block, "type", None)
    if kind == "text":
        return block.text
    if kind == "tool_use":
        return f"[ran {block.name}]"
    if kind == "tool_result":
        content = block.content if isinstance(block.content, str) else " ".join(
            str(part.get("text", "")) for part in block.content if isinstance(part, dict))
        return f"[tool result{' (error)' if block.is_error else ''}: {' '.join(content.split())[:300]}]"
    return ""


def _text(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content
    return "\n".join(t for t in (_block_text(b) for b in message.content) if t)


def _typed_by_user(message: Message) -> bool:
    """A user message the user wrote, not one carrying tool results back to the model."""
    return message.role == "user" and (isinstance(message.content, str)
                                       or not any(getattr(b, "type", None) == "tool_result" for b in message.content))


def _since_compaction(conversation: Conversation) -> list[Message]:
    from src.compact_service.messages import get_messages_after_boundary
    return [m for m in get_messages_after_boundary(conversation.messages) if not m._is_internal]


def transcript(conversation: Conversation) -> str:
    """The session since the last compaction as plain text, USER/CLYDE labelled, cut to its last TRANSCRIPT_CHARS."""
    lines = [f"{'USER' if _typed_by_user(m) else 'CLYDE'}: {_text(m).strip()}" for m in _since_compaction(conversation) if _text(m).strip()]
    return "\n\n".join(lines)[-TRANSCRIPT_CHARS:]


def _user_words(conversation: Conversation) -> str:
    """Everything the user typed this session (not tool results), whitespace-folded and lower-cased, for the evidence check."""
    typed = [_text(m) for m in _since_compaction(conversation) if _typed_by_user(m)]
    return " ".join(" ".join(typed).split()).lower()


def _notes_text(root: Path) -> str:
    rows = [f"[{scope}] {note}" for scope in memory.SCOPES for note in memory.entries(scope, root)]
    return "\n".join(rows) or "(none yet)"


def parse(text: str) -> list[dict]:
    """The JSON list in a model's answer, after any reasoning (`</think>`) and code fence; [] when there is none."""
    text = text.rsplit("</think>", 1)[-1]
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def check(raw: dict, conversation: Conversation, root: Path, *, adds_only: bool = False) -> Edit | str:
    """An Edit when `raw` passes every check, else why it was set aside."""
    action, scope = str(raw.get("action", "")).lower(), str(raw.get("scope", "")).lower()
    note, evidence = " ".join(str(raw.get("note", "")).split()), " ".join(str(raw.get("evidence", "")).split())
    # small models copy the transcript's speaker label or quote marks into the quote; a CLYDE line still fails, it is not the user's
    evidence = re.sub(r"^(user|clyde)\s*:\s*", "", evidence, flags=re.IGNORECASE).strip("\"'“”‘’. ")
    if action not in ("add", "drop") or scope not in memory.SCOPES or not note:
        return "not a usable edit"
    if adds_only and action == "drop":
        return f"auto-refine never drops a note (run /refine to drop \"{note}\")"
    if len(evidence) < 8 or evidence.lower() not in _user_words(conversation):
        return f"its evidence is not a quote from your messages: \"{note}\""
    existing = memory.entries(scope, root)
    if action == "add" and any(n.lower() == note.lower() for n in existing):
        return f"already remembered: \"{note}\""
    if action == "add" and len(note) > memory.MAX_ENTRY_CHARS:
        return f"too long to keep: \"{note[:60]}…\""
    if action == "drop" and note not in existing:
        return f"no such note to drop: \"{note}\""
    return Edit(action, scope, note, evidence)


def review(provider: Any, model: str, conversation: Conversation, root: Path, focus: str = "",
           *, adds_only: bool = False) -> tuple[list[Edit], list[str], dict | None]:
    """Ask the model for edits. Returns (edits that passed the checks, why the others were set aside, the call's usage)."""
    session = transcript(conversation)
    if not session:
        return [], [], None
    prompt = REVIEW_PROMPT.format(max_edits=MAX_EDITS, max_chars=memory.MAX_ENTRY_CHARS, transcript=session, notes=_notes_text(root),
                                  focus=f"- Focus on this, from the user: {focus}\n" if focus else "")
    request = to_canonical(Conversation.from_dict({"messages": [{"role": "user", "content": prompt}]}), SYSTEM_PROMPT, flatten_tools=True)
    response = trace.model_call(provider, model, request, lambda: stream_with_retry(provider, request, model, (), lambda _c: None, reasoning="off"))
    edits: list[Edit] = []
    skipped: list[str] = []
    for raw in parse(response.message.text or "")[:MAX_EDITS]:
        result = check(raw, conversation, root, adds_only=adds_only)
        if isinstance(result, str):
            skipped.append(result)
        elif result not in edits:
            edits.append(result)
    return edits, skipped, getattr(response, "usage", None)


def _history_path() -> Path:
    return clyde_home() / HISTORY


def _read_history() -> list[dict]:
    try:
        lines = _history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _write_history(rows: list[dict]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def apply(edit: Edit, root: Path, trigger: str) -> str:
    """Make the edit in the memory notes and log it. Returns the note as stored; ValueError (from memory) when it cannot be made."""
    if edit.action == "add":
        stored = memory.add(edit.scope, root, edit.note)
    else:
        stored = memory.forget(edit.scope, root, memory.entries(edit.scope, root).index(edit.note) + 1)
    row = {"id": secrets.token_hex(4), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "trigger": trigger,
           **asdict(edit), "note": stored, "root": str(root), "undone": False}
    _write_history([*_read_history(), row])
    return stored


def undo(root: Path) -> str:
    """Reverse the latest refine edit not yet undone (a project note only from this project). Returns what was done; ValueError when nothing."""
    rows = _read_history()
    for row in reversed(rows):
        if row.get("undone") or (row.get("scope") == "project" and row.get("root") != str(root)):
            continue
        scope, note = row.get("scope", "user"), row.get("note", "")
        if row.get("action") == "add":
            notes = memory.entries(scope, root)
            if note in notes:
                memory.forget(scope, root, notes.index(note) + 1)
            done = f"dropped the {scope} note \"{note}\""
        else:
            memory.add(scope, root, note)
            done = f"put back the {scope} note \"{note}\""
        row["undone"] = True
        _write_history(rows)
        return done
    raise ValueError("no refine edit to undo")


def describe(edit: Edit) -> str:
    verb = "Remember" if edit.action == "add" else "Forget"
    return f"{verb} ({edit.scope}): {edit.note}\n  because you said: \"{edit.evidence}\""
