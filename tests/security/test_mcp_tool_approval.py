"""MCP tool calls and resource reads ask before they run, as the README says hold mode does for anything that changes things."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.mcp_client import McpServerTool
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.mcp import MCPTool
from src.tool_system.tools.mcp_resources import ReadMcpResourceTool


class _Client:
    name = "srv"

    def __init__(self):
        self.calls: list[tuple] = []

    def call_tool(self, name, args):
        self.calls.append(("tool", name, args))
        return {"content": [{"type": "text", "text": "ok"}]}

    def read_resource(self, uri):
        self.calls.append(("resource", uri))
        return {"text": "data"}


class TestMcpApproval(unittest.TestCase):
    def setUp(self):
        self.client = _Client()
        self.ctx = ToolContext(workspace_root=Path(tempfile.mkdtemp()).resolve(), mcp_clients={"srv": self.client})
        self.asked: list[tuple[str, str]] = []

        def handler(tool_name, message, suggestion):
            self.asked.append((tool_name, message))
            return self.answer, False

        self.answer = True
        self.ctx.permission_handler = handler
        self.writer = McpServerTool(self.client, {"name": "write_file", "inputSchema": {"type": "object"}})
        self.reader = McpServerTool(self.client, {"name": "read_thing", "annotations": {"readOnlyHint": True}, "inputSchema": {"type": "object"}})
        self.registry = ToolRegistry([self.writer, self.reader, MCPTool(), ReadMcpResourceTool()])

    def _dispatch(self, name, args):
        return self.registry.dispatch(ToolCall(name=name, input=args), self.ctx)

    def test_a_tool_that_is_not_read_only_asks_and_a_no_stops_it(self):
        self.answer = False
        result = self._dispatch("mcp__srv__write_file", {"path": "x"})
        self.assertTrue(result.is_error)
        self.assertEqual(len(self.asked), 1)
        self.assertIn("write_file", self.asked[0][1])
        self.assertIn("srv", self.asked[0][1])
        self.assertEqual(self.client.calls, [])

    def test_a_yes_lets_it_run(self):
        self.assertFalse(self._dispatch("mcp__srv__write_file", {"path": "x"}).is_error)
        self.assertEqual(self.client.calls[0][:2], ("tool", "write_file"))

    def test_a_read_only_annotated_tool_does_not_ask(self):
        self.assertFalse(self._dispatch("mcp__srv__read_thing", {}).is_error)
        self.assertEqual(self.asked, [])

    def test_the_generic_mcp_tool_always_asks(self):
        self._dispatch("MCP", {"server": "srv", "tool": "anything", "input": {}})
        self.assertEqual([a[0] for a in self.asked], ["MCP"])

    def test_reading_a_file_or_secret_resource_asks_but_an_ordinary_one_does_not(self):
        self._dispatch("ReadMcpResourceTool", {"server": "srv", "uri": "https://example.com/doc"})
        self.assertEqual(self.asked, [])
        self._dispatch("ReadMcpResourceTool", {"server": "srv", "uri": "file:///etc/hosts"})
        self._dispatch("ReadMcpResourceTool", {"server": "srv", "uri": "file:///home/u/.ssh/id_rsa"})
        self.assertEqual(len(self.asked), 2)

    def test_with_no_one_to_ask_nothing_runs(self):
        self.ctx.permission_handler = None
        self.assertTrue(self._dispatch("mcp__srv__write_file", {}).is_error)
        self.assertEqual(self.client.calls, [])


if __name__ == "__main__":
    unittest.main()
