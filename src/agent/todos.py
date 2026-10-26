"""Todo list persistence for Clyde's own todo list.

Todos live in ~/.clyde/todos.json so they survive across sessions and are
visible to both the agent loop (TodoWrite tool) and slash commands (/todo).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.config import clyde_home

VALID_STATUSES = {"pending", "in_progress", "completed"}


@dataclass
class TodoItem:
    content: str
    status: str = "pending"
    active_form: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["activeForm"] = d.pop("active_form")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TodoItem":
        d = dict(d)
        d["active_form"] = d.pop("activeForm", d.get("content", ""))
        return cls(
            content=str(d.get("content", "")),
            status=str(d.get("status", "pending")),
            active_form=str(d.get("active_form", d.get("content", ""))),
        )


def _path() -> Path:
    p = clyde_home() / "todos.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load() -> list[TodoItem]:
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [TodoItem.from_dict(d) for d in data if isinstance(d, dict)]


def save(todos: list[TodoItem]) -> None:
    path = _path()
    path.write_text(
        json.dumps([t.to_dict() for t in todos], indent=2), encoding="utf-8"
    )


def add(content: str, active_form: str | None = None) -> TodoItem:
    todos = load()
    item = TodoItem(content=content.strip(), active_form=active_form or content.strip())
    todos.append(item)
    save(todos)
    return item


def set_status(index: int, status: str) -> TodoItem | None:
    if status not in VALID_STATUSES:
        return None
    todos = load()
    if index < 0 or index >= len(todos):
        return None
    todos[index].status = status
    save(todos)
    return todos[index]


def remove(index: int) -> bool:
    todos = load()
    if index < 0 or index >= len(todos):
        return False
    todos.pop(index)
    save(todos)
    return True


def clear() -> None:
    save([])
