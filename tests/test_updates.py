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


LATEST = updates.Target("latest", FULL)
STABLE = updates.Target("stable", "e" * 40, "0.2.0", "v0.2.0")


class TestCompare(unittest.TestCase):
    def test_latest_compares_commits(self):
        self.assertEqual(updates.compare(OLD, LATEST).state, "behind")
        self.assertEqual(updates.compare(ii.Install("uv-tool", "0", "/x", commit="ddddddd"), LATEST).state, "current")
        self.assertEqual(updates.compare(ii.Install("pip", "0", "/x"), LATEST).state, "unknown")     # no recorded commit
        self.assertEqual(updates.compare(OLD, None).state, "unknown")

    def test_stable_compares_versions_and_never_suggests_a_downgrade(self):
        at = lambda v: ii.Install("uv-tool", v, "/x", commit="aaaaaaa")
        self.assertEqual(updates.compare(at("0.1.0"), STABLE).state, "behind")
        self.assertEqual(updates.compare(at("0.2.0"), STABLE).state, "current")
        self.assertEqual(updates.compare(at("0.3.1"), STABLE).state, "ahead")
        self.assertEqual(updates.compare(at("dev"), STABLE).state, "unknown")

    def test_update_commands_follow_the_method(self):
        make = lambda m: ii.Install(method=m, version="0", location="/x")
        self.assertEqual(updates.update_command(make("uv-tool"))[:3], ["uv", "tool", "install"])
        self.assertTrue(updates.update_command(make("uv-tool"), STABLE)[-1].endswith("ClydeCLI@v0.2.0"))
        self.assertTrue(updates.update_command(make("uv-tool"), LATEST)[-1].endswith("ClydeCLI@" + FULL))     # the checked commit
        self.assertTrue(updates.update_command(make("uv-tool"))[-1].endswith("ClydeCLI"))                     # no target: newest main
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
        with patch.object(updates, "_ls_remote", return_value=None), patch("urllib.request.urlopen", opener):   # git unavailable
            return updates.fetch_remote_commit()

    def test_a_sha_is_returned_and_anything_else_is_none(self):
        self.assertEqual(self._fetch(FULL.encode()), FULL)
        self.assertIsNone(self._fetch(b"<html>rate limited</html>"))
        self.assertIsNone(self._fetch(b"abc"))
        import urllib.error
        self.assertIsNone(self._fetch(urllib.error.URLError("offline")))


class TestTags(unittest.TestCase):
    def _tags(self, body):
        with patch.object(updates, "_ls_remote", return_value=None), patch.object(updates, "_get", return_value=body):   # git unavailable
            return updates.fetch_newest_tag()

    def test_the_highest_release_tag_wins_and_other_tags_are_ignored(self):
        tags = [{"name": "v0.9.0", "commit": {"sha": "a" * 40}}, {"name": "v0.10.0", "commit": {"sha": "b" * 40}},
                {"name": "v1.0.0-rc1", "commit": {"sha": "c" * 40}}, {"name": "nightly", "commit": {"sha": "d" * 40}},
                {"name": "v0.2.0", "commit": {"sha": "not a sha"}}]
        got = self._tags(json.dumps(tags))
        self.assertEqual((got.version, got.ref, got.commit), ("0.10.0", "v0.10.0", "b" * 40))      # 10 > 9, not text order

    def test_no_tags_or_a_bad_answer_is_none(self):
        for body in ("[]", "not json", "{}", None):
            self.assertIsNone(self._tags(body), body)


