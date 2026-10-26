from __future__ import annotations

import subprocess
from pathlib import Path

from ..security.git_safe import git_cmd, git_env
from .context_cache import cut
from .models import GitContext

_MAX_STATUS_CHARS = 2_000


def collect_git_context(workspace_root: str | Path) -> GitContext:
    cwd = Path(workspace_root).expanduser().resolve()

    top = _run_git(cwd, "rev-parse", "--show-toplevel")
    if top is None or top.returncode != 0:
        return GitContext(available=False, error="not a git repository")

    repo_root_text = (top.stdout or "").strip()
    if not repo_root_text:
        return GitContext(available=False, error="unable to resolve git root")
    repo_root = Path(repo_root_text).resolve()

    branch = _read_git_text(repo_root, "symbolic-ref", "--short", "HEAD")
    if not branch:
        branch = _read_git_text(repo_root, "rev-parse", "--short", "HEAD")

    status = _read_git_text(repo_root, "status", "--short", "--branch")
    if status:
        status = cut(status, _MAX_STATUS_CHARS)

    recent_commit = _read_git_text(repo_root, "log", "-1", "--oneline", "--decorate")

    return GitContext(
        available=True,
        repo_root=repo_root,
        branch=branch or None,
        status=status or None,
        recent_commit=recent_commit or None,
    )


def _read_git_text(cwd: Path, *args: str) -> str | None:
    result = _run_git(cwd, *args)
    if result is None or result.returncode != 0:
        return None
    text = (result.stdout or "").strip()
    return text or None


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            git_cmd(*args),
            cwd=str(cwd),
            env=git_env(),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
