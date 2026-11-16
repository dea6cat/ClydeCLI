"""What Clyde's local web pages (Bonnie, the station) send with every response, so the two servers cannot drift apart:
no caching unless asked, no MIME sniffing, their content policy, no referrer, and header values that cannot end the
headers early."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler


def send_response(handler: BaseHTTPRequestHandler, status: int, body: bytes, ctype: str, csp: str, *,
                  cache: str = "no-store", extra: dict[str, str] | None = None) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", cache)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", csp)
    handler.send_header("Referrer-Policy", "no-referrer")
    for name, value in (extra or {}).items():
        handler.send_header(name, value.replace("\r", " ").replace("\n", " "))   # one stray newline would end the headers
    handler.end_headers()
    handler.wfile.write(body)
