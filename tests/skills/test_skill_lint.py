"""Tests for the skill lint /doctor runs."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.skills.lint import lint_skill_dir, lint_skills


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

    def test_a_missing_ts_script_is_reported(self):
        self.skill("tsx", "---\ndescription: x\n---\nRun `npx tsx scripts/build.ts`.\n\n| example | scripts/eval.ts:8 |\n")
        problems = "\n".join(lint_skill_dir(self.base)[1])
        self.assertIn("runs scripts/build.ts", problems)
        self.assertNotIn("eval.ts", problems)   # mentioned in a table, not run

    def test_a_same_named_skill_with_other_content_is_reported_as_hidden(self):
        home = self.base / "home"
        for folder, body in ((".agents", "one"), (".claude", "two"), (".codex", "one")):
            target = home / folder / "skills" / "pack"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(f"---\ndescription: x\n---\n{body}\n", encoding="utf-8")
        with patch.object(Path, "home", return_value=home), patch("src.plugins.skill_dirs", return_value=[]), \
                patch.dict(os.environ, {"CLYDE_SKILLS_DIR": "", "CLAUDE_SKILLS_DIR": "", "CLYDE_MANAGED_SKILLS_DIR": "", "XDG_CONFIG_HOME": ""}):
            _, problems = lint_skills()
        hidden = [p for p in problems if "hidden by" in p]
        # ~/.codex (lowest) and ~/.agents hold the same content: no problem there. ~/.claude wins over both with other content.
        self.assertEqual(hidden, ["~/.agents/skills/pack: hidden by ~/.claude/skills/pack, a different skill with the same name"])

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
