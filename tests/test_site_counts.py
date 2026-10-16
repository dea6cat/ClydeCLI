"""The website counter: what the receiver keeps, what it refuses, and that no visitor is stored. The script itself is tested in
tests/site_analytics.test.mjs, which this file also runs when Node is installed."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from tools.telemetry_receiver import SiteCounts, make_handler, report

ROOT = Path(__file__).resolve().parent.parent


class TestSiteCounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "counts.json"
        self.day = ["2026-10-16"]
        self.site = SiteCounts(self.path, today=lambda: self.day[0])

    def hit(self, name="features", event=False, referrer="", bot=0, address="1.1.1.1", agent="UA"):
        return self.site.hit(name, event, referrer, bot, address, agent)

    def today(self):
        return self.site.days[self.day[0]]

    def test_page_views_clicks_and_referrers_are_counted_apart(self):
        self.hit(referrer="github.com"); self.hit(referrer="github-readme"); self.hit(referrer="")
        self.hit("tab-bonnie", event=True)
        counts = self.today()
        self.assertEqual((counts["page:features"], counts["event:tab-bonnie"]), (3, 1))
        self.assertEqual((counts["ref:github.com"], counts["ref:github-readme"], counts["ref:direct"]), (1, 1, 1))

    def test_a_click_adds_no_referrer_and_no_visitor(self):
        self.hit("tab-bonnie", event=True, referrer="github.com")
        self.assertEqual(set(self.today()), {"event:tab-bonnie"})

    def test_a_bot_and_a_name_that_is_not_a_plain_word_are_ignored(self):
        self.assertFalse(self.hit(bot=153))
        for bad in ("../etc/passwd", "", "<b>x</b>", "a" * 80, "UPPER SPACE"):
            with self.subTest(bad):
                self.assertFalse(self.hit(bad))
        self.assertEqual(self.site.days, {})

    def test_a_referrer_that_is_not_a_plain_word_is_counted_as_other(self):
        self.hit(referrer="<script>alert(1)</script>")
        self.assertEqual(self.today()["ref:other"], 1)

    def test_a_visitor_counts_once_a_day_and_again_the_next_day(self):
        self.hit(address="1.1.1.1"); self.hit(address="1.1.1.1"); self.hit(address="2.2.2.2")
        self.assertEqual(self.today()["visitors"], 2)
        self.day[0] = "2026-10-17"
        self.hit(address="1.1.1.1")
        self.assertEqual(self.site.days["2026-10-17"]["visitors"], 1)

    def test_nothing_that_identifies_a_visitor_is_saved(self):
        self.hit(address="203.0.113.77", agent="Mozilla/5.0 SecretBrowser")
        saved = self.path.read_text()
        for secret in ("203.0.113.77", "SecretBrowser", "Mozilla"):
            self.assertNotIn(secret, saved)

    def test_counts_survive_a_restart(self):
        self.hit(); self.hit()
        again = SiteCounts(self.path, today=lambda: self.day[0])
        self.assertEqual(again.days[self.day[0]]["page:features"], 2)

    def test_the_report_ranks_pages_clicks_and_referrers(self):
        self.hit(referrer="github.com"); self.hit("bonnie", referrer="github.com"); self.hit(referrer="google.com")
        self.hit("tab-keys", event=True)
        text = report(json.loads(self.path.read_text()))
        self.assertIn("3 page views", text)
        self.assertLess(text.index("features"), text.index("bonnie"))
        self.assertLess(text.index("github.com"), text.index("google.com"))
        self.assertIn("tab-keys", text)


class TestCountEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = SiteCounts(Path(self.tmp.name) / "counts.json")
        server = HTTPServer(("127.0.0.1", 0), make_handler(Path(self.tmp.name) / "events.jsonl", self.site))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(self, query):
        with urllib.request.urlopen(f"{self.base}/count?{query}", timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def test_a_beacon_is_counted_and_answered_with_a_pixel(self):
        status, kind, body = self.get("p=%2Ffeatures&r=github.com&t=Features&rnd=abc")
        self.assertEqual((status, kind), (200, "image/gif"))
        self.assertTrue(body.startswith(b"GIF89a"))
        self.assertEqual(next(iter(self.site.days.values()))["page:features"], 1)

    def test_a_refused_beacon_gets_the_same_pixel(self):
        self.assertEqual(self.get("p=%2Ffeatures&b=153")[0:2], (200, "image/gif"))
        self.assertEqual(self.get("p=..%2Fsecret")[0:2], (200, "image/gif"))
        self.assertEqual(self.site.days, {})

    def test_an_unknown_path_is_a_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/other", timeout=5)
        self.assertEqual(caught.exception.code, 404)


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestTheScript(unittest.TestCase):
    def test_the_real_site_script_passes_its_node_tests(self):
        done = subprocess.run(["node", "--test", str(ROOT / "tests" / "site_analytics.test.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout[-1500:] + done.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
