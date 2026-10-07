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


class TestUninstall(unittest.TestCase):
    def test_the_command_follows_the_install_method(self):
        make = lambda m: ii.Install(method=m, version="0", location="/x")
        self.assertEqual(ii.uninstall_command(make("uv-tool")), ["uv", "tool", "uninstall", "clyde-cli"])
        self.assertEqual(ii.uninstall_command(make("pipx")), ["pipx", "uninstall", "clyde-cli"])
        self.assertEqual(ii.uninstall_command(make("pip"))[-3:], ["uninstall", "-y", "clyde-cli"])
        self.assertIsNone(ii.uninstall_command(make("editable")))

    def test_purge_only_targets_a_folder_that_is_really_clydes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            good = root / ".clyde"
            good.mkdir()
            with patch("src.config.clyde_home", return_value=good):
                self.assertEqual(ii.purge_target(), good)
            for bad in (root, root / "documents", root / "missing"):
                bad.mkdir(exist_ok=True) if bad.name == "documents" else None
                with patch("src.config.clyde_home", return_value=bad):
                    self.assertIsNone(ii.purge_target(), str(bad))
            with patch("src.config.clyde_home", return_value=good), patch("pathlib.Path.home", return_value=good):
                self.assertIsNone(ii.purge_target())


class TestUninstallHandler(unittest.TestCase):
    def setUp(self):
        from io import StringIO
        from rich.console import Console
        self.out = StringIO()
        self.console = Console(file=self.out, width=140)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name).resolve() / ".clyde"
        self.data.mkdir()
        (self.data / "keys.json").write_text("{}")
        self.install = ii.Install(method="uv-tool", version="0", location="/x")

    def _run(self, *, purge=False, yes=False, answer=True, returncode=0, install=None):
        from src import cli
        with patch.object(ii, "detect", return_value=install or self.install), \
                patch("src.config.clyde_home", return_value=self.data), \
                patch("rich.prompt.Confirm.ask", return_value=answer), \
                patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode)) as run:
            code = cli.handle_uninstall(self.console, purge=purge, assume_yes=yes)
        return code, run

    def test_declining_removes_nothing(self):
        code, run = self._run(answer=False)
        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertTrue((self.data / "keys.json").exists())

    def test_uninstall_keeps_the_data_unless_purged(self):
        code, run = self._run(yes=True)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0], ["uv", "tool", "uninstall", "clyde-cli"])
        self.assertTrue((self.data / "keys.json").exists())
        code, _ = self._run(yes=True, purge=True)
        self.assertEqual(code, 0)
        self.assertFalse(self.data.exists())

    def test_a_failed_removal_leaves_the_data_alone(self):
        code, _ = self._run(yes=True, purge=True, returncode=1)
        self.assertEqual(code, 1)
        self.assertTrue((self.data / "keys.json").exists())
        self.assertIn("failed", self.out.getvalue())

    def test_a_source_checkout_is_not_managed(self):
        code, run = self._run(yes=True, install=ii.Install(method="editable", version="0", location="/src/Clyde"))
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_purge_with_a_wrong_folder_is_refused_before_anything_runs(self):
        self.data = self.data.parent / "documents"
        self.data.mkdir()
        code, run = self._run(yes=True, purge=True)
        self.assertEqual(code, 2)
        run.assert_not_called()
        self.assertTrue(self.data.exists())
