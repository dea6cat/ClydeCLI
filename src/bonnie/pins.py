"""Pinned sessions: a list of session ids in ~/.clyde/bonnie/pins.json. Ids of sessions that are gone are harmless and
dropped the next time the list is written."""
from __future__ import annotations

import json

from src.bonnie.theme import folder

MAX_PINS = 100


def load() -> list[str]:
    try:
        raw = json.loads((folder() / "pins.json").read_text())
    except (OSError, ValueError):
        return []
    return [i for i in raw if isinstance(i, str)] if isinstance(raw, list) else []


def set_pinned(session_id: str, pinned: bool) -> None:
    """Pin or unpin; a new pin goes to the top. Raises OSError when the file can't be written."""
    ids = [i for i in load() if i != session_id]
    if pinned:
        ids.insert(0, session_id)
    (folder()).mkdir(parents=True, exist_ok=True)
    (folder() / "pins.json").write_text(json.dumps(ids[:MAX_PINS]))
