"""MCP stdio client against a tiny fake server (no network, no SDK)."""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.mcp_client import McpServerTool, connect_servers, find_foreign_servers, import_servers, load_servers
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools import ListMcpResourcesTool, ReadMcpResourceTool

FAKE_SERVER = textwrap.dedent('''
    import json, sys
    def send(msg):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\\n"); sys.stdout.flush()
    print("server log line on stdout", flush=True)
    for line in sys.stdin:
        msg = json.loads(line)
        method, rid = msg.get("method"), msg.get("id")
        if rid is None:
            continue
        if method == "initialize":
            send({"id": 99, "method": "ping"})  # a server-to-client request mid-handshake
            send({"id": rid, "result": {"protocolVersion": "2025-06-18",
                  "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "fake"}}})
        elif method == "tools/list":
            if not msg["params"].get("cursor"):
                send({"id": rid, "result": {"tools": [{"name": "echo", "description": "Echo text",
                      "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                      "annotations": {"readOnlyHint": True}}], "nextCursor": "p2"}})
            else:
                send({"id": rid, "result": {"tools": [{"name": "fail", "inputSchema": {"type": "object"}}]}})
        elif method == "tools/call":
            args = msg["params"]["arguments"]
            if msg["params"]["name"] == "fail":
                send({"id": rid, "result": {"content": [{"type": "text", "text": "it broke"}], "isError": True}})
            else:
                send({"id": rid, "result": {"content": [{"type": "text", "text": "echo: " + args["text"]}]}})
        elif method == "resources/list":
            send({"id": rid, "result": {"resources": [{"uri": "mem://a", "name": "a"}]}})
        elif method == "resources/read":
            send({"id": rid, "result": {"contents": [{"uri": msg["params"]["uri"], "text": "hello"}]}})
        else:
            send({"id": rid, "error": {"code": -32601, "message": "nope"}})
''')


class TestMcpClient(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        script = self.root / "server.py"
        script.write_text(FAKE_SERVER)
        self.clients, self.errors = connect_servers(
            {"fake": {"command": sys.executable, "args": [str(script)]},
             "remote": {"type": "websocket"},
             "missing": {"command": str(self.root / "no-such-binary")}},
            self.root,
        )
        self.ctx = ToolContext(workspace_root=self.root, mcp_clients=self.clients)
        self.registry = ToolRegistry([McpServerTool(self.clients["fake"], t) for t in self.clients["fake"].tools])

    def tearDown(self) -> None:
        for client in self.clients.values():
            client.close()
        self.tmp.cleanup()

    def test_connects_lists_every_page_and_reports_failures(self) -> None:
        self.assertEqual(self.clients["fake"].list_tools(), ["echo", "fail"])
        self.assertEqual(set(self.errors), {"remote", "missing"})
        self.assertIn("needs a `command` (stdio) or a `url`", self.errors["remote"])

    def test_tool_call_through_the_registry(self) -> None:
        spec = self.registry.get("mcp__fake__echo").spec()
        self.assertTrue(spec.is_read_only)
        out = self.registry.dispatch(ToolCall(name="mcp__fake__echo", input={"text": "hi"}), self.ctx)
        self.assertFalse(out.is_error)
        self.assertEqual(out.output, "echo: hi")

    def test_server_side_error_is_a_tool_error(self) -> None:
        out = self.registry.dispatch(ToolCall(name="mcp__fake__fail", input={}), self.ctx)
        self.assertTrue(out.is_error)
        self.assertEqual(out.output, "it broke")

    def test_input_is_checked_against_the_server_schema(self) -> None:
        from src.tool_system.errors import ToolInputError

        with self.assertRaises(ToolInputError):
            self.registry.dispatch(ToolCall(name="mcp__fake__echo", input={}), self.ctx)

    def test_resources_via_the_builtin_tools(self) -> None:
        listed = ListMcpResourcesTool().run({}, self.ctx).output
        self.assertEqual([(r["server"], r["uri"]) for r in listed], [("fake", "mem://a")])
        read = ReadMcpResourceTool().run({"server": "fake", "uri": "mem://a"}, self.ctx).output
        self.assertEqual(read["contents"][0]["text"], "hello")

    def test_calls_after_the_server_exits_fail_cleanly(self) -> None:
        self.clients["fake"].close()
        out = self.registry.dispatch(ToolCall(name="mcp__fake__echo", input={"text": "x"}), self.ctx)
        self.assertTrue(out.is_error)
        self.assertIn("not running", out.output["error"])

    def test_load_servers(self) -> None:
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"a": {"command": "x"}, "bad": 3}}))
        self.assertEqual(load_servers(settings), {"a": {"command": "x"}})
        self.assertEqual(load_servers(self.root / "missing.json"), {})



class TestMcpImport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_finds_stdio_servers_in_json_and_toml(self) -> None:
        claude = self.root / ".claude.json"
        claude.write_text(json.dumps({"mcpServers": {"gh": {"command": "npx", "args": ["gh"], "env": {"T": "secret"}},
                                                     "web": {"type": "http", "url": "https://x"}}}))
        codex = self.root / "config.toml"
        codex.write_text('[mcp_servers.docs]\ncommand = "docs-mcp"\nargs = ["--stdio"]\n')
        found = find_foreign_servers((("Claude Code", claude, "mcpServers"), ("Codex", codex, "mcp_servers"),
                                      ("Cursor", self.root / "missing.json", "mcpServers")))
        self.assertEqual([(agent, list(servers)) for agent, _, servers in found], [("Claude Code", ["gh", "web"]), ("Codex", ["docs"])])

    def test_import_keeps_existing_names_and_protects_the_file(self) -> None:
        dest = self.root / "settings.json"
        dest.write_text(json.dumps({"hooks": {}, "mcpServers": {"gh": {"command": "mine"}}}))
        added = import_servers({"gh": {"command": "theirs"}, "docs": {"command": "docs-mcp"}}, dest)
        self.assertEqual(added, ["docs"])
        data = json.loads(dest.read_text())
        self.assertEqual(data["mcpServers"]["gh"]["command"], "mine")
        self.assertEqual(data["hooks"], {})
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(import_servers({"docs": {"command": "x"}}, dest), [])


if __name__ == "__main__":
    unittest.main()
