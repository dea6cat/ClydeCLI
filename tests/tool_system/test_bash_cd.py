"""A bare `cd` moves the session; `cd x && cmd` runs the whole command (it used to run only the cd)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.tools.bash import BashTool


class TestBashCd(unittest.TestCase):
    def test_compound_cd_runs_the_rest_and_bare_cd_moves(self):
        ws = Path(tempfile.mkdtemp()).resolve()
        (ws / "sub").mkdir()
        (ws / "sub" / "marker.txt").write_text("x")
        ctx = ToolContext(workspace_root=ws)
        out = BashTool().run({"command": f"cd {ws / 'sub'} && ls"}, ctx).output
        self.assertEqual((out["exit_code"], out["stdout"]), (0, "marker.txt\n"))
        self.assertEqual(ctx.cwd, ws)                                # a compound cd doesn't move the session
        BashTool().run({"command": "cd sub"}, ctx)
        self.assertEqual(ctx.cwd, ws / "sub")


if __name__ == "__main__":
    unittest.main()
