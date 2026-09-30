from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.tools import lsp
from src.tool_system.tools.lsp import LSPTool, encode, read_frame

# A tiny LSP server: answers initialize, definition, hover and shutdown, logs every method it sees.
_FAKE_SERVER = r'''
import json, sys
log = open(sys.argv[1], "a")
inp, out = sys.stdin.buffer, sys.stdout.buffer

def send(msg):
    body = json.dumps(msg).encode()
    out.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    out.flush()

while True:
    length = None
    while True:
        line = inp.readline()
        if not line:
            sys.exit(0)
        if not line.strip():
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
    msg = json.loads(inp.read(length))
    method = msg.get("method")
    log.write(method + "\n"); log.flush()
    if method == "initialize":
        send({"jsonrpc": "2.0", "method": "window/logMessage", "params": {"type": 3, "message": "hi"}})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})
    elif method == "textDocument/definition":
        p = msg["params"]
        send({"jsonrpc": "2.0", "id": msg["id"], "result": [{"uri": p["textDocument"]["uri"], "range": {
            "start": p["position"], "end": {"line": p["position"]["line"], "character": 9}}}]})
    elif method == "textDocument/hover":
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "boom"}})
    elif method == "workspace/symbol":  # bigger than a pipe buffer, so it arrives in pieces
        send({"jsonrpc": "2.0", "id": msg["id"], "result": [{"name": msg["params"]["query"], "pad": "x" * 300000}]})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
    elif method == "exit":
        sys.exit(0)
'''


class TestFraming(unittest.TestCase):
    def test_encode_then_read_frame_round_trips(self) -> None:
        msg = {"jsonrpc": "2.0", "id": 1, "result": {"text": "héllo"}}
        self.assertEqual(read_frame(io.BytesIO(encode(msg))), msg)

    def test_read_frame_returns_none_on_eof_or_truncated_body(self) -> None:
        self.assertIsNone(read_frame(io.BytesIO(b"")))
        self.assertIsNone(read_frame(io.BytesIO(b"Content-Length: 50\r\n\r\n{}")))


class TestLSPTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "methods.log"
        self.source = self.root / "mod.py"
        self.source.write_text("def greet():\n    return 1\n")
        self.ctx = ToolContext(workspace_root=self.root)
        self.env = patch.dict(os.environ, {"PATH": str(self.bin)})
        self.env.start()

    def tearDown(self) -> None:
        lsp.shutdown_all()
        self.env.stop()
        self.tmp.cleanup()

    def _install_fake_pylsp(self) -> None:
        script = self.root / "fake_server.py"
        script.write_text(_FAKE_SERVER)
        exe = self.bin / "pylsp"
        exe.write_text(f"#!/bin/sh\nexec {sys.executable} {script} {self.log}\n")
        exe.chmod(0o755)

    def _run(self, operation: str, line: int = 1, character: int = 5):
        return LSPTool().run({"operation": operation, "filePath": "mod.py", "line": line, "character": character}, self.ctx)

    def test_no_server_installed_names_what_to_install(self) -> None:
        out = self._run("goToDefinition")
        self.assertTrue(out.is_error)
        self.assertIn("pyright", out.output["error"])
        self.assertIn("pip install python-lsp-server", out.output["error"])

    def test_go_to_definition_through_fake_server(self) -> None:
        self._install_fake_pylsp()
        out = self._run("goToDefinition", line=1, character=5)
        self.assertFalse(out.is_error, out.output)
        loc = out.output["result"][0]
        self.assertEqual(loc["file"], "mod.py")
        self.assertEqual(loc["range"]["start"], {"line": 1, "character": 5})

        # Same server is reused, and server errors surface as tool errors.
        err = self._run("hover")
        self.assertTrue(err.is_error)
        self.assertIn("boom", err.output["error"])

        lsp.shutdown_all()
        methods = self.log.read_text().split()
        self.assertEqual(methods.count("initialize"), 1)
        self.assertEqual(methods[:3], ["initialize", "initialized", "textDocument/didOpen"])
        self.assertEqual(methods[-2:], ["shutdown", "exit"])

    def test_large_response_split_across_reads(self) -> None:
        self._install_fake_pylsp()
        out = self._run("workspaceSymbol", line=1, character=6)
        self.assertFalse(out.is_error, out.output)
        self.assertEqual(out.output["result"][0]["name"], "greet")

    def test_unanswered_request_times_out(self) -> None:
        self._install_fake_pylsp()
        with patch.object(lsp, "REQUEST_TIMEOUT", 0.2):
            out = self._run("documentSymbol")
        self.assertTrue(out.is_error)
        self.assertIn("timed out", out.output["error"])

    def test_rejects_zero_based_position(self) -> None:
        from src.tool_system.errors import ToolInputError

        with self.assertRaises(ToolInputError):
            self._run("hover", line=0)


if __name__ == "__main__":
    unittest.main()
