"""Writes that a crash or a full disk cannot tear.

A plain `path.write_text(...)` truncates the file first: if the process dies halfway, the file is empty or cut off and the user's
settings, sessions or rules are gone. `write_safely` writes a temporary file beside it, flushes it to the disk (fsync), replaces
the real file in one step and flushes the folder, so a reader sees the old file or the new one, never half of either. For JSON the
last good version is kept beside it as `<name>.prev`, and `read_json_safely` falls back to it when the file is missing or cut off.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

PREV = ".prev"


def _sync_folder(folder: Path) -> None:
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return   # a platform that cannot open a folder: the file itself is already flushed
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _is_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return True


def write_safely(path: Path, text: str, *, private: bool = False, keep_prev: bool = False) -> None:
    """Replace `path` with `text` in one step. `private`: owner-only (0600) from the start; otherwise the file keeps the mode it had,
    or the usual one for a new file. `keep_prev`: first copy the current file to `<name>.prev` if it is valid JSON (a cut-off file
    never overwrites the good copy)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600 if private else (path.stat().st_mode & 0o777 if path.exists() else None)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")   # created 0600: never readable by others, even briefly
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is None:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        if keep_prev and path.is_file() and _is_json(path):
            shutil.copy2(path, path.with_name(path.name + PREV))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _sync_folder(path.parent)


def write_json_safely(path: Path, data: Any, *, indent: int | None = 2, private: bool = False, sort_keys: bool = False) -> None:
    """`write_safely` for JSON, keeping the last good version as `<name>.prev`."""
    write_safely(path, json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=False) + "\n", private=private, keep_prev=True)


def read_json_safely(path: Path) -> Any:
    """The JSON in `path`; when it is missing or cut off, the last good copy. Raises what reading `path` raised if neither works."""
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as first:
        try:
            return json.loads(path.with_name(path.name + PREV).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise first from None
