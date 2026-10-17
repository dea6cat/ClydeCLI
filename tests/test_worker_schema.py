"""worker/schema.json is generated from src/telemetry.py, and the Worker accepts every event the client can queue."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import telemetry
from tools.export_telemetry_schema import TARGET, rendered

ROOT = Path(__file__).resolve().parent.parent


def sample(rule):
    return rule[0] if isinstance(rule, list) else True if rule == "bool" else 1


class TestSchemaFile(unittest.TestCase):
    def test_the_committed_file_is_what_the_exporter_writes(self):
        self.assertEqual(TARGET.read_text(encoding="utf-8"), rendered(), "run: python3 tools/export_telemetry_schema.py")

    def test_every_event_has_a_plain_data_form(self):
        data = telemetry.schema_json()
        self.assertEqual(set(data) - {"_common"}, set(telemetry.SCHEMA))

    def test_what_the_client_adds_to_every_event_fits_the_common_lists(self):
        with tempfile.TemporaryDirectory() as tmp, patch("src.telemetry.clyde_home", return_value=Path(tmp)):
            telemetry.turn_on()
            common = telemetry._common()
        lists = telemetry.schema_json()["_common"]
        for name in ("os", "arch", "ram_gb"):
            self.assertIn(common[name], lists[name])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestWorkerAcceptsTheClient(unittest.TestCase):
    def test_every_event_the_client_can_queue_passes_the_worker_check(self):
        with tempfile.TemporaryDirectory() as tmp, patch("src.telemetry.clyde_home", return_value=Path(tmp)), \
                patch.dict(os.environ, {"CLYDE_TELEMETRY": "on"}):
            telemetry.turn_on()
            for event, fields in telemetry.schema_json().items():
                if event != "_common":
                    self.assertTrue(telemetry.record(event, **{name: sample(rule) for name, rule in fields.items()}), event)
            queued = telemetry.queued()
        self.assertEqual({e["event"] for e in queued}, set(telemetry.SCHEMA))
        script = ("import { valid } from './worker/src/index.js';"
                  "const events = JSON.parse(process.argv[1]);"
                  "console.log(JSON.stringify(events.map(valid)));")
        result = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(queued)], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [True] * len(queued))


if __name__ == "__main__":
    unittest.main()
