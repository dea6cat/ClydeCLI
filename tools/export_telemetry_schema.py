"""Write worker/schema.json from src/telemetry.py, the one place the telemetry schema is defined.

    python3 tools/export_telemetry_schema.py

tests/test_worker_schema.py fails when the committed file differs from this output, so the Worker can never accept
an event the client would not send, or the reverse.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.telemetry import schema_json  # noqa: E402

TARGET = ROOT / "worker" / "schema.json"


def rendered() -> str:
    return json.dumps(schema_json(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_text(rendered(), encoding="utf-8")
    print(f"wrote {TARGET}")
