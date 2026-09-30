"""Session management with persistence."""

from __future__ import annotations

import json
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
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(
            session_id=session_id,
            provider=provider,
            model=model
        )


def _sessions_dir() -> Path:
    return Path.home() / ".clyde" / "sessions"
