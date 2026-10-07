"""Automations: schedules, the store, and the API and scheduler over a real REPL."""
from __future__ import annotations

import unittest
from datetime import datetime

from src.bonny import automations as au
from tests.bonny import test_server as ts
from tests.bonny.test_artifacts import temp_dir

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


class TestAutomations(ts.BonnyCase):
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
        before, seen = self.repl.session.session_id, self.bonny.events.last()
        self.bonny.tick(due_at)
        self.wait_for("turn_end", after=seen)
        self.assertNotEqual(self.repl.session.session_id, before)
        self.assertTrue(self.repl.tool_context.plan_mode)
        self.assertIsNotNone(au.get(str(self.root), row["id"])["last_run"])
        self.bonny.tick(due_at)   # next_run moved on, so nothing is queued again
        self.assertEqual(self.bonny.control.prompts.qsize(), 0)

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
