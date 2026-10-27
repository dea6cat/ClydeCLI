"""Pinned sessions: a list of session ids in ~/.clyde/bonnie/pins.json. Ids of sessions that are gone are harmless and
dropped the next time the list is written."""
from __future__ import annotations


from src.bonnie.theme import folder
from src.safe_write import read_json_safely, write_json_safely

MAX_PINS = 100


def load() -> list[str]:
    try:
        raw = read_json_safely(folder() / "pins.json")
    except (OSError, ValueError):
        return []
    return [i for i in raw if isinstance(i, str)] if isinstance(raw, list) else []


def set_pinned(session_id: str, pinned: bool) -> None:
    """Pin or unpin; a new pin goes to the top. Raises OSError when the file can't be written."""
    ids = [i for i in load() if i != session_id]
    if pinned:
        ids.insert(0, session_id)
    (folder()).mkdir(parents=True, exist_ok=True)
    write_json_safely(folder() / "pins.json", ids[:MAX_PINS], indent=None)
