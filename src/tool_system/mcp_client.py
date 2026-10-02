"""MCP (Model Context Protocol) client, stdlib only, over three transports.

Servers come from `mcpServers` in ~/.clyde/settings.json, in Claude Code's format:
    {"mcpServers": {
        "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                   "env": {"GITHUB_TOKEN": "..."}},                                   # stdio
        "linear": {"type": "http", "url": "https://mcp.linear.app/mcp",
                   "headers": {"Authorization": "Bearer ${LINEAR_TOKEN}"}},           # Streamable HTTP
        "legacy": {"type": "sse", "url": "https://example.com/sse"}}}                 # HTTP+SSE (2024-11-05)

stdio messages are newline-delimited JSON-RPC 2.0. Streamable HTTP POSTs each message and reads the
reply as JSON or an SSE stream, keeping the Mcp-Session-Id the server hands out. Legacy SSE holds a
GET stream open, POSTs to the endpoint its first event names, and reads replies off the stream. A
`url` with no `type` (Cursor's form) tries Streamable HTTP and falls back to SSE, as the spec advises;
Gemini CLI's `httpUrl` means Streamable HTTP. `${VAR}` in a url or header comes from the environment.
Remote servers authenticate with headers; OAuth sign-in is not supported.

Each server's tools are registered as `mcp__<server>__<tool>`; resources are reachable through
ListMcpResourcesTool / ReadMcpResourceTool.
"""

from __future__ import annotations

import atexit
import itertools
import json
import os
import re
import socket
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from .protocol import ToolResult
from .registry import ToolSpec

PROTOCOL_VERSION = "2025-06-18"
CONNECT_TIMEOUT = 30
CALL_TIMEOUT = 120
_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


class McpError(Exception):
    pass


def load_servers(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """`mcpServers` from the user settings file; {} when missing or unreadable."""
    path = path or Path.home() / ".clyde" / "settings.json"
    try:
        servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return {k: v for k, v in servers.items() if isinstance(v, dict)} if isinstance(servers, dict) else {}


class McpClient:
    """The protocol over any transport; requests may come from any thread. A transport implements
    `_send` and feeds every message it receives to `_receive`."""

    def __init__(self, name: str, cwd: Path | None = None) -> None:
        self.name = name
        self._ids = itertools.count(1)
        self._pending: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self._roots = [{"uri": Path(cwd or Path.cwd()).resolve().as_uri(), "name": "workspace"}]
        self.server_info: dict[str, Any] = {}
        self.tools: list[dict[str, Any]] = []

    def _send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def _receive(self, msg: Any) -> None:
        """One message from the server: a request to answer, or the reply a caller waits for."""
        if not isinstance(msg, dict):
            return
        if "method" in msg and "id" in msg:
            self._answer_server_request(msg)
        elif "id" in msg and msg["id"] in self._pending:
            event, box = self._pending[msg["id"]]
            box.update(msg)
            event.set()

    def _fail_pending(self, reason: str) -> None:
        for event, box in list(self._pending.values()):
            box.setdefault("error", {"message": reason})
            event.set()

    def _answer_server_request(self, msg: dict[str, Any]) -> None:
        if msg["method"] == "ping":
            reply: dict[str, Any] = {"result": {}}
        elif msg["method"] == "roots/list":
            reply = {"result": {"roots": self._roots}}
        else:
            reply = {"error": {"code": -32601, "message": f"method not supported: {msg['method']}"}}
        try:
            self._send({"id": msg["id"], **reply})
        except McpError:
            pass

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = CALL_TIMEOUT) -> Any:
        rid = next(self._ids)
        event, box = threading.Event(), {}
        self._pending[rid] = (event, box)
        try:
            self._send({"id": rid, "method": method, "params": params or {}})
            if not event.wait(timeout):
                raise McpError(f"MCP server '{self.name}' timed out on {method}")
        finally:
            self._pending.pop(rid, None)
        if "error" in box:
            raise McpError(str(box["error"].get("message", box["error"])))
        return box.get("result")

    # --- protocol --------------------------------------------------------
    def initialize(self, timeout: float = CONNECT_TIMEOUT) -> None:
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"roots": {"listChanged": False}},
            "clientInfo": {"name": "clyde-cli", "version": "0.1.0"},
        }, timeout)
        self.server_info = result or {}
        self._send({"method": "notifications/initialized"})
        if "tools" in self.server_info.get("capabilities", {}):
            self.tools = self._list("tools/list", "tools", timeout)

    def _list(self, method: str, key: str, timeout: float = CALL_TIMEOUT) -> list[dict[str, Any]]:
        items, cursor = [], None
        while True:
            page = self.request(method, {"cursor": cursor} if cursor else {}, timeout) or {}
            items += page.get(key) or []
            cursor = page.get("nextCursor")
            if not cursor:
                return items

    def list_tools(self) -> list[str]:
        return [t["name"] for t in self.tools]

    def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": tool_name, "arguments": args}) or {}

    def list_resources(self) -> list[dict[str, Any]]:
        if "resources" not in self.server_info.get("capabilities", {}):
            return []
        return self._list("resources/list", "resources")

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self.request("resources/read", {"uri": uri}) or {}


