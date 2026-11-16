"""Shell command classification: what asks even in all-in mode, and what is refused outright."""

from __future__ import annotations

import unittest

from src.tool_system.shell import DANGEROUS_PATTERNS, is_major_command


class TestShell(unittest.TestCase):
    def test_force_deleting_a_branch_is_major_a_safe_delete_is_not(self):
        self.assertTrue(is_major_command("git branch -D feature"))
        self.assertFalse(is_major_command("git branch -d feature"))   # -d deletes only a merged branch

    def test_case_does_not_hide_a_major_command(self):
        self.assertTrue(is_major_command("GIT PUSH origin main"))

    def test_what_is_refused_outright_is_not_also_merely_major(self):
        for command in ("shutdown -h now", "sudo rm x", "mkfs.ext4 /dev/sda1", "dd if=/dev/zero of=/dev/sda"):
            self.assertTrue(any(p.search(command) for p in DANGEROUS_PATTERNS), command)


if __name__ == "__main__":
    unittest.main()
