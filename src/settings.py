"""The user's settings files, ~/.clyde/settings.json (read and written) and settings.toml (read only), and the stores
that remember a yes or no for one exact project entry. Every feature that keeps state in them goes through here, so
they are all read the same way and written the same safe, owner-only way (MCP entries and headers can hold tokens)."""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, Callable

from src.config import clyde_home
from src.safe_write import write_json_safely


def json_path() -> Path:
    return clyde_home() / "settings.json"


def paths() -> tuple[Path, Path]:
    """Every user settings file, JSON first."""
    return json_path(), clyde_home() / "settings.toml"


def read_file(path: Path) -> Any:
    """A settings file's content, parsed by its suffix. Raises OSError or ValueError."""
    text = Path(path).read_text(encoding="utf-8")
    return tomllib.loads(text) if Path(path).suffix == ".toml" else json.loads(text)


def read_json(path: Path | None = None) -> dict[str, Any]:
    """The JSON settings file as a dict; {} when it is missing, unreadable or not an object."""
    try:
        data = read_file(path or json_path())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update(change: Callable[[dict[str, Any]], bool], path: Path | None = None) -> bool:
    """Read the JSON settings file, let `change` edit it in place, and write it back when `change` returns True.
    A file that exists but is not a JSON object raises ValueError rather than being overwritten."""
    path = path or json_path()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    changed = change(data)
    if changed:
        write_json_safely(path, data, private=True)
    return changed


class Approvals:
    """Yes/no answers for one exact project entry (a project's allow list, one MCP server), keyed by the project's
    folder plus a digest of the entry, so a changed entry is asked about again."""

    def __init__(self, filename: str) -> None:
        self.filename = filename

    def _path(self) -> Path:
        return clyde_home() / self.filename

    @staticmethod
    def key(root: Path, entry: Any, *names: str) -> str:
        digest = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:16]
        return "::".join([str(Path(root).resolve()), *names, digest])

    def _answers(self) -> dict[str, Any]:
        try:
            answers = json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return answers if isinstance(answers, dict) else {}

    def get(self, key: str) -> bool | None:
        value = self._answers().get(key)
        return value if isinstance(value, bool) else None

    def set(self, key: str, answer: bool) -> None:
        answers = self._answers()
        answers[key] = answer
        write_json_safely(self._path(), answers, indent=1, sort_keys=True)
