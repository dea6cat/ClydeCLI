"""Automations: prompts Bonnie runs on a schedule, saved in ~/.clyde/bonnie/automations.json.

They run only while Bonnie is open (no daemon), each run in a session of its own, in the project they were made in. A run
that was due while Bonnie was closed is skipped, not replayed on launch. Unattended runs are read-only (plan mode) unless
the automation was made with edits allowed, since nobody is there to answer a permission card.

Every change to the file happens under a lock that other Bonnie windows respect too (`automations.lock`), so two windows cannot lose each
other's edits, and a due run is claimed in the same step that moves its next time on: it fires once however many windows are open. What
the scheduler decided, and why, is appended to `automations.log` (one JSON line each), and the page shows the latest on each row.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:   # Windows: only the threads of one window are held apart there
    fcntl = None  # type: ignore[assignment]

from src.bonnie.theme import folder
from src.safe_write import read_json_safely, write_json_safely, write_safely

MAX_PROMPT = 4000
MAX_NAME = 80
MAX_AUTOMATIONS = 50
MIN_EVERY = 5                 # minutes
MAX_EVERY = 7 * 24 * 60
LATE = timedelta(minutes=5)   # a run this much past its time is skipped
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_AT = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_STAMP = "%Y-%m-%dT%H:%M:%S"
LOG_KEEP = 500        # decisions kept in the log
_THREAD = threading.RLock()
_HELD = threading.local()   # how deep this thread is inside the lock: taking it again must not wait for itself


def clean_schedule(raw: Any) -> dict[str, Any]:
    """A valid schedule: every N minutes, daily at HH:MM, or weekly on some days at HH:MM. Raises ValueError otherwise."""
    if not isinstance(raw, dict):
        raise ValueError("pick a schedule")
    kind = raw.get("kind")
    if kind == "every":
        minutes = raw.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not MIN_EVERY <= minutes <= MAX_EVERY:
            raise ValueError(f"every {MIN_EVERY} minutes to every 7 days")
        return {"kind": "every", "minutes": minutes}
    if kind in ("daily", "weekly"):
        at = raw.get("at")
        if not isinstance(at, str) or not _AT.match(at):
            raise ValueError("the time is HH:MM")
        if kind == "daily":
            return {"kind": "daily", "at": at}
        days = raw.get("days")
        if not isinstance(days, list) or not days or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days):
            raise ValueError("pick at least one day")
        return {"kind": "weekly", "days": sorted(set(days)), "at": at}
    raise ValueError("pick a schedule")


def next_run(schedule: dict[str, Any], after: datetime) -> datetime:
    """The first run strictly after `after` (local time)."""
    if schedule["kind"] == "every":
        return after + timedelta(minutes=schedule["minutes"])
    hour, minute = int(schedule["at"][:2]), int(schedule["at"][3:])
    days = schedule.get("days", range(7))
    for ahead in range(8):
        day = after + timedelta(days=ahead)
        at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at > after and at.weekday() in days:
            return at
    raise ValueError("no run found")   # unreachable for a clean schedule


def describe(schedule: dict[str, Any]) -> str:
    if schedule["kind"] == "every":
        m = schedule["minutes"]
        return f"Every {m // 60} h" if m % 60 == 0 and m >= 60 else f"Every {m} min"
    if schedule["kind"] == "daily":
        return f"Daily at {schedule['at']}"
    return f"{', '.join(DAYS[d] for d in schedule['days'])} at {schedule['at']}"


def _file() -> Path:
    return folder() / "automations.json"


@contextmanager
def _locked() -> Iterator[None]:
    """Hold the automations file for one read-modify-write, against other threads and other Bonnie windows."""
    with _THREAD:
        depth = getattr(_HELD, "depth", 0)
        if depth:
            _HELD.depth = depth + 1
            try:
                yield
            finally:
                _HELD.depth = depth
            return
        folder().mkdir(parents=True, exist_ok=True)
        fd = os.open(folder() / "automations.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_EX)
            _HELD.depth = 1
            yield
        finally:
            _HELD.depth = 0
            os.close(fd)   # closing releases the lock


def _log_file() -> Path:
    return folder() / "automations.log"


def record(row: dict[str, Any], what: str, why: str, now: datetime | None = None) -> None:
    """Append one decision to the log: `what` is ran, skipped, created, paused, resumed or deleted, and `why` says so in a sentence."""
    entry = {"t": (now or datetime.now()).strftime(_STAMP), "id": row.get("id"), "name": row.get("name"), "project": row.get("project"), "what": what, "why": why}
    with _locked():
        path = _log_file()
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        lines.append(json.dumps(entry, ensure_ascii=False))
        write_safely(path, "\n".join(lines[-LOG_KEEP:]) + "\n")


def history(project: str, automation_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """The newest decisions for `project` (or one of its automations), newest first."""
    try:
        lines = _log_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue   # a line cut off by a crash
        if isinstance(e, dict) and e.get("project") == project and (automation_id is None or e.get("id") == automation_id):
            out.append(e)
            if len(out) >= limit:
                break
    return out


def _load() -> list[dict[str, Any]]:
    try:
        raw = read_json_safely(_file())
    except (OSError, ValueError):
        return []
    return [a for a in raw if isinstance(a, dict) and isinstance(a.get("id"), str)] if isinstance(raw, list) else []


def _save(rows: list[dict[str, Any]]) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    write_json_safely(_file(), rows, indent=1)


def listing(project: str) -> list[dict[str, Any]]:
    return [a for a in _load() if a.get("project") == project]


def add(project: str, name: Any, prompt: Any, schedule: Any, edits: Any, now: datetime) -> dict[str, Any]:
    """Create an automation for `project`. Raises ValueError with a sentence the page can show."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ValueError(f"the prompt is 1 to {MAX_PROMPT} characters")
    name = " ".join(name.split())[:MAX_NAME] if isinstance(name, str) else ""
    if edits is not None and not isinstance(edits, bool):
        raise ValueError("edits is true or false")
    schedule = clean_schedule(schedule)
    with _locked():
        rows = _load()
        if len(rows) >= MAX_AUTOMATIONS:
            raise ValueError(f"at most {MAX_AUTOMATIONS} automations")
        row = {"id": uuid.uuid4().hex[:12], "name": name or " ".join(prompt.split())[:40], "prompt": prompt.strip(), "schedule": schedule,
               "edits": bool(edits), "paused": False, "project": project, "last_run": None, "next_run": next_run(schedule, now).strftime(_STAMP)}
        _save(rows + [row])
        record(row, "created", f"{describe(schedule)}; first run {row['next_run'].replace('T', ' ')}", now)
    return row


