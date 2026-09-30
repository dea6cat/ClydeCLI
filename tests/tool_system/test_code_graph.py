"""CodeGraph tool, context section and background refresh, against a fake `graphify` on PATH."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.context_system import build_context_prompt
from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.tools.code_graph import CodeGraphTool, start_background_refresh

# Records its argv; `update` writes a graph like the real one does.
FAKE_GRAPHIFY = """#!/bin/sh
echo "$@" >> "$GRAPHIFY_LOG"
if [ "$1" = update ]; then
  mkdir -p graphify-out
  echo '{"nodes": []}' > graphify-out/graph.json
  printf '## God Nodes (most connected)\\n1. `Engine` - 40 edges\\n2. `run()` - 12 edges\\n\\n## Communities\\n' > graphify-out/GRAPH_REPORT.md
  echo "[graphify watch] Rebuilt: 2 nodes"; echo "Code graph updated."
  exit 0
fi
echo "NODE result for $1 $2"
"""


class TestCodeGraph(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "graphify"
        exe.write_text(FAKE_GRAPHIFY)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.log = self.root / "calls.log"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                                           "GRAPHIFY_LOG": str(self.log), "CLYDE_CODE_GRAPH": ""})
        self.env.start()
        self.ctx = ToolContext(workspace_root=self.repo)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_first_query_builds_the_graph_then_queries_it(self) -> None:
        out = CodeGraphTool().run({"action": "query", "question": "how does auth work"}, self.ctx)
        self.assertFalse(out.is_error)
        self.assertEqual(out.output, "NODE result for query how does auth work")
        calls = self._calls()
        self.assertEqual(calls[0], "update .")
        self.assertIn(f"--graph {self.repo / 'graphify-out' / 'graph.json'}", calls[1])

    def test_actions_map_to_graphify_commands(self) -> None:
        tool = CodeGraphTool()
        tool.run({"action": "update"}, self.ctx)
        tool.run({"action": "path", "source": "A", "target": "B"}, self.ctx)
        tool.run({"action": "affected", "target": "X", "depth": 3}, self.ctx)
        tool.run({"action": "god_nodes"}, self.ctx)
        calls = [c.split(" --graph")[0] for c in self._calls()]
        self.assertEqual(calls, ["update .", "path A B", "affected X --depth 3", "god-nodes --top 10"])

    def test_missing_fields_and_missing_graphify(self) -> None:
        with self.assertRaisesRegex(ToolInputError, "path needs: source, target"):
            CodeGraphTool().run({"action": "path"}, self.ctx)
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            with self.assertRaisesRegex(ToolInputError, "uv tool install graphifyy"):
                CodeGraphTool().run({"action": "explain", "target": "X"}, self.ctx)

    def test_context_prompt_points_at_the_tool_once_a_graph_exists(self) -> None:
        self.assertNotIn("## Code Graph", build_context_prompt(self.repo))
        CodeGraphTool().run({"action": "update"}, self.ctx)
        prompt = build_context_prompt(self.repo)
        self.assertIn("## Code Graph", prompt)
        self.assertIn("CodeGraph tool", prompt)
        self.assertIn("- `Engine` - 40 edges", prompt)

    def test_background_refresh_only_in_git_repos_and_excludes_output(self) -> None:
        self.assertIsNone(start_background_refresh(self.repo))  # not a git repo yet
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        thread = start_background_refresh(self.repo)
        self.assertIsNotNone(thread)
        thread.join(10)
        self.assertTrue((self.repo / "graphify-out" / "graph.json").exists())
        self.assertIn("graphify-out/", (self.repo / ".git" / "info" / "exclude").read_text().splitlines())
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertNotIn("graphify-out", status)

    def test_refresh_can_be_switched_off(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        with patch.dict(os.environ, {"CLYDE_CODE_GRAPH": "off"}):
            self.assertIsNone(start_background_refresh(self.repo))


if __name__ == "__main__":
    unittest.main()
