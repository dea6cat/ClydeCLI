from __future__ import annotations

import html
import http.client
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionResult
from ..protocol import ToolResult
from ..registry import ToolSpec


_TAG_RE = re.compile(r"<[^>]+>")


def _blocked_address(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _is_private_host(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    return any(_blocked_address(info[4][0]) for info in infos)


def _connect_checked(address, timeout=None, source_address=None):
    """Connect the way socket.create_connection does, but resolve once, refuse the connection if any answer is a private
    address, and connect to one of the answers that was checked. A host that answers with a public address for the early check
    and a private one for the connection (DNS rebinding) is stopped here, because this is the last lookup there is."""
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if any(_blocked_address(info[4][0]) for info in infos):
        raise ToolPermissionError("refusing to fetch localhost/private network URLs")
    error: OSError | None = None
    for family, kind, proto, _, sockaddr in infos:
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            error = e
            sock.close()
    raise error or OSError("no address to connect to")


class _CheckedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_checked


class _CheckedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_checked


class _CheckedHTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_CheckedHTTPConnection, req)


class _CheckedHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_CheckedHTTPSConnection, req, context=self._context)


def _check_url(url: str) -> urllib.parse.ParseResult:
    """The same rules for the URL asked for and for every redirect it leads to: http(s) only, never a local or private address.
    A public host the user approved must not be able to bounce Clyde into localhost, the LAN or a cloud metadata address."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolPermissionError("only http/https URLs are allowed")
    if not parsed.netloc:
        raise ToolInputError("url must include a network location")
    hostname = parsed.hostname or ""
    if hostname in {"localhost"} or hostname.endswith(".localhost") or _is_private_host(hostname):
        raise ToolPermissionError("refusing to fetch localhost/private network URLs")
    return parsed


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _check_url(newurl)
        except (ToolPermissionError, ToolInputError) as e:
            raise ToolPermissionError(f"refusing a redirect to {newurl}: {e}") from e
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _html_to_text(raw: str) -> str:
    without_tags = _TAG_RE.sub(" ", raw)
    without_tags = re.sub(r"\s+", " ", without_tags).strip()
    return html.unescape(without_tags)


class WebFetchTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="WebFetch",
            description="Fetch a URL and return extracted text content.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            is_read_only=True,
            max_result_size_chars=50_000,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        """Ask once per call, showing the whole URL; a `WebFetch(domain:...)` rule skips the prompt."""
        url = tool_input.get("url")
        host = urllib.parse.urlparse(url).hostname if isinstance(url, str) else None
        if not host:
            return PermissionResult.allow()  # Input validation happens in run()
        shown = url if len(url) <= 300 else f"{url[:300]}… (+{len(url) - 300} more characters)"
        return PermissionResult.ask(message=f"Fetch {shown}")   # all of it: a key can ride in the query, past a host-only prompt

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        url = tool_input["url"]
        if not isinstance(url, str) or not url:
            raise ToolInputError("url must be a non-empty string")

        _check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "clyde-cli/0.1"})
        with urllib.request.build_opener(_CheckedHTTP, _CheckedHTTPS, _CheckedRedirects).open(req, timeout=15) as resp:
            raw_bytes = resp.read(1_000_000)
            content_type = resp.headers.get("Content-Type", "")

        text = raw_bytes.decode("utf-8", errors="replace")
        if "text/html" in content_type:
            text = _html_to_text(text)

        if len(text) > 100_000:
            text = text[:100_000] + "\n\n... [truncated] ..."

        return ToolResult(
            name="WebFetch",
            output={"url": url, "content_type": content_type, "content": text},
        )

