"""Without an OS sandbox, a shell command that names a place outside the project asks, even a read-only one; all-in mode lets only the read-only ones through."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import _is_major
from src.tool_system.tools.bash import BashTool, reaches_outside_project, removes_running_install


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

    def test_all_in_mode_still_asks_to_change_something_outside_but_not_to_look(self):
        spec = BashTool().spec()
        self.assertTrue(_is_major(spec, {"command": "echo x > /etc/hosts"}, self.ctx))
        self.assertTrue(_is_major(spec, {"command": "find /etc -name x | tar -czf /etc/a.tgz -T -"}, self.ctx))
        self.assertFalse(_is_major(spec, {"command": "ls /etc"}, self.ctx))
        self.assertFalse(_is_major(spec, {"command": "find /var/data -type f -name '*x*' | head -5"}, self.ctx))
        self.assertFalse(_is_major(spec, {"command": "ls"}, self.ctx))

    def test_deleting_the_environment_clyde_runs_from_is_named_in_the_question(self):
        tool_dir = f"{sys.prefix}"
        for command in (f"rm -rf {tool_dir}", f"mv {tool_dir} /tmp/x", "uv tool uninstall clyde-cli"):
            self.assertTrue(removes_running_install(command) or "uv tool" in command, command)
        result = BashTool().check_permissions({"command": f"rm -rf {tool_dir}"}, self.ctx)
        self.assertEqual(result.behavior.value, "ask")
        self.assertIn("deletes the Clyde that is running", result.message)
        self.assertFalse(removes_running_install(f"ls {tool_dir}"))
        self.assertFalse(removes_running_install("rm -rf build"))

    def test_the_tool_no_longer_offers_a_way_out_of_a_sandbox(self):
        self.assertNotIn("unsandboxed", BashTool().spec().input_schema["properties"])
        (self.root / "a.txt").write_text("x")
        result = BashTool().run({"command": "cat a.txt"}, self.ctx)
        self.assertNotIn("sandboxed", result.output)
        self.assertEqual(result.output["stdout"].strip(), "x")


class TestFilesAndFoldersOutside(unittest.TestCase):
    """Read, Write, Edit, NotebookEdit, Glob, Grep and a Bash cwd outside the project ask; a yes covers that file or folder for the session."""

    def setUp(self):
        base = Path(tempfile.mkdtemp()).resolve()
        self.root, self.other = base / "proj", base / "other"
        self.root.mkdir()
        self.other.mkdir()
        (self.other / "note.txt").write_text("hello\n")
        self.asked: list[str] = []
        self.answer = True
        self.ctx = ToolContext(workspace_root=self.root)
        self.ctx.permission_handler = lambda tool, message, suggestion: (self.asked.append(message) or self.answer, False)
        self.registry = build_default_registry()

    def call(self, name, **input):
        return self.registry.dispatch(ToolCall(name=name, input=input), self.ctx)

    def test_a_yes_lets_the_edit_through_and_covers_that_file_afterwards(self):
        note = str(self.other / "note.txt")
        self.call("Read", file_path=note)                              # Edit needs a Read first
        self.asked.clear()
        self.assertFalse(self.call("Edit", file_path=note, old_string="hello", new_string="bye").is_error)
        self.assertEqual((self.other / "note.txt").read_text(), "bye\n")
        self.assertEqual(len(self.asked), 0)                           # the Read's yes already covered this file
        self.assertIn("outside the project", self.call("Write", file_path=str(self.other / "new.txt"), content="x") and self.asked[-1])
        self.assertTrue((self.other / "new.txt").exists())

    def test_a_no_leaves_it_alone_and_asks_again_next_time(self):
        self.answer = False
        target = self.other / "new.txt"
        for _ in range(2):
            self.assertTrue(self.call("Write", file_path=str(target), content="x").is_error)
        self.assertFalse(target.exists())
        self.assertEqual(len(self.asked), 2)

    def test_all_in_mode_asks_the_first_time_only(self):
        self.ctx.auto_approve = True
        note = str(self.other / "note.txt")
        self.call("Read", file_path=note)
        self.call("Read", file_path=note)
        self.assertEqual(len(self.asked), 1)

    def test_without_a_way_to_ask_it_is_refused(self):
        self.ctx.permission_handler = None
        self.assertTrue(self.call("Write", file_path=str(self.other / "x.txt"), content="x").is_error)
        self.assertTrue(self.call("Read", file_path=str(self.other / "note.txt")).is_error)

    def test_a_folder_yes_covers_what_is_under_it(self):
        self.assertFalse(self.call("Grep", pattern="hello", path=str(self.other)).is_error)
        self.assertEqual(len(self.asked), 1)
        self.assertFalse(self.call("Read", file_path=str(self.other / "note.txt")).is_error)
        self.assertEqual(len(self.asked), 1)                           # under the folder already approved
        self.assertTrue(self.call("Read", file_path=str(self.other.parent / "elsewhere.txt")).is_error)   # a sibling is not covered
        self.assertEqual(len(self.asked), 2)

    def test_inside_the_project_nothing_new_asks(self):
        (self.root / "a.txt").write_text("x")
        self.call("Read", file_path=str(self.root / "a.txt"))
        self.call("Glob", pattern="*.txt", path=str(self.root))
        self.assertEqual(self.asked, [])

    def test_a_read_only_command_naming_another_folder_asks_through_dispatch(self):
        self.assertFalse(self.call("Bash", command="ls /etc").is_error)
        self.assertEqual(len(self.asked), 1)
        self.assertIn("outside the project", self.asked[0])
        self.asked.clear()
        self.call("Bash", command="ls")
        self.assertEqual(self.asked, [])
        self.ctx.permission_rules = {"allow": ["Bash(ls /etc:*)"], "deny": []}   # a rule the user wrote covers it
        self.call("Bash", command="ls /etc")
        self.assertEqual(self.asked, [])

    def test_a_shell_in_another_folder_and_cd_ask_then_work(self):
        self.assertEqual(self.call("Bash", command="ls", cwd=str(self.other)).output["stdout"].strip(), "note.txt")
        self.assertIn("outside the project", self.asked[0])
        self.asked.clear()
        self.assertFalse(self.call("Bash", command="cd /etc").is_error)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.ctx.cwd, Path("/etc").resolve())


if __name__ == "__main__":
    unittest.main()
