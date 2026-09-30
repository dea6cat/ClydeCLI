"""LSP tool: a stdlib JSON-RPC-over-stdio client for language servers found on PATH.

One server per (command, workspace) is started lazily and kept alive for the session;
all of them are shut down at exit.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec

INIT_TIMEOUT = 30.0
REQUEST_TIMEOUT = 30.0

# ext -> ordered (binary, argv, languageId) candidates; the first one on PATH wins.
_PY = [("pyright-langserver", ["pyright-langserver", "--stdio"], "python"), ("pylsp", ["pylsp"], "python")]
_TS = ("typescript-language-server", ["typescript-language-server", "--stdio"])
_SERVERS: dict[str, list[tuple[str, list[str], str]]] = {
    ".py": _PY,
    ".pyi": _PY,
    ".ts": [(*_TS, "typescript")],
    ".tsx": [(*_TS, "typescriptreact")],
    ".js": [(*_TS, "javascript")],
    ".jsx": [(*_TS, "javascriptreact")],
    ".mjs": [(*_TS, "javascript")],
    ".cjs": [(*_TS, "javascript")],
    ".go": [("gopls", ["gopls"], "go")],
    ".rs": [("rust-analyzer", ["rust-analyzer"], "rust")],
    ".dart": [("dart", ["dart", "language-server"], "dart")],
    ".c": [("clangd", ["clangd"], "c")],
    ".h": [("clangd", ["clangd"], "c")],
    ".cc": [("clangd", ["clangd"], "cpp")],
    ".cpp": [("clangd", ["clangd"], "cpp")],
    ".hpp": [("clangd", ["clangd"], "cpp")],
}
_INSTALL_HINTS = {
    "pyright-langserver": "npm install -g pyright",
    "pylsp": "pip install python-lsp-server",
    "typescript-language-server": "npm install -g typescript-language-server typescript",
    "gopls": "go install golang.org/x/tools/gopls@latest",
    "rust-analyzer": "rustup component add rust-analyzer",
    "dart": "install the Dart or Flutter SDK",
    "clangd": "install clangd (LLVM)",
}

# operation -> LSP method; None means handled specially in _run_operation.
_OPERATIONS = {
    "goToDefinition": "textDocument/definition",
    "findReferences": "textDocument/references",
    "hover": "textDocument/hover",
    "documentSymbol": "textDocument/documentSymbol",
    "workspaceSymbol": "workspace/symbol",
    "goToImplementation": "textDocument/implementation",
    "prepareCallHierarchy": "textDocument/prepareCallHierarchy",
    "incomingCalls": None,
    "outgoingCalls": None,
}


class LSPError(Exception):
    pass


def encode(msg: dict) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def read_frame(stream) -> dict | None:
    """Read one Content-Length-framed JSON-RPC message; None on EOF or a malformed frame."""
    length = None
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1])
            except ValueError:
                return None
    if length is None:
        return None
    body = stream.read(length)
    if len(body) < length:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _message(method: str, params: dict | None, rid: int | None = None) -> dict:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        msg["id"] = rid
    if params is not None:  # shutdown/exit take no params
        msg["params"] = params
    return msg


class LSPServer:
    def __init__(self, argv: list[str], root: Path, language_id: str) -> None:
        self.language_id = language_id
        self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, cwd=root)
        self._wlock = threading.Lock()
        self._id = 0
        self._waiting: dict[int, tuple[threading.Event, list[dict]]] = {}
        self._documents: dict[str, tuple[int, str]] = {}  # uri -> (version, text)
        self.closed = False
        threading.Thread(target=self._read_loop, daemon=True).start()
        try:
            self.request("initialize", {
                "processId": os.getpid(),
                "rootUri": root.as_uri(),
                "workspaceFolders": [{"uri": root.as_uri(), "name": root.name or "root"}],
                "capabilities": {"textDocument": {
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "definition": {"linkSupport": True},
                }},
            }, INIT_TIMEOUT)
        except LSPError:
            self.close()
            raise
        self.notify("initialized", {})

    def _write(self, msg: dict) -> None:
        with self._wlock:
            try:
                self._proc.stdin.write(encode(msg))
                self._proc.stdin.flush()
            except (OSError, ValueError):
                self.closed = True

    def _read_loop(self) -> None:
        while True:
            msg = read_frame(self._proc.stdout)
            if msg is None:
                break
            mid = msg.get("id")
            if mid is None:
                continue  # notifications (diagnostics, progress) are ignored
            if "method" in msg:  # server -> client request; answer so the server doesn't block
                items = (msg.get("params") or {}).get("items")
                result = [None] * len(items) if msg["method"] == "workspace/configuration" and isinstance(items, list) else None
                self._write({"jsonrpc": "2.0", "id": mid, "result": result})
                continue
            waiter = self._waiting.get(mid)
            if waiter is not None:
                waiter[1].append(msg)
                waiter[0].set()
        self.closed = True
        for event, _ in list(self._waiting.values()):
            event.set()

    def request(self, method: str, params: dict | None, timeout: float | None = None) -> Any:
        timeout = REQUEST_TIMEOUT if timeout is None else timeout
        if self.closed:
            raise LSPError("language server has exited")
        with self._wlock:
            self._id += 1
            rid = self._id
        event, box = threading.Event(), []
        self._waiting[rid] = (event, box)
        try:
            self._write(_message(method, params, rid))
            if not event.wait(timeout):
                raise LSPError(f"{method} timed out after {timeout:g}s")
        finally:
            self._waiting.pop(rid, None)
        if not box:
            raise LSPError("language server has exited")
        if "error" in box[0]:
            raise LSPError(f"{method} failed: {box[0]['error'].get('message', box[0]['error'])}")
        return box[0].get("result")

    def notify(self, method: str, params: dict | None) -> None:
        self._write(_message(method, params))

    def sync(self, path: Path) -> str:
        """Open the file in the server (or push its new text if it changed); returns its URI."""
        uri = path.as_uri()
        text = path.read_text(encoding="utf-8", errors="replace")
        known = self._documents.get(uri)
        if known is None:
            self.notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": self.language_id, "version": 1, "text": text}})
            self._documents[uri] = (1, text)
        elif known[1] != text:
            version = known[0] + 1
            self.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": version},
                                                   "contentChanges": [{"text": text}]})
            self._documents[uri] = (version, text)
        return uri

    def close(self) -> None:
        if not self.closed:
            try:
                self.request("shutdown", None, 2.0)
            except LSPError:
                pass
            self.notify("exit", None)
        self.closed = True
        try:
            self._proc.wait(2.0)
        except subprocess.TimeoutExpired:
            self._proc.kill()


_ACTIVE: dict[tuple[tuple[str, ...], Path], LSPServer] = {}
_ACTIVE_LOCK = threading.Lock()


def shutdown_all() -> None:
    with _ACTIVE_LOCK:
        servers = list(_ACTIVE.values())
        _ACTIVE.clear()
    for server in servers:
        server.close()


atexit.register(shutdown_all)


def server_for(path: Path, root: Path) -> LSPServer:
    """The running server for this file's language in `root`, starting it if needed."""
    candidates = _SERVERS.get(path.suffix.lower())
    if not candidates:
        raise LSPError(f"no language server is known for {path.suffix or 'extensionless'} files")
    found = next(((argv, lang) for binary, argv, lang in candidates if shutil.which(binary)), None)
    if found is None:
        hints = " or ".join(f"{b} ({_INSTALL_HINTS[b]})" for b, _, _ in candidates)
        raise LSPError(f"no language server for {path.suffix} files found on PATH; install {hints}")
    argv, lang = found
    key = (tuple(argv), root)
    with _ACTIVE_LOCK:
        server = _ACTIVE.get(key)
        if server is None or server.closed:
            try:
                server = LSPServer(argv, root, lang)
            except OSError as exc:
                raise LSPError(f"could not start {argv[0]}: {exc}") from exc
            _ACTIVE[key] = server
        return server