class TestGit(unittest.TestCase):
    """Versions come from `git ls-remote`, which reads the refs themselves: the GitHub web API answers from a 60-second public cache,
    so right after a push it still names the old commit, and it allows 60 requests an hour per IP address."""

    def _run(self, stdout="", returncode=0, error=None):
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with patch("subprocess.run", side_effect=error, return_value=done) as run:
            return updates._ls_remote("refs/heads/main"), run

    def test_it_parses_refs_and_drops_anything_that_is_not_a_sha(self):
        got, run = self._run(f"{FULL}\trefs/heads/main\nnot-a-sha\trefs/heads/x\nno tab here\n")
        self.assertEqual(got, [(FULL, "refs/heads/main")])
        self.assertEqual(run.call_args.args[0][:3], ["git", "ls-remote", updates.REMOTE_URL])
        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")      # never stops to ask for a password
        self.assertGreater(run.call_args.kwargs["timeout"], 0)

    def test_a_missing_git_a_failure_or_a_timeout_is_none_not_an_error(self):
        self.assertIsNone(self._run(error=FileNotFoundError())[0])
        self.assertIsNone(self._run(returncode=128)[0])
        self.assertIsNone(self._run(error=subprocess.TimeoutExpired("git", 10))[0])

    def test_main_comes_from_git_and_the_web_api_is_never_asked(self):
        with patch.object(updates, "_ls_remote", return_value=[(FULL, "refs/heads/main")]), patch.object(updates, "_get") as web:
            self.assertEqual(updates.fetch_remote_commit(), FULL)
        web.assert_not_called()

    def test_git_that_works_but_lists_no_main_is_none_without_guessing_from_the_api(self):
        with patch.object(updates, "_ls_remote", return_value=[]), patch.object(updates, "_get") as web:
            self.assertIsNone(updates.fetch_remote_commit())
        web.assert_not_called()

    def test_without_git_main_falls_back_to_the_web_api(self):
        with patch.object(updates, "_ls_remote", return_value=None), patch.object(updates, "_get", return_value=FULL):
            self.assertEqual(updates.fetch_remote_commit(), FULL)

    def test_the_highest_tag_wins_and_an_annotated_tags_commit_beats_the_tag_object(self):
        listed = [("1" * 40, "refs/tags/v0.9.0"), ("2" * 40, "refs/tags/v0.10.0"), ("3" * 40, "refs/tags/v0.10.0^{}"),
                  ("4" * 40, "refs/tags/v1.0.0-rc1"), ("5" * 40, "refs/tags/vNEXT")]
        with patch.object(updates, "_ls_remote", return_value=listed), patch.object(updates, "_get") as web:
            got = updates.fetch_newest_tag()
        self.assertEqual((got.version, got.ref, got.commit), ("0.10.0", "v0.10.0", "3" * 40))   # 10 > 9, and the peeled commit
        web.assert_not_called()

    def test_a_repository_with_no_release_tags_has_no_stable_target(self):
        with patch.object(updates, "_ls_remote", return_value=[]), patch.object(updates, "_get") as web:
            self.assertIsNone(updates.fetch_newest_tag())
        web.assert_not_called()


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

    def test_the_cache_is_refreshed_at_most_once_a_day_per_channel(self):
        calls = []
        fetch = lambda channel: calls.append(channel) or (LATEST if channel == "latest" else STABLE)
        self.assertTrue(updates.refresh_cache(fetch, now=10_000_000.0, channel="latest"))
        self.assertFalse(updates.refresh_cache(fetch, now=10_000_000.0 + updates.CHECK_EVERY_S - 1, channel="latest"))
        self.assertTrue(updates.refresh_cache(fetch, now=10_000_000.0 + 5, channel="stable"))        # a new channel asks at once
        self.assertTrue(updates.refresh_cache(fetch, now=10_000_000.0 + 5 + updates.CHECK_EVERY_S + 1, channel="stable"))
        self.assertEqual(calls, ["latest", "stable", "stable"])
        self.assertEqual(json.loads((self.home / "update_check.json").read_text())["ref"], "v0.2.0")

    def test_a_failed_fetch_stores_nothing_and_does_not_start_the_clock(self):
        self.assertFalse(updates.refresh_cache(lambda channel: None, now=10_000_000.0, channel="latest"))
        self.assertFalse((self.home / "update_check.json").exists())

    def test_the_note_appears_only_when_behind_on_the_cached_channel_and_checks_are_on(self):
        updates.refresh_cache(lambda channel: LATEST, now=10_000_000.0, channel="latest")
        note = updates.cached_note(OLD, channel="latest")
        self.assertIn("aaaaaaa → ddddddd", note)
        self.assertIn("clyde update", note)
        self.assertIsNone(updates.cached_note(ii.Install("uv-tool", "0", "/x", commit="ddddddd"), channel="latest"))
        self.assertIsNone(updates.cached_note(OLD, channel="stable"))            # the cache is for another channel
        with patch.dict(os.environ, {updates.ENV_DISABLE: "1"}):
            self.assertIsNone(updates.cached_note(OLD, channel="latest"))

    def test_a_stable_note_names_the_versions(self):
        updates.refresh_cache(lambda channel: STABLE, now=10_000_000.0, channel="stable")
        self.assertIn("0.1.0 → 0.2.0, stable channel", updates.cached_note(ii.Install("uv-tool", "0.1.0", "/x"), channel="stable"))
        self.assertIsNone(updates.cached_note(ii.Install("uv-tool", "0.3.0", "/x"), channel="stable"))   # newer than stable

    def test_a_broken_cache_gives_no_note(self):
        (self.home / "update_check.json").write_text("not json")
        self.assertIsNone(updates.cached_note(OLD, channel="latest"))

    def test_the_background_check_is_off_when_disabled(self):
        with patch.dict(os.environ, {updates.ENV_DISABLE: "1"}), patch("threading.Thread") as thread:
            updates.start_background_check()
        thread.assert_not_called()


