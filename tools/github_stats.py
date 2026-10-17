"""Keep GitHub's repository numbers past the 14 days GitHub shows them for, and who starred, forked or watches.

    python3 tools/github_stats.py                       # collect for dea6cat/ClydeCLI into ~/github-stats/dea6cat-ClydeCLI.json
    python3 tools/github_stats.py OWNER/REPO --out FILE
    python3 tools/github_stats.py report [OWNER/REPO]   # what changed, from the saved file

Run it at least every two weeks (daily is better, e.g. from cron: `17 6 * * * python3 /path/to/tools/github_stats.py`), because GitHub
drops traffic older than 14 days. It uses the `gh` CLI, so it needs `gh auth login` as someone with push access to the repository.

GitHub does not say who cloned or viewed a repository, only how many and how many were unique, so this saves counts. Stargazers, forks and
watchers are public GitHub accounts; their usernames are saved with the day first seen. The file stays on your machine, never in the repository.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_REPO = "dea6cat/ClydeCLI"
STAR_HEADER = "Accept: application/vnd.github.star+json"


def gh_fetch(path: str, *, star_dates: bool = False) -> Any:
    """GET one GitHub API path through `gh`, following pagination; a list endpoint comes back as one flat list."""
    command = ["gh", "api", "--paginate", "--slurp", path] + (["-H", STAR_HEADER] if star_dates else [])
    pages = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)
    return [item for page in pages for item in page] if pages and isinstance(pages[0], list) else (pages[0] if pages else {})


def default_path(repo: str) -> Path:
    return Path.home() / "github-stats" / (repo.replace("/", "-") + ".json")


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"clones": data.get("clones", {}), "views": data.get("views", {}), "referrers": data.get("referrers", {}), "paths": data.get("paths", {}),
            "counts": data.get("counts", {}), "people": data.get("people", {"stars": {}, "forks": {}, "watchers": {}})}


def collect(repo: str, state: dict, fetch: Callable[..., Any] = gh_fetch, today: str | None = None) -> dict:
    """Merge today's GitHub numbers into `state` (a dict from load). Per-day traffic is replaced by GitHub's latest figure for that day."""
    day = today or datetime.now(timezone.utc).date().isoformat()
    for kind in ("clones", "views"):
        for entry in fetch(f"repos/{repo}/traffic/{kind}").get(kind, []):
            state[kind][entry["timestamp"][:10]] = {"count": entry["count"], "uniques": entry["uniques"]}
    state["referrers"][day] = {r["referrer"]: {"count": r["count"], "uniques": r["uniques"]} for r in fetch(f"repos/{repo}/traffic/popular/referrers")}
    state["paths"][day] = {p["path"]: {"count": p["count"], "uniques": p["uniques"]} for p in fetch(f"repos/{repo}/traffic/popular/paths")}
    info = fetch(f"repos/{repo}")
    state["counts"][day] = {"stars": info["stargazers_count"], "forks": info["forks_count"], "watchers": info["subscribers_count"],
                            "open_issues": info["open_issues_count"]}
    seen = {"stars": [s["user"]["login"] for s in fetch(f"repos/{repo}/stargazers", star_dates=True)],
            "forks": [f["owner"]["login"] for f in fetch(f"repos/{repo}/forks")],
            "watchers": [w["login"] for w in fetch(f"repos/{repo}/subscribers")]}
    for group, logins in seen.items():
        for login in logins:
            state["people"][group].setdefault(login, day)
    return state


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def report(state: dict, today: str | None = None) -> str:
    day = today or datetime.now(timezone.utc).date().isoformat()
    lines = []
    for kind in ("clones", "views"):
        days = sorted(state[kind])
        total = sum(state[kind][d]["count"] for d in days)
        lines.append(f"{kind}: {total} over {len(days)} saved days ({days[0]} to {days[-1]})" if days else f"{kind}: nothing saved yet")
    latest = state["counts"].get(max(state["counts"], default=""), {})
    lines.append("now: " + (", ".join(f"{k} {v}" for k, v in latest.items()) or "no counts saved yet"))
    for group, people in state["people"].items():
        new = sorted(login for login, first in people.items() if first == day)
        lines.append(f"{group}: {len(people)} total" + (f"; new today: {', '.join(new)}" if new else ""))
    top = state["referrers"].get(max(state["referrers"], default=""), {})
    if top:
        lines.append("referrers: " + ", ".join(f"{name} ({v['count']})" for name, v in sorted(top.items(), key=lambda kv: -kv[1]["count"])[:5]))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    out = Path(argv[argv.index("--out") + 1]).expanduser() if "--out" in argv else None
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and not (i > 0 and argv[i - 1] == "--out")]
    show = bool(args) and args[0] == "report"
    repo = next((a for a in args if "/" in a), DEFAULT_REPO)
    path = out or default_path(repo)
    state = load(path)
    if not show:
        try:
            save(path, collect(repo, state))
        except (subprocess.CalledProcessError, FileNotFoundError, KeyError, ValueError) as e:
            print(f"could not collect: {e}", file=sys.stderr)
            return 1
        print(f"saved {path}")
    print(report(state))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
