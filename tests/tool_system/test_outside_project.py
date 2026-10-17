"""Without an OS sandbox, a shell command that names a place outside the project asks, even a read-only one and even in all-in mode."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.registry import _is_major
from src.tool_system.tools.bash import BashTool, reaches_outside_project


class TestOutsideProject(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve() / "proj"
        self.root.mkdir()
        self.ctx = ToolContext(workspace_root=self.root)
        patcher = patch.dict(os.environ, {"HOME": "/Users/someone"})   # the suite's own HOME is a temp folder, which counts as temp
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_names_outside_the_project_are_caught(self):
        for command in ("ls /etc", "cat ~/notes.txt", "cat $HOME/notes.txt", "ls ../../../../../../../../../../etc", "echo x > /etc/hosts",
                        "echo x 2>>~/log", "cp a /Users/someone/b", "echo $(cat /etc/hosts)"):
            self.assertTrue(reaches_outside_project(command, self.ctx), command)

    def test_the_project_and_temp_folders_are_fine(self):
        for command in ("ls", "ls src", f"cat {self.root}/a.txt", "ls /tmp/x", "echo x > /dev/null", "cd src && ls ..", "git status", "echo 'a (b)' >&2; exit 3"):
            self.assertFalse(reaches_outside_project(command, self.ctx), command)

    def test_an_extra_working_folder_counts_as_the_project(self):
        extra = Path(tempfile.mkdtemp()).resolve()
        ctx = ToolContext(workspace_root=self.root)
        ctx.permission_context.additional_working_directories = (extra,)
        self.assertFalse(reaches_outside_project(f"ls {extra}", ctx))

    def test_a_read_only_command_outside_asks_and_inside_does_not(self):
        self.assertEqual(BashTool().check_permissions({"command": "ls /etc"}, self.ctx).behavior.value, "ask")
        self.assertEqual(BashTool().check_permissions({"command": "ls"}, self.ctx).behavior.value, "allow")

    def test_all_in_mode_still_asks(self):
        spec = BashTool().spec()
        self.assertTrue(_is_major(spec, {"command": "ls /etc"}, self.ctx))
        self.assertFalse(_is_major(spec, {"command": "ls"}, self.ctx))

    def test_the_tool_no_longer_offers_a_way_out_of_a_sandbox(self):
        self.assertNotIn("unsandboxed", BashTool().spec().input_schema["properties"])
        (self.root / "a.txt").write_text("x")
        result = BashTool().run({"command": "cat a.txt"}, self.ctx)
        self.assertNotIn("sandboxed", result.output)
        self.assertEqual(result.output["stdout"].strip(), "x")


if __name__ == "__main__":
    unittest.main()
