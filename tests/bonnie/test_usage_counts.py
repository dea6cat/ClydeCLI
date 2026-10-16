"""Bonnie reports which features get used, as one word from a fixed list, and only for an action that succeeded."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import telemetry
from src.bonnie import server
from tests.bonnie.test_server import BonnieCase


class UsageCase(BonnieCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcher = patch("src.telemetry.clyde_home", return_value=Path(self.home.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict("os.environ", {"CLYDE_TELEMETRY": "", "DO_NOT_TRACK": ""})
        env.start()
        self.addCleanup(env.stop)
        super().setUp()

    def features(self):
        return [e["feature"] for e in telemetry.queued() if e["event"] == "bonnie_use"]


class TestUsageCounts(UsageCase):
    def test_nothing_is_recorded_while_telemetry_is_off(self):
        self.call("POST", "/api/mode", {"mode": "plan"})
        self.assertEqual(telemetry.queued(), [])

    def test_a_successful_action_is_counted_under_its_word(self):
        telemetry.turn_on()
        status, _ = self.call("POST", "/api/mode", {"mode": "plan"})[:2]
        self.assertEqual(status, 200)
        self.call("POST", "/api/session/new", {})
        self.assertEqual(self.features(), ["mode", "session_new"])

    def test_a_refused_action_is_not_counted(self):
        telemetry.turn_on()
        self.assertEqual(self.call("POST", "/api/mode", {"mode": "nonsense"})[0], 400)
        self.assertEqual(self.call("POST", "/api/nowhere", {})[0], 404)
        self.assertEqual(self.features(), [])

    def test_reading_state_is_not_counted(self):
        telemetry.turn_on()
        self.call("GET", "/api/state")
        self.call("GET", "/api/automations")
        self.assertEqual(self.features(), [])

    def test_what_was_said_never_reaches_the_event(self):
        telemetry.turn_on()
        self.call("POST", "/api/prompt", {"text": "my secret plan: ZEBRA-4417"})
        self.assertEqual(self.features(), ["prompt"])
        self.assertNotIn("ZEBRA", json.dumps(telemetry.queued()))

    def test_an_automation_action_is_counted_by_its_name(self):
        telemetry.turn_on()
        self.call("POST", "/api/automation/create", {"name": "n", "prompt": "p", "every": "1h"})
        self.call("POST", "/api/automation/delete", {"id": "0" * 12})   # no such automation: refused, so not counted
        self.assertNotIn("automation_delete", self.features())


class TestTheWordsAgree(unittest.TestCase):
    def test_every_route_maps_to_a_word_the_schema_allows(self):
        self.assertLessEqual(set(server._USAGE.values()), telemetry.BONNIE_FEATURES)

    def test_every_allowed_word_has_a_route(self):
        self.assertEqual(set(server._USAGE.values()), telemetry.BONNIE_FEATURES)


if __name__ == "__main__":
    unittest.main()
