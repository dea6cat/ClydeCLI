"""Folders the user has said Clyde may run the project's own tooling in, without asking each time.

Running a project's linters, language servers or build scripts runs the project's code, which is what a hostile repository
wants. So that is off by default and only the user can turn it on: the list lives in the user's own settings file
(`{"trustedFolders": ["/path"]}` in ~/.clyde/settings.json), never in a project, which could otherwise vouch for itself.
"""
from __future__ import annotations

from pathlib import Path

from .hooks import _read, settings_paths


def trusted(root: Path) -> bool:
    """Whether `root`, or a folder above it, is listed under trustedFolders in the user's settings."""
    resolved = Path(root).resolve()
    for path in settings_paths():
        try:
            data = _read(path)
        except (OSError, ValueError):
            continue
        listed = data.get("trustedFolders") if isinstance(data, dict) else None
        for entry in listed if isinstance(listed, list) else []:
            try:
                if isinstance(entry, str) and resolved.is_relative_to(Path(entry).expanduser().resolve()):
                    return True
            except OSError:
                continue
    return False
