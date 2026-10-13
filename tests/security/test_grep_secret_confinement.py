"""A recursive Grep must not return the contents of secret files or of files outside the workspace."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.tools.grep import GrepTool


class TestGrepWalk(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp()).resolve()
        self.root = base / "ws"
        self.root.mkdir()
        outside = base / "outside.txt"
        outside.write_text("CANARY-outside\n")
        (self.root / "notes.txt").write_text("CANARY-ordinary\n")
        (self.root / ".env").write_text("CANARY-env=1\n")
        (self.root / "id_rsa").write_text("CANARY-ssh\n")
        (self.root / "deploy.pem").write_text("CANARY-pem\n")
        (self.root / "link.txt").symlink_to(outside)
        self.ctx = ToolContext(workspace_root=self.root, cwd=self.root)

    def _grep(self, **extra):
        return GrepTool().run({"pattern": "CANARY", "output_mode": "content", **extra}, self.ctx).output

    def test_secret_files_and_outside_symlinks_are_not_read(self):
        out = self._grep()
        self.assertIn("CANARY-ordinary", out["content"])
        for leaked in ("CANARY-env", "CANARY-ssh", "CANARY-pem", "CANARY-outside"):
            self.assertNotIn(leaked, out["content"])
        self.assertEqual(sorted(Path(f).name for f in out["filenames"]), ["notes.txt"])

    def test_the_model_is_told_files_were_skipped(self):
        self.assertEqual(self._grep()["skippedFiles"], 4)

    def test_files_mode_leaks_no_names_of_skipped_files_either(self):
        out = GrepTool().run({"pattern": "CANARY", "output_mode": "files_with_matches"}, self.ctx).output
        self.assertEqual(sorted(Path(f).name for f in out["filenames"]), ["notes.txt"])


if __name__ == "__main__":
    unittest.main()
