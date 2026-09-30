"""Tests for the session-scoped cron matcher and scheduler."""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.tools.cron import CronCreateTool, cron_matches, parse_cron, pop_due_jobs

# 2026-09-30 is a Wednesday (cron day-of-week 3).
WED_0930 = datetime(2026, 9, 30, 9, 30)


class TestCronMatcher(unittest.TestCase):
    def test_star_matches_everything(self) -> None:
        self.assertTrue(cron_matches("* * * * *", WED_0930))

    def test_exact_fields(self) -> None:
        self.assertTrue(cron_matches("30 9 30 9 *", WED_0930))
        self.assertFalse(cron_matches("31 9 * * *", WED_0930))
        self.assertFalse(cron_matches("30 10 * * *", WED_0930))

    def test_lists_ranges_steps(self) -> None:
        self.assertTrue(cron_matches("0,15,30,45 * * * *", WED_0930))
        self.assertTrue(cron_matches("25-35 9-17 * * *", WED_0930))
        self.assertTrue(cron_matches("*/15 * * * *", WED_0930))
        self.assertFalse(cron_matches("*/7 * * * *", WED_0930))
        self.assertTrue(cron_matches("10-40/10 * * * *", WED_0930))
        self.assertTrue(cron_matches("0/10 * * * *", WED_0930))
        self.assertFalse(cron_matches("1-59/2 * * * *", WED_0930))

    def test_day_of_week(self) -> None:
        self.assertTrue(cron_matches("* * * * 3", WED_0930))
        self.assertTrue(cron_matches("* * * * 1-5", WED_0930))
        self.assertFalse(cron_matches("* * * * 0,6", WED_0930))
        self.assertTrue(cron_matches("* * * * 7", datetime(2026, 10, 4, 0, 0)))  # Sunday

    def test_day_of_month_or_day_of_week_when_both_restricted(self) -> None:
        self.assertTrue(cron_matches("* * 1 * 3", WED_0930))  # weekday hits, day-of-month does not
        self.assertFalse(cron_matches("* * 1 * 4", WED_0930))
        self.assertFalse(cron_matches("* * 1 * *", WED_0930))

    def test_invalid_expressions_raise(self) -> None:
        for expr in ("* * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "*/0 * * * *", "5-1 * * * *", "a * * * *"):
            with self.subTest(expr=expr), self.assertRaises(ValueError):
                parse_cron(expr)

    def test_create_rejects_invalid_cron(self) -> None:
        ctx = ToolContext(workspace_root=Path.cwd())
        with self.assertRaises(ToolInputError):
            CronCreateTool().run({"cron": "every day", "prompt": "ping"}, ctx)
        self.assertEqual(ctx.crons, {})


class TestPopDueJobs(unittest.TestCase):
    def setUp(self) -> None:
        self.crons = {
            "every": {"id": "every", "cron": "* * * * *", "prompt": "a", "recurring": True},
            "at931": {"id": "at931", "cron": "31 9 * * *", "prompt": "b", "recurring": False},
        }

    def test_nothing_due_within_the_same_minute(self) -> None:
        self.assertEqual(pop_due_jobs(self.crons, WED_0930, WED_0930.replace(second=59)), [])

    def test_selects_jobs_whose_minute_passed(self) -> None:
        due = pop_due_jobs(self.crons, WED_0930.replace(second=40), datetime(2026, 9, 30, 9, 31, 5))
        self.assertEqual([j["id"] for j in due], ["every", "at931"])

    def test_one_shot_removed_recurring_kept(self) -> None:
        pop_due_jobs(self.crons, WED_0930, datetime(2026, 9, 30, 9, 31))
        self.assertEqual(list(self.crons), ["every"])

    def test_recurring_fires_once_for_many_missed_minutes(self) -> None:
        due = pop_due_jobs(self.crons, WED_0930, datetime(2026, 9, 30, 9, 45))
        self.assertEqual([j["id"] for j in due].count("every"), 1)


class TestReplCronRun(unittest.TestCase):
    def test_due_job_runs_as_a_turn_before_the_prompt(self) -> None:
        from src.repl import ClydeREPL
        from tests.repl.test_repl import _fake_provider_env

        with patch("src.repl.core.Session.create"), _fake_provider_env():
            repl = ClydeREPL(model="glm:glm-4.5")
        repl.tool_context.crons["j1"] = {"id": "j1", "cron": "* * * * *", "prompt": "check build", "recurring": False}
        repl._cron_checked_at = datetime(2026, 9, 30, 9, 0)

        with patch.object(repl, "chat") as chat, patch.object(repl.prompt_session, "prompt", side_effect=EOFError):
            repl.run()

        chat.assert_called_once_with("check build")
        self.assertEqual(repl.tool_context.crons, {})


if __name__ == "__main__":
    unittest.main()
