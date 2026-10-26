"""`clyde station` shows what a run recorded and answers its approvals."""
from __future__ import annotations

import io
import tempfile
import threading
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
