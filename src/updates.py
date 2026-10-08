"""`clyde update` and the quiet "an update is available" note.

Clyde is installed from its git repository. The `latest` channel follows the newest commit on `main`; `stable` follows the
newest `vX.Y.Z` tag. Stable never suggests a downgrade: it compares versions.
Versions are read from the git server itself (`git ls-remote`), not the GitHub web API, so a push shows up at once; the API is
only the fallback when git is missing.
The note never slows start-up: a background thread refreshes a cache at most once a day, and the next start reads it.
Nothing is installed without the user running `clyde update`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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

REMOTE_URL = "https://github.com/dea6cat/ClydeCLI"
REPO_URL = "git+" + REMOTE_URL
COMMIT_API = "https://api.github.com/repos/dea6cat/ClydeCLI/commits/main"
TAGS_API = "https://api.github.com/repos/dea6cat/ClydeCLI/tags?per_page=100"
CHECK_EVERY_S = 24 * 3600
ENV_DISABLE = "CLYDE_NO_UPDATE_CHECK"      # "1" turns the start-up check off
_TIMEOUT_S = 5
_GIT_TIMEOUT_S = 10


@dataclass(frozen=True)
class Target:
    """What a channel points at: the newest commit on main (latest), or the newest tagged release (stable)."""
    channel: str
    commit: str                  # full sha
    version: str | None = None   # "0.2.0", stable only
    ref: str | None = None       # the git tag, "v0.2.0", stable only


@dataclass(frozen=True)
class Status:
    state: str                   # "current", "behind", "ahead" (newer than stable) or "unknown" (nothing to compare)
    local: str | None
    remote: str | None


_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")     # release tags only; "v1.0.0-rc1" and the like are ignored


def _semver(text: str | None) -> tuple[int, int, int] | None:
    match = _TAG.match(f"v{text.removeprefix('v')}") if text else None
    return tuple(int(g) for g in match.groups()) if match else None   # type: ignore[return-value]


def _get(url: str, accept: str) -> str | None:
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "clyde-cli"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _is_sha(text: str) -> bool:
    return len(text) == 40 and all(c in "0123456789abcdef" for c in text)


def _ls_remote(*patterns: str) -> list[tuple[str, str]] | None:
    """(sha, ref) pairs the repository's git server lists for these ref patterns, or None when git itself can't answer (not
    installed, offline, timed out). Asking git rather than the GitHub web API matters: the API answers from a 60-second public
    cache, so right after a push it still names the old commit, and without a token it allows 60 requests an hour per IP address.
    git ls-remote reads the refs themselves, and `clyde` is installed with git anyway."""
    try:
        done = subprocess.run(["git", "ls-remote", REMOTE_URL, *patterns], capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})   # never stop to ask for a password
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    pairs = [tuple(line.split("\t", 1)) for line in done.stdout.splitlines() if "\t" in line]
    return [(sha, ref) for sha, ref in pairs if _is_sha(sha)]


def fetch_remote_commit() -> str | None:
    """The full sha of the newest commit on main, or None when it cannot be learned."""
    listed = _ls_remote("refs/heads/main")
    if listed is not None:
        return next((sha for sha, ref in listed if ref == "refs/heads/main"), None)
    sha = (_get(COMMIT_API, "application/vnd.github.sha") or "").strip()   # no git: the web API, which can lag a minute
    return sha if _is_sha(sha) else None


def _newest_release(tags: dict[str, str]) -> Target | None:
    best: tuple[tuple[int, int, int], Target] | None = None
    for name, sha in tags.items():
        version = _semver(name)
        if version and _is_sha(sha) and (best is None or version > best[0]):
            best = (version, Target("stable", sha, ".".join(map(str, version)), name))
    return best[1] if best else None


def fetch_newest_tag() -> Target | None:
    """The highest `vX.Y.Z` tag, or None when there is none or it cannot be learned."""
    listed = _ls_remote("refs/tags/v*")
    if listed is not None:
        tags: dict[str, str] = {}
        for sha, ref in listed:
            name = ref.removeprefix("refs/tags/")
            peeled = name.endswith("^{}")                 # an annotated tag also lists the commit it points at: that one wins
            if peeled or name not in tags:
                tags[name.removesuffix("^{}")] = sha
        return _newest_release(tags)
    try:
        listed_api = json.loads(_get(TAGS_API, "application/vnd.github+json") or "")
    except ValueError:
        return None
    return _newest_release({tag.get("name", ""): (tag.get("commit") or {}).get("sha", "")
                            for tag in listed_api if isinstance(tag, dict)} if isinstance(listed_api, list) else {})


def fetch_target(channel: str) -> Target | None:
    if channel == "stable":
        return fetch_newest_tag()
    sha = fetch_remote_commit()
    return Target("latest", sha) if sha else None


def compare(info: install_info.Install, target: Target | None) -> Status:
    """Is this install behind the channel's target? Latest compares commits (so the install must have recorded its commit);
    stable compares versions and never suggests a downgrade."""
    if target is None:
        return Status("unknown", info.commit or info.version, None)
    if target.channel == "stable":
        mine, theirs = _semver(info.version), _semver(target.version)
        if mine is None or theirs is None:
            return Status("unknown", info.version, target.version)
        return Status("behind" if theirs > mine else "current" if theirs == mine else "ahead", info.version, target.version)
    if not info.commit:
        return Status("unknown", None, target.commit[:7])
    return Status("current" if target.commit.startswith(info.commit) else "behind", info.commit, target.commit[:7])


def update_command(info: install_info.Install, target: Target | None = None) -> list[str] | None:
    """The command that moves this install to the target (newest main when none is given), or None for a source checkout
    (update it with git)."""
    # Pin to what was checked: the tag for stable, the exact commit for latest, so the install cannot differ from the report
    # even if main moves in between. Without a target (GitHub unreachable) the newest main is installed.
    pin = (target.ref or target.commit) if target else None
    url = REPO_URL + (f"@{pin}" if pin else "")
    return {
        "uv-tool": ["uv", "tool", "install", "--force", "--python", "3.14", url],
        "pipx": ["pipx", "install", "--force", url],
        "pip": [sys.executable, "-m", "pip", "install", "--upgrade", url],
    }.get(info.method)


def _cache_path() -> Path:
    return clyde_home() / "update_check.json"


def _read_cache() -> dict:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def forget_cache() -> None:
    """Drop the cached answer, so the start-up note cannot name a commit the user just moved past."""
    _cache_path().unlink(missing_ok=True)


def refresh_cache(fetch: Callable[[str], Target | None] = fetch_target, now: float | None = None, channel: str | None = None) -> bool:
    """Ask GitHub about the configured channel unless the cache is under a day old (and for the same channel); True when a
    fresh answer was stored."""
    from src.config import get_update_channel
    channel = channel or get_update_channel()
    now = time.time() if now is None else now
    cache = _read_cache()
    if cache.get("channel") == channel and now - float(cache.get("checked_at", 0) or 0) < CHECK_EVERY_S:
        return False
    target = fetch(channel)
    if target is None:
        return False
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(json.dumps({"checked_at": now, "channel": channel, "commit": target.commit,
                                             "version": target.version, "ref": target.ref}), encoding="utf-8")
    except OSError:
        return False
    return True


def cached_note(info: install_info.Install | None = None, channel: str | None = None) -> str | None:
    """The one-line note when the cached answer says this install is behind; None otherwise or when checks are off."""
    from src.config import get_update_channel
    if os.environ.get(ENV_DISABLE) == "1":
        return None
    channel = channel or get_update_channel()
    cache = _read_cache()
    commit = cache.get("commit")
    if cache.get("channel") != channel or not isinstance(commit, str):
        return None
    status = compare(info or install_info.detect(), Target(channel, commit, cache.get("version"), cache.get("ref")))
    if status.state != "behind":
        return None
    return f"A newer ClydeCLI is available ({status.local} → {status.remote}, {channel} channel). Run `clyde update`."


def start_background_check() -> None:
    """Refresh the cache without making anyone wait: a daemon thread, silent on every failure."""
    if os.environ.get(ENV_DISABLE) == "1":
        return
    threading.Thread(target=refresh_cache, name="clyde-update-check", daemon=True).start()
