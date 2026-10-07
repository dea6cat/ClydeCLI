"""Choosing the project Bonny works in: browse folders, make a new one, and remember the recent ones
(~/.clyde/bonny/projects.json). Everything raises ValueError with a sentence the page can show."""
from __future__ import annotations

import json
from pathlib import Path

from src.bonny.theme import folder

MAX_RECENT = 12
MAX_DIRS = 500
_BAD_NAME = set('/\\\0')


def _dir(path: object) -> Path:
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        raise ValueError("pick a folder")
    found = Path(path).expanduser()
    if not found.is_absolute():
        raise ValueError("the folder must be a full path")
    found = found.resolve()
    if not found.is_dir():
        raise ValueError("that folder doesn't exist")
    return found


def recent() -> list[str]:
    try:
        raw = json.loads((folder() / "projects.json").read_text())
    except (OSError, ValueError):
        return []
    return [p for p in raw if isinstance(p, str) and Path(p).is_dir()] if isinstance(raw, list) else []


def remember(path: Path) -> None:
    """Put `path` first in the recent list. A list that can't be saved is only a lost convenience."""
    ids = [str(path), *[p for p in recent() if p != str(path)]][:MAX_RECENT]
    try:
        folder().mkdir(parents=True, exist_ok=True)
        (folder() / "projects.json").write_text(json.dumps(ids))
    except OSError:
        pass


def browse(path: object) -> dict:
    """The folder at `path` and its subfolders (hidden ones left out), with its parent for an Up button."""
    here = _dir(path)
    try:
        names = sorted((p.name for p in here.iterdir() if p.is_dir() and not p.name.startswith(".")), key=str.lower)
    except OSError as e:
        raise ValueError(f"can't read that folder: {e.strerror or e}") from e
    return {"path": str(here), "parent": str(here.parent) if here.parent != here else None, "dirs": names[:MAX_DIRS],
            "home": str(Path.home()), "recent": recent()}


def make_dir(parent: object, name: object) -> Path:
    """A new folder called `name` inside `parent`; refuses names that would leave `parent` and folders that already exist."""
    base = _dir(parent)
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 100 or name in (".", "..") or _BAD_NAME & set(name):
        raise ValueError("the folder name can't be empty or contain slashes")
    target = base / name
    try:
        target.mkdir()
    except FileExistsError as e:
        raise ValueError("a folder with that name already exists") from e
    except OSError as e:
        raise ValueError(f"couldn't create the folder: {e.strerror or e}") from e
    return target.resolve()


def choose(path: object) -> Path:
    return _dir(path)
