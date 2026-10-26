"""The station's floor plan, derived from what a run recorded: rooms, objects in them, hallways between them.

    room     a team with one scope. The deck holds Clyde, the master and the advisor: they plan and review, with no
             worktree and no file tools. Each worker has its own bay: its own worktree is its own scope.
    object   a capability a member was given (the `tools` event the run recorded), by family: read files, write files,
             shell, web, MCP, other. It carries only counts taken from events: used, failed, asked, allowed, denied.
             Whether a tool asks is decided per call, so an object never claims a fixed "asks" or "free".
    hallway  a handoff lane that exists in the design, with a state taken from the event that used it: dark until that
             event, lit after, waiting while a request sits unanswered, refused when the user discarded the work.
             There is no worker-to-worker hallway: workers hand off only through the deck.

Nothing here is drawn from anything but the run's files, so the page can't show what the run did not record.
"""
from __future__ import annotations

from typing import Any

_READ = {"Read", "Glob", "Grep", "Map", "LSP", "Data", "RetrieveContext"}
_WRITE = {"Edit", "Write", "NotebookEdit"}
_SHELL = {"Bash", "PowerShell"}
_WEB = {"WebFetch", "WebSearch"}
_MCP = {"MCP", "ListMcpResourcesTool", "ReadMcpResourceTool"}
FAMILIES = ("read", "write", "shell", "web", "mcp", "other")   # display families; grouping is presentation, not a claim


def family(tool: str) -> str:
    for name, tools in (("read", _READ), ("write", _WRITE), ("shell", _SHELL), ("web", _WEB), ("mcp", _MCP)):
        if tool in tools:
            return name
    return "mcp" if tool.startswith("mcp__") else "other"


def _first(events: list[dict[str, Any]], who: str, kind: str, **match: Any) -> dict[str, Any] | None:
    for e in events:
        if e["kind"] == kind and e["who"] == who and all(e.get(k) == v for k, v in match.items()):
            return e
    return None


def _objects(member: str, tools: list[str], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One object per family of tools the member was given, with counts from its own events."""
    out = []
    for fam in FAMILIES:
        granted = [t for t in tools if family(t) == fam]
        if not granted:
            continue
        mine = [e for e in events if e["who"] == member and e["kind"] in ("tool_use", "tool_error", "approval_asked")
                and family(e.get("tool", "")) == fam]
        asks = {e["approval"] for e in mine if e["kind"] == "approval_asked"}
        answers = [e for e in events if e["kind"] == "approval_answered" and e.get("approval") in asks]
        out.append({"id": f"{member}:{fam}", "family": fam, "tools": granted,
                    "used": sum(e["kind"] == "tool_use" for e in mine), "failed": sum(e["kind"] == "tool_error" for e in mine),
                    "asked": len(asks), "allowed": sum(bool(e.get("allow")) for e in answers),
                    "denied": sum(not e.get("allow") for e in answers), "last": max((e["t"] for e in mine), default=None)})
    return out


def build(state: dict[str, Any], events: list[dict[str, Any]], asks: list[dict[str, Any]], crew: list[dict[str, Any]],
          clyde: str, spend: dict[str, Any]) -> dict[str, Any]:
    """{"rooms": [...], "hallways": [...]} for a run: its state, events, pending asks, crew rows, Clyde's state, spend."""
    roles = state.get("roles") or {}
    workers = [w["name"] for w in roles.get("workers", [])]
    advisor = bool(roles.get("advisor"))
    granted = {e["who"]: e.get("tools") or [] for e in events if e["kind"] == "tools"}
    people = {c["name"]: c for c in crew}
    answered = [e for e in events if e["kind"] == "approval_answered"]

    deck = {"id": "deck", "kind": "deck", "label": "deck",
            "members": [{"name": "clyde", "doing": clyde}, *[people[n] for n in ("master", "advisor") if n in people]],
            "objects": [{"id": "deck:approvals", "family": "approvals", "pending": len(asks),
                         "asked": sum(e["kind"] == "approval_asked" for e in events),
                         "allowed": sum(bool(e.get("allow")) for e in answered), "denied": sum(not e.get("allow") for e in answered)},
                        {"id": "deck:ledger", "family": "ledger", "usd": spend.get("usd", 0.0), "unpriced": spend.get("unpriced", 0)}]}
    bays = [{"id": n, "kind": "bay", "label": n, "members": [people[n]] if n in people else [],
             "objects": _objects(n, granted.get(n, []), events)} for n in workers]
    landed, discarded = _first(events, "user", "landed"), _first(events, "user", "discarded")
    outbox = {"id": "outbox", "kind": "outbox", "label": "outbox", "state": "landed" if landed else "discarded" if discarded else "empty",
              "path": (landed or {}).get("outbox")}

    def lane(lid: str, kind: str, src: str, dst: str, event: dict[str, Any] | None, state: str = "lit", count: int = 1) -> dict[str, Any]:
        return {"id": lid, "kind": kind, "from": src, "to": dst, "state": state if event else "dark", "count": count if event else 0,
                "at": event["t"] if event else None}

    halls = []
    split = _first(events, "master", "split")
    results = _first(events, "advisor", "reviewing") if advisor else _first(events, "master", "reporting")
    for n in workers:
        asked = [e for e in events if e["kind"] == "approval_asked" and e["who"] == n]
        waiting = any(a.get("who") == n for a in asks)
        halls.append(lane(f"task:{n}", "task", "deck", n, split))
        halls.append(lane(f"results:{n}", "results", n, "deck", results))
        halls.append(lane(f"approvals:{n}", "approvals", n, "deck", asked[-1] if asked else None, "waiting" if waiting else "lit", len(asked)))
    if advisor:
        halls.append(lane("review", "review", "deck", "deck", _first(events, "advisor", "reviewed")))
    halls.append(lane("report", "report", "deck", "deck", _first(events, "clyde", "status", status="awaiting_approval")))
    halls.append(lane("landing", "landing", "deck", "outbox", landed or discarded, "refused" if discarded and not landed else "lit"))
    return {"rooms": [deck, *bays, outbox], "hallways": halls}
