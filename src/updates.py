"""`clyde update` and the quiet "an update is available" note.

Clyde is installed from its git repository, so "newest" means the newest commit on `main` (a release channel comes later).
The note never slows start-up: a background thread refreshes a cache at most once a day, and the next start reads it.
Nothing is installed without the user running `clyde update`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src import install_info
from src.config import clyde_home

REPO_URL = "git+https://github.com/dea6cat/ClydeCLI"
COMMIT_API = "https://api.github.com/repos/dea6cat/ClydeCLI/commits/main"
CHECK_EVERY_S = 24 * 3600
ENV_DISABLE = "CLYDE_NO_UPDATE_CHECK"      # "1" turns the start-up check off
_TIMEOUT_S = 5


@dataclass(frozen=True)
class Status:
    state: str                   # "current", "behind" or "unknown" (nothing to compare)
    local: str | None
    remote: str | None


def fetch_remote_commit() -> str | None:
    """The full sha of the newest commit on main, or None when GitHub cannot be reached or answers oddly."""
    request = urllib.request.Request(COMMIT_API, headers={"Accept": "application/vnd.github.sha", "User-Agent": "clyde-cli"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            sha = response.read().decode("ascii", errors="replace").strip()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else None


def compare(info: install_info.Install, remote: str | None) -> Status:
    """Is this install behind `remote`? Only an install that recorded its commit can be compared."""
    if remote is None or not info.commit:
        return Status("unknown", info.commit, remote[:7] if remote else None)
    return Status("current" if remote.startswith(info.commit) else "behind", info.commit, remote[:7])


def update_command(info: install_info.Install) -> list[str] | None:
    """The command that moves this install to the newest main, or None for a source checkout (update it with git)."""
    return {
        "uv-tool": ["uv", "tool", "install", "--force", "--python", "3.14", REPO_URL],
        "pipx": ["pipx", "install", "--force", REPO_URL],
        "pip": [sys.executable, "-m", "pip", "install", "--upgrade", REPO_URL],
    }.get(info.method)


def _cache_path() -> Path:
    return clyde_home() / "update_check.json"


def _read_cache() -> dict:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def refresh_cache(fetch: Callable[[], str | None] = fetch_remote_commit, now: float | None = None) -> bool:
    """Ask GitHub unless the cache is under a day old; True when a fresh answer was stored."""
    now = time.time() if now is None else now
    if now - float(_read_cache().get("checked_at", 0) or 0) < CHECK_EVERY_S:
        return False
    remote = fetch()
    if remote is None:
        return False
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(json.dumps({"checked_at": now, "remote": remote}), encoding="utf-8")
    except OSError:
        return False
    return True


def cached_note(info: install_info.Install | None = None) -> str | None:
    """The one-line note when the cached answer says this install is behind; None otherwise or when checks are off."""
    if os.environ.get(ENV_DISABLE) == "1":
        return None
    status = compare(info or install_info.detect(), _read_cache().get("remote"))
    if status.state != "behind":
        return None
    return f"A newer ClydeCLI is available ({status.local} → {status.remote}). Run `clyde update`."


def start_background_check() -> None:
    """Refresh the cache without making anyone wait: a daemon thread, silent on every failure."""
    if os.environ.get(ENV_DISABLE) == "1":
        return
    threading.Thread(target=refresh_cache, name="clyde-update-check", daemon=True).start()
