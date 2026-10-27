"""Orchestration end to end with scripted models: split, concurrent workers in worktrees, approvals, review, outbox."""
from __future__ import annotations

import json
import subprocess
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import orchestration
from src.agent.harness import Harness, HarnessModel
from src.agent.orchestration import build_plan, land, orchestrate
from src.agent.runs import Run
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply

USAGE = {"input_tokens": 3, "output_tokens": 2}


def _harness(name: str, kind: str = "provider", models=("m",)) -> Harness:
    return Harness(name=name, kind=kind, models=[HarnessModel(model_id=m) for m in models])


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


class Plan(unittest.TestCase):
    def test_a_role_needs_a_runnable_harness_and_a_model_it_really_has(self):
        harnesses = [_harness("provider:a", models=("m1", "m2")), _harness("claude", kind="cli", models=("haiku",)),
                     _harness("codex", kind="cli", models=())]
        ok = build_plan("t", ("provider:a", "m1"), ("provider:a", "m2"), [("provider:a", "m1"), ("provider:a", "m1")], harnesses)
        self.assertEqual([w.ref for w in ok.workers], ["a:m1", "a:m1"])
        self.assertEqual((ok.master.ref, ok.advisor.ref), ("a:m1", "a:m2"))
        self.assertIn("no model 'zzz'", build_plan("t", ("provider:a", "zzz"), None, [("provider:a", "m1")], harnesses))
        self.assertIn("not found", build_plan("t", ("provider:b", "m"), None, [("provider:a", "m1")], harnesses))
        self.assertEqual(build_plan("t", ("provider:a", "m1"), None, [("claude", "haiku")], harnesses).workers[0].ref, "claude:haiku")
        self.assertIn("can't run", build_plan("t", ("provider:a", "m1"), None, [("codex", "default")], harnesses))
        self.assertIn("needs a provider model", build_plan("t", ("claude", "haiku"), None, [("provider:a", "m1")], harnesses))
        self.assertEqual(build_plan("t", ("provider:a", "m1"), None, [], harnesses), "No workers picked.")

    def test_a_local_model_in_the_plan_is_called_out(self):
        harnesses = [_harness("provider:ollama", models=("qwen",)), _harness("provider:a")]
        plan = build_plan("t", ("provider:a", "m"), None, [("provider:ollama", "qwen")], harnesses)
        self.assertIn("one at a time", orchestration.format_plan(plan))


class TeamSize(unittest.TestCase):
    def test_a_plan_has_at_most_as_many_workers_as_the_station_has_room_for(self):
        from src.agent.runs import MAX_TEAM
        harnesses = [_harness("provider:m"), _harness("provider:w")]
        many = [("provider:w", "m")] * (MAX_TEAM + 1)
        self.assertIn(f"At most {MAX_TEAM} workers", build_plan("t", ("provider:m", "m"), None, many, harnesses))
        self.assertNotIsInstance(build_plan("t", ("provider:m", "m"), None, many[:MAX_TEAM], harnesses), str)


class CostCapPrompt(unittest.TestCase):
    def test_the_cap_is_a_positive_number_of_dollars_or_empty(self):
        from src.repl.orchestrate import _parse_cap
        self.assertEqual((_parse_cap(""), _parse_cap("  "), _parse_cap("2"), _parse_cap("$0.50")), (None, None, 2.0, 0.5))
        for bad in ("abc", "0", "-1", "1e9", "nan"):
            self.assertIsInstance(_parse_cap(bad), str, bad)


class HandOver(unittest.TestCase):
    def test_a_full_team_refuses_the_order_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp, patch("src.agent.runs.clyde_home", return_value=Path(tmp)):
            run = Run.create("t", {"workers": []})
            run.set_status("running")
            order = {"id": run.order("one more"), "task": "one more"}
            names = [f"worker-{i}" for i in range(1, 13)]
            self.assertIsNone(orchestration._hand_over(run, order, names, None, Path(tmp), None, None))
            self.assertEqual(len(names), 12)
            self.assertEqual(run.pending_orders(), [])
            self.assertIn(("clyde", "order_refused"), [(e["who"], e["kind"]) for e in run.events()])


