"""The floor plan comes only from what the run recorded: nothing is lit, used or counted before its event."""
from __future__ import annotations

import unittest
from typing import Any

from src.agent.station_layout import build, family

STATE = {"roles": {"master": "m:big", "advisor": "claude:haiku", "kinds": {}, "workers": [{"name": "worker-1", "model": "a"}, {"name": "worker-2", "model": "b"}]}}
CREW = [{"name": n, "model": "x", "kind": None, "doing": "idle", "constraint": None} for n in ("master", "advisor", "worker-1", "worker-2")]
NATIVE_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "Bash", "WebFetch", "MCP", "Remember", "TodoWrite"]


def ev(t: float, who: str, kind: str, **data: Any) -> dict[str, Any]:
    return {"t": t, "who": who, "kind": kind, **data}


def plan(events, asks=(), state=None, clyde="watching the workers", crew=None):
    return build(state or STATE, list(events), list(asks), crew or CREW, clyde, {"usd": 0.0, "unpriced": 0})


def lanes(layout) -> dict[str, dict[str, Any]]:
    return {h["id"]: h for h in layout["hallways"]}


def room(layout, rid):
    return next(r for r in layout["rooms"] if r["id"] == rid)


class Families(unittest.TestCase):
    def test_tools_group_into_display_families(self):
        self.assertEqual([family(t) for t in ("Read", "Grep", "Edit", "Write", "Bash", "WebFetch", "MCP", "mcp__github__x", "TodoWrite")],
                         ["read", "read", "write", "write", "shell", "web", "mcp", "mcp", "other"])


class Rooms(unittest.TestCase):
    def test_a_deck_one_bay_per_worker_and_an_outbox_and_no_worker_to_worker_hallway(self):
        layout = plan([ev(1, "clyde", "created")])
        self.assertEqual([r["id"] for r in layout["rooms"]], ["deck", "worker-1", "worker-2", "outbox"])
        self.assertEqual([m["name"] for m in room(layout, "deck")["members"]], ["clyde", "master", "advisor"])   # one capability scope
        for hall in layout["hallways"]:
            self.assertFalse(hall["from"].startswith("worker") and hall["to"].startswith("worker"), hall)   # workers hand off only through the deck
        self.assertEqual({h["id"] for h in layout["hallways"]},
                         {"task:worker-1", "results:worker-1", "approvals:worker-1", "task:worker-2", "results:worker-2",
                          "approvals:worker-2", "review", "report", "landing"})

    def test_without_an_advisor_there_is_no_review_lane_and_results_go_to_the_master(self):
        state = {"roles": {"master": "m", "advisor": None, "workers": [{"name": "worker-1", "model": "a"}]}}
        layout = plan([ev(1, "master", "reporting")], state=state, crew=[c for c in CREW if c["name"] in ("master", "worker-1")])
        self.assertNotIn("review", lanes(layout))
        self.assertEqual(lanes(layout)["results:worker-1"]["state"], "lit")   # bound to the master's reporting, there being no advisor
        self.assertEqual([m["name"] for m in room(layout, "deck")["members"]], ["clyde", "master"])


class Orchestrators(unittest.TestCase):
    def test_bonnie_stands_beside_clyde_on_the_deck_and_says_what_she_last_collected(self):
        state = {"roles": {**STATE["roles"], "orchestrators": ["clyde", "bonnie"]}}
        deck = room(plan([], state=state), "deck")["members"]
        self.assertEqual([(m["name"], m["doing"]) for m in deck[:2]], [("clyde", "watching the workers"), ("bonnie", "waiting at the deck")])
        collected = room(plan([ev(1, "bonnie", "check", target="worker-2", reason="result")], state=state), "deck")["members"][1]
        self.assertEqual(collected["doing"], "collected worker-2's result")
        self.assertEqual([m["name"] for m in room(plan([]), "deck")["members"]][:2], ["clyde", "master"])   # an older run has no Bonnie


