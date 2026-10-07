"""Session management with persistence."""

from __future__ import annotations

from src.config import clyde_home

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from .conversation import Conversation


@dataclass
class Session:
    """Session manager with persistence."""
    session_id: str
    provider: str
    model: str
    conversation: Conversation = field(default_factory=Conversation)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # Workspace the session ran in, so /resume can list only this project's sessions.
    cwd: str = field(default_factory=lambda: str(Path.cwd()))

    def save(self):
        """Save session to disk."""
        session_dir = _sessions_dir()
        session_dir.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat()

        session_file = session_dir / f"{self.session_id}.json"

        session_data = {
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "conversation": self.conversation.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cwd": self.cwd,
        }

        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)

    @classmethod
    def load(cls, session_id: str) -> Optional['Session']:
        """Load session from disk."""
        session_file = _sessions_dir() / f"{session_id}.json"

        if not session_file.exists():
            return None

        with open(session_file, 'r') as f:
            data = json.load(f)

        return cls._from_data(data)

    @classmethod
    def list_recent(cls, cwd: str) -> list['Session']:
        """Saved sessions for one workspace, most recently updated first. Unreadable files are skipped."""
        sessions = []
        for path in _sessions_dir().glob("*.json"):
            try:
                session = cls._from_data(json.loads(path.read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if session.cwd == cwd:
                sessions.append(session)
        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)

    @classmethod
    def archive(cls, session_id: str) -> bool:
        """Move a saved session out of /resume's list (to sessions/archive/); False when there is no such session."""
        return _move(session_id, _sessions_dir(), _archive_dir())

    @classmethod
    def unarchive(cls, session_id: str) -> bool:
        """Bring an archived session back; False when it is not archived."""
        return _move(session_id, _archive_dir(), _sessions_dir())

    @classmethod
    def search(cls, cwd: str, query: str, archived: bool = False) -> list[tuple['Session', str]]:
        """This workspace's sessions whose messages contain `query` (any case), newest first, each with a snippet
        around the first match. `archived` searches the archive instead."""
        needle = query.strip().lower()
        if not needle:
            return []
        found = []
        for path in (_archive_dir() if archived else _sessions_dir()).glob("*.json"):
            try:
                session = cls._from_data(json.loads(path.read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if session.cwd != cwd:
                continue
            for message in session.conversation.messages:
                text = _message_text(message)
                at = text.lower().find(needle)
                if at >= 0:
                    start = max(0, at - 40)
                    found.append((session, " ".join(text[start:at + len(needle) + 60].split())))
                    break
        return sorted(found, key=lambda pair: pair[0].updated_at, reverse=True)

    @classmethod
    def _from_data(cls, data: dict) -> 'Session':
        return cls(
            session_id=data["session_id"],
            provider=data["provider"],
            model=data["model"],
            conversation=Conversation.from_dict(data["conversation"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            cwd=data.get("cwd", ""),   # sessions saved before cwd was recorded
        )

    @classmethod
    def create(cls, provider: str, model: str) -> 'Session':
        """Create a new session."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id, n = stamp, 1
        # Ids are to the second: a session saved (or archived) in the same second must not be overwritten by this one.
        while (_sessions_dir() / f"{session_id}.json").exists() or (_archive_dir() / f"{session_id}.json").exists():
            n += 1
            session_id = f"{stamp}_{n}"
        return cls(
            session_id=session_id,
            provider=provider,
            model=model
        )


def _sessions_dir() -> Path:
    return clyde_home() / "sessions"


def _archive_dir() -> Path:
    return _sessions_dir() / "archive"


def _move(session_id: str, source: Path, target: Path) -> bool:
    """Move one session file between folders. The id is a file name, so anything else is refused."""
    if not re.fullmatch(r"[\w.-]+", session_id) or session_id.startswith("."):
        return False
    file = source / f"{session_id}.json"
    if not file.is_file():
        return False
    target.mkdir(parents=True, exist_ok=True)
    file.replace(target / file.name)
    return True


def _message_text(message) -> str:
    if isinstance(message.content, str):
        return message.content
    return " ".join(getattr(block, "text", "") for block in message.content if isinstance(getattr(block, "text", None), str))
