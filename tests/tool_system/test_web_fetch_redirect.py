"""WebFetch: the private-network rules apply to every redirect, not only the first URL."""

from __future__ import annotations

import http.server
import threading
import unittest
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolPermissionError
from src.tool_system.tools import web_fetch
from src.tool_system.tools.web_fetch import WebFetchTool


def _serve(handler_class):
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class TestRedirects(unittest.TestCase):
    def setUp(self):
        self.hits: list[str] = []
        hits = self.hits

        class Internal(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"internal only")

            def log_message(self, *args):
                pass

        self.internal = _serve(Internal)
        target = f"http://127.0.0.1:{self.internal.server_port}/admin"

        class Front(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.front = _serve(Front)
        self.addCleanup(lambda: [s.shutdown() or s.server_close() for s in (self.internal, self.front)])

    def _fetch(self):
        real = web_fetch._is_private_host
        first = [True]

        def guard(host):
            if first[0]:   # the URL the user approved is public: let it through, as a real public host would pass
                first[0] = False
                return False
            return real(host)

        with patch.object(web_fetch, "_is_private_host", guard):
            return WebFetchTool().run({"url": f"http://127.0.0.1:{self.front.server_port}/"}, ToolContext(workspace_root="."))

    def test_a_redirect_into_a_private_address_is_refused_and_never_requested(self):
        with self.assertRaises(ToolPermissionError) as raised:
            self._fetch()
        self.assertIn("refusing a redirect", str(raised.exception))
        self.assertEqual(self.hits, [])

    def test_a_private_address_asked_for_directly_is_still_refused(self):
        with self.assertRaises(ToolPermissionError):
            WebFetchTool().run({"url": f"http://127.0.0.1:{self.internal.server_port}/"}, ToolContext(workspace_root="."))
        self.assertEqual(self.hits, [])

    def test_other_schemes_are_refused_on_a_redirect_too(self):
        with self.assertRaises(ToolPermissionError):
            web_fetch._check_url("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
