"""Automations: schedules, the store, and the API and scheduler over a real REPL."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from src.bonnie import automations as au
from tests.bonnie import test_server as ts
from tests.bonnie.test_artifacts import temp_dir

MON_9 = datetime(2026, 10, 5, 9, 0, 0)   # a Monday
STAMP = "%Y-%m-%dT%H:%M:%S"


class TestSchedule(unittest.TestCase):
    def test_the_next_run_for_each_kind(self):
        self.assertEqual(au.next_run({"kind": "every", "minutes": 90}, MON_9), datetime(2026, 10, 5, 10, 30))
        self.assertEqual(au.next_run({"kind": "daily", "at": "09:00"}, MON_9), datetime(2026, 10, 6, 9, 0))   # strictly after
        self.assertEqual(au.next_run({"kind": "daily", "at": "17:30"}, MON_9), datetime(2026, 10, 5, 17, 30))
        weekly = {"kind": "weekly", "days": [2, 4], "at": "08:00"}   # Wed, Fri
        self.assertEqual(au.next_run(weekly, MON_9), datetime(2026, 10, 7, 8, 0))
        self.assertEqual(au.next_run(weekly, datetime(2026, 10, 9, 8, 0)), datetime(2026, 10, 14, 8, 0))   # next Wed

    def test_bad_schedules_are_refused_and_good_ones_described(self):
        for bad in (None, {}, {"kind": "every", "minutes": 1}, {"kind": "every", "minutes": True}, {"kind": "daily", "at": "25:00"},
                    {"kind": "weekly", "days": [], "at": "08:00"}, {"kind": "weekly", "days": [7], "at": "08:00"}):
            with self.assertRaises(ValueError):
                au.clean_schedule(bad)
        self.assertEqual(au.describe(au.clean_schedule({"kind": "weekly", "days": [4, 0, 0], "at": "08:00"})), "Mon, Fri at 08:00")
        self.assertEqual(au.describe({"kind": "every", "minutes": 120}), "Every 2 h")


class TestLockAndLog(ts.BonnieCase):
    def setUp(self):
        super().setUp()
        for name in ("automations.json", "automations.json.prev", "automations.log", "automations.lock"):
            (au.folder() / name).unlink(missing_ok=True)
        self.project = "/p"

    def test_a_due_run_is_claimed_once_however_many_ask_at_the_same_moment(self):
        import threading
        row = au.add(self.project, "n", "look", {"kind": "every", "minutes": 30}, False, MON_9)
        at = datetime.strptime(row["next_run"], STAMP)
        got, barrier = [], threading.Barrier(8)

        def ask():
            barrier.wait()
            got.extend(au.due(self.project, at, claim=True))

        threads = [threading.Thread(target=ask) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(len(got), 1)
        self.assertEqual([e["what"] for e in au.history(self.project, row["id"])], ["ran", "created"])

    def test_two_windows_adding_at_once_lose_nothing(self):
        import os
        import subprocess
        import sys
        code = ("import sys\nfrom datetime import datetime\nfrom src.bonnie import automations as au\n"
                "for i in range(12): au.add('/p', sys.argv[1] + str(i), 'look', {'kind': 'every', 'minutes': 30}, False, datetime(2026, 10, 5, 9, 0))\n")
        env = {**os.environ, "HOME": os.environ["HOME"], "PYTHONPATH": os.getcwd()}
        procs = [subprocess.Popen([sys.executable, "-c", code, tag], env=env, cwd=os.getcwd()) for tag in ("a", "b", "c")]
        for p in procs:
            self.assertEqual(p.wait(60), 0)
        names = sorted(a["name"] for a in au.listing(self.project))
        self.assertEqual(len(names), 36)   # three windows, twelve each: no edit was lost
        self.assertEqual(len(set(names)), 36)

    def test_every_decision_is_logged_with_its_reason_and_the_log_is_bounded(self):
        row = au.add(self.project, "n", "look", {"kind": "every", "minutes": 30}, False, MON_9)
        au.update(self.project, row["id"], "pause")
        au.update(self.project, row["id"], "resume")
        late = datetime.strptime(au.get(self.project, row["id"])["next_run"], STAMP) + timedelta(hours=3)
        self.assertEqual(au.due(self.project, late, claim=True), [])   # missed while closed
        again = datetime.strptime(au.get(self.project, row["id"])["next_run"], STAMP)
        self.assertEqual(len(au.due(self.project, again, claim=True)), 1)
        au.update(self.project, row["id"], "delete")
        log = au.history(self.project, row["id"])
        self.assertEqual([e["what"] for e in log], ["deleted", "ran", "skipped", "resumed", "paused", "created"])
        skipped = next(e for e in log if e["what"] == "skipped")
        self.assertIn("Bonnie was closed", skipped["why"])
        self.assertIn("3 h", skipped["why"])
        self.assertEqual(au.history("/other", row["id"]), [])   # another project sees none of it
        for i in range(au.LOG_KEEP + 30):
            au.record(row, "ran", f"n{i}")
        lines = (au.folder() / "automations.log").read_text().splitlines()
        self.assertEqual(len(lines), au.LOG_KEEP)
        (au.folder() / "automations.log").write_text("\n".join(lines) + '\n{"t": "cut')   # a crash cut the last line
        self.assertEqual(len(au.history(self.project, row["id"], 5)), 5)


class TestAutomations(ts.BonnieCase):
    def setUp(self):
        super().setUp()
        self.root = temp_dir(self)
        self.repl.tool_context.workspace_root = self.root
        (au.folder() / "automations.json").unlink(missing_ok=True)
        self.addCleanup((au.folder() / "automations.json").unlink, missing_ok=True)

    def create(self, **over):
        body = {"name": "Morning look", "prompt": "what changed overnight?", "schedule": {"kind": "every", "minutes": 30}, **over}
        return self.call("POST", "/api/automation/create", body)

    def test_create_list_pause_and_delete_stay_inside_the_open_project(self):
        status, made = self.create()
        self.assertEqual(status, 200)
        row = made["automation"]
        self.assertEqual((row["edits"], row["paused"]), (False, False))
        listed = self.call("GET", "/api/automations")[1]["automations"]
        self.assertEqual([(a["name"], a["when"]) for a in listed], [("Morning look", "Every 30 min")])
        self.assertEqual(self.call("POST", "/api/automation/pause", {"id": row["id"]})[0], 200)
        self.assertTrue(self.call("GET", "/api/automations")[1]["automations"][0]["paused"])
        self.repl.tool_context.workspace_root = temp_dir(self)   # another project sees none of it
        self.assertEqual(self.call("GET", "/api/automations")[1]["automations"], [])
        self.assertEqual(self.call("POST", "/api/automation/delete", {"id": row["id"]})[0], 404)
        self.repl.tool_context.workspace_root = self.root
        self.assertEqual(self.call("POST", "/api/automation/delete", {"id": row["id"]})[0], 200)
        self.assertEqual(self.call("GET", "/api/automations")[1]["automations"], [])

    def test_the_list_shows_the_last_decision_and_the_history_answers_for_one_automation(self):
        row = self.create()[1]["automation"]
        self.call("POST", "/api/automation/pause", {"id": row["id"]})
        listed = self.call("GET", "/api/automations")[1]["automations"][0]
        self.assertEqual((listed["last"]["what"], listed["last"]["why"]), ("paused", "you asked for it"))
        self.assertEqual(self.call("POST", "/api/automation/run", {"id": row["id"]})[0], 200)
        history = self.call("GET", "/api/automation/history?id=" + row["id"])[1]["history"]
        self.assertEqual([e["what"] for e in history][:3], ["ran", "paused", "created"])
        self.assertEqual(history[0]["why"], "you pressed Run now")
        self.assertEqual(self.call("GET", "/api/automation/history?id=../x")[0], 400)

    def test_bad_input_is_refused(self):
        self.assertEqual(self.create(prompt="  ")[0], 400)
        self.assertEqual(self.create(prompt="x" * 4001)[0], 400)
        self.assertEqual(self.create(schedule={"kind": "every", "minutes": 2})[0], 400)
        self.assertEqual(self.create(edits="yes")[0], 400)
        self.assertEqual(self.call("POST", "/api/automation/explode", {"id": "abc"})[0], 400)
        self.assertEqual(self.call("POST", "/api/automation/run", {"id": "../x"})[0], 400)

    def test_a_due_run_is_read_only_gets_its_own_session_and_is_not_repeated(self):
        row = self.create()[1]["automation"]
        due_at = datetime.strptime(row["next_run"], STAMP)
        self.call("POST", "/api/prompt", {"text": "hi"})   # a saved session, so a run has to leave it
        self.wait_for("turn_end")
        before, seen = self.repl.session.session_id, self.bonnie.events.last()
        self.bonnie.tick(due_at)
        self.wait_for("turn_end", after=seen)
        self.assertNotEqual(self.repl.session.session_id, before)
        self.assertTrue(self.repl.tool_context.plan_mode)
        self.assertIsNotNone(au.get(str(self.root), row["id"])["last_run"])
        self.bonnie.tick(due_at)   # next_run moved on, so nothing is queued again
        self.assertEqual(self.bonnie.control.prompts.qsize(), 0)

    def test_a_run_missed_while_closed_is_skipped_and_a_paused_one_never_fires(self):
        row = self.create()[1]["automation"]
        due_at = datetime.strptime(row["next_run"], STAMP)
        much_later = due_at.replace(year=due_at.year + 1)
        self.assertEqual(au.due(str(self.root), much_later), [])
        self.assertGreater(datetime.strptime(au.get(str(self.root), row["id"])["next_run"], STAMP), much_later)
        au.update(str(self.root), row["id"], "pause")
        self.assertEqual(au.due(str(self.root), datetime.strptime(au.get(str(self.root), row["id"])["next_run"], STAMP)), [])

    def test_edits_are_an_opt_in_and_run_now_queues_a_turn(self):
        row = self.create(edits=True)[1]["automation"]
        self.assertEqual(self.call("POST", "/api/automation/run", {"id": row["id"]})[0], 200)
        self.wait_for("turn_end")
        self.assertTrue(self.repl.tool_context.auto_approve)
