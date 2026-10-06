from __future__ import annotations

import os
import time
from pathlib import Path

from .models import WorkspaceSnapshot

_IGNORED_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
_WALK_BUDGET_S = 1.0
_KEY_FILE_CANDIDATES = (
    "README.md",
    "CLYDE.md",
    "CLAUDE.md",
    "AGENTS.md",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "package.json",
    "Makefile",
)


def build_workspace_snapshot(
    workspace_root: str | Path,
    *,
    cwd: str | Path | None = None,
    top_level_limit: int = 12,
) -> WorkspaceSnapshot:
    root = Path(workspace_root).expanduser().resolve()
    current = Path(cwd).expanduser().resolve() if cwd is not None else root
    if not _is_within(current, root):
        current = root

    entries: list[str] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except Exception:
        children = []
    for child in children:
        if child.name in _IGNORED_NAMES:
            continue
        marker = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{marker}")
        if len(entries) >= top_level_limit:
            break

    key_files = tuple(name for name in _KEY_FILE_CANDIDATES if (root / name).exists())
    python_file_count, test_file_count = _count_python_files(root)

    return WorkspaceSnapshot(
        workspace_root=root,
        current_directory=current,
        top_level_entries=tuple(entries),
        key_files=key_files,
        python_file_count=python_file_count,
        test_file_count=test_file_count,
    )


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _count_python_files(root: Path) -> tuple[int, int]:
    """Count .py and test_*.py files, skipping ignored and hidden folders and giving up after _WALK_BUDGET_S.

    An unbounded walk of a huge root such as the home folder took minutes before the model was ever asked.
    """
    deadline = time.monotonic() + _WALK_BUDGET_S
    python = tests = 0
    for _, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _IGNORED_NAMES and not d.startswith(".")]
        for name in files:
            if name.endswith(".py"):
                python += 1
                tests += name.startswith("test_")
        if time.monotonic() > deadline:
            break
    return python, tests
