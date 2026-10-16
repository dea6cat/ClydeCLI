"""A reference receiver for Clyde's telemetry batches, for trying it out or hosting your own.

    python3 tools/telemetry_receiver.py 8787 events.jsonl
    clyde telemetry endpoint http://localhost:8787 && clyde telemetry on && clyde telemetry send

It accepts POST {"events": [...]} and appends each event to a JSON Lines file, re-checking every event against the
schema in src/telemetry.py so a client that sends more than it should is refused. It stores no IP address and no header.
For anything public, put it behind HTTPS (Clyde only sends to https, or to localhost).
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.telemetry import SCHEMA, _valid  # noqa: E402

COMMON = {"event", "v", "id", "os", "arch", "py", "ram_gb", "day"}
MAX_BATCH = 1000


def acceptable(event: object) -> bool:
    if not isinstance(event, dict) or event.get("event") not in SCHEMA:
        return False
    fields = {k: v for k, v in event.items() if k not in COMMON}
    return COMMON <= set(event) and _valid(event["event"], fields)


def make_handler(store: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:   # noqa: N802
            try:
                size = int(self.headers.get("Content-Length", "0"))
                events = json.loads(self.rfile.read(min(size, 1_000_000))).get("events")
            except (ValueError, AttributeError):
                return self._reply(400)
            if not isinstance(events, list) or len(events) > MAX_BATCH or not all(acceptable(e) for e in events):
                return self._reply(422)
            with store.open("a", encoding="utf-8") as f:
                f.writelines(json.dumps(e, sort_keys=True) + "\n" for e in events)
            self._reply(204)

        def _reply(self, status: int) -> None:
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_args) -> None:   # nothing is logged: no address, no path
            pass
    return Handler


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    path = Path(sys.argv[2] if len(sys.argv) > 2 else "events.jsonl")
    print(f"listening on :{port}, appending to {path}")
    HTTPServer(("127.0.0.1", port), make_handler(path)).serve_forever()