class Objects(unittest.TestCase):
    def test_a_member_gets_an_object_per_family_it_was_given_and_nothing_else(self):
        events = [ev(1, "worker-1", "tools", tools=NATIVE_TOOLS), ev(1, "worker-2", "tools", tools=["Edit"]), ev(1, "advisor", "tools", tools=[])]
        layout = plan(events)
        self.assertEqual([o["family"] for o in room(layout, "worker-1")["objects"]], ["read", "write", "shell", "web", "mcp", "other"])
        self.assertEqual([o["family"] for o in room(layout, "worker-2")["objects"]], ["write"])   # aider: editing only
        self.assertEqual([o["id"] for o in room(layout, "deck")["objects"]], ["deck:approvals", "deck:ledger"])   # a toolless advisor adds none
        self.assertEqual(room(plan([]), "worker-1")["objects"], [])   # no grant recorded, no object shown

    def test_counts_come_from_the_members_own_events_and_asks_join_their_answers(self):
        events = [ev(1, "worker-1", "tools", tools=NATIVE_TOOLS),
                  ev(2, "worker-1", "tool_use", tool="Read"), ev(3, "worker-1", "tool_use", tool="Grep"), ev(4, "worker-1", "tool_use", tool="Edit"),
                  ev(5, "worker-1", "tool_use", tool="Bash"), ev(5.1, "worker-1", "approval_asked", approval="a1", tool="Bash"),
                  ev(6, "user", "approval_answered", approval="a1", allow=True),
                  ev(7, "worker-1", "tool_use", tool="Bash"), ev(7.1, "worker-1", "approval_asked", approval="a2", tool="Bash"),
                  ev(8, "user", "approval_answered", approval="a2", allow=False), ev(8.5, "worker-1", "tool_error", tool="Bash"),
                  ev(9, "worker-2", "tool_use", tool="Read")]   # another worker's use is not worker-1's
        objects = {o["family"]: o for o in room(plan(events), "worker-1")["objects"]}
        self.assertEqual((objects["read"]["used"], objects["write"]["used"], objects["web"]["used"]), (2, 1, 0))
        shell = objects["shell"]
        self.assertEqual((shell["used"], shell["asked"], shell["allowed"], shell["denied"], shell["failed"], shell["last"]), (2, 2, 1, 1, 1, 8.5))
        self.assertEqual((objects["read"]["asked"], objects["web"]["last"]), (0, None))

    def test_the_deck_counts_every_ask_and_how_many_are_waiting(self):
        events = [ev(1, "worker-1", "approval_asked", approval="a1", tool="Bash"), ev(2, "worker-2", "approval_asked", approval="a2", tool="Bash"),
                  ev(3, "user", "approval_answered", approval="a1", allow=True)]
        desk = room(plan(events, asks=[{"id": "a2", "who": "worker-2", "tool": "Bash"}]), "deck")["objects"][0]
        self.assertEqual((desk["asked"], desk["allowed"], desk["denied"], desk["pending"]), (2, 1, 0, 1))


class Hallways(unittest.TestCase):
    def test_nothing_is_lit_before_its_event(self):
        layout = plan([ev(1, "clyde", "created"), ev(2, "master", "splitting")])
        self.assertEqual({h["state"] for h in layout["hallways"]}, {"dark"})   # splitting is not a handoff; the split is
        self.assertEqual({h["count"] for h in layout["hallways"]}, {0})
        self.assertEqual(room(layout, "outbox")["state"], "empty")

    def test_each_lane_lights_on_its_own_event_in_the_order_they_happen(self):
        events = [ev(1, "master", "split", tasks=["a", "b"])]
        self.assertEqual([h["id"] for h in plan(events)["hallways"] if h["state"] == "lit"], ["task:worker-1", "task:worker-2"])
        events.append(ev(2, "advisor", "reviewing"))
        self.assertEqual({h["id"] for h in plan(events)["hallways"] if h["state"] == "lit"},
                         {"task:worker-1", "task:worker-2", "results:worker-1", "results:worker-2"})
        events += [ev(3, "advisor", "reviewed"), ev(4, "clyde", "status", status="awaiting_approval")]
        lit = {h["id"] for h in plan(events)["hallways"] if h["state"] == "lit"}
        self.assertTrue({"review", "report"} <= lit)
        self.assertEqual(lanes(plan(events))["landing"]["state"], "dark")   # the user has not decided
        events.append(ev(5, "user", "landed", outbox="/home/x/outbox/r"))
        layout = plan(events)
        self.assertEqual((lanes(layout)["landing"]["state"], room(layout, "outbox")["state"], room(layout, "outbox")["path"]),
                         ("lit", "landed", "/home/x/outbox/r"))

    def test_a_discard_refuses_the_landing_lane(self):
        layout = plan([ev(1, "user", "discarded", outbox=None)])
        self.assertEqual((lanes(layout)["landing"]["state"], room(layout, "outbox")["state"]), ("refused", "discarded"))

    def test_an_unanswered_ask_makes_that_workers_lane_wait_and_an_answered_one_stays_lit(self):
        events = [ev(1, "worker-1", "approval_asked", approval="a1", tool="Bash"), ev(2, "worker-2", "approval_asked", approval="a2", tool="Bash"),
                  ev(3, "user", "approval_answered", approval="a2", allow=True)]
        halls = lanes(plan(events, asks=[{"id": "a1", "who": "worker-1", "tool": "Bash"}]))
        self.assertEqual((halls["approvals:worker-1"]["state"], halls["approvals:worker-2"]["state"]), ("waiting", "lit"))
        self.assertEqual(halls["approvals:worker-1"]["count"], 1)
        self.assertEqual(lanes(plan([]))["approvals:worker-1"]["state"], "dark")

    def test_without_the_split_event_the_task_lanes_stay_dark_even_with_workers_running(self):
        events = [ev(1, "master", "splitting"), ev(2, "worker-1", "started"), ev(3, "worker-2", "started")]
        self.assertEqual({lanes(plan(events))[f"task:worker-{i}"]["state"] for i in (1, 2)}, {"dark"})


if __name__ == "__main__":
    unittest.main()
