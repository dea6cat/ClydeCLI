"""MCP over Streamable HTTP and legacy HTTP+SSE, against local fake servers (127.0.0.1, stdlib)."""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.tool_system.mcp_client import McpHttpClient, McpSseClient, _sse_events, connect_servers, remote_spec

TOOLS = [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]


def _answer(msg: dict) -> dict | None:
    """The fake server's reply to one request (None for notifications and replies)."""
    method, rid = msg.get("method"), msg.get("id")
    if rid is None or method is None:
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                                        "serverInfo": {"name": "fake"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        text = msg["params"]["arguments"]["text"]
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "echo: " + text}]}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "nope"}}


class _Server:
    """A fake MCP server. Streamable HTTP at /mcp (or 405 there when sse_only); legacy SSE stream at
    GET /sse, whose endpoint event points at /messages; 401 at /locked."""

    def __init__(self, sse_only: bool = False):
        self.seen: list[tuple[str, dict, dict]] = []   # (path, headers, message)
        self.stream: queue.Queue = queue.Queue()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _empty(self, code: int) -> None:
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                if self.path == "/locked":
                    return self._empty(401)
                if sse_only and not self.path.startswith("/messages"):
                    return self._empty(405)
                msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, msg))
                reply = _answer(msg)
                if self.path.startswith("/messages"):        # legacy SSE: the reply goes out on the stream
                    if reply:
                        outer.stream.put(reply)
                    return self._empty(202)
                if reply is None:
                    return self._empty(202)
                self.send_response(200)
                if msg["method"] == "initialize":
                    self.send_header("Mcp-Session-Id", "s-123")
                if msg["method"] == "tools/list":            # streamed, with a server request first
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    ping = {"jsonrpc": "2.0", "id": 99, "method": "ping"}
                    self.wfile.write(f"event: message\ndata: {json.dumps(ping)}\n\n".encode())
                    self.wfile.write(f"data: {json.dumps(reply)}\n\n".encode())
                    return
                body = json.dumps(reply).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path != "/sse":
                    return self._empty(404)
                outer.seen.append((self.path, dict(self.headers), {}))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"event: endpoint\ndata: /messages?session=1\n\n")
                self.wfile.flush()
                while (msg := outer.stream.get()) is not None:
                    self.wfile.write(f"event: message\ndata: {json.dumps(msg)}\n\n".encode())
                    self.wfile.flush()

            def do_DELETE(self):
                outer.seen.append((self.path, dict(self.headers), {"deleted": True}))
                self._empty(200)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.stream.put(None)
        self.httpd.shutdown()
        self.httpd.server_close()


class TestStreamableHttp(unittest.TestCase):
    def setUp(self):
        self.server = _Server()
        self.addCleanup(self.server.stop)
        self.cwd = Path(tempfile.mkdtemp())

    def test_initializes_lists_tools_from_a_stream_and_calls_with_the_session(self):
        with patch.dict(os.environ, {"FAKE_TOKEN": "t0k"}):
            clients, errors = connect_servers({"remote": {"type": "http", "url": self.server.url + "/mcp",
                                                          "headers": {"Authorization": "Bearer ${FAKE_TOKEN}"}}}, self.cwd)
        self.assertEqual(errors, {})
        client = clients["remote"]
        self.assertIsInstance(client, McpHttpClient)
        self.assertEqual(client.list_tools(), ["echo"])
        self.assertEqual(client.call_tool("echo", {"text": "hi"})["content"][0]["text"], "echo: hi")
        posts = [(h, m) for path, h, m in self.server.seen if path == "/mcp"]
        self.assertEqual(posts[0][0].get("authorization"), "Bearer t0k")                 # ${VAR} expanded
        self.assertNotIn("mcp-session-id", posts[0][0])                                  # none before initialize
        self.assertTrue(all(h.get("mcp-session-id") == "s-123" for h, _ in posts[1:]))   # then on every POST
        self.assertTrue(all(h.get("mcp-protocol-version") == "2025-06-18" for h, _ in posts[1:]))
        self.assertIn({"jsonrpc": "2.0", "id": 99, "result": {}}, [m for _, m in posts])  # answered the server's ping
        client.close()
        self.assertTrue(any(m.get("deleted") for _, _, m in self.server.seen))           # session ended politely

    def test_an_auth_failure_reads_clearly(self):
        _, errors = connect_servers({"remote": {"type": "http", "url": self.server.url + "/locked"}}, self.cwd)
        self.assertEqual(errors["remote"], "MCP server 'remote' needs sign-in: run /mcp login remote")
        _, errors = connect_servers({"keyed": {"type": "http", "url": self.server.url + "/locked",
                                               "headers": {"Authorization": "Bearer wrong"}}}, self.cwd)
        self.assertIn("HTTP 401 (check the server's headers or token)", errors["keyed"])   # your own header: no OAuth