class TestHandler(unittest.TestCase):
    def _run(self, install, target, *, check=False, returncode=0, channel=None, saved="latest"):
        from src import cli
        out = StringIO()
        with patch.object(ii, "detect", return_value=install), patch.object(updates, "fetch_target", return_value=target), \
                patch("src.config.get_update_channel", return_value=channel or saved), \
                patch("src.config.set_update_channel") as saver, \
                patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode)) as run:
            code = cli.handle_update(Console(file=out, width=140), check_only=check, channel=channel)
        return code, out.getvalue(), run, saver

    def test_check_reports_without_running_anything(self):
        code, text, run, _ = self._run(OLD, LATEST, check=True)
        self.assertEqual(code, 1)
        self.assertIn("A newer version exists", text)
        self.assertEqual(self._run(ii.Install("uv-tool", "0", "/x", commit="ddddddd"), LATEST, check=True)[0], 0)
        self.assertEqual(self._run(OLD, None, check=True)[0], 2)
        run.assert_not_called()

    def test_update_runs_the_install_command_when_behind_and_not_when_current(self):
        code, _, run, _ = self._run(OLD, LATEST)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0][:3], ["uv", "tool", "install"])
        code, text, run, _ = self._run(ii.Install("uv-tool", "0", "/x", commit="ddddddd"), LATEST)
        self.assertEqual(code, 0)
        self.assertIn("Already up to date", text)
        run.assert_not_called()

    def test_a_finished_update_drops_the_cached_answer(self):
        updates._cache_path().parent.mkdir(parents=True, exist_ok=True)
        updates._cache_path().write_text("{}", encoding="utf-8")
        self._run(OLD, LATEST)
        self.assertFalse(updates._cache_path().exists())

    def test_stable_installs_the_tag_and_never_downgrades(self):
        code, _, run, _ = self._run(ii.Install("uv-tool", "0.1.0", "/x", commit="aaaaaaa"), STABLE, saved="stable")
        self.assertEqual(code, 0)
        self.assertTrue(run.call_args.args[0][-1].endswith("@v0.2.0"))
        code, text, run, _ = self._run(ii.Install("uv-tool", "0.9.0", "/x", commit="aaaaaaa"), STABLE, saved="stable")
        self.assertEqual(code, 0)
        self.assertIn("Not downgrading", text)
        run.assert_not_called()

    def test_stable_with_no_release_yet_changes_nothing(self):
        code, text, run, _ = self._run(OLD, None, saved="stable")
        self.assertEqual(code, 2)
        self.assertIn("no release yet", text)
        run.assert_not_called()

    def test_the_channel_flag_is_saved(self):
        _, _, _, saver = self._run(OLD, STABLE, channel="stable")
        saver.assert_called_once_with("stable")

    def test_update_does_nothing_when_the_check_cannot_be_made_on_latest(self):
        code, _, run, _ = self._run(OLD, None)
        self.assertEqual(code, 0)             # latest: go ahead and reinstall the newest main
        run.assert_called_once()

    def test_a_failed_command_is_reported_and_a_source_checkout_is_not_managed(self):
        code, text, _, _ = self._run(OLD, LATEST, returncode=1)
        self.assertEqual(code, 1)
        self.assertIn("failed", text)
        code, _, run, _ = self._run(ii.Install("editable", "0", "/src"), LATEST)
        self.assertEqual(code, 2)
        run.assert_not_called()


class TestChannelConfig(unittest.TestCase):
    def test_the_default_is_latest_and_a_bad_value_is_refused(self):
        from src import config
        with tempfile.TemporaryDirectory() as tmp, patch("src.config.get_config_path", return_value=Path(tmp) / "config.json"):
            self.assertEqual(config.get_update_channel(), "latest")
            config.set_update_channel("stable")
            self.assertEqual(config.get_update_channel(), "stable")
            with self.assertRaises(ValueError):
                config.set_update_channel("nightly")
            self.assertEqual(config.get_update_channel(), "stable")


class TestInstallScript(unittest.TestCase):
    SCRIPT = Path(__file__).resolve().parents[1] / "install.sh"

    def test_the_ref_is_checked_before_anything_is_installed(self):
        for bad in ("v1;rm -rf ~", "main && curl evil", "a b", "$(id)"):
            done = subprocess.run(["sh", str(self.SCRIPT)], capture_output=True, text=True, timeout=20,
                                  env={"CLYDE_REF": bad, "PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir()})
            self.assertEqual(done.returncode, 1, bad)
            self.assertIn("CLYDE_REF may only contain", done.stderr)
            self.assertNotIn("Installing", done.stdout)

    def test_the_ref_is_appended_to_the_repository_url(self):
        text = self.SCRIPT.read_text()
        self.assertIn('REPO="git+https://github.com/dea6cat/ClydeCLI${CLYDE_REF:+@$CLYDE_REF}"', text)


if __name__ == "__main__":
    unittest.main()
