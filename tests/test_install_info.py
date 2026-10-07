"""How Clyde was installed and what else answers to `clyde`, against fake environments (never the real PATH or home)."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import install_info as ii

ROOT = Path(__file__).resolve().parents[1]


def _program(folder: Path, name: str, body: str = "#!/bin/sh\necho x\n") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class TestDetect(unittest.TestCase):
    def _detect(self, direct: dict, prefix: str) -> ii.Install:
        with patch.object(ii, "_direct_url", return_value=direct), patch.object(sys, "prefix", prefix):
            return ii.detect()

    def test_editable_checkout(self):
        got = self._detect({"url": "file:///src/ClydeCLI", "dir_info": {"editable": True}}, "/x/.venv")
        self.assertEqual((got.method, got.location), ("editable", "/src/ClydeCLI"))

    def test_uv_tool_from_git_records_the_commit(self):
        got = self._detect({"url": "https://github.com/a/b", "vcs_info": {"commit_id": "abcdef1234567"}},
                           "/home/u/.local/share/uv/tools/clyde-cli")
        self.assertEqual((got.method, got.commit), ("uv-tool", "abcdef1"))

    def test_pipx_and_plain_pip(self):
        self.assertEqual(self._detect({}, "/home/u/.local/pipx/venvs/clyde-cli").method, "pipx")
        self.assertEqual(self._detect({}, "/usr/lib/python3").method, "pip")


class TestCommandsOnPath(unittest.TestCase):
    def test_distinct_programs_are_listed_and_symlinks_to_one_program_count_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = _program(root / "a", "clyde")
            (root / "b").mkdir()
            (root / "b" / "clyde").symlink_to(real)
            other = _program(root / "c", "clyde")
            path = os.pathsep.join(str(root / d) for d in ("a", "b", "c", "missing", ""))
            self.assertEqual(ii.clyde_commands(path), [real, other])
            self.assertEqual(ii.clyde_commands(str(root / "b")), [root / "b" / "clyde"])
            self.assertEqual(ii.clyde_commands(""), [])


class TestClaudeCode(unittest.TestCase):
    def test_found_with_its_version_or_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            _program(Path(tmp), "claude", "#!/bin/sh\necho '2.1.291 (Claude Code)'\n")
            with patch("shutil.which", return_value=str(Path(tmp) / "claude")):
                self.assertEqual(ii.claude_code(), (str(Path(tmp) / "claude"), "2.1.291 (Claude Code)"))
        with patch("shutil.which", return_value=None):
            self.assertIsNone(ii.claude_code())


class TestReport(unittest.TestCase):
    def _report(self, commands: list[Path], claude) -> str:
        with patch.object(ii, "clyde_commands", return_value=commands), patch.object(ii, "claude_code", return_value=claude), \
                patch("src.license_gate.is_accepted", return_value=True):
            return "\n".join(ii.report_lines())

    def test_one_install_is_clean(self):
        text = self._report([Path("/a/clyde")], None)
        self.assertNotIn("✗", text)
        self.assertIn("Claude Code: not found", text)

    def test_two_installs_and_no_install_are_flagged(self):
        self.assertIn("several programs answer to `clyde`", self._report([Path("/a/clyde"), Path("/b/clyde")], None))
        self.assertIn("no `clyde` on PATH", self._report([], ("/c/claude", "2.1.291 (Claude Code)")))

    def test_claude_code_is_named_with_the_import_commands(self):
        text = self._report([Path("/a/clyde")], ("/c/claude", "2.1.291 (Claude Code)"))
        self.assertIn("2.1.291 (Claude Code) at /c/claude", text)
        self.assertIn("clyde hooks import", text)


class TestCli(unittest.TestCase):
    def test_doctor_prints_the_install_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, "-m", "src.cli", "doctor"], cwd=tmp, capture_output=True, text=True, timeout=60,
                                  env={"PYTHONPATH": str(ROOT), "HOME": tmp, "CLYDE_ACCEPT_LICENSE": "1", "PATH": "/usr/bin:/bin"})
        self.assertIn("ClydeCLI install:", done.stdout, done.stderr)
        self.assertIn("installed with", done.stdout)
        self.assertIn("/doctor inside clyde", done.stdout)


if __name__ == "__main__":
    unittest.main()
