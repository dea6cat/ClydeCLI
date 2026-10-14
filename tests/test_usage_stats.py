"""/settings Stats: what the traces and sessions add up to."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from src.ui import usage_stats as stats

TODAY = date(2026, 10, 13)


def _req(days_ago: int, ref: str = "a:m", tokens: int = 100) -> stats.Request:
    return stats.Request(TODAY - timedelta(days=days_ago), ref, stats.Totals(input=tokens))


class TestUsageStats(unittest.TestCase):
    def test_traces_give_tokens_per_model_and_skip_everything_else(self):
        folder = Path(tempfile.mkdtemp())
        good = {"ts": "2026-10-07T14:14:01.695", "event": "model_request", "provider": "ollama", "model": "m",
                "usage": {"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 5}}
        lines = [json.dumps(good), json.dumps({**good, "event": "turn"}), "not json", json.dumps({**good, "ts": "bad"})]
        (folder / "s.jsonl").write_text("\n".join(lines))
        found = stats.load_requests(folder)
        self.assertEqual(found, [stats.Request(date(2026, 10, 7), "ollama:m", stats.Totals(10, 2, 5, 0))])

    def test_sessions_come_from_their_timestamps(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "a.json").write_text(json.dumps({"created_at": "2026-10-13T10:00:00", "updated_at": "2026-10-13T12:30:00"}))
        (folder / "b.json").write_text("{}")
        self.assertEqual(stats.load_sessions(folder), [stats.Session(datetime(2026, 10, 13, 10), datetime(2026, 10, 13, 12, 30))])

    def test_models_are_ranked_and_a_range_leaves_out_older_days(self):
        reqs = [_req(0, "a:small", 10), _req(1, "a:big", 500), _req(40, "a:big", 500)]
        self.assertEqual([r for r, _ in stats.by_model(reqs, stats.first_day("all", TODAY, reqs))], ["a:big", "a:small"])
        self.assertEqual(stats.by_model(reqs, stats.first_day("30", TODAY, reqs))[0][1].total, 500)
        self.assertEqual(stats.by_model(reqs, stats.first_day("7", TODAY, reqs))[0][0], "a:big")

    def test_streaks_count_consecutive_days_and_today_may_still_be_ahead(self):
        reqs = [_req(d) for d in (0, 1, 2, 5, 6, 7, 8)]
        o = stats.overview(reqs, [], stats.first_day("all", TODAY, reqs), TODAY)
        self.assertEqual((o.longest_streak, o.current_streak, o.active_days, o.span_days), (4, 3, 7, 9))
        yesterday = stats.overview([_req(1), _req(2)], [], TODAY - timedelta(days=2), TODAY)
        self.assertEqual(yesterday.current_streak, 2)

    def test_the_overview_names_the_favorite_and_the_longest_session(self):
        sessions = [stats.Session(datetime(2026, 10, 13, 9), datetime(2026, 10, 13, 11, 5))]
        o = stats.overview([_req(0, "a:x", 5), _req(0, "a:y", 50)], sessions, TODAY, TODAY)
        self.assertEqual((o.favorite, o.sessions, stats.duration(o.longest_session)), ("a:y", 1, "2h 5m"))
        self.assertEqual(stats.overview([], [], TODAY, TODAY).favorite, "none yet")

    def test_numbers_are_short(self):
        self.assertEqual([stats.compact(n) for n in (12, 1500, 13_400_000, 8_700_000_000)], ["12", "1.5k", "13.4m", "8.7b"])
        self.assertEqual(stats.duration(timedelta(days=9, hours=13, minutes=19)), "9d 13h 19m")

    def test_the_chart_and_heatmap_draw_with_and_without_data(self):
        reqs = [_req(2, "a:x", 100), _req(0, "a:x", 300), _req(0, "a:y", 50)]
        since = TODAY - timedelta(days=9)
        series = [(ref, stats.daily(reqs, ref, since, TODAY)) for ref in ("a:x", "a:y")]
        text = "".join(t for _, t in stats.chart(series, since, TODAY))
        self.assertIn("Tokens per Day", text)
        self.assertIn("● a:x", text)
        self.assertIn("Oct", "".join(t for _, t in stats.heatmap(reqs, TODAY)))
        self.assertIn("Less", "".join(t for _, t in stats.heatmap([], TODAY)))
        self.assertIn("300", "".join(t for _, t in stats.chart([("a:x", [300])], TODAY, TODAY)))


if __name__ == "__main__":
    unittest.main()