class Split(unittest.TestCase):
    def test_only_the_exact_count_of_tasks_is_accepted(self):
        self.assertEqual(orchestration._split('sure {"tasks": ["a", "b"]} done', 2), ["a", "b"])
        for bad in ('{"tasks": ["a"]}', '{"tasks": ["a", ""]}', "no json", '{"tasks": "ab"}', '{"x": 1}'):
            self.assertIsNone(orchestration._split(bad, 2), bad)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("src.agent.runs.clyde_home", return_value=Path(self.tmp.name) / "home")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "init")

    def _run(self, workers, on_approval=None):
        providers = {
            "m": FakeProvider(reply('{"tasks": ["write a.txt", "write b.txt"]}', usage=USAGE),
                              reply("Both done.\nVERDICT: APPROVE", usage=USAGE), name="m"),
            "adv": FakeProvider(reply("Looks right.", usage=USAGE), name="adv"),
            **workers,
        }
        plan = build_plan("two files", ("provider:m", "m"), ("provider:adv", "m"),
                          [("provider:w1", "m"), ("provider:w2", "m")], [_harness(f"provider:{n}") for n in providers])
        return orchestrate(plan, "make a.txt and b.txt", workspace=self.repo, parent=ToolContext(workspace_root=self.repo),
                           registry=build_default_registry(), providers=providers, on_approval=on_approval)

    def test_two_workers_write_in_their_own_worktrees_and_the_files_land_in_the_outbox(self):
        w1 = FakeProvider(reply(tool_calls=[("Write", {"file_path": "a.txt", "content": "A\n"})]), reply("wrote a", usage=USAGE), name="w1")
        w2 = FakeProvider(reply(tool_calls=[("Write", {"file_path": "b.txt", "content": "B\n"})]), reply("wrote b", usage=USAGE), name="w2")
        outcome = self._run({"w1": w1, "w2": w2})
        self.assertNotIsInstance(outcome, str, outcome)
        self.assertEqual((outcome.verdict, outcome.failed), ("approve", []))
        run = outcome.run
        self.assertEqual(run.state()["status"], "awaiting_approval")
        self.assertFalse((self.repo / "a.txt").exists())   # the project is untouched until the user decides
        kinds = [(e["who"], e["kind"]) for e in run.events()]
        for who in ("worker-1", "worker-2"):
            self.assertIn((who, "started"), kinds)
            self.assertIn((who, "finished"), kinds)
            self.assertIn((who, "constraint"), kinds)   # the rule a native worker really runs under is on record
        checks = [(e["who"], e["target"], e["reason"]) for e in run.events() if e["kind"] == "check"]
        for worker in ("worker-1", "worker-2"):
            self.assertIn(("clyde", worker, "brief"), checks)    # Clyde takes each worker its task
            self.assertIn(("bonnie", worker, "result"), checks)  # Bonnie collects what it made
        self.assertEqual(run.state()["roles"]["orchestrators"], ["clyde", "bonnie"])
        tools = {e["who"]: e["tools"] for e in run.events() if e["kind"] == "tools"}
        self.assertEqual((tools["master"], tools["advisor"]), ([], []))   # a model call with no tools
        self.assertTrue({"Read", "Write", "Edit", "Bash", "Grep"} <= set(tools["worker-1"]))
        self.assertTrue(not {"Agent", "TeamCreate", "TeamDelete"} & set(tools["worker-1"]))   # a worker can't start agents of its own
        self.assertEqual(run.state()["roles"]["kinds"], {"master": "provider", "advisor": "provider", "worker-1": "provider", "worker-2": "provider"})
        self.assertEqual({r["who"] for r in run.ledger()}, {"master", "advisor", "worker-1", "worker-2"})
        out = land(run, approve=True)
        self.assertEqual((out / "worker-1" / "files" / "a.txt").read_text(), "A\n")
        self.assertEqual((out / "worker-2" / "files" / "b.txt").read_text(), "B\n")
        self.assertIn("a.txt", (out / "worker-1" / "changes.patch").read_text())
        self.assertIn("VERDICT", (out / "report.md").read_text())
        self.assertEqual(Run.open(run.id).state()["status"], "done")
        listed = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True, check=False).stdout
        self.assertEqual(len(listed.strip().splitlines()), 1)   # the worktrees were removed
        self.assertNotIn("clyde-run", subprocess.run(["git", "branch"], cwd=self.repo, capture_output=True, text=True, check=False).stdout)

    def test_a_worker_the_user_adds_mid_run_gets_its_task_through_clyde_and_is_recorded(self):
        started = []
        w1 = FakeProvider(reply(tool_calls=[("Bash", {"command": "echo hi > c.txt"})]), reply("tried"), reply("did the extra"), reply("did the extra"), name="w1")
        w2 = FakeProvider(reply("nothing to do"), name="w2")

        def on_approval(ask):   # the first request arrives while the run works: this is the moment the user adds a worker
            started[0].order("write c.txt")
            return False

        providers = {"m": FakeProvider(reply('{"tasks": ["a", "b"]}', usage=USAGE), reply("ok\nVERDICT: APPROVE", usage=USAGE), name="m"),
                     "adv": FakeProvider(reply("fine"), name="adv"), "w1": w1, "w2": w2}
        plan = build_plan("t", ("provider:m", "m"), ("provider:adv", "m"), [("provider:w1", "m"), ("provider:w2", "m")], [_harness(f"provider:{n}") for n in providers])
        outcome = orchestrate(plan, "spec", workspace=self.repo, parent=ToolContext(workspace_root=self.repo), registry=build_default_registry(),
                              providers=providers, on_approval=on_approval, on_start=started.append)
        run = outcome.run
        events = run.events()
        self.assertEqual([r["name"] for r in run.state()["roles"]["workers"]], ["worker-1", "worker-2", "worker-3"], [(e["who"], e["kind"], e.get("note")) for e in events])
        self.assertEqual(run.state()["roles"]["kinds"]["worker-3"], "provider")
        self.assertIn("worker-3", run.state()["workspaces"])
        kinds = [(e["who"], e["kind"]) for e in events]
        for pair in (("user", "ordered"), ("worker-3", "tools"), ("worker-3", "started"), ("worker-3", "finished")):
            self.assertIn(pair, kinds)
        self.assertLess(kinds.index(("user", "ordered")), kinds.index(("worker-3", "started")))   # asked first, then it began
        self.assertIn(("clyde", "worker-3", "brief"), [(e["who"], e.get("target"), e.get("reason")) for e in events if e["kind"] == "check"])
        self.assertIn(("bonnie", "worker-3", "result"), [(e["who"], e.get("target"), e.get("reason")) for e in events if e["kind"] == "check"])
        order = json.loads(next((run.root / "orders").glob("*.json")).read_text())
        self.assertEqual((order["status"], order["worker"]), ("accepted", "worker-3"))
        self.assertEqual(run.pending_orders(), [])
        land(run, approve=False)

    def test_a_task_the_user_gives_a_worker_runs_after_its_first_in_the_same_conversation(self):
        started = []
        w1 = FakeProvider(reply(tool_calls=[("Bash", {"command": "echo hi > c.txt"})]), reply("tried"), name="w1")
        w2 = FakeProvider(reply("first done"), reply("second done"), name="w2")

        def on_approval(ask):   # while worker-1 waits, the user gives worker-2 a task
            started[0].order("also write d.txt", "worker-2")
            return False

        providers = {"m": FakeProvider(reply('{"tasks": ["a", "b"]}', usage=USAGE), reply("ok\nVERDICT: APPROVE", usage=USAGE), name="m"),
                     "adv": FakeProvider(reply("fine"), name="adv"), "w1": w1, "w2": w2}
        plan = build_plan("t", ("provider:m", "m"), ("provider:adv", "m"), [("provider:w1", "m"), ("provider:w2", "m")], [_harness(f"provider:{n}") for n in providers])
        outcome = orchestrate(plan, "spec", workspace=self.repo, parent=ToolContext(workspace_root=self.repo), registry=build_default_registry(),
                              providers=providers, on_approval=on_approval, on_start=started.append)
        run = outcome.run
        mine = [(e["kind"], e.get("note")) for e in run.events() if e["who"] == "worker-2" and e["kind"] in ("started", "finished", "failed")]
        self.assertEqual(mine, [("started", None), ("finished", None), ("started", "a task from you"), ("finished", None)])
        self.assertIn(("clyde", "worker-2", "brief"), [(e["who"], e.get("target"), e.get("reason")) for e in run.events() if e["kind"] == "check"])
        order = json.loads(next((run.root / "orders").glob("*.json")).read_text())
        self.assertEqual((order["status"], order["worker"]), ("accepted", "worker-2"))
        self.assertEqual([r["name"] for r in run.state()["roles"]["workers"]], ["worker-1", "worker-2"])   # nobody was added
        self.assertGreater(len(w2.requests[-1]["conversation"].messages), 2)   # the second task saw the first in its conversation
        self.assertIn("A task from you", (run.root / "workers" / "worker-2" / "summary.md").read_text())
        land(run, approve=False)

    def test_a_command_waits_for_an_approval_and_a_no_reaches_the_worker(self):
        asked = []
        w1 = FakeProvider(reply(tool_calls=[("Bash", {"command": "echo hi > c.txt"})]), reply("tried"), name="w1")
        w2 = FakeProvider(reply("nothing to do"), name="w2")

        def on_approval(ask):
            asked.append((ask["who"], ask["tool"]))
            return False

        outcome = self._run({"w1": w1, "w2": w2}, on_approval=on_approval)
        self.assertEqual(asked, [("worker-1", "Bash")])
        picked = [(e["who"], e["target"], e["reason"]) for e in outcome.run.events() if e["kind"] == "check" and e["reason"] == "approval"]
        self.assertEqual(picked, [("clyde", "worker-1", "approval")])   # Clyde took the request to the user
        result = str(w1.requests[-1]["conversation"].messages[-1].tool_results[0].content).lower()
        self.assertTrue("denied" in result or "permission" in result or "not allowed" in result, result)
        land(outcome.run, approve=False)
        self.assertEqual(outcome.run.state()["status"], "stopped")

    def test_ctrl_c_while_a_worker_waits_stops_the_run_and_removes_its_worktrees(self):
        w1 = FakeProvider(reply(tool_calls=[("Bash", {"command": "echo hi > c.txt"})]), reply("never"), name="w1")
        w2 = FakeProvider(reply("done"), name="w2")

        def on_approval(_ask):
            raise KeyboardInterrupt

        outcome = self._run({"w1": w1, "w2": w2}, on_approval=on_approval)
        self.assertEqual(outcome.run.state()["status"], "stopped")
        self.assertEqual(outcome.report, "Stopped before the review.")
        self.assertEqual(outcome.run.pending(), [])   # the waiting ask was answered no, not left hanging
        listed = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True, check=False).stdout
        self.assertEqual(len(listed.strip().splitlines()), 1)
        self.assertFalse((self.repo / "c.txt").exists())

    def test_stop_from_the_station_stops_every_worker_the_same_way_as_ctrl_c(self):
        started = []
        w1 = FakeProvider(reply(tool_calls=[("Bash", {"command": "echo hi > c.txt"})]), reply("never"), name="w1")
        w2 = FakeProvider(reply("done"), name="w2")

        def on_approval(_ask):   # the user presses Stop while worker-1 waits for an answer
            started[0].stop()
            return True   # even a yes does not let it go on: the stop wins

        providers = {"m": FakeProvider(reply('{"tasks": ["a", "b"]}'), name="m"), "adv": FakeProvider(reply("x"), name="adv"), "w1": w1, "w2": w2}
        plan = build_plan("t", ("provider:m", "m"), ("provider:adv", "m"), [("provider:w1", "m"), ("provider:w2", "m")], [_harness(f"provider:{n}") for n in providers])
        outcome = orchestrate(plan, "spec", workspace=self.repo, parent=ToolContext(workspace_root=self.repo), registry=build_default_registry(),
                              providers=providers, on_approval=on_approval, on_start=started.append)
        run = outcome.run
        self.assertEqual((run.state()["status"], outcome.report), ("stopped", "Stopped before the review."))
        kinds = [(e["who"], e["kind"]) for e in run.events()]
        self.assertLess(kinds.index(("user", "stop_requested")), kinds.index(("clyde", "stopping")))
        self.assertNotIn(("advisor", "reviewing"), kinds)   # it never went on to the review
        with self.assertRaises(ValueError):
            run.order("one more")   # nothing new is taken on a stopped run
        listed = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True, check=False).stdout
        self.assertEqual(len(listed.strip().splitlines()), 1)
        self.assertFalse((self.repo / "c.txt").exists())

    def test_the_run_stops_when_its_priced_spend_reaches_the_cap_and_says_so(self):
        w1 = FakeProvider(reply("done a", usage=USAGE), name="w1")
        w2 = FakeProvider(reply("done b", usage=USAGE), name="w2")
        providers = {"m": FakeProvider(reply('{"tasks": ["a", "b"]}', usage=USAGE), reply("ok\nVERDICT: APPROVE", usage=USAGE), name="m"),
                     "adv": FakeProvider(reply("fine", usage=USAGE), name="adv"), "w1": w1, "w2": w2}
        plan = build_plan("t", ("provider:m", "m"), ("provider:adv", "m"), [("provider:w1", "m"), ("provider:w2", "m")], [_harness(f"provider:{n}") for n in providers])
        with patch("src.agent.cost_tracker.estimate_usd", return_value=1.0):   # every call costs a dollar
            outcome = orchestrate(plan, "spec", workspace=self.repo, parent=ToolContext(workspace_root=self.repo), registry=build_default_registry(),
                                  providers=providers, cost_cap=2.5)
        run = outcome.run
        self.assertEqual((run.state()["status"], outcome.report, run.state()["cap_usd"]), ("stopped", "Stopped at the cost cap.", 2.5))
        events = [(e["who"], e["kind"]) for e in run.events()]
        self.assertEqual(events.count(("clyde", "cost_cap")), 1)
        self.assertNotIn(("advisor", "reviewing"), events)   # no review, no report: nothing more is bought
        self.assertNotIn(("master", "reporting"), events)
        self.assertGreaterEqual(run.total_spend()[0], 2.5)
        listed = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True, check=False).stdout
        self.assertEqual(len(listed.strip().splitlines()), 1)

    def test_a_run_under_its_cap_finishes_as_usual_and_unpriced_spend_is_not_counted(self):
        providers = {"m": FakeProvider(reply('{"tasks": ["a"]}', usage=USAGE), reply("ok\nVERDICT: APPROVE", usage=USAGE), name="m"), "w1": FakeProvider(reply("x", usage=USAGE), name="w1")}
        plan = build_plan("t", ("provider:m", "m"), None, [("provider:w1", "m")], [_harness(f"provider:{n}") for n in providers])
        with patch("src.agent.cost_tracker.estimate_usd", return_value=None):   # no price: the cap cannot see it
            outcome = orchestrate(plan, "spec", workspace=self.repo, parent=ToolContext(workspace_root=self.repo), registry=build_default_registry(),
                                  providers=providers, cost_cap=0.01)
        self.assertEqual(outcome.run.state()["status"], "awaiting_approval")
        self.assertNotIn(("clyde", "cost_cap"), [(e["who"], e["kind"]) for e in outcome.run.events()])
        land(outcome.run, approve=False)

    def test_a_worker_never_has_more_than_its_lead(self):
        from src.tool_system.permissions import ToolPermissionContext
        from src.tool_system.tools.agent import offered_tools
        from src.agent.agent_types import GENERAL, AgentType
        parent = ToolContext(workspace_root=self.repo, permission_context=ToolPermissionContext.from_iterables(["Bash"], ["mcp__evil"], workspace_root=self.repo),
                             permission_rules={"deny": ["WebFetch"], "ask": [], "allow": []})
        context = orchestration._worker_context(parent, self.repo, Run.create("t", {}), "worker-1", threading.Event(), None, "m")
        self.assertTrue(context.permission_context.blocks_tool("Bash") and context.permission_context.blocks_tool("mcp__evil_x"))   # what the lead is denied stays denied
        self.assertIs(context.permission_rules, parent.permission_rules)
        offered = offered_tools(build_default_registry(), AgentType(GENERAL, "orchestrated worker"), parent.permission_rules)
        self.assertNotIn("WebFetch", offered)                                    # a bare deny hides the tool from the worker
        self.assertFalse({"Agent", "TeamCreate", "TeamDelete"} & set(offered))   # and a worker can never start workers of its own

    def test_a_local_model_among_the_workers_makes_them_run_one_at_a_time(self):
        import threading
        import time
        live, peak, lock = [0], [0], threading.Lock()

        class Slow(FakeProvider):
            def stream(self, *args, **kwargs):
                with lock:
                    live[0] += 1
                    peak[0] = max(peak[0], live[0])
                time.sleep(0.15)
                try:
                    return super().stream(*args, **kwargs)
                finally:
                    with lock:
                        live[0] -= 1

        providers = {"m": FakeProvider(reply('{"tasks": ["a", "b"]}'), reply("ok\nVERDICT: APPROVE"), name="m"),
                     "ollama": Slow(reply("one"), reply("two"), name="ollama", models=("q",)),
                     "cloud": Slow(reply("one"), reply("two"), name="cloud")}

        def peak_for(second: str) -> tuple[int, list[str]]:
            live[0] = peak[0] = 0
            for p in (providers["ollama"], providers["cloud"]):
                p._responses = [reply("x"), reply("y")]
            for p in (providers["m"],):
                p._responses = [reply('{"tasks": ["a", "b"]}'), reply("ok\nVERDICT: APPROVE")]
            harnesses = [_harness("provider:m"), _harness("provider:ollama", models=("q",)), _harness("provider:cloud")]
            plan = build_plan("t", ("provider:m", "m"), None, [("provider:ollama", "q"), (second, "q" if second.endswith("ollama") else "m")], harnesses)
            out = orchestrate(plan, "s", workspace=self.repo, parent=ToolContext(workspace_root=self.repo),
                              registry=build_default_registry(), providers=providers)
            land(out.run, approve=False)
            return peak[0], [e["kind"] for e in out.run.events()]

        peak_local, kinds = peak_for("provider:ollama")
        self.assertEqual(peak_local, 1)
        self.assertIn("serialized", kinds)
        peak_mixed, _ = peak_for("provider:cloud")
        self.assertEqual(peak_mixed, 1)   # one local worker is enough to serialize the whole team
        # and without any local model they do overlap
        for p in (providers["cloud"],):
            p._responses = [reply("x"), reply("y")]
        providers["m"]._responses = [reply('{"tasks": ["a", "b"]}'), reply("ok\nVERDICT: APPROVE")]
        live[0] = peak[0] = 0
        plan = build_plan("t", ("provider:m", "m"), None, [("provider:cloud", "m")] * 2, [_harness("provider:m"), _harness("provider:cloud")])
        out = orchestrate(plan, "s", workspace=self.repo, parent=ToolContext(workspace_root=self.repo),
                          registry=build_default_registry(), providers=providers)
        land(out.run, approve=False)
        self.assertEqual(peak[0], 2)

    def test_a_bold_verdict_counts_and_a_bad_split_is_retried_then_reported(self):
        providers = {"m": FakeProvider(reply("here you go: no json"), reply("still prose"), reply("Done.\n**VERDICT: APPROVE**"), name="m"),
                     "w1": FakeProvider(reply("a"), name="w1"), "w2": FakeProvider(reply("b"), name="w2")}
        plan = build_plan("t", ("provider:m", "m"), None, [("provider:w1", "m"), ("provider:w2", "m")], [_harness(f"provider:{n}") for n in providers])
        outcome = orchestrate(plan, "s", workspace=self.repo, parent=ToolContext(workspace_root=self.repo),
                              registry=build_default_registry(), providers=providers)
        self.assertEqual(outcome.verdict, "approve")
        self.assertEqual(len(outcome.notes), 1)
        self.assertIn("whole spec", outcome.notes[0])
        asked = [r["conversation"].messages[0].text for r in providers["m"].requests[:2]]
        self.assertNotIn("not the JSON asked for", asked[0])
        self.assertIn("not the JSON asked for", asked[1])
        land(outcome.run, approve=False)

    def test_on_start_runs_once_the_run_exists_and_before_any_model_call(self):
        seen = []
        providers = {"m": FakeProvider(reply('{"tasks": ["a"]}'), reply("ok\nVERDICT: APPROVE"), name="m"), "w1": FakeProvider(reply("x"), name="w1")}
        plan = build_plan("t", ("provider:m", "m"), None, [("provider:w1", "m")], [_harness(f"provider:{n}") for n in providers])

        def on_start(run):
            seen.append((run.state()["roles"]["workers"][0]["name"], [e["kind"] for e in run.events()], len(providers["m"].requests)))

        outcome = orchestrate(plan, "s", workspace=self.repo, parent=ToolContext(workspace_root=self.repo),
                              registry=build_default_registry(), providers=providers, on_start=on_start)
        self.assertEqual(seen, [("worker-1", ["created", "tools", "tools"], 0)])   # the grants are on record before anything runs
        land(outcome.run, approve=False)

    def test_a_worker_that_fails_is_reported_and_the_others_still_finish(self):
        outcome = self._run({"w1": FakeProvider(RuntimeError("boom"), name="w1"), "w2": FakeProvider(reply("done"), name="w2")})
        self.assertEqual(outcome.failed, ["worker-1"])
        self.assertIn("boom", (outcome.run.root / "workers" / "worker-1" / "summary.md").read_text())
        land(outcome.run, approve=False)

    def test_outside_a_git_repo_it_says_so_and_creates_nothing(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        plan = build_plan("t", ("provider:m", "m"), None, [("provider:m", "m")], [_harness("provider:m")])
        out = orchestrate(plan, "s", workspace=plain, parent=ToolContext(workspace_root=plain), registry=build_default_registry(),
                          providers={"m": FakeProvider(name="m")})
        self.assertIn("git repository", out)
        self.assertEqual(Run.all(), [])


if __name__ == "__main__":
    unittest.main()
