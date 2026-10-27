"""An orchestration run on disk: ~/.clyde/runs/<id>/.

    run.json          task, roles, status, timestamps
    events.jsonl      one line per thing that happened (who, kind, data), appended as it happens
    ledger.jsonl      one line per model call group: who, model, usage, estimated USD
    approvals/<n>.json  a worker's request for a yes or no; written pending, answered by the REPL or `clyde station`
    orders/<n>.json     the user's request, from the station, to add a worker with a task; written pending, taken or refused by the run
    workers/<name>/   transcript.json and summary.md for each worker

Every reader (the REPL that started the run, `clyde station` in another terminal) reads these files, so
what is shown is only what was recorded. Folders are 0700 and files 0600: transcripts hold file contents.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from src.config import clyde_home

_POLL_S = 0.3
MAX_TEAM = 12   # workers in one run, however they joined: the station has room for this many at the bar
ORDER_CHARS = 2000   # the longest task one order can carry


def runs_dir() -> Path:
    return clyde_home() / "runs"


def outbox_dir() -> Path:
    return clyde_home() / "outbox"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)   # a reader never sees half a file


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_lines(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue   # a line still being written
        if isinstance(row, dict):
            rows.append(row)
    return rows


class Run:
    def __init__(self, root: Path):
        self.root = root
        self.id = root.name
        self._lock = threading.Lock()

    # --- lifecycle -------------------------------------------------------------------------------------------

    @classmethod
    def create(cls, task: str, roles: dict[str, Any]) -> "Run":
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        root = _private_dir(runs_dir() / run_id)
        _private_dir(root / "approvals")
        _private_dir(root / "workers")
        run = cls(root)
        _write_json(root / "run.json", {"id": run_id, "task": task, "roles": roles, "status": "planning", "started": time.time()})
        run.event("clyde", "created", task=task)
        return run

    @classmethod
    def open(cls, run_id: str) -> "Run | None":
        if not run_id or "/" in run_id or run_id.startswith("."):
            return None
        root = runs_dir() / run_id
        return cls(root) if (root / "run.json").is_file() else None

    @classmethod
    def all(cls) -> list["Run"]:
        try:
            names = sorted((p.name for p in runs_dir().iterdir() if (p / "run.json").is_file()), reverse=True)
        except OSError:
            return []
        return [cls(runs_dir() / n) for n in names]

    def state(self) -> dict[str, Any]:
        return _read_json(self.root / "run.json") or {}

    def update(self, **fields: Any) -> None:
        with self._lock:
            _write_json(self.root / "run.json", {**self.state(), **fields})

    def set_status(self, status: str) -> None:
        self.update(status=status, **({"ended": time.time()} if status in ("done", "failed", "stopped") else {}))
        self.event("clyde", "status", status=status)

    def worker_dir(self, name: str) -> Path:
        return _private_dir(self.root / "workers" / name)

    # --- events and spend ------------------------------------------------------------------------------------

    def _append(self, name: str, row: dict[str, Any]) -> None:
        path = self.root / name
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with self._lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)

    def event(self, who: str, kind: str, **data: Any) -> None:
        self._append("events.jsonl", {"t": time.time(), "who": who, "kind": kind, **data})

    def events(self) -> list[dict[str, Any]]:
        return _read_lines(self.root / "events.jsonl")

    def spend(self, who: str, ref: str, usage: dict[str, int] | None, usd: float | None = None, *, always: bool = False) -> None:
        """Record a call group. `usd` is a cost the model's own tool reported; without it the catalog price is used.
        `always` writes the row even with no usage and no cost, so a CLI that reports nothing counts as unpriced."""
        from src.agent.cost_tracker import estimate_usd
        usage = {k: v for k, v in (usage or {}).items() if isinstance(v, int)}
        if usage or usd is not None or always:
            self._append("ledger.jsonl", {"t": time.time(), "who": who, "model": ref, "usage": usage,
                                          "usd": usd if usd is not None else estimate_usd(ref, usage) if usage else None})

    def ledger(self) -> list[dict[str, Any]]:
        return _read_lines(self.root / "ledger.jsonl")

    def total_spend(self) -> tuple[float, int]:
        """(estimated USD over the priced rows, how many rows had no price): an unpriced model is never shown as free."""
        rows = self.ledger()
        return sum(r["usd"] for r in rows if isinstance(r.get("usd"), (int, float))), sum(1 for r in rows if r.get("usd") is None)

    # --- approvals -------------------------------------------------------------------------------------------

    def ask(self, who: str, tool: str, message: str, cancel: threading.Event | None = None) -> bool:
        """File a request and wait for its answer; no answer before `cancel` is set counts as no."""
        approval_id = uuid.uuid4().hex[:8]
        path = self.root / "approvals" / f"{approval_id}.json"
        _write_json(path, {"id": approval_id, "who": who, "tool": tool, "message": message[:4000], "status": "pending", "t": time.time()})
        self.event(who, "approval_asked", approval=approval_id, tool=tool)
        while not (cancel is not None and cancel.is_set()):
            row = _read_json(path)
            if row and row.get("status") != "pending":
                return row["status"] == "approved"
            time.sleep(_POLL_S)
        self.answer(approval_id, False)
        return False

    def pending(self) -> list[dict[str, Any]]:
        rows = [_read_json(p) for p in sorted((self.root / "approvals").glob("*.json"))]
        return sorted((r for r in rows if r and r.get("status") == "pending"), key=lambda r: r.get("t", 0))

    def answer(self, approval_id: str, allow: bool) -> bool:
        """Answer a pending request; False when it is unknown or was already answered."""
        if not approval_id.isalnum():
            return False
        path = self.root / "approvals" / f"{approval_id}.json"
        with self._lock:
            row = _read_json(path)
            if not row or row.get("status") != "pending":
                return False
            _write_json(path, {**row, "status": "approved" if allow else "denied", "answered": time.time()})
        self.event("user", "approval_answered", approval=approval_id, allow=allow)
        return True

    # --- orders: the user adds a worker --------------------------------------------------------------------------

    def order(self, task: str) -> str:
        """File the user's request for one more worker, doing `task`; the run takes it or refuses it, and says so.
        Raises ValueError (the reason, fit to show the user) when it cannot be filed: the run is not working, no task, too long, team full."""
        task = task.strip()
        state = self.state()
        if state.get("status") != "running":
            raise ValueError("the run is not working right now: workers can only be added while it is")
        if not task:
            raise ValueError("say what the new worker should do")
        if len(task) > ORDER_CHARS:
            raise ValueError(f"the task is longer than {ORDER_CHARS} characters")
        if len((state.get("roles") or {}).get("workers", [])) + len(self.pending_orders()) >= MAX_TEAM:
            raise ValueError(f"the team is full ({MAX_TEAM} workers)")
        order_id = uuid.uuid4().hex[:8]
        _write_json(_private_dir(self.root / "orders") / f"{order_id}.json", {"id": order_id, "task": task, "status": "pending", "t": time.time()})
        self.event("user", "ordered", order=order_id, task=task[:200])
        return order_id

    def pending_orders(self) -> list[dict[str, Any]]:
        rows = [_read_json(p) for p in sorted((self.root / "orders").glob("*.json"))]
        return sorted((r for r in rows if r and r.get("status") == "pending"), key=lambda r: r.get("t", 0))

    def settle_order(self, order_id: str, status: str, **note: Any) -> None:
        """Mark an order `accepted` (with its `worker`) or `refused` (with `why`)."""
        path = self.root / "orders" / f"{order_id}.json"
        row = _read_json(path)
        if row:
            _write_json(path, {**row, "status": status, **note})

    def permission_handler(self, who: str, cancel: threading.Event | None = None) -> Callable[[str, str, str | None], tuple[bool, bool]]:
        """A ToolContext.permission_handler for one worker: each ask is filed here; nothing is remembered across asks."""
        return lambda tool, message, _rule: (self.ask(who, tool, message, cancel), False)
