"""Map tool, context section and background refresh, against a fake `graphify` on PATH."""

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
from src.tool_system.tools.code_map import MapTool, start_background_refresh

# Records its argv; `update` writes a graph like the real one does.
FAKE_GRAPHIFY = """#!/bin/sh
echo "$@" >> "$GRAPHIFY_LOG"
if [ "$1" = update ]; then
  mkdir -p "$GRAPHIFY_OUT"
  echo '{"nodes": []}' > "$GRAPHIFY_OUT/graph.json"
  printf '## God Nodes (most connected)\\n1. `Engine` - 40 edges\\n2. `run()` - 12 edges\\n\\n## Communities\\n' > "$GRAPHIFY_OUT/GRAPH_REPORT.md"
  echo "[graphify watch] Rebuilt: 2 nodes, 3 edges, 1 communities"; echo "Code graph updated."
  exit 0
fi
echo "NODE result for $1 $2"
"""


class TestMap(unittest.TestCase):
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
                                           "GRAPHIFY_LOG": str(self.log), "CLYDE_MAP": ""})
        self.env.start()
        self.ctx = ToolContext(workspace_root=self.repo)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_first_query_builds_the_graph_then_queries_it(self) -> None:
        out = MapTool().run({"action": "query", "question": "how does auth work"}, self.ctx)
        self.assertFalse(out.is_error)
        self.assertEqual(out.output, "NODE result for query how does auth work")
        calls = self._calls()
        self.assertEqual(calls[0], "update .")
        self.assertIn(f"--graph {self.repo / '.clyde' / 'code-map' / 'map.json'}", calls[1])

    def test_actions_map_to_graphify_commands(self) -> None:
        tool = MapTool()
        self.assertEqual(tool.run({"action": "update"}, self.ctx).output, "Map updated: 2 symbols, 3 links, 1 clusters.")
        tool.run({"action": "path", "source": "A", "target": "B"}, self.ctx)
        tool.run({"action": "affected", "target": "X", "depth": 3}, self.ctx)
        tool.run({"action": "god_nodes"}, self.ctx)
        calls = [c.split(" --graph")[0] for c in self._calls()]
        self.assertEqual(calls, ["update .", "path A B", "affected X --depth 3", "god-nodes --top 10"])

    def test_missing_fields_and_missing_graphify(self) -> None:
        with self.assertRaisesRegex(ToolInputError, "path needs: source, target"):
            MapTool().run({"action": "path"}, self.ctx)
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            with self.assertRaisesRegex(ToolInputError, "uv tool install graphifyy"):
                MapTool().run({"action": "explain", "target": "X"}, self.ctx)

    def test_context_prompt_points_at_the_tool_once_a_graph_exists(self) -> None:
        self.assertNotIn("## Code Map", build_context_prompt(self.repo))
        MapTool().run({"action": "update"}, self.ctx)
        prompt = build_context_prompt(self.repo)
        self.assertIn("## Code Map", prompt)
        self.assertIn("Map tool", prompt)
        self.assertIn("- `Engine` - 40 edges", prompt)

    def test_background_refresh_only_in_git_repos_and_excludes_output(self) -> None:
        self.assertIsNone(start_background_refresh(self.repo))  # not a git repo yet
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        thread = start_background_refresh(self.repo)
        self.assertIsNotNone(thread)
        thread.join(10)
        self.assertTrue((self.repo / ".clyde" / "code-map" / "map.json").exists())
        self.assertFalse((self.repo / "graphify-out").exists())
        self.assertIn(".clyde/code-map/", (self.repo / ".git" / "info" / "exclude").read_text().splitlines())
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertNotIn("code-map", status)

    def test_refresh_can_be_switched_off(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        with patch.dict(os.environ, {"CLYDE_MAP": "off"}):
            self.assertIsNone(start_background_refresh(self.repo))


if __name__ == "__main__":
    unittest.main()


class TestMapCommand(unittest.TestCase):
    """/map turns its words into one Map tool call, and reports a missing graphify as text."""

    def _call(self, args: str):
        from src.command_system import create_command_context, execute_command_sync
        from src.tool_system.protocol import ToolResult
        seen: list[dict] = []
        with patch.object(MapTool, "run", lambda self, tool_input, ctx: seen.append(tool_input) or ToolResult(name="Map", output="ok")):
            ok, text, error = execute_command_sync("map", args, create_command_context(workspace_root=Path(".")))
        self.assertTrue(ok, error)
        self.assertEqual(text, "ok")
        return seen[0]

    def test_words_become_the_matching_action(self):
        self.assertEqual(self._call(""), {"action": "god_nodes"})
        self.assertEqual(self._call("update"), {"action": "update"})
        self.assertEqual(self._call("explain Foo"), {"action": "explain", "target": "Foo"})
        self.assertEqual(self._call("affected Foo"), {"action": "affected", "target": "Foo"})
        self.assertEqual(self._call("path A B"), {"action": "path", "source": "A", "target": "B"})
        self.assertEqual(self._call("how does login work"), {"action": "query", "question": "how does login work"})
        self.assertEqual(self._call("query login"), {"action": "query", "question": "login"})

    def test_a_missing_graphify_is_reported_not_raised(self):
        from src.command_system import create_command_context, execute_command_sync
        with patch("src.tool_system.tools.code_map.shutil.which", return_value=None):
            ok, text, _ = execute_command_sync("map", "", create_command_context(workspace_root=Path(".")))
        self.assertTrue(ok)
        self.assertIn("graphify", text)
