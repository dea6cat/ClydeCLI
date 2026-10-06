"""The licence acknowledgment: asked once, typed phrase only, recorded per machine, enforced on every command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src import license_gate as gate

ROOT = Path(__file__).resolve().parents[1]


class TestGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = patch("src.license_gate.clyde_home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop(gate.ENV_ACCEPT, None)
        self.addCleanup(env.stop)
        self.console = Console(file=StringIO(), width=120)

    def _typed(self, text: str) -> bool:
        with patch("builtins.input", return_value=text):
            return gate.prompt_and_record(self.console)

    def test_only_the_phrase_accepts_and_it_is_recorded(self):
        for no in ("", "y", "yes", "ok", "I accept it please"):
            self.assertFalse(self._typed(no), no)
            self.assertFalse(gate.is_accepted())
        self.assertTrue(self._typed("  i ACCEPT "))
        self.assertTrue(gate.is_accepted())
        record = json.loads((self.home / "license.json").read_text())
        self.assertEqual((record["license"], record["terms"]), (gate.LICENSE_NAME, gate.TERMS_VERSION))
        self.assertIn("accepted_at", record)

    def test_ctrl_c_or_end_of_input_declines(self):
        for error in (EOFError, KeyboardInterrupt):
            with patch("builtins.input", side_effect=error):
                self.assertFalse(gate.prompt_and_record(self.console))
        self.assertFalse(gate.is_accepted())

    def test_an_old_or_foreign_or_broken_record_asks_again(self):
        path = self.home / "license.json"
        for bad in ('{"license": "MIT", "terms": 1}', f'{{"license": "{gate.LICENSE_NAME}", "terms": 0}}', "not json", "[]"):
            path.write_text(bad)
            self.assertFalse(gate.is_accepted(), bad)

    def test_no_terminal_and_no_env_refuses_and_records_nothing(self):
        with patch("sys.stdin.isatty", return_value=False):
            self.assertFalse(gate.ensure_accepted(self.console))
        self.assertFalse((self.home / "license.json").exists())

    def test_the_env_var_accepts_one_run_without_recording(self):
        with patch.dict(os.environ, {gate.ENV_ACCEPT: "1"}):
            self.assertTrue(gate.ensure_accepted(self.console))
        self.assertFalse((self.home / "license.json").exists())

    def test_an_unwritable_home_does_not_count_as_accepted(self):
        with patch("src.license_gate.record_acceptance", side_effect=OSError("read-only")):
            self.assertFalse(self._typed("I accept"))


class TestCli(unittest.TestCase):
    """The real entry point in a throwaway HOME."""

    def _run(self, home: Path, *args: str, env_accept: bool = False, stdin: str = "") -> subprocess.CompletedProcess:
        env = {"PYTHONPATH": str(ROOT), "HOME": str(home), "PATH": "/usr/bin:/bin"}
        if env_accept:
            env[gate.ENV_ACCEPT] = "1"
        return subprocess.run([sys.executable, "-m", "src.cli", *args], cwd=home, env=env, input=stdin, capture_output=True,
                              text=True, timeout=60)

    def test_without_acceptance_every_command_is_refused_but_version_and_license_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            refused = self._run(home, "config")
            self.assertEqual(refused.returncode, gate.EXIT_DECLINED, refused.stderr)
            self.assertIn("accept its licence", refused.stderr)
            self.assertEqual(self._run(home, "-p", "hi").returncode, gate.EXIT_DECLINED)
            self.assertEqual(self._run(home, "--acp").returncode, gate.EXIT_DECLINED)
            self.assertEqual(self._run(home, "--version").returncode, 0)
            shown = self._run(home, "license")
            self.assertEqual(shown.returncode, 0)
            self.assertIn("Not accepted yet", shown.stdout)
            self.assertIn("PolyForm Noncommercial", shown.stdout)

    def test_accept_from_a_script_records_it_and_then_commands_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            done = self._run(home, "license", "accept", env_accept=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue((home / ".clyde" / "license.json").exists())
            self.assertIn("Accepted on this machine", self._run(home, "license").stdout)
            self.assertEqual(self._run(home, "config").returncode, 0)

    def test_declining_the_prompt_exits_3_and_saves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            done = self._run(home, "license", "accept", stdin="no\n")
            self.assertEqual(done.returncode, gate.EXIT_DECLINED)
            self.assertFalse((home / ".clyde" / "license.json").exists())


if __name__ == "__main__":
    unittest.main()
