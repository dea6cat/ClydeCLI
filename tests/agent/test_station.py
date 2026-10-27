"""`clyde station` shows what a run recorded and answers its approvals."""
from __future__ import annotations

import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src.agent import runs, station
from src.agent.runs import Run


class Station(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (patch("src.agent.runs.clyde_home", return_value=Path(self.tmp.name)), patch.object(runs, "_POLL_S", 0.01)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _console(self):
        self.buffer = io.StringIO()
        return Console(file=self.buffer, width=120)

    def _run(self):
        run = Run.create("add login", {"master": "a:big", "advisor": None,
                                       "workers": [{"name": "worker-1", "model": "a:small"}, {"name": "worker-2", "model": "b:small"}]})
        run.set_status("running")
        run.event("worker-1", "started")
        run.event("worker-1", "tool_use", tool="Edit")
        return run

    def _waiting_ask(self, run):
        """worker-2 asks to run a command and waits; returns the thread so the test can join it."""
        thread = threading.Thread(target=run.ask, args=("worker-2", "Bash", "run: ls"), daemon=True)
        thread.start()
        for _ in range(500):
            if run.pending():
                return thread
            threading.Event().wait(0.01)
        self.fail("the ask never appeared")

    def test_each_member_shows_what_its_last_event_says(self):
        run = self._run()
        thread = self._waiting_ask(run)
        crew = {name: doing for name, _model, doing in station._crew(run)}
        self.assertEqual(crew, {"master": "idle", "worker-1": "using Edit", "worker-2": "waiting for approval"})
        run.answer(run.pending()[0]["id"], False)
        thread.join(5)

    def test_the_view_shows_spend_unpriced_calls_and_the_pending_ask_and_approve_answers_it(self):
        run = self._run()
        with patch("src.agent.cost_tracker.estimate_usd", side_effect=[0.5, None]):
            run.spend("worker-1", "a:small", {"input_tokens": 1})
            run.spend("worker-2", "b:small", {"input_tokens": 1})
        thread = self._waiting_ask(run)
        console = self._console()
        console.print(station.render(run))
        out = self.buffer.getvalue()
        for part in ("running", "$0.5000 + 1 unpriced", "worker-2 asks to use Bash", "using Edit"):
            self.assertIn(part, out)
        self.assertEqual(station.command(self._console(), "approve", run.id), 0)
        thread.join(5)
        self.assertEqual(run.pending(), [])
        self.assertEqual(station.command(self._console(), "approve", run.id), 1)   # nothing left to answer

    def test_every_active_run_is_shown_and_approve_answers_the_oldest_ask_across_them(self):
        first, second = self._run(), self._run()
        old = Run.create("long gone", {"master": "a:big", "workers": []})
        old.set_status("done")
        stale = Run.create("died with its session", {"master": "a:big", "workers": []})
        stale.update(status="running", started=time.time() - 7 * 3600)
        with patch("src.agent.runs.time.time", return_value=time.time() - 7 * 3600):
            stale.event("clyde", "x")   # its last event is seven hours old
        threads = []
        for run in (first, second):
            threads.append(self._waiting_ask(run))
            threading.Event().wait(0.02)   # first's ask is older than second's
        console = self._console()
        console.print(station._show(station.select_runs(None)))
        out = self.buffer.getvalue()
        self.assertIn(first.id, out)
        self.assertIn(second.id, out)
        self.assertNotIn(old.id, out)      # finished
        self.assertNotIn(stale.id, out)    # left over from a dead session
        self.assertEqual(station.command(self._console(), "approve", None), 0)
        self.assertEqual(first.pending(), [])        # the oldest ask was the one answered
        self.assertEqual(len(second.pending()), 1)
        self.assertEqual(station.command(self._console(), "deny", second.id), 0)   # or name the run
        for thread in threads:
            thread.join(5)

    def test_the_snapshot_says_what_clyde_is_doing_and_carries_each_members_kind_and_rule(self):
        run = Run.create("add login", {"master": "a:big", "advisor": "claude:haiku", "kinds": {"master": "provider", "advisor": "cli", "worker-1": "provider"},
                                       "workers": [{"name": "worker-1", "model": "a:small"}]})
        run.event("worker-1", "constraint", note="edits inside its own worktree are free")
        for status, clyde in (("planning", "briefing the team"), ("running", "watching the workers"), ("reviewing", "waiting for the review"),
                              ("awaiting_approval", "waiting for your decision"), ("done", "landed the work")):
            run.set_status(status)
            self.assertEqual(station.snapshot(run)["clyde"], clyde)
        crew = {c["name"]: c for c in station.snapshot(run)["crew"]}
        self.assertEqual((crew["advisor"]["kind"], crew["worker-1"]["constraint"]), ("cli", "edits inside its own worktree are free"))
        self.assertIsNone(crew["master"]["constraint"])   # nothing recorded, nothing shown
        thread = self._waiting_ask(run)
        self.assertEqual(station.snapshot(run)["clyde"], "waiting on you for 1 request")
        run.answer(run.pending()[0]["id"], False)
        thread.join(5)

    def test_bookkeeping_events_are_not_what_a_member_is_doing(self):
        run = Run.create("t", {"master": "a:big", "advisor": None, "workers": [{"name": "worker-1", "model": "a"}]})
        run.event("worker-1", "tools", tools=["Read"])
        run.event("worker-1", "constraint", note="files only")
        run.event("bonnie", "check", target="worker-1", reason="result")
        self.assertEqual(station.snapshot(run)["crew"][1]["doing"], "idle")   # granted tools and a rule are not activity
        run.event("worker-1", "started")
        self.assertEqual(station.snapshot(run)["crew"][1]["doing"], "working")

    def test_ls_and_the_no_runs_message(self):
        console = self._console()
        self.assertEqual(station.command(console, "show", None, once=True), 1)
        self.assertIn("No runs yet", self.buffer.getvalue())
        run = self._run()
        console = self._console()
        self.assertEqual(station.command(console, "ls", None), 0)
        self.assertIn(run.id, self.buffer.getvalue())
        self.assertEqual(station.command(self._console(), "approve", "nope"), 1)


if __name__ == "__main__":
    unittest.main()
