"""A repository's MCP server must never take over a name the user's own server already owns."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.mcp_client import McpServerTool, merge_servers, register_mcp_tools
from src.tool_system.registry import ToolRegistry


class _Client:
    def __init__(self, name):
        self.name = name
        self.tools = [{"name": "t", "inputSchema": {"type": "object"}}]
        self.called = False

    def call_tool(self, name, args):
        self.called = True
        return {"content": [{"type": "text", "text": self.name}]}


class TestCollisions(unittest.TestCase):
    def test_the_users_server_comes_first_and_wins_the_exposed_name(self):
        user, project = _Client("my.srv"), _Client("my_srv")
        registry = ToolRegistry([])
        warnings = register_mcp_tools(registry, {"my.srv": user, "my_srv": project})
        self.assertEqual(len(registry.list_specs()), 1)
        from src.tool_system.context import ToolContext
        from src.tool_system.protocol import ToolCall
        registry.dispatch(ToolCall(name="mcp__my_srv__t", input={}), ToolContext(workspace_root=Path(tempfile.mkdtemp()), auto_approve=True))
        self.assertTrue(user.called)
        self.assertFalse(project.called)
        self.assertEqual(len(warnings), 1)
        self.assertIn("my_srv", warnings[0])
        self.assertIn("my.srv", warnings[0])

    def test_merge_puts_the_users_servers_first_even_when_the_project_reuses_a_name(self):
        merged = merge_servers({"a": {"command": "user"}}, {"a": {"command": "repo"}, "b": {"command": "repo-b"}})
        self.assertEqual(list(merged), ["a", "b"])
        self.assertEqual(merged["a"], {"command": "user"})

    def test_a_project_entry_that_clashes_with_a_users_server_after_sanitising_is_never_asked_about(self):
        from rich.console import Console
        from src.repl.core import ClydeREPL

        home, repo = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()).resolve()
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"my_srv": {"command": "repo-server"}}}))
        repl = ClydeREPL.__new__(ClydeREPL)
        repl.console, repl.headless = Console(file=open(os.devnull, "w")), False

        def no_ask(*a, **k):
            raise AssertionError("must not ask about a server that cannot be used")

        with patch.object(Path, "home", return_value=home), patch("rich.prompt.Confirm.ask", no_ask):
            self.assertEqual(repl._project_mcp_servers(repo, {"my.srv"}), {})


if __name__ == "__main__":
    unittest.main()
