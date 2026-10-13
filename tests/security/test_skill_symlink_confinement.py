"""A repository's own skill folders may only contribute files that live inside the repository."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.skills.loader import clear_skill_registry, get_all_skills, load_skills_from_dir

BODY = "---\ndescription: d\n---\n{text}\n"


class TestProjectSkillSymlinks(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp()).resolve()
        self.project = base / "repo"
        self.project.mkdir()
        self.outside = base / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("CANARY-secret\n")
        self.skills = self.project / ".clyde" / "skills"
        self.skills.mkdir(parents=True)
        home = base / "home"
        home.mkdir()
        patcher = patch.object(Path, "home", return_value=home)
        patcher.start()
        self.addCleanup(patcher.stop)
        clear_skill_registry()
        self.addCleanup(clear_skill_registry)

    def _names(self):
        return {s.name for s in get_all_skills(project_root=self.project)}

    def test_a_skill_md_symlinked_to_an_outside_file_is_not_loaded(self):
        (self.skills / "leak").mkdir()
        (self.skills / "leak" / "SKILL.md").symlink_to(self.outside / "secret.txt")
        self.assertNotIn("leak", self._names())
        self.assertNotIn("CANARY", "".join(s.markdown_content for s in get_all_skills(project_root=self.project)))

    def test_a_skill_folder_symlinked_outside_is_not_loaded(self):
        (self.outside / "pack").mkdir()
        (self.outside / "pack" / "SKILL.md").write_text(BODY.format(text="CANARY-pack"))
        (self.skills / "pack").symlink_to(self.outside / "pack")
        self.assertNotIn("pack", self._names())

    def test_a_skills_folder_that_is_itself_a_symlink_outside_is_not_loaded(self):
        (self.outside / "all" / "x").mkdir(parents=True)
        (self.outside / "all" / "x" / "SKILL.md").write_text(BODY.format(text="CANARY-all"))
        self.skills.rmdir()
        self.skills.symlink_to(self.outside / "all")
        self.assertNotIn("x", self._names())

    def test_ordinary_project_skills_still_load_and_so_do_links_inside_the_repo(self):
        (self.skills / "good").mkdir()
        (self.skills / "good" / "SKILL.md").write_text(BODY.format(text="fine"))
        (self.project / "shared").mkdir()
        (self.project / "shared" / "SKILL.md").write_text(BODY.format(text="shared"))
        (self.skills / "inside").symlink_to(self.project / "shared")
        self.assertTrue({"good", "inside"} <= self._names())

    def test_loading_a_folder_directly_is_unchanged(self):
        (self.skills / "good").mkdir()
        (self.skills / "good" / "SKILL.md").write_text(BODY.format(text="fine"))
        self.assertEqual([s.name for s in load_skills_from_dir(self.skills)], ["good"])


if __name__ == "__main__":
    unittest.main()
