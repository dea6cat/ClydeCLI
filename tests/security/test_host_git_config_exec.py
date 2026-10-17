"""Model-writable repository config and hooks must never run through Clyde's own git calls."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.context_system.git_context import collect_git_context
from src.tool_system.context import ToolContext
from src.tool_system.protocol import ToolCall, ToolResult
from src.tool_system.registry import ToolRegistry, _is_major
from src.tool_system.tools.bash import BashTool, reaches_outside_project
from src.tool_system.tools.write import FileWriteTool


def _repo() -> Path:
    root = Path(tempfile.mkdtemp()).resolve()
    run = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (root / "a.txt").write_text("x\n")
    run("add", ".")
    run("commit", "-qm", "init")
    return root


class TestHostGitIgnoresRepoCode(unittest.TestCase):
    def test_a_planted_fsmonitor_does_not_run(self):
        root = _repo()
        marker = root.parent / f"{root.name}.fsmonitor-ran"
        script = root.parent / f"{root.name}.fsmon.sh"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        script.chmod(0o755)
        subprocess.run(["git", "config", "core.fsmonitor", str(script)], cwd=root, check=True)
        (root / "b.txt").write_text("y\n")
        collect_git_context(root)
        self.assertFalse(marker.exists(), "git ran a core.fsmonitor command taken from the repository config")

    def test_every_workspace_git_spawn_goes_through_the_safe_helper(self):
        import re
        offenders = []
        for rel in ("src/context_system/git_context.py", "src/review.py", "src/tool_system/plan_file.py",
                    "src/tool_system/tools/worktree.py", "src/tool_system/tools/code_map.py"):
            text = (Path(__file__).resolve().parents[2] / rel).read_text()
            if re.search(r"\[\s*[\"']git[\"']", text):
                offenders.append(rel)
        self.assertEqual(offenders, [], "these files still build a bare ['git', ...] argv")


class TestGitControlFilesAreProtected(unittest.TestCase):
    def setUp(self):
        self.root = _repo()
        self.ctx = ToolContext(workspace_root=self.root)

    def test_all_in_mode_still_asks_before_writing_git_config_or_hooks(self):
        spec = FileWriteTool().spec()
        for rel in (".git/config", ".git/hooks/post-checkout", ".git/hooks/pre-commit"):
            self.assertTrue(_is_major(spec, {"file_path": str(self.root / rel)}, self.ctx), rel)
        self.assertFalse(_is_major(spec, {"file_path": str(self.root / "a.txt")}, self.ctx))

    def test_a_shell_command_that_names_git_config_or_hooks_asks_even_all_in(self):
        for command in ("echo x >> .git/config", "cp h .git/hooks/pre-commit", f"echo x > {self.root}/.git/hooks/post-merge"):
            self.assertTrue(_is_major(BashTool().spec(), {"command": command}, self.ctx), command)
            self.assertTrue(reaches_outside_project(command, self.ctx), command)
        self.assertFalse(reaches_outside_project("git status && ls a.txt", self.ctx))


if __name__ == "__main__":
    unittest.main()
