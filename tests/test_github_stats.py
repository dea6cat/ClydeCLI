"""tools/github_stats.py keeps GitHub's 14-day traffic numbers and who starred, forked or watches, merged across runs."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import github_stats as gs


def fake(clones=(), views=(), stars=(), forks=(), watchers=(), counts=(0, 0, 0)):
    data = {
        "repos/o/r/traffic/clones": {"clones": [{"timestamp": f"{d}T00:00:00Z", "count": c, "uniques": u} for d, c, u in clones]},
        "repos/o/r/traffic/views": {"views": [{"timestamp": f"{d}T00:00:00Z", "count": c, "uniques": u} for d, c, u in views]},
        "repos/o/r/traffic/popular/referrers": [{"referrer": "github.com", "count": 5, "uniques": 3}],
        "repos/o/r/traffic/popular/paths": [{"path": "/o/r", "count": 7, "uniques": 4}],
        "repos/o/r": {"stargazers_count": counts[0], "forks_count": counts[1], "subscribers_count": counts[2], "open_issues_count": 0},
        "repos/o/r/stargazers": [{"user": {"login": s}} for s in stars],
        "repos/o/r/forks": [{"owner": {"login": f}} for f in forks],
        "repos/o/r/subscribers": [{"login": w} for w in watchers],
    }
    return lambda path, **_: data[path]


class TestCollect(unittest.TestCase):
    def test_traffic_days_accumulate_and_a_days_latest_figure_wins(self):
        state = gs.load(Path("/nonexistent/x.json"))
        gs.collect("o/r", state, fake(clones=[("2026-10-14", 52, 24), ("2026-10-15", 10, 5)]), today="2026-10-15")
        gs.collect("o/r", state, fake(clones=[("2026-10-15", 121, 35), ("2026-10-16", 3, 2)]), today="2026-10-16")
        self.assertEqual(state["clones"]["2026-10-14"], {"count": 52, "uniques": 24})   # no longer reported by GitHub, still kept
        self.assertEqual(state["clones"]["2026-10-15"], {"count": 121, "uniques": 35})  # the later figure replaces the earlier
        self.assertEqual(sorted(state["clones"]), ["2026-10-14", "2026-10-15", "2026-10-16"])

    def test_people_keep_the_day_they_were_first_seen(self):
        state = gs.load(Path("/nonexistent/x.json"))
        gs.collect("o/r", state, fake(stars=["ana"], forks=["bo"], watchers=["ana"], counts=(1, 1, 1)), today="2026-10-15")
        gs.collect("o/r", state, fake(stars=["ana", "cy"], forks=["bo"], counts=(2, 1, 0)), today="2026-10-16")
        self.assertEqual(state["people"]["stars"], {"ana": "2026-10-15", "cy": "2026-10-16"})
        self.assertEqual(state["people"]["forks"], {"bo": "2026-10-15"})
        self.assertEqual(state["people"]["watchers"], {"ana": "2026-10-15"})   # someone who stops watching is not erased
        self.assertEqual(state["counts"]["2026-10-16"]["stars"], 2)

    def test_the_file_round_trips_and_a_missing_or_broken_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "stats.json"
            state = gs.collect("o/r", gs.load(path), fake(stars=["ana"], counts=(1, 0, 0)), today="2026-10-15")
            gs.save(path, state)
            self.assertEqual(gs.load(path)["people"]["stars"], {"ana": "2026-10-15"})
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(gs.load(path)["clones"], {})


class TestReport(unittest.TestCase):
    def test_it_names_who_is_new_today_and_the_top_referrers(self):
        state = gs.load(Path("/nonexistent/x.json"))
        gs.collect("o/r", state, fake(clones=[("2026-10-16", 4, 2)], stars=["ana"], counts=(1, 0, 0)), today="2026-10-15")
        gs.collect("o/r", state, fake(clones=[("2026-10-16", 4, 2)], stars=["ana", "cy"], counts=(2, 0, 0)), today="2026-10-16")
        text = gs.report(state, today="2026-10-16")
        self.assertIn("clones: 4 over 1 saved days", text)
        self.assertIn("stars: 2 total; new today: cy", text)
        self.assertIn("referrers: github.com (5)", text)

    def test_an_empty_file_reports_nothing_saved_instead_of_failing(self):
        text = gs.report(gs.load(Path("/nonexistent/x.json")), today="2026-10-16")
        self.assertIn("nothing saved yet", text)


class TestCommandLine(unittest.TestCase):
    def test_report_reads_only_the_saved_file_and_never_calls_github(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            gs.save(path, gs.collect("o/r", gs.load(path), fake(stars=["ana"], counts=(1, 0, 0)), today="2026-10-15"))
            original = gs.gh_fetch
            gs.gh_fetch = lambda *a, **k: self.fail("report must not call GitHub")
            try:
                self.assertEqual(gs.main(["report", "o/r", "--out", str(path)]), 0)
            finally:
                gs.gh_fetch = original


if __name__ == "__main__":
    unittest.main()
