"""Pinned sessions: stored locally, shown first, validated."""
from __future__ import annotations

from src.bonnie import pins
from tests.bonnie import test_server as ts
from tests.bonnie.test_artifacts import session, temp_dir


class TestPins(ts.BonnieCase):
    def setUp(self):
        super().setUp()
        self.root = temp_dir(self)
        self.repl.tool_context.workspace_root = self.root
        for n, when in (("pa", "2026-10-07T10:00:00"), ("pb", "2026-10-07T11:00:00"), ("pc", "2026-10-07T12:00:00")):
            session(n, self.root, [("1", "Write", {"file_path": str(self.root / "f")}, False)], when).save()
        (pins.folder() / "pins.json").unlink(missing_ok=True)
        self.addCleanup((pins.folder() / "pins.json").unlink, missing_ok=True)

    def ids(self):
        return [(s["id"], s["pinned"]) for s in self.call("GET", "/api/sessions")[1]["sessions"]]

    def test_pinned_sessions_come_first_and_unpinning_restores_the_order(self):
        self.assertEqual(self.ids(), [("pc", False), ("pb", False), ("pa", False)])
        self.assertEqual(self.call("POST", "/api/session/pin", {"id": "pa", "pinned": True})[0], 200)
        self.assertEqual(self.call("POST", "/api/session/pin", {"id": "pb", "pinned": True})[0], 200)
        self.assertEqual(self.ids(), [("pb", True), ("pa", True), ("pc", False)])
        self.call("POST", "/api/session/pin", {"id": "pb", "pinned": False})
        self.assertEqual(self.ids(), [("pa", True), ("pc", False), ("pb", False)])

    def test_bad_pins_are_refused_and_a_broken_file_reads_as_empty(self):
        for body in ({"id": "../x", "pinned": True}, {"id": "pa"}, {"id": "pa", "pinned": "yes"}):
            self.assertEqual(self.call("POST", "/api/session/pin", body)[0], 400)
        pins.folder().mkdir(parents=True, exist_ok=True)
        (pins.folder() / "pins.json").write_text("not json")
        self.assertEqual(pins.load(), [])
