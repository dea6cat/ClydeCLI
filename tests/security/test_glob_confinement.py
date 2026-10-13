"""Glob must list only files inside the allowed folders, and not secret ones."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.tools.glob import GlobTool


class TestGlobConfinement(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp()).resolve()
        self.root = base / "ws"
        self.root.mkdir()
        self.sibling = base / "sibling"
        self.sibling.mkdir()
        (self.sibling / "outside.txt").write_text("x")
        (self.root / "a.py").write_text("x")
        (self.root / ".env").write_text("x")
        (self.root / "deploy.pem").write_text("x")
        (self.root / "link.txt").symlink_to(self.sibling / "outside.txt")
        self.ctx = ToolContext(workspace_root=self.root, cwd=self.root)

    def _glob(self, pattern, **extra):
        return GlobTool().run({"pattern": pattern, **extra}, self.ctx).output["filenames"]

    def test_an_absolute_pattern_or_dot_dot_cannot_list_outside(self):
        for pattern in (f"{self.sibling}/*", "../sibling/*", "sub/../../sibling/*"):
            with self.assertRaises(ToolInputError, msg=pattern):
                self._glob(pattern)

    def test_secret_files_and_outside_symlinks_are_not_listed(self):
        names = {Path(p).name for p in self._glob("*", limit=100)}
        self.assertIn("a.py", names)
        self.assertFalse({".env", "deploy.pem", "link.txt"} & names, names)

    def test_dotfiles_match_only_when_not_secret_and_ordinary_patterns_work(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "b.py").write_text("x")
        self.assertEqual(sorted(Path(p).name for p in self._glob("**/*.py")), ["a.py", "b.py"])


if __name__ == "__main__":
    unittest.main()
