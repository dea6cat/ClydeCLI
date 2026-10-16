"""A reference receiver for Clyde's telemetry batches and the website's visit counter, for trying them out or hosting your own.

    python3 tools/telemetry_receiver.py 8787 events.jsonl site-counts.json
    python3 tools/telemetry_receiver.py report site-counts.json

POST / takes {"events": [...]} from `clyde telemetry send` and appends each event to a JSON Lines file, re-checking every one
against the schema in src/telemetry.py so a client that sends more than it should is refused.

GET /count takes the beacon site/analytics.js sends (GoatCounter's format: p= page or event, e= event flag, r= referrer, b= bot
flag) and adds one to a daily counter: pages, clicks, referrers, and unique visitors. A visitor is counted by a hash of address and
browser with a salt that changes every day and lives only in memory, so nothing identifying is written anywhere, and no address,
header or request line is logged. For anything public, put it behind HTTPS (Clyde only sends telemetry to https or localhost).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.telemetry import SCHEMA, _valid  # noqa: E402

COMMON = {"event", "v", "id", "os", "arch", "py", "ram_gb", "day"}
MAX_BATCH = 1000
NAME = re.compile(r"[a-z0-9][a-z0-9/_.-]{0,59}")
GIF = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


def acceptable(event: object) -> bool:
    if not isinstance(event, dict) or event.get("event") not in SCHEMA:
        return False
    fields = {k: v for k, v in event.items() if k not in COMMON}
    return COMMON <= set(event) and _valid(event["event"], fields)


class SiteCounts:
    """Daily counters: page:<name>, event:<name>, ref:<host or label>, visitors. Saved as JSON after every hit."""

    def __init__(self, path: Path | None, today=lambda: datetime.now(timezone.utc).date().isoformat()) -> None:
        self.path, self._today, self._lock = path, today, threading.Lock()
        self.days: dict[str, Counter] = {}
        if path and path.exists():
            self.days = {d: Counter(c) for d, c in json.loads(path.read_text(encoding="utf-8")).items()}
        self._salt_day, self._salt, self._seen = "", b"", set()

    def hit(self, name: str, event: bool, referrer: str, bot: int, address: str, agent: str) -> bool:
        """Count one beacon; False when it was ignored (a bot, or a name or referrer that is not a plain word)."""
        name, referrer = name.strip().lstrip("/").lower(), referrer.strip().lower()
        if bot >= 150 or not NAME.fullmatch(name):
            return False
        with self._lock:
            day = self._today()
            counts = self.days.setdefault(day, Counter())
            counts[("event:" if event else "page:") + name] += 1
            if not event:
                counts["ref:" + (referrer if NAME.fullmatch(referrer) else "direct" if not referrer else "other")] += 1
                if day != self._salt_day:   # a new day: a new salt, and yesterday's visitors are forgotten
                    self._salt_day, self._salt, self._seen = day, secrets.token_bytes(16), set()
                visitor = hashlib.sha256(self._salt + address.encode() + b"|" + agent.encode()).hexdigest()
                if visitor not in self._seen:
                    self._seen.add(visitor)
                    counts["visitors"] += 1
            if self.path:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({d: dict(sorted(c.items())) for d, c in sorted(self.days.items())}, indent=1), encoding="utf-8")
                tmp.replace(self.path)
            return True


def report(days: dict[str, dict]) -> str:
    total: Counter = Counter()
    for counts in days.values():
        total.update(counts)
    pages = sorted(((k[5:], v) for k, v in total.items() if k.startswith("page:")), key=lambda kv: -kv[1])
    clicks = sorted(((k[6:], v) for k, v in total.items() if k.startswith("event:")), key=lambda kv: -kv[1])
    refs = sorted(((k[4:], v) for k, v in total.items() if k.startswith("ref:")), key=lambda kv: -kv[1])
    lines = [f"{len(days)} day(s): {sum(v for _, v in pages)} page views, {total['visitors']} visitor-days (a person on two days counts twice)"]
    for title, rows in (("pages", pages), ("clicks", clicks), ("came from", refs)):
        lines += ["", title] + [f"  {v:6}  {k}" for k, v in rows] if rows else []
    return "\n".join(lines)


def make_handler(store: Path, site: SiteCounts | None = None):
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

        def do_GET(self) -> None:   # noqa: N802
            url = urlparse(self.path)
            if url.path != "/count" or site is None:
                return self._reply(404)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                bot = int(query.get("b", "0") or 0)
            except ValueError:
                bot = 0
            forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            site.hit(query.get("p", ""), query.get("e", "").lower() in ("1", "true", "on"), query.get("r", ""), bot,
                     forwarded or self.client_address[0], self.headers.get("User-Agent", ""))
            self.send_response(200)   # always the same pixel, so a probe learns nothing about what was kept
            self.send_header("Content-Type", "image/gif")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(GIF)

        def _reply(self, status: int) -> None:
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_args) -> None:   # nothing is logged: no address, no path
            pass
    return Handler


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        print(report(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))))
        sys.exit(0)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    path = Path(sys.argv[2] if len(sys.argv) > 2 else "events.jsonl")
    counts_path = Path(sys.argv[3] if len(sys.argv) > 3 else "site-counts.json")
    print(f"listening on :{port}; telemetry -> {path}, site counts -> {counts_path}")
    HTTPServer(("127.0.0.1", port), make_handler(path, SiteCounts(counts_path))).serve_forever()
