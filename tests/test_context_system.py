from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent.conversation import Conversation
from src.context_system import build_context_prompt
from src.context_system.git_context import collect_git_context
from src.tool_system.agent_loop import run_agent_loop
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
