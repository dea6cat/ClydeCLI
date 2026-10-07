"""clyde update and the update note: never touches the network or the real home in tests."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src import install_info as ii
from src import updates

FULL = "d" * 40
OLD = ii.Install(method="uv-tool", version="0", location="/x", commit="aaaaaaa")
SAME = ii.Install(method="uv-tool", version="0", location="/x", commit="dddddd0"[:7])


class TestCompare(unittest.TestCase):
    def test_states(self):
        self.assertEqual(updates.compare(OLD, FULL).state, "behind")
        self.assertEqual(updates.compare(ii.Install("uv-tool", "0", "/x", commit="ddddddd"), FULL).state, "current")
        self.assertEqual(updates.compare(ii.Install("pip", "0", "/x"), FULL).state, "unknown")     # no recorded commit
        self.assertEqual(updates.compare(OLD, None).state, "unknown")

    def test_update_commands_follow_the_method(self):
        make = lambda m: ii.Install(method=m, version="0", location="/x")
        self.assertEqual(updates.update_command(make("uv-tool"))[:3], ["uv", "tool", "install"])
        self.assertIn("--force", updates.update_command(make("pipx")))
        self.assertIn("--upgrade", updates.update_command(make("pip")))
        self.assertIsNone(updates.update_command(make("editable")))


class TestFetch(unittest.TestCase):
    def _fetch(self, body: bytes | Exception):
        class Response:
            def __enter__(self_):
                return self_
            def __exit__(self_, *a):
                return False
            def read(self_):
                return body
        def opener(request, timeout):
            if isinstance(body, Exception):
                raise body
            return Response()
        with patch("urllib.request.urlopen", opener):
            return updates.fetch_remote_commit()

    def test_a_sha_is_returned_and_anything_else_is_none(self):
        self.assertEqual(self._fetch(FULL.encode()), FULL)
        self.assertIsNone(self._fetch(b"<html>rate limited</html>"))
        self.assertIsNone(self._fetch(b"abc"))
        import urllib.error
        self.assertIsNone(self._fetch(urllib.error.URLError("offline")))


class TestCacheAndNote(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = patch("src.updates.clyde_home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop(updates.ENV_DISABLE, None)
        self.addCleanup(env.stop)

    def test_the_cache_is_refreshed_at_most_once_a_day(self):
        calls = []
        fetch = lambda: calls.append(1) or FULL
        self.assertTrue(updates.refresh_cache(fetch, now=10_000_000.0))
        self.assertFalse(updates.refresh_cache(fetch, now=10_000_000.0 + updates.CHECK_EVERY_S - 1))
        self.assertTrue(updates.refresh_cache(fetch, now=10_000_000.0 + updates.CHECK_EVERY_S + 1))
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads((self.home / "update_check.json").read_text())["remote"], FULL)

    def test_a_failed_fetch_stores_nothing_and_does_not_start_the_clock(self):
        self.assertFalse(updates.refresh_cache(lambda: None, now=10_000_000.0))
        self.assertFalse((self.home / "update_check.json").exists())

    def test_the_note_appears_only_when_behind_and_checks_are_on(self):
        (self.home / "update_check.json").write_text(json.dumps({"checked_at": 1.0, "remote": FULL}))
        note = updates.cached_note(OLD)
        self.assertIn("aaaaaaa → ddddddd", note)
        self.assertIn("clyde update", note)
        self.assertIsNone(updates.cached_note(ii.Install("uv-tool", "0", "/x", commit="ddddddd")))
        with patch.dict(os.environ, {updates.ENV_DISABLE: "1"}):
            self.assertIsNone(updates.cached_note(OLD))

    def test_a_broken_cache_gives_no_note(self):
        (self.home / "update_check.json").write_text("not json")
        self.assertIsNone(updates.cached_note(OLD))

    def test_the_background_check_is_off_when_disabled(self):
        with patch.dict(os.environ, {updates.ENV_DISABLE: "1"}), patch("threading.Thread") as thread:
            updates.start_background_check()
        thread.assert_not_called()


class TestHandler(unittest.TestCase):
    def _run(self, install, remote, *, check=False, returncode=0):
        from src import cli
        out = StringIO()
        with patch.object(ii, "detect", return_value=install), patch.object(updates, "fetch_remote_commit", return_value=remote), \
                patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode)) as run:
            code = cli.handle_update(Console(file=out, width=140), check_only=check)
        return code, out.getvalue(), run

    def test_check_reports_without_running_anything(self):
        code, text, run = self._run(OLD, FULL, check=True)
        self.assertEqual(code, 1)
        self.assertIn("A newer version exists", text)
        self.assertEqual(self._run(ii.Install("uv-tool", "0", "/x", commit="ddddddd"), FULL, check=True)[0], 0)
        self.assertEqual(self._run(OLD, None, check=True)[0], 2)
        run.assert_not_called()

    def test_update_runs_the_install_command_when_behind_and_not_when_current(self):
        code, _, run = self._run(OLD, FULL)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0][:3], ["uv", "tool", "install"])
        code, text, run = self._run(ii.Install("uv-tool", "0", "/x", commit="ddddddd"), FULL)
        self.assertEqual(code, 0)
        self.assertIn("Already up to date", text)
        run.assert_not_called()

    def test_update_still_runs_when_the_check_cannot_be_made(self):
        code, _, run = self._run(OLD, None)
        self.assertEqual(code, 0)
        run.assert_called_once()

    def test_a_failed_command_is_reported_and_a_source_checkout_is_not_managed(self):
        code, text, _ = self._run(OLD, FULL, returncode=1)
        self.assertEqual(code, 1)
        self.assertIn("failed", text)
        code, _, run = self._run(ii.Install("editable", "0", "/src"), FULL)
        self.assertEqual(code, 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
