"""Shell commands that print a secret ask, however the path is spelled."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.secret_paths import command_reads_secret


class TestSecretReadGuard(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        (self.home / ".clyde").mkdir()
        (self.home / ".clyde" / "keys.json").write_text("{}")
        (self.home / ".clyde" / "settings.json").write_text("{}")
        (self.home / ".ssh").mkdir()
        (self.home / ".ssh" / "id_dummy").write_text("k")
        self.work = self.home / "proj"
        self.work.mkdir()
        (self.work / "README.md").write_text("hi")
        for p in (patch.dict(os.environ, {"HOME": str(self.home)}), patch.object(Path, "home", return_value=self.home)):
            p.start()
            self.addCleanup(p.stop)
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)   # not "/": later tests read files by relative path

    def test_the_plain_spelling_asks_as_before(self):
        self.assertTrue(command_reads_secret("cat ~/.clyde/keys.json"))

    def test_globs_braces_and_relative_names_after_a_cd_ask(self):
        for cmd in ("cat ~/.clyde/ke*", "cat ~/.clyde/{keys,none}.json", "cd ~/.clyde && cat keys.json",
                    "cd ~/.clyde; cat ./keys.json", "cat ~/.ssh/id_*"):
            self.assertTrue(command_reads_secret(cmd), cmd)

    def test_secret_directories_ask_with_or_without_a_trailing_slash(self):
        for cmd in ("grep -r . ~/.ssh", "grep -r . ~/.ssh/", "tar cf - ~/.clyde", "cp -r ~/.ssh /tmp/x"):
            self.assertTrue(command_reads_secret(cmd), cmd)

    def test_the_process_environment_and_clydes_other_secret_files_ask(self):
        for cmd in ("cat /proc/self/environ", "cat ~/.clyde/settings.json", "env", "printenv", "printenv | head", "set", "export -p"):
            self.assertTrue(command_reads_secret(cmd), cmd)

    def test_ordinary_commands_do_not_ask(self):
        for cmd in ("cat README.md", "ls", "ls ~/.ssh", "cd src && ls", "echo hi", "git status", "env FOO=1 ls", "grep -r todo ."):
            self.assertFalse(command_reads_secret(cmd), cmd)


if __name__ == "__main__":
    unittest.main()