class TestLegacySse(unittest.TestCase):
    def test_sse_endpoint_and_replies_on_the_stream(self):
        server = _Server()
        self.addCleanup(server.stop)
        clients, errors = connect_servers({"old": {"type": "sse", "url": server.url + "/sse"}}, Path(tempfile.mkdtemp()))
        self.assertEqual(errors, {})
        self.assertIsInstance(clients["old"], McpSseClient)
        self.assertEqual(clients["old"].list_tools(), ["echo"])
        self.assertEqual(clients["old"].call_tool("echo", {"text": "yo"})["content"][0]["text"], "echo: yo")
        self.assertTrue(all(path.startswith("/messages") for path, _, m in server.seen if "method" in m))
        clients["old"].close()

    def test_a_bare_url_falls_back_to_sse_when_the_post_is_refused(self):
        server = _Server(sse_only=True)
        self.addCleanup(server.stop)
        clients, errors = connect_servers({"cursorish": {"url": server.url + "/sse"}}, Path(tempfile.mkdtemp()))
        self.assertEqual(errors, {})
        self.assertIsInstance(clients["cursorish"], McpSseClient)
        self.assertEqual(clients["cursorish"].list_tools(), ["echo"])
        clients["cursorish"].close()

    def test_an_explicit_http_server_does_not_fall_back(self):
        server = _Server(sse_only=True)
        self.addCleanup(server.stop)
        _, errors = connect_servers({"strict": {"type": "http", "url": server.url + "/sse"}}, Path(tempfile.mkdtemp()))
        self.assertIn("HTTP 405", errors["strict"])


class TestUserAgent(unittest.TestCase):
    def test_clyde_identifies_itself_unless_the_config_says_otherwise(self):
        from src.providers.base import _USER_AGENT
        from src.tool_system.mcp_client import _with_agent
        self.assertEqual(_with_agent({"Authorization": "x"}), {"User-Agent": _USER_AGENT, "Authorization": "x"})
        self.assertEqual(_with_agent({"user-agent": "mine"}), {"user-agent": "mine"})


class TestConfig(unittest.TestCase):
    def test_remote_spec_reads_each_agents_format(self):
        self.assertEqual(remote_spec({"type": "http", "url": "https://a/mcp"})[0], "http")
        self.assertEqual(remote_spec({"type": "sse", "url": "https://a/sse"})[0], "sse")
        self.assertEqual(remote_spec({"httpUrl": "https://a/mcp"})[0], "http")      # Gemini CLI
        self.assertEqual(remote_spec({"url": "https://a/mcp"})[0], "auto")          # Cursor
        self.assertIsNone(remote_spec({"command": "npx"}))

    def test_sse_parser_joins_data_lines_and_names_events(self):
        events = list(_sse_events(["event: endpoint", "data: /m", "", "data: {\"a\":", "data: 1}", ""]))
        self.assertEqual(events, [("endpoint", "/m"), ("message", "{\"a\":\n1}")])


if __name__ == "__main__":
    unittest.main()
