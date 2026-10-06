from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path
from unittest import mock

from src.agent.conversation import Conversation
from src.context_system import build_context_prompt
from src.context_system.claude_md import load_claude_md_context
from src.context_system.git_context import collect_git_context
from src.context_system.project_summary import build_project_summary
from src.agent.agent_loop import run_agent_loop
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply


class TestContextSystem(unittest.TestCase):
    def test_build_context_prompt_includes_workspace_and_claude_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("Project rule: always add tests.", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

            prompt = build_context_prompt(root)

            self.assertIn("## Runtime Context", prompt)
            self.assertIn("## Project Instructions", prompt)
            self.assertIn("Project rule: always add tests.", prompt)
            self.assertIn("README.md", prompt)
            self.assertIn("pyproject.toml", prompt)

    def test_readme_excerpt_keeps_leading_sections_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "# Demo\nA demo tool.\n\n## Install\npip install demo\n\n## Details\n" + "x" * 5000
            (root / "Readme.MD").write_text(body, encoding="utf-8")

            summary = build_project_summary(root, max_readme_tokens=100)

            self.assertEqual(summary.readme_path.name, "Readme.MD")
            self.assertIn("# Demo", summary.readme_excerpt)
            self.assertIn("pip install demo", summary.readme_excerpt)
            self.assertNotIn("## Details", summary.readme_excerpt)
            self.assertTrue(summary.readme_excerpt.endswith("...[truncated]"))

    def test_readme_excerpt_hard_cuts_oversized_first_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.rst").write_text("Demo\n====\n" + "y" * 5000, encoding="utf-8")

            summary = build_project_summary(root, max_readme_tokens=50)

            self.assertTrue(summary.readme_excerpt.startswith("Demo"))
            self.assertLess(len(summary.readme_excerpt), 250)

    def test_entry_points_from_pyproject_and_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "demo"\n[project.scripts]\ndemo = "demo.cli:main"\n', encoding="utf-8")
            (root / "package.json").write_text(json.dumps({"main": "index.js", "bin": {"dm": "bin/dm.js"}}), encoding="utf-8")

            entries = build_project_summary(root).entry_points

            self.assertEqual(entries, (
                "demo -> demo.cli:main (pyproject)",
                "main -> index.js (package.json)",
                "dm -> bin/dm.js (package.json)",
            ))

    def test_context_prompt_includes_project_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Path, "home", return_value=Path(tmp) / "home"):
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "README.md").write_text("# Demo\nShips widgets.\n", encoding="utf-8")

            prompt = build_context_prompt(root)

            self.assertIn("## Project Summary", prompt)
            self.assertIn("Ships widgets.", prompt)

    def test_claude_md_loads_user_memory_and_project_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / ".clyde").mkdir(parents=True)
            (home / ".clyde" / "CLAUDE.md").write_text("user memory", encoding="utf-8")
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "CLAUDE.md").write_text("shared rules", encoding="utf-8")
            (root / "CLAUDE.local.md").write_text("my local notes", encoding="utf-8")

            with mock.patch.object(Path, "home", return_value=home):
                ctx = load_claude_md_context(root)

            self.assertEqual([f.content for f in ctx.files], ["user memory", "shared rules", "my local notes"])

    def test_collect_git_context_handles_non_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = collect_git_context(tmp)
            self.assertFalse(ctx.available)

    def test_agent_loop_injects_context_prompt_for_non_anthropic(self) -> None:
        registry = build_default_registry(include_user_tools=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("Follow the CLAUDE instructions.", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")

            ctx = ToolContext(workspace_root=root)

            conversation = Conversation()
            conversation.add_user_message("hello")

            provider = FakeProvider(reply("ok"))

            out = run_agent_loop(conversation, provider, "fake-model", registry, ctx, verbose=False)
            self.assertEqual(out.response_text, "ok")
            system_message = {"content": provider.requests[0]["conversation"].system_prompt}
            self.assertIn("## Runtime Context", system_message["content"])
            self.assertIn("## Project Instructions", system_message["content"])
            self.assertIn("Follow the CLAUDE instructions.", system_message["content"])


if __name__ == "__main__":
    unittest.main()


class TestMemoryFileNames(unittest.TestCase):
    def test_clyde_md_wins_then_claude_md_then_agents_md(self):
        import tempfile
        from unittest import mock
        from src.context_system.claude_md import load_claude_md_context

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            sub = root / "pkg"
            sub.mkdir(parents=True)
            (root / "CLYDE.md").write_text("clyde root")
            (root / "CLAUDE.md").write_text("claude root")       # same folder: CLYDE.md wins
            (sub / "AGENTS.md").write_text("agents pkg")         # only AGENTS.md here: read
            (root / "CLYDE.local.md").write_text("mine")
            (root / "CLAUDE.local.md").write_text("old mine")    # same folder: CLYDE.local.md wins
            with mock.patch.object(Path, "home", return_value=Path(tmp) / "home"):
                files = load_claude_md_context(root, cwd=sub).files
        self.assertEqual([f.content for f in files], ["agents pkg", "clyde root", "mine"])


class TestOtherHarnessFiles(unittest.TestCase):
    def test_gemini_cursor_and_copilot_files_are_read_when_nothing_else_is(self):
        import tempfile
        from unittest import mock
        from src.context_system.claude_md import load_claude_md_context

        for rel in ("GEMINI.md", ".cursorrules", ".github/copilot-instructions.md"):
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Path, "home", return_value=Path(tmp) / "home"):
                root = Path(tmp) / "repo"
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(f"notes from {rel}")
                self.assertEqual([f.content for f in load_claude_md_context(root).files], [f"notes from {rel}"], rel)


class TestWorkspaceSnapshotWalk(unittest.TestCase):
    def test_counts_skip_ignored_and_hidden_folders(self):
        import tempfile
        from pathlib import Path
        from src.context_system.workspace_snapshot import build_workspace_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("a.py", "pkg/test_b.py", "node_modules/x.py", ".venv/y.py", ".cache/z.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("")
            snap = build_workspace_snapshot(root)
        self.assertEqual((snap.python_file_count, snap.test_file_count), (2, 1))

    def test_a_spent_budget_stops_the_walk(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from src.context_system import workspace_snapshot as ws
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for d in ("one", "two", "three"):
                (root / d).mkdir()
                (root / d / "m.py").write_text("")
            with patch.object(ws, "_WALK_BUDGET_S", -1):
                snap = ws.build_workspace_snapshot(root)
        self.assertLess(snap.python_file_count, 3)