def _word_at(text: str, line: int, character: int) -> str:
    lines = text.splitlines()
    if line >= len(lines):
        return ""
    for match in re.finditer(r"\w+", lines[line]):
        if match.start() <= character <= match.end():
            return match.group()
    return ""


def _readable(value: Any, root: Path) -> Any:
    """Make an LSP result model-friendly: file URIs -> workspace-relative paths, positions -> 1-based."""
    if isinstance(value, list):
        return [_readable(v, root) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"line", "character"} and all(isinstance(v, int) for v in value.values()):
        return {"line": value["line"] + 1, "character": value["character"] + 1}
    out = {}
    for key, v in value.items():
        if key in ("uri", "targetUri") and isinstance(v, str) and v.startswith("file:"):
            p = Path(unquote(urlparse(v).path))
            out["file"] = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        else:
            out[key] = _readable(v, root)
    return out


def _run_operation(server: LSPServer, operation: str, path: Path, line: int, character: int) -> Any:
    uri = server.sync(path)
    doc = {"textDocument": {"uri": uri}}
    pos = {**doc, "position": {"line": line, "character": character}}
    if operation == "documentSymbol":
        return server.request("textDocument/documentSymbol", doc)
    if operation == "workspaceSymbol":
        return server.request("workspace/symbol", {"query": _word_at(server._documents[uri][1], line, character)})
    if operation == "findReferences":
        return server.request("textDocument/references", {**pos, "context": {"includeDeclaration": True}})
    if operation in ("incomingCalls", "outgoingCalls"):
        items = server.request("textDocument/prepareCallHierarchy", pos) or []
        return [call for item in items for call in server.request(f"callHierarchy/{operation}", {"item": item}) or []]
    return server.request(_OPERATIONS[operation], pos)


class LSPTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="LSP",
            description=(
                "Query a language server for code intelligence: goToDefinition, findReferences, hover, "
                "documentSymbol, workspaceSymbol, goToImplementation, prepareCallHierarchy, incomingCalls, "
                "outgoingCalls. line and character are 1-based. The server is picked by file extension."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "operation": {"type": "string", "enum": list(_OPERATIONS)},
                    "filePath": {"type": "string"},
                    "line": {"type": "integer", "minimum": 1},
                    "character": {"type": "integer", "minimum": 1},
                },
                "required": ["operation", "filePath", "line", "character"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        operation = tool_input.get("operation")
        file_path = tool_input.get("filePath")
        line, character = tool_input.get("line"), tool_input.get("character")
        if operation not in _OPERATIONS:
            raise ToolInputError(f"operation must be one of: {', '.join(_OPERATIONS)}")
        if not isinstance(file_path, str) or not file_path:
            raise ToolInputError("filePath must be a non-empty string")
        if not isinstance(line, int) or line < 1 or not isinstance(character, int) or character < 1:
            raise ToolInputError("line and character must be integers >= 1")

        path = context.ensure_allowed_path(file_path)
        if not path.is_file():
            return ToolResult(name="LSP", output={"error": f"file not found: {file_path}"}, is_error=True)
        try:
            server = server_for(path, context.workspace_root)
            result = _run_operation(server, operation, path, line - 1, character - 1)
        except LSPError as exc:
            return ToolResult(name="LSP", output={"error": str(exc)}, is_error=True)
        return ToolResult(name="LSP", output={"operation": operation, "result": _readable(result, context.workspace_root)})
