"""A command is read-only only if bash cannot be made to run something else while expanding it."""

from __future__ import annotations

import unittest

from src.tool_system.tools.bash import is_read_only_command


class TestExpansionIsNotReadOnly(unittest.TestCase):
    def test_the_audit_payload_is_not_read_only(self):
        self.assertFalse(is_read_only_command("echo ${x:=$'\\x24\\x28id\\x29'} ${x@P}"))

    def test_expansions_that_assign_or_evaluate_are_not_read_only(self):
        for cmd in ("echo ${x@P}", "echo ${x@E}", "echo ${x:=ls}", "echo ${x=ls}", "echo ${x:?oops}",
                    "echo ${!y}", "echo ${x//a/b}", "echo $((1+1))", "echo $'\\x41'", 'echo $"hi"', "echo ${x"):
            self.assertFalse(is_read_only_command(cmd), cmd)

    def test_ordinary_read_only_commands_stay_read_only(self):
        for cmd in ("ls -la", "git status", "echo $HOME", "echo ${HOME}", "cat README.md | head -5", "pwd && ls src"):
            self.assertTrue(is_read_only_command(cmd), cmd)


if __name__ == "__main__":
    unittest.main()
