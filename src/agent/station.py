"""`clyde station`: the live state of an orchestration run, read from its files (agent/runs.py).

    clyde station              live view of every active run (the newest when none is), refreshed until they settle
    clyde station --once       the same, printed once
    clyde station ls           every run, newest first
    clyde station watch [id] [--who NAME]   the event stream, one line each (one team member's with --who)
    clyde station panes [id]   open a tmux window: the live view and a pane per team member
    clyde station approve|deny [id]   answer the oldest pending request, across the active runs or in one run

It shows only what the run recorded: a crew member's state comes from its last event, and spend from the ledger.
"""
from __future__ import annotations

import time
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from src.agent.runs import Run

_ENDED = ("done", "failed", "stopped")
_SETTLED = (*_ENDED, "awaiting_approval")   # the live view stops here: what is left is the user's decision in clyde
_STATE = {"splitting": "splitting the task", "split": "tasks handed out", "reviewing": "reviewing the work", "reviewed": "review done",
          "reporting": "writing the report", "reported": "report written", "started": "working", "approval_asked": "waiting for approval", "approval_answered": "working",
          "finished": "finished", "failed": "failed"}


def _crew(run: Run) -> list[tuple[str, str, str]]:
    """(name, model, what it is doing) for the master, advisor and each worker, from the events so far."""
    roles = run.state().get("roles") or {}
    people = [("master", roles.get("master") or "")]
    if roles.get("advisor"):
        people.append(("advisor", roles["advisor"]))
    people += [(w["name"], w["model"]) for w in roles.get("workers", [])]
    last: dict[str, dict[str, Any]] = {}
    for e in run.events():
        last[e["who"]] = e
    out = []
    for name, model in people:
        e = last.get(name)
        if e is None:
            doing = "idle"
        elif e["kind"] == "tool_use":
            doing = f"using {e.get('tool', '?')}"
        elif e["kind"] == "tool_error":
            doing = f"{e.get('tool', '?')} failed"
        else:
            doing = _STATE.get(e["kind"], e["kind"])
        out.append((name, model, doing))
    return out


def render(run: Run) -> Table:
    state = run.state()
    usd, unpriced = run.total_spend()
    spend = f"${usd:.4f}" + (f" + {unpriced} unpriced" if unpriced else "")
    table = Table(box=None, pad_edge=False, header_style="bold", title=f"{run.id} · {state.get('status', '?')} · {spend}",
                  caption=(state.get("task") or "")[:100], title_justify="left", caption_justify="left")
    for col in ("WHO", "MODEL", "DOING"):
        table.add_column(col)
    for name, model, doing in _crew(run):
        table.add_row(name, model, Text(doing, style="yellow" if "approval" in doing else ""))
    for ask in run.pending():
        table.add_row("", Text(f"{ask['who']} asks to use {ask['tool']}: {ask['message'][:60]}", style="yellow"), f"clyde station approve {run.id}")
    return table


_STALE_S = 6 * 3600   # a run whose last event is older than this is left over from a session that died, not active


def _last_activity(run: Run) -> float:
    events = run.events()
    return events[-1]["t"] if events else run.state().get("started", 0)


def _active() -> list[Run]:
    """Every run still going (several /orchestrate runs can be open at once); the newest run when none is."""
    runs = Run.all()
    live = [r for r in runs if r.state().get("status") not in _ENDED and time.time() - _last_activity(r) < _STALE_S]
    return live or runs[:1]


def _select(run_id: str | None) -> list[Run]:
    if run_id:
        run = Run.open(run_id)
        return [run] if run else []
    return _active()


def _show(runs: list[Run]) -> Group:
    return Group(*[render(r) for r in runs])


def command(console: Console, action: str, target: str | None, once: bool = False, who: str | None = None) -> int:
    if action == "ls":
        for run in Run.all():
            s = run.state()
            console.print(f"{run.id}  {s.get('status', '?'):18} {(s.get('task') or '')[:60]}", markup=False)
        return 0
    runs = _select(target)
    if not runs:
        console.print("No runs yet. Start one with /orchestrate in clyde.", markup=False)
        return 1
    if action in ("approve", "deny"):
        waiting = sorted(((a, r) for r in runs for a in r.pending()), key=lambda pair: pair[0].get("t", 0))
        if not waiting:
            console.print("Nothing is waiting.", markup=False)
            return 1
        ask, run = waiting[0]   # the oldest request, across every active run
        run.answer(ask["id"], action == "approve")
        console.print(f"{action}d: {ask['who']} {ask['tool']} (run {run.id})", markup=False)
        return 0
    if action == "panes":
        from src.agent import panes
        console.print(panes.open_panes(runs[0]), markup=False)
        return 0
    if action == "watch":
        run, seen = runs[0], 0
        try:
            while True:
                events = [e for e in run.events() if who is None or e["who"] == who]
                for e in events[seen:]:
                    detail = e.get("tool") or e.get("status") or e.get("note") or ""
                    console.print(f"{time.strftime('%H:%M:%S', time.localtime(e['t']))} {e['who']:10} {e['kind']} {detail}", markup=False)
                seen = len(events)
                if run.state().get("status") in _ENDED:
                    return 0
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    if once:
        console.print(_show(runs))
        return 0
    try:
        with Live(_show(runs), console=console, refresh_per_second=2) as live:
            while any(r.state().get("status") not in _SETTLED for r in runs):
                time.sleep(0.5)
                runs = _select(target)   # a run started meanwhile joins the view
                live.update(_show(runs))
            live.update(_show(runs))
    except KeyboardInterrupt:
        pass
    return 0
