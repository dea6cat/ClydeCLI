"""The legacy Python skill loader runs only modules inside the skills folder, and only after a yes."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.tools.skill import SkillTool

MODULE = "from pathlib import Path\nPath(r'{marker}').write_text('ran')\ndef run(payload, context):\n    return 'ok'\n"


class TestLegacySkill(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp()).resolve()
        self.skills = base / "skills"
        self.skills.mkdir()
        self.outside = base / "outside"
        self.outside.mkdir()
        self.marker = base / "marker"
        self.ctx = ToolContext(workspace_root=base)
        patcher = patch.dict(os.environ, {"CLYDE_SKILLS_DIR": str(self.skills)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, name):
        try:
            return SkillTool().run({"name": name}, self.ctx)
        except Exception as exc:  # a refusal may be an error result or an exception; both are fine
            return exc

    def _plant(self, where: Path, name="evil"):
        (where / f"{name}.py").write_text(MODULE.format(marker=self.marker))

    def test_an_absolute_name_does_not_run_an_outside_module(self):
        self._plant(self.outside)
        self._run(str(self.outside / "evil"))
        self.assertFalse(self.marker.exists())

    def test_dot_dot_does_not_climb_out_of_the_skills_folder(self):
        self._plant(self.outside)
        self._run("../outside/evil")
        self.assertFalse(self.marker.exists())

    def test_a_symlinked_module_pointing_outside_does_not_run(self):
        self._plant(self.outside)
        (self.skills / "link.py").symlink_to(self.outside / "evil.py")
        self._run("link")
        self.assertFalse(self.marker.exists())

    def test_a_module_inside_the_skills_folder_still_runs(self):
        self._plant(self.skills, "good")
        result = self._run("good")
        self.assertTrue(self.marker.exists())
        self.assertEqual(result.output["output"], "ok")

    def test_running_python_asks_first_but_a_markdown_skill_does_not(self):
        tool = SkillTool()
        self.assertEqual(tool.check_permissions({"name": "good"}, self.ctx).behavior.value, "ask")
        self.assertEqual(tool.check_permissions({"skill": "explain-code"}, self.ctx).behavior.value, "allow")


if __name__ == "__main__":
    unittest.main()