class McpStdioClient(McpClient):
    """One running server process, newline-delimited JSON-RPC over its stdin and stdout."""

    def __init__(self, name: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
        super().__init__(name, cwd)
        self._proc = subprocess.Popen(
            [command, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, **(env or {})}, cwd=cwd, text=True, encoding="utf-8", bufsize=1,
        )
        self._write_lock = threading.Lock()
        threading.Thread(target=self._read_loop, daemon=True, name=f"mcp-{name}").start()

    def _send(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            if self._proc.stdin is None or self._proc.poll() is not None:
                raise McpError(f"MCP server '{self.name}' is not running")
            self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            self._proc.stdin.flush()

    def _read_loop(self) -> None:
        for line in self._proc.stdout or ():
            try:
                self._receive(json.loads(line))
            except ValueError:
                continue  # servers sometimes log to stdout
        self._fail_pending(f"MCP server '{self.name}' exited")   # process exited: wake every waiter

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()  # the spec's stdio shutdown: close input, then terminate
                self._proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()


def _sse_events(lines: Any) -> Iterator[tuple[str, str]]:
    """(event, data) pairs from a text/event-stream, read line by line."""
    event, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n") if isinstance(raw, bytes) else raw.rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, "\n".join(data)


def _http_error(name: str, e: Exception) -> McpError:
    if isinstance(e, urllib.error.HTTPError):
        body = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
        hint = " (check the server's headers or token)" if e.code in (401, 403) else ""
        return McpError(f"MCP server '{name}' answered HTTP {e.code}{hint}: {body}".rstrip(": "))
    reason = getattr(e, "reason", e)
    return McpError(f"MCP server '{name}' unreachable: {reason}")


class McpHttpClient(McpClient):
    """Streamable HTTP: each message is a POST; a request's reply comes back as JSON or as an SSE
    stream that may carry server requests first. The server's session id rides on every later POST."""

    def __init__(self, name: str, url: str, headers: dict[str, str] | None = None, cwd: Path | None = None) -> None:
        super().__init__(name, cwd)
        self.url, self._headers = url, dict(headers or {})
        self._session: str | None = None

    def _send(self, message: dict[str, Any]) -> None:
        headers = {**self._headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        if message.get("method") != "initialize":
            headers["MCP-Protocol-Version"] = self.server_info.get("protocolVersion", PROTOCOL_VERSION)
        body = json.dumps({"jsonrpc": "2.0", **message}).encode()
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=CALL_TIMEOUT)
        except (urllib.error.URLError, OSError) as e:
            raise _http_error(self.name, e) from e
        with resp:
            self._session = resp.headers.get("Mcp-Session-Id") or self._session
            if resp.status == 202 or "id" not in message or "method" not in message:
                return   # a notification or a reply to the server: accepted, nothing comes back
            if "text/event-stream" in (resp.headers.get("Content-Type") or ""):
                for _event, data in _sse_events(resp):
                    try:
                        msg = json.loads(data)
                    except ValueError:
                        continue
                    self._receive(msg)
                    if isinstance(msg, dict) and msg.get("id") == message["id"] and "method" not in msg:
                        return   # our reply: stop reading, the server may hold the stream open
            else:
                payload = json.loads(resp.read() or b"null")
                for msg in payload if isinstance(payload, list) else [payload]:
                    self._receive(msg)

    def close(self) -> None:
        if not self._session:
            return
        try:   # the spec's polite end of a session; servers may answer 405
            urllib.request.urlopen(urllib.request.Request(self.url, headers={**self._headers, "Mcp-Session-Id": self._session},
                                                          method="DELETE"), timeout=5).close()
        except (urllib.error.URLError, OSError):
            pass


class McpSseClient(McpClient):
    """HTTP+SSE (protocol 2024-11-05): a GET stream stays open; its first `endpoint` event names the
    URL to POST messages to, and replies arrive on the stream."""

    def __init__(self, name: str, url: str, headers: dict[str, str] | None = None, cwd: Path | None = None) -> None:
        super().__init__(name, cwd)
        self.url, self._headers = url, dict(headers or {})
        self._endpoint: str | None = None
        self._ready = threading.Event()
        self._error: McpError | None = None
        self._stream: Any = None
        threading.Thread(target=self._read_loop, daemon=True, name=f"mcp-sse-{name}").start()
        if not self._ready.wait(CONNECT_TIMEOUT):
            raise McpError(f"MCP server '{name}' sent no endpoint over SSE")
        if self._error:
            raise self._error

    def _read_loop(self) -> None:
        req = urllib.request.Request(self.url, headers={**self._headers, "Accept": "text/event-stream"})
        try:
            self._stream = urllib.request.urlopen(req, timeout=None)
            for event, data in _sse_events(self._stream):
                if event == "endpoint":
                    self._endpoint = urllib.parse.urljoin(self.url, data.strip())
                    self._ready.set()
                elif event == "message":
                    try:
                        self._receive(json.loads(data))
                    except ValueError:
                        continue
        except (urllib.error.URLError, OSError, ValueError) as e:
            self._error = _http_error(self.name, e)
        self._ready.set()
        self._fail_pending(f"MCP server '{self.name}' closed its SSE stream")

    def _send(self, message: dict[str, Any]) -> None:
        if not self._endpoint:
            raise self._error or McpError(f"MCP server '{self.name}' is not connected")
        req = urllib.request.Request(self._endpoint, data=json.dumps({"jsonrpc": "2.0", **message}).encode(),
                                     headers={**self._headers, "Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=CALL_TIMEOUT).close()
        except (urllib.error.URLError, OSError) as e:
            raise _http_error(self.name, e) from e

    def close(self) -> None:
        # Closing the response while the reader thread is blocked in readline deadlocks on the
        # buffer's lock; shutting the socket down makes that read return, and the thread exits.
        # ponytail: reaches urllib's private socket (resp.fp.raw._sock); own an http.client connection if that moves.
        sock = getattr(getattr(getattr(self._stream, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _expand(value: Any) -> str:
    """${VAR} and $VAR from the environment, so tokens can stay out of the settings file."""
    return os.path.expandvars(str(value))


def remote_spec(cfg: dict[str, Any]) -> tuple[str, str, dict[str, str]] | None:
    """(transport, url, headers) for a remote server config, or None for a stdio one. transport is
    http, sse, or auto (a bare `url`: try http, fall back to sse)."""
    kind = str(cfg.get("type") or "").lower()
    url = cfg.get("httpUrl") or cfg.get("url") or cfg.get("serverUrl")
    if not url:
        return None
    transport = ("http" if kind in ("http", "streamable-http", "streamable_http") or cfg.get("httpUrl")
                 else "sse" if kind == "sse" else "auto")
    headers = {str(k): _expand(v) for k, v in (cfg.get("headers") or {}).items()}
    return transport, _expand(url), headers


def _connect_remote(name: str, transport: str, url: str, headers: dict[str, str], cwd: Path) -> McpClient:
    if transport in ("http", "auto"):
        client: McpClient = McpHttpClient(name, url, headers, cwd)
        try:
            client.initialize()
            return client
        except McpError as e:
            # The spec's fallback: an old server rejects the POST with 4xx; then try HTTP+SSE.
            if transport == "http" or not re.search(r"HTTP 4\d\d", str(e)):
                raise
    client = McpSseClient(name, url, headers, cwd)
    try:
        client.initialize()
    except McpError:
        client.close()
        raise
    return client


def flatten_content(result: dict[str, Any]) -> str:
    """The text of a tools/call result; non-text blocks are summarized."""
    parts = []
    for block in result.get("content") or []:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "resource":
            parts.append(block.get("resource", {}).get("text") or f"[resource {block.get('resource', {}).get('uri', '')}]")
        else:
            parts.append(f"[{block.get('type', 'content')} {block.get('mimeType', '')}]".strip())
    if not parts and "structuredContent" in result:
        parts.append(json.dumps(result["structuredContent"]))
    return "\n".join(p for p in parts if p) or "(no output)"


class McpServerTool:
    """One MCP server tool, exposed to the model as mcp__<server>__<tool>."""

    def __init__(self, client: McpClient, tool: dict[str, Any]) -> None:
        self._client = client
        self._tool = tool
        self._name = f"mcp__{_NAME_RE.sub('_', client.name)}__{_NAME_RE.sub('_', tool['name'])}"

    def spec(self) -> ToolSpec:
        schema = self._tool.get("inputSchema") or {"type": "object", "properties": {}}
        annotations = self._tool.get("annotations") or {}
        return ToolSpec(
            name=self._name,
            description=(self._tool.get("description") or f"{self._tool['name']} from MCP server {self._client.name}")[:2048],
            input_schema=schema,
            is_read_only=bool(annotations.get("readOnlyHint")),
            is_destructive=not annotations.get("readOnlyHint"),
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: Any) -> ToolResult:
        try:
            result = self._client.call_tool(self._tool["name"], tool_input)
        except McpError as e:
            return ToolResult(name=self._name, output={"error": str(e)}, is_error=True)
        return ToolResult(name=self._name, output=flatten_content(result), is_error=bool(result.get("isError")),
                          content_type="text")


def connect_servers(servers: dict[str, dict[str, Any]], cwd: Path) -> tuple[dict[str, McpClient], dict[str, str]]:
    """Start or reach and initialize every server; return (clients, errors by server name)."""
    clients: dict[str, McpClient] = {}
    errors: dict[str, str] = {}
    for name, cfg in servers.items():
        remote = remote_spec(cfg)
        if remote is not None:
            try:
                clients[name] = _connect_remote(name, *remote, cwd)
                atexit.register(clients[name].close)
            except McpError as e:
                errors[name] = str(e)
            continue
        if cfg.get("type") not in (None, "stdio") or not cfg.get("command"):
            errors[name] = "needs a `command` (stdio) or a `url` (http or sse)"
            continue
        try:
            client = McpStdioClient(name, cfg["command"], [str(a) for a in cfg.get("args", [])],
                                    {k: str(v) for k, v in (cfg.get("env") or {}).items()}, cwd)
        except OSError as e:
            errors[name] = str(e)
            continue
        try:
            client.initialize()
        except McpError as e:
            client.close()
            errors[name] = str(e)
            continue
        clients[name] = client
        atexit.register(client.close)
    return clients, errors


def foreign_server_sources() -> tuple[tuple[str, Path, str], ...]:
    """(agent, path, key) of other agents' user-level MCP server lists, offered by `clyde mcp import`."""
    home = Path.home()
    return (
        ("Claude Code", home / ".claude.json", "mcpServers"),
        ("Cursor", home / ".cursor" / "mcp.json", "mcpServers"),
        ("Gemini CLI", home / ".gemini" / "settings.json", "mcpServers"),
        ("Codex", home / ".codex" / "config.toml", "mcp_servers"),
        ("Copilot CLI", home / ".copilot" / "mcp-config.json", "mcpServers"),
    )


def find_foreign_servers(sources: tuple[tuple[str, Path, str], ...] | None = None) -> list[tuple[str, Path, dict[str, dict[str, Any]]]]:
    """(agent, path, {name: server config}) for every other agent that defines stdio or remote servers."""
    import tomllib

    found = []
    for agent, path, key in sources or foreign_server_sources():
        try:
            text = path.read_text(encoding="utf-8")
            data = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
        except (OSError, ValueError):
            continue
        servers = data.get(key) if isinstance(data, dict) else None
        usable = {}
        for name, cfg in (servers.items() if isinstance(servers, dict) else []):
            if not isinstance(cfg, dict):
                continue
            if cfg.get("command") and cfg.get("type") in (None, "stdio"):
                usable[name] = {k: cfg[k] for k in ("command", "args", "env") if k in cfg}
            elif any(cfg.get(k) for k in ("url", "httpUrl", "serverUrl")):
                usable[name] = {k: cfg[k] for k in ("type", "url", "httpUrl", "serverUrl", "headers") if k in cfg}
        if usable:
            found.append((agent, path, usable))
    return found


def import_servers(servers: dict[str, dict[str, Any]], dest: Path | None = None) -> list[str]:
    """Add servers to `mcpServers` in the settings file, keeping any with the same name; return the added names."""
    dest = dest or Path.home() / ".clyde" / "settings.json"
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{dest} is not a JSON object")
    table = data.setdefault("mcpServers", {})
    added = [name for name in servers if name not in table]
    if added:
        table.update({name: servers[name] for name in added})
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        dest.chmod(0o600)  # env blocks often carry API tokens
    return added
