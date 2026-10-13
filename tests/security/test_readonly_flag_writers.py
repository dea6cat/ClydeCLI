"""Commands on the read-only list stop being read-only when a flag makes them write or run another program."""

from __future__ import annotations

import unittest

from src.tool_system.tools.bash import is_read_only_command


class TestFlagWriters(unittest.TestCase):
    def test_tree_flags_that_write_files_are_not_read_only(self):
        for cmd in ("tree -o out.txt", "tree -oout.txt", "tree -ao out.txt", "tree -R", "tree -aR", "tree --output=out.txt"):
            self.assertFalse(is_read_only_command(cmd), cmd)

    def test_other_listed_commands_with_writing_or_program_running_flags_are_not_read_only(self):
        for cmd in ("rg --hostname-bin x pat", "rg -z pat", "rg -uz pat", "rg --search-zip pat", "file -C", "file -aC x",
                    "date -s '2020-01-01'", "date --set=x", "date -us x"):
            self.assertFalse(is_read_only_command(cmd), cmd)

    def test_the_same_commands_without_those_flags_stay_read_only(self):
        for cmd in ("tree", "tree -L 2", "tree -a -I node_modules", "rg pat", "rg -i pat src", "file x.bin", "date", "date -u",
                    "find . -name '*.py'", "git log --oneline"):
            self.assertTrue(is_read_only_command(cmd), cmd)


if __name__ == "__main__":
    unittest.main()
