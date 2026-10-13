"""A deny written for mcp__<server>__<tool> must also stop the generic MCP tool and the resource tools for that server."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolPermissionError
from src.tool_system.mcp_client import McpServerTool
from src.tool_system.permissions import ToolPermissionContext
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.mcp import MCPTool
from src.tool_system.tools.mcp_resources import ListMcpResourcesTool, ReadMcpResourceTool


class _Client:
    name = "my.srv"   # sanitised to my_srv in the exposed name

    def __init__(self):
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append(name)
        return {"content": [{"type": "text", "text": "ok"}]}

    def read_resource(self, uri):
        self.calls.append(uri)
        return {"text": "x"}

    def list_resources(self):
        return []


class TestMcpDeny(unittest.TestCase):
    def setUp(self):
        self.client = _Client()
        root = Path(tempfile.mkdtemp()).resolve()
        self.ctx = ToolContext(workspace_root=root, mcp_clients={"my.srv": self.client}, auto_approve=True)
        self.tool = McpServerTool(self.client, {"name": "dangerous", "inputSchema": {"type": "object"}})
        self.registry = ToolRegistry([self.tool, MCPTool(), ReadMcpResourceTool(), ListMcpResourcesTool()])

    def _dispatch(self, name, args):
        try:
            return self.registry.dispatch(ToolCall(name=name, input=args), self.ctx)
        except ToolPermissionError as exc:
            return exc

    def _ran(self):
        return bool(self.client.calls)

    def test_a_rule_deny_on_the_exposed_name_also_blocks_the_generic_tool(self):
        self.ctx.permission_rules = {"allow": [], "deny": ["mcp__my_srv__dangerous"]}
        self._dispatch("mcp__my_srv__dangerous", {})
        self._dispatch("MCP", {"server": "my.srv", "tool": "dangerous", "input": {}})
        self.assertFalse(self._ran())

    def test_a_deny_name_on_the_exposed_name_also_blocks_the_generic_tool(self):
        self.ctx.permission_context = ToolPermissionContext.from_iterables(deny_names=["mcp__my_srv__dangerous"])
        self._dispatch("MCP", {"server": "my.srv", "tool": "dangerous", "input": {}})
        self.assertFalse(self._ran())

    def test_a_different_tool_is_not_affected(self):
        self.ctx.permission_rules = {"allow": [], "deny": ["mcp__my_srv__dangerous"]}
        self._dispatch("MCP", {"server": "my.srv", "tool": "harmless", "input": {}})
        self.assertEqual(self.client.calls, ["harmless"])

    def test_a_server_wide_deny_prefix_blocks_resource_tools_for_that_server(self):
        self.ctx.permission_context = ToolPermissionContext.from_iterables(deny_prefixes=["mcp__my_srv__"])
        self._dispatch("ReadMcpResourceTool", {"server": "my.srv", "uri": "https://x/y"})
        self.assertFalse(self._ran())


if __name__ == "__main__":
    unittest.main()
