"""Discover: the plugins listed by two public repos, pooled into one list.

Both publish a `marketplace.json` (name, description, source per plugin). Clyde fetches them keylessly
from raw.githubusercontent.com, caches the pool for a day, and keeps serving the cache when the network
is down. Nothing here is a Clyde-run marketplace: it is a read of those repos, shown with their names.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from src.config import clyde_home

# (label, "owner/repo", path of the catalog file)
REPOS = (
    ("Anthropic", "anthropics/claude-plugins-official", ".claude-plugin/marketplace.json"),
    ("Cursor", "cursor/plugins", ".cursor-plugin/marketplace.json"),
)
TTL_S = 24 * 3600
_TIMEOUT_S = 10


@dataclass(frozen=True)
class Entry:
    name: str
    description: str
    origin: str          # "Anthropic" or "Cursor"
    category: str
    url: str             # git URL to clone
    subdir: str = ""     # folder of the plugin inside that clone


def _cache_path():
    return clyde_home() / "plugin_catalog.json"


def _fetch(repo: str, path: str) -> dict[str, Any]:
    request = urllib.request.Request(f"https://raw.githubusercontent.com/{repo}/main/{path}", headers={"User-Agent": "clyde-cli"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def parse(origin: str, repo: str, catalog: dict[str, Any]) -> list[Entry]:
    """Entries of one catalog. A source is a folder of that repo, a git URL, or a folder of a git URL;
    any other kind of source is left out."""
    found = []
    for item in catalog.get("plugins") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        source = item.get("source")
        if isinstance(source, str):
            url, subdir = f"https://github.com/{repo}.git", source.removeprefix("./").strip("/")
        elif isinstance(source, dict) and source.get("source") in ("url", "git-subdir") and isinstance(source.get("url"), str):
            url, subdir = source["url"], str(source.get("path") or "").removeprefix("./").strip("/")
        else:
            continue
        found.append(Entry(item["name"], str(item.get("description") or ""), origin, str(item.get("category") or ""), url, subdir))
    return found


def entries(*, refresh: bool = False) -> tuple[list[Entry], str]:
    """(the pooled plugins, a note about where they came from: empty when fresh, else why it is stale or empty)."""
    path = _cache_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    if not refresh and time.time() - cached.get("fetched", 0) < TTL_S and cached.get("catalogs"):
        return _pool(cached["catalogs"]), ""
    catalogs, failed = {}, []
    for origin, repo, file in REPOS:
        try:
            catalogs[origin] = _fetch(repo, file)
        except (OSError, ValueError):
            failed.append(origin)
            if origin in (cached.get("catalogs") or {}):
                catalogs[origin] = cached["catalogs"][origin]
    if catalogs and len(failed) < len(REPOS):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched": time.time(), "catalogs": catalogs}), encoding="utf-8")
    note = f"could not reach {', '.join(failed)}; showing what was saved" if failed and catalogs else (
        f"could not reach {', '.join(failed)}" if failed else "")
    return _pool(catalogs), note


def _pool(catalogs: dict[str, Any]) -> list[Entry]:
    repos = {origin: repo for origin, repo, _ in REPOS}
    return sorted((e for origin, catalog in catalogs.items() for e in parse(origin, repos[origin], catalog)),
                  key=lambda e: (e.name.lower(), e.origin))


def narrow(pool: list[Entry], query: str) -> list[Entry]:
    """Entries whose name, description, category or origin contain every word of `query`, ignoring case."""
    words = query.lower().split()
    return [e for e in pool if all(w in f"{e.name} {e.description} {e.category} {e.origin}".lower() for w in words)]
