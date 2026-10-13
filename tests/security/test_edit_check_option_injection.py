"""The post-edit lint must never let a model-chosen path act as a linter option or leave the workspace."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system import checks
from src.tool_system.checks import Tooling, edit_check_for, lint_files


class TestLintArgv(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.calls: list[list[str]] = []
        patcher = patch.object(checks, "_run", lambda argv, root, timeout: (self.calls.append(argv) or (0, "")))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tooling(self):
        return Tooling(self.root, {"ruff": ["ruff"], "mypy": ["mypy"]})

    def test_operands_follow_a_double_dash_and_never_look_like_options(self):
        hostile = self.root / "--output-file=" / "tmp" / "victim.py"
        hostile.parent.mkdir(parents=True)
        hostile.write_text("x = 1\n")
        lint_files(self._tooling(), [hostile])
        for argv in self.calls:
            self.assertIn("--", argv)
            operands = argv[argv.index("--") + 1:]
            self.assertTrue(operands)
            self.assertFalse(any(o.startswith("-") for o in operands), argv)

    def test_an_ordinary_file_is_still_linted_by_relative_name(self):
        ok = self.root / "pkg" / "a.py"
        ok.parent.mkdir()
        ok.write_text("x = 1\n")
        lint_files(self._tooling(), [ok])
        self.assertTrue(any(argv[-1].endswith("pkg/a.py") for argv in self.calls))


class TestEditCheckConfinement(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n")
        patcher = patch.object(checks, "checks_enabled", lambda: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_path_outside_the_workspace_gets_no_check(self):
        outside = Path(tempfile.mkdtemp()).resolve() / "evil.py"
        outside.write_text("x = 1\n")
        self.assertIsNone(edit_check_for("Write", {"file_path": str(outside)}, self.root))
        self.assertIsNone(edit_check_for("Write", {"file_path": "../" + outside.parent.name + "/evil.py"}, self.root))

    def test_a_symlink_that_leaves_the_workspace_gets_no_check(self):
        outside = Path(tempfile.mkdtemp()).resolve() / "evil.py"
        outside.write_text("x = 1\n")
        (self.root / "link.py").symlink_to(outside)
        self.assertIsNone(edit_check_for("Edit", {"file_path": "link.py"}, self.root))

    def test_a_workspace_file_still_gets_a_check(self):
        (self.root / "a.py").write_text("x = 1\n")
        self.assertIsNotNone(edit_check_for("Write", {"file_path": "a.py"}, self.root))


if __name__ == "__main__":
    unittest.main()
