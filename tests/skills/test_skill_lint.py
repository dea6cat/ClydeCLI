"""Tests for the skill lint /doctor runs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.skills.lint import lint_skill_dir


class TestSkillLint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def skill(self, name: str, text: str) -> Path:
        folder = self.base / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(text, encoding="utf-8")
        return folder

    def test_clean_skill_has_no_problems(self):
        folder = self.skill("ok", "---\ndescription: Packs a file\n---\nRun `python3 scripts/pack.py`.\n")
        (folder / "scripts").mkdir()
        (folder / "scripts" / "pack.py").write_text("", encoding="utf-8")
        self.assertEqual(lint_skill_dir(self.base), (1, []))

    def test_each_silent_problem_is_reported(self):
        (self.base / "empty").mkdir()
        (self.base / ".trash").mkdir()
        self.skill("open", "---\ndescription: never closed\nbody\n")
        self.skill("dead", "---\ndescription: x\ndisable-model-invocation: true\nuser-invocable: false\n---\nbody\n")
        self.skill("noscript", "---\ndescription: x\n---\nRun ${CLAUDE_SKILL_DIR}/scripts/run.sh, not tools/scripts/other.py.\n")

        checked, problems = lint_skill_dir(self.base)

        self.assertEqual(checked, 3)
        text = "\n".join(problems)
        self.assertIn("empty: no SKILL.md", text)
        self.assertNotIn(".trash", text)
        self.assertIn("open/SKILL.md: frontmatter is never closed", text)
        self.assertIn("open/SKILL.md: no `description:`", text)
        self.assertIn("dead/SKILL.md: disable-model-invocation and user-invocable: false", text)
        self.assertIn("noscript/SKILL.md: runs scripts/run.sh", text)
        self.assertNotIn("other.py", text)
        self.assertEqual(len(problems), 5)

    def test_skill_escaping_the_project_is_reported(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name) / "evil"
        target.mkdir()
        (target / "SKILL.md").write_text("---\ndescription: x\n---\n", encoding="utf-8")
        (self.base / "evil").symlink_to(target)

        checked, problems = lint_skill_dir(self.base, confine_to=self.base)

        self.assertEqual(checked, 0)
        self.assertEqual(len(problems), 1)
        self.assertIn("points outside the project", problems[0])


if __name__ == "__main__":
    unittest.main()
