"""MCP (Model Context Protocol) client over stdio, stdlib only.

Servers come from `mcpServers` in ~/.clyde/settings.json, in Claude Code's format:
    {"mcpServers": {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                               "env": {"GITHUB_TOKEN": "..."}}}}

Each server's tools are registered as `mcp__<server>__<tool>`; resources are reachable through
ListMcpResourcesTool / ReadMcpResourceTool. Messages are newline-delimited JSON-RPC 2.0.
"""

from __future__ import annotations

import atexit
import itertools
import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

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


class McpStdioClient:
    """One running server process; requests may come from any thread."""

    def __init__(self, name: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
        self.name = name
        self._proc = subprocess.Popen(
            [command, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, **(env or {})}, cwd=cwd, text=True, encoding="utf-8", bufsize=1,
        )
        self._ids = itertools.count(1)
        self._pending: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self._write_lock = threading.Lock()
        self._roots = [{"uri": Path(cwd or Path.cwd()).resolve().as_uri(), "name": "workspace"}]
        threading.Thread(target=self._read_loop, daemon=True, name=f"mcp-{name}").start()
        self.server_info: dict[str, Any] = {}
        self.tools: list[dict[str, Any]] = []

    # --- transport -------------------------------------------------------
    def _send(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            if self._proc.stdin is None or self._proc.poll() is not None:
                raise McpError(f"MCP server '{self.name}' is not running")
            self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            self._proc.stdin.flush()

    def _read_loop(self) -> None:
        for line in self._proc.stdout or ():
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # servers sometimes log to stdout
            if not isinstance(msg, dict):
                continue
            if "method" in msg and "id" in msg:
                self._answer_server_request(msg)
            elif "id" in msg and msg["id"] in self._pending:
                event, box = self._pending[msg["id"]]
                box.update(msg)
                event.set()
        for event, box in list(self._pending.values()):  # process exited: wake every waiter
            box.setdefault("error", {"message": f"MCP server '{self.name}' exited"})
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

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()  # the spec's stdio shutdown: close input, then terminate
                self._proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()


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

    def __init__(self, client: McpStdioClient, tool: dict[str, Any]) -> None:
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


def connect_servers(servers: dict[str, dict[str, Any]], cwd: Path) -> tuple[dict[str, McpStdioClient], dict[str, str]]:
    """Start and initialize every stdio server; return (clients, errors by server name)."""
    clients, errors = {}, {}
    for name, cfg in servers.items():
        if cfg.get("type") not in (None, "stdio") or not cfg.get("command"):
            errors[name] = "only stdio servers (a `command`) are supported"
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
    """(agent, path, {name: stdio server config}) for every other agent that defines stdio servers."""
    import tomllib

    found = []
    for agent, path, key in sources or foreign_server_sources():
        try:
            text = path.read_text(encoding="utf-8")
            data = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
        except (OSError, ValueError):
            continue
        servers = data.get(key) if isinstance(data, dict) else None
        stdio = {
            name: {k: cfg[k] for k in ("command", "args", "env") if k in cfg}
            for name, cfg in (servers.items() if isinstance(servers, dict) else [])
            if isinstance(cfg, dict) and cfg.get("command") and cfg.get("type") in (None, "stdio")
        }
        if stdio:
            found.append((agent, path, stdio))
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
