"""tmux panes for a run, against a fake tmux that records what it is asked to do."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src.agent import panes, station
from src.agent.runs import Run

FAKE_TMUX = '''#!{python}
import json, sys
open({record!r}, "a").write(json.dumps(sys.argv[1:]) + "\\n")
if {fail!r} and sys.argv[1] == "split-window":
    sys.stderr.write("no space for new pane")
    sys.exit(1)
if sys.argv[1] == "new-window":
    print("@7")
'''


class Panes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch("src.agent.runs.clyde_home", return_value=self.root / "home")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.record = self.root / "tmux.log"

    def _tmux(self, fail: bool = False) -> str:
        path = self.root / "tmux"
        path.write_text(FAKE_TMUX.format(python=sys.executable, record=str(self.record), fail=fail), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    def _calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def _run(self, advisor: bool = True) -> Run:
        return Run.create("t", {"master": "a:big", "advisor": "claude:haiku" if advisor else None,
                                "workers": [{"name": "worker-1", "model": "a:small"}, {"name": "worker-2", "model": "claude:haiku"}]})

    def test_a_pane_for_the_overview_the_advisor_and_each_worker_only_watching_its_own_events(self):
        run = self._run()
        titles = [title for title, _ in panes.pane_commands(run)]
        self.assertEqual(titles, ["overview", "advisor", "worker-1", "worker-2"])
        commands = dict(panes.pane_commands(run))
        self.assertIn(f"station watch {run.id} --who worker-2", commands["worker-2"])
        self.assertTrue(commands["overview"].endswith(f"station {run.id}"))
        self.assertEqual([t for t, _ in panes.pane_commands(self._run(advisor=False))], ["overview", "worker-1", "worker-2"])

    def test_outside_tmux_a_detached_session_is_made_and_the_attach_command_is_given(self):
        run = self._run()
        with patch.dict(os.environ):
            os.environ.pop("TMUX", None)
            message = panes.open_panes(run, self._tmux())
        calls = self._calls()
        self.assertEqual(calls[0][:5], ["new-session", "-d", "-s", f"clyde-{run.id}", "-n"])
        self.assertIn(f"tmux attach -t clyde-{run.id}", message)
        self.assertIn("4 panes", message)
        self.assertEqual(["remain-on-exit"], [c[4] for c in calls if c[0] == "set-option"])   # the last lines stay readable
        self.assertEqual(sum(c[0] == "split-window" for c in calls), 3)
        targets = {c[c.index("-t") + 1] for c in calls if c[0] in ("set-option", "split-window", "select-layout")}
        self.assertEqual(targets, {f"clyde-{run.id}:run"})   # every step is aimed at the new session's window
        self.assertEqual(calls[-1][:2], ["select-layout", "-t"])
        self.assertIn("tiled", calls[-1])

    def test_inside_tmux_the_window_joins_the_current_session(self):
        run = self._run(advisor=False)
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-501/default,1,0"}):
            message = panes.open_panes(run, self._tmux())
        calls = self._calls()
        self.assertEqual(calls[0][:4], ["new-window", "-d", "-P", "-F"])   # -d: your own window keeps focus
        self.assertEqual({c[c.index("-t") + 1] for c in calls[1:]}, {"@7"})   # the window id new-window returned
        self.assertIn("new window", message)

    def test_no_tmux_or_a_tmux_that_fails_is_a_message_not_a_crash(self):
        run = self._run()
        with patch("src.agent.panes.tmux_path", return_value=None):
            self.assertIn("tmux is not installed", panes.open_panes(run))
        with patch.dict(os.environ):
            os.environ.pop("TMUX", None)
            self.assertIn("no space for new pane", panes.open_panes(run, self._tmux(fail=True)))


class WatchOneMember(unittest.TestCase):
    def test_watch_who_prints_only_that_members_events(self):
        with tempfile.TemporaryDirectory() as tmp, patch("src.agent.runs.clyde_home", return_value=Path(tmp)):
            run = Run.create("t", {"master": "a", "workers": []})
            run.event("worker-1", "tool_use", tool="Edit")
            run.event("worker-2", "tool_use", tool="Bash")
            run.set_status("done")
            buffer = io.StringIO()
            self.assertEqual(station.command(Console(file=buffer, width=120), "watch", run.id, who="worker-1"), 0)
        out = buffer.getvalue()
        self.assertIn("worker-1", out)
        self.assertIn("Edit", out)
        self.assertNotIn("worker-2", out)


if __name__ == "__main__":
    unittest.main()
