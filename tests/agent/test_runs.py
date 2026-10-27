"""A run on disk: state, events, spend, and the approvals a worker waits on."""
from __future__ import annotations

import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import runs
from src.agent.runs import Run


class RunStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch("src.agent.runs.clyde_home", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        poll = patch.object(runs, "_POLL_S", 0.01)
        poll.start()
        self.addCleanup(poll.stop)

    def test_a_run_keeps_its_state_events_and_is_found_again(self):
        run = Run.create("add login", {"master": "mistral:large"})
        run.set_status("running")
        run.event("worker-1", "tool_use", tool="Read")
        again = Run.open(run.id)
        self.assertEqual((again.state()["task"], again.state()["status"]), ("add login", "running"))
        self.assertEqual([e["kind"] for e in again.events()], ["created", "status", "tool_use"])
        self.assertEqual([r.id for r in Run.all()], [run.id])

    def test_an_order_is_filed_only_for_a_working_run_with_a_task_and_room(self):
        run = Run.create("t", {"workers": [{"name": "worker-1", "model": "m"}]})
        with self.assertRaises(ValueError):
            run.order("go")   # still planning
        run.set_status("running")
        for bad in ("", "   ", "x" * (runs.ORDER_CHARS + 1)):
            with self.assertRaises(ValueError):
                run.order(bad)
        self.assertEqual(run.pending_orders(), [])
        first = run.order("  write c.txt  ")
        self.assertEqual([(o["id"], o["task"]) for o in run.pending_orders()], [(first, "write c.txt")])
        self.assertIn(("user", "ordered"), [(e["who"], e["kind"]) for e in run.events()])
        run.settle_order(first, "accepted", worker="worker-2")
        self.assertEqual(run.pending_orders(), [])
        with self.assertRaises(ValueError):
            run.order("go", "worker-9")   # not on this team
        given = run.order("also this", "worker-1")
        self.assertEqual([(o["id"], o.get("worker")) for o in run.pending_orders()], [(given, "worker-1")])   # the earlier one was settled
        self.assertEqual([e for e in run.events() if e["kind"] == "ordered"][-1]["worker"], "worker-1")
        full = Run.create("t", {"workers": [{"name": f"worker-{i}", "model": "m"} for i in range(runs.MAX_TEAM)]})
        full.set_status("running")
        with self.assertRaises(ValueError):
            full.order("one too many")
        for path in (run.root / "orders", next((run.root / "orders").glob("*.json"))):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0, path)

    def test_files_are_private(self):
        run = Run.create("t", {})
        run.event("clyde", "x")
        for path in (run.root, run.root / "run.json", run.root / "events.jsonl"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0, path)

    def test_a_run_id_cannot_leave_the_runs_folder(self):
        for bad in ("../x", "a/b", ".hidden", ""):
            self.assertIsNone(Run.open(bad))

    def test_a_line_being_written_is_skipped_not_fatal(self):
        run = Run.create("t", {})
        with open(run.root / "events.jsonl", "a", encoding="utf-8") as f:
            f.write('{"t": 1, "who": "w", "kind": "half')
        self.assertEqual([e["kind"] for e in run.events()], ["created"])

    def test_spend_is_summed_and_an_unpriced_model_is_counted_not_free(self):
        run = Run.create("t", {})
        with patch("src.agent.cost_tracker.estimate_usd", side_effect=[0.5, None, 0.25]):
            run.spend("w1", "a:m", {"input_tokens": 10, "output_tokens": 5})
            run.spend("w2", "b:m", {"input_tokens": 10})
            run.spend("w3", "a:m", {"input_tokens": 1})
        self.assertEqual(run.total_spend(), (0.75, 1))
        run.spend("w4", "a:m", None)   # nothing to record
        self.assertEqual(len(run.ledger()), 3)

    def test_a_worker_waits_for_the_answer_and_gets_it(self):
        run = Run.create("t", {})
        handler = run.permission_handler("worker-1")
        got = []
        t = threading.Thread(target=lambda: got.append(handler("Bash", "run: ls", None)))
        t.start()
        for _ in range(500):
            if run.pending():
                break
            threading.Event().wait(0.01)
        (ask,) = run.pending()
        self.assertEqual((ask["who"], ask["tool"]), ("worker-1", "Bash"))
        self.assertTrue(Run.open(run.id).answer(ask["id"], True))   # another process, same files
        t.join(5)
        self.assertEqual(got, [(True, False)])
        self.assertFalse(run.answer(ask["id"], False))   # already answered
        self.assertEqual(run.pending(), [])

    def test_a_stopped_run_counts_as_no_and_a_bad_id_is_refused(self):
        run = Run.create("t", {})
        cancel = threading.Event()
        cancel.set()
        self.assertFalse(run.ask("w", "Bash", "m", cancel))
        self.assertEqual(run.pending(), [])
        self.assertFalse(run.answer("../x", True))


if __name__ == "__main__":
    unittest.main()