def update(project: str, automation_id: str, change: str) -> bool:
    """`delete`, `pause` or `resume` one automation of `project`; False when it isn't there."""
    with _locked():
        rows = _load()
        mine = next((a for a in rows if a["id"] == automation_id and a.get("project") == project), None)
        if mine is None:
            return False
        if change == "delete":
            rows.remove(mine)
        else:
            mine["paused"] = change == "pause"
        _save(rows)
        record(mine, {"delete": "deleted", "pause": "paused", "resume": "resumed"}.get(change, change), "you asked for it")
    return True


def get(project: str, automation_id: str) -> dict[str, Any] | None:
    return next((a for a in listing(project) if a["id"] == automation_id), None)


def mark_ran(automation_id: str, now: datetime, why: str = "run now") -> None:
    """Record a run and move the next one past `now`."""
    with _locked():
        rows = _load()
        for a in rows:
            if a["id"] == automation_id:
                a["last_run"] = now.strftime(_STAMP)
                a["next_run"] = next_run(a["schedule"], now).strftime(_STAMP)
                record(a, "ran", why, now)
        _save(rows)


def _hours(late: timedelta) -> str:
    minutes = int(late.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def due(project: str, now: datetime, claim: bool = False) -> list[dict[str, Any]]:
    """The running automations of `project` whose time has come. Runs missed by more than LATE are rescheduled, not returned, and the
    log says why. With `claim` the returned runs are also marked as run in the same step, so a second window asking a moment later
    gets nothing: each due run fires once."""
    with _locked():
        rows, out, changed = _load(), [], False
        for a in rows:
            if a.get("project") != project or a.get("paused"):
                continue
            try:
                at = datetime.strptime(a["next_run"], _STAMP)
                if at > now:
                    continue
                if now - at > LATE:
                    a["next_run"] = next_run(a["schedule"], now).strftime(_STAMP)
                    changed = True
                    record(a, "skipped", f"it was due {at.strftime('%Y-%m-%d %H:%M')} and Bonnie was closed, {_hours(now - at)} late; it will not run for a missed time", now)
                    continue
            except (KeyError, ValueError):
                continue
            if claim:
                a["last_run"] = now.strftime(_STAMP)
                a["next_run"] = next_run(a["schedule"], now).strftime(_STAMP)
                changed = True
                record(a, "ran", "on schedule", now)
            out.append(dict(a))
        if changed:
            _save(rows)
        return out
