"""README and instruction files taken from a repository must really be inside it and must not be secrets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.context_system.builder import build_context_prompt
from src.context_system.claude_md import load_claude_md_context


class TestContextSymlinks(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp()).resolve()
        self.root = base / "repo"
        self.root.mkdir()
        self.outside = base / "outside.txt"
        self.outside.write_text("CANARY-outside\n")
        home = base / "home"
        home.mkdir()
        patcher = patch.object(Path, "home", return_value=home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_readme_symlinked_outside_does_not_reach_the_prompt(self):
        (self.root / "README.md").symlink_to(self.outside)
        self.assertNotIn("CANARY", build_context_prompt(self.root))

    def test_a_readme_symlinked_to_a_secret_inside_the_repo_does_not_reach_the_prompt(self):
        (self.root / ".env").write_text("CANARY-env=1\n")
        (self.root / "README.md").symlink_to(self.root / ".env")
        self.assertNotIn("CANARY", build_context_prompt(self.root))

    def test_an_ordinary_readme_still_does(self):
        (self.root / "README.md").write_text("# Title\n\nCANARY-readme\n")
        self.assertIn("CANARY-readme", build_context_prompt(self.root))

    def test_instruction_files_symlinked_outside_are_not_loaded(self):
        for name in ("CLAUDE.md", "AGENTS.md"):
            (self.root / name).symlink_to(self.outside)
            self.assertEqual(load_claude_md_context(self.root).files, (), name)
            (self.root / name).unlink()

    def test_an_instruction_file_symlinked_inside_the_repo_still_loads(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "rules.md").write_text("CANARY-rules\n")
        (self.root / "CLAUDE.md").symlink_to(self.root / "docs" / "rules.md")
        self.assertIn("CANARY-rules", load_claude_md_context(self.root).files[0].content)

    def test_readme_text_with_a_long_backtick_run_cannot_close_the_fence(self):
        (self.root / "README.md").write_text("# T\n\n`````\nescaped\n`````\n\nINJECTED-after-fence\n")
        lines = build_context_prompt(self.root).splitlines()
        opening = lines[next(i for i, line in enumerate(lines) if line.startswith("### ./README.md")) + 1]
        ticks = len(opening) - len(opening.lstrip("`"))
        self.assertGreaterEqual(ticks, 6)   # longer than the five-backtick run inside the README
        self.assertEqual(lines.count("`" * ticks), 1)   # and the README itself holds no line that closes it

if __name__ == "__main__":
    unittest.main()
