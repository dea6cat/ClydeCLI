"""MCP OAuth sign-in end to end, against a fake authorization server and MCP server on 127.0.0.1.
The "browser" is a thread that follows the sign-in page's redirect, as a real one would."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.tool_system import mcp_oauth
from src.tool_system.mcp_client import McpAuthRequired, connect_servers


class _Auth:
    """Fake MCP server (/mcp, bearer-protected) plus its authorization server, on one port."""

    def __init__(self, tamper_state: bool = False):
        self.valid: set[str] = set()
        self.seen_auth: list[str] = []
        self.challenge, self.redirects, self.issued = "", [], 0
        self.refresh_ok = True
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, code: int, obj: dict, headers: dict | None = None) -> None:
                body = json.dumps(obj).encode()
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length", 0)))

            def do_GET(self):
                path, _, query = self.path.partition("?")
                base = outer.url
                if path == "/.well-known/oauth-protected-resource/mcp":
                    return self._json(200, {"resource": base + "/mcp", "authorization_servers": [base], "scopes_supported": ["mcp:tools"]})
                if path == "/.well-known/oauth-authorization-server":
                    return self._json(200, {"issuer": base, "authorization_endpoint": base + "/authorize", "token_endpoint": base + "/token",
                                            "registration_endpoint": base + "/register", "code_challenge_methods_supported": ["S256"]})
                if path == "/authorize":
                    q = dict(urllib.parse.parse_qsl(query))
                    assert q["code_challenge_method"] == "S256" and q["resource"] == base + "/mcp" and q["scope"] == "mcp:tools"
                    outer.challenge = q["code_challenge"]
                    state = "forged" if tamper_state else q["state"]
                    self.send_response(302)
                    self.send_header("Location", f"{q['redirect_uri']}?code=c0de&state={state}")
                    self.end_headers()
                    return
                self._json(404, {})

            def do_POST(self):
                if self.path == "/register":
                    reg = json.loads(self._body())
                    outer.redirects.append(reg["redirect_uris"][0])
                    return self._json(201, {"client_id": "clyde-client"})
                if self.path == "/token":
                    form = dict(urllib.parse.parse_qsl(self._body().decode()))
                    if form["grant_type"] == "authorization_code":
                        digest = hashlib.sha256(form["code_verifier"].encode()).digest()
                        verifier_ok = base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == outer.challenge
                        if form["code"] != "c0de" or not verifier_ok:
                            return self._json(400, {"error": "invalid_grant"})
                    elif not outer.refresh_ok:
                        return self._json(400, {"error": "invalid_grant"})
                    outer.issued += 1
                    token = f"at-{outer.issued}"
                    outer.valid.add(token)
                    return self._json(200, {"access_token": token, "refresh_token": "rt", "expires_in": 3600, "token_type": "Bearer"})
                if self.path == "/mcp":
                    auth = self.headers.get("Authorization", "")
                    outer.seen_auth.append(auth)
                    if auth.removeprefix("Bearer ") not in outer.valid:
                        return self._json(401, {"error": "unauthorized"}, {
                            "WWW-Authenticate": f'Bearer resource_metadata="{outer.url}/.well-known/oauth-protected-resource/mcp"'})
                    msg = json.loads(self._body())
                    if "id" not in msg or "method" not in msg:
                        self.send_response(202)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    result = {"initialize": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "secure"}},
                              "tools/list": {"tools": [{"name": "whoami", "inputSchema": {"type": "object"}}]}}.get(msg["method"], {})
                    return self._json(200, {"jsonrpc": "2.0", "id": msg["id"], "result": result})
                self._json(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _browser(url: str) -> None:
    threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=10).read(), daemon=True).start()


class TestOAuth(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.auth = _Auth()
        self.addCleanup(self.auth.stop)
        self.cfg = {"secure": {"type": "http", "url": self.auth.url + "/mcp"}}

    def test_without_a_sign_in_the_server_asks_for_one(self):
        _, errors = connect_servers(self.cfg, self.home)
        self.assertEqual(errors["secure"], "MCP server 'secure' needs sign-in: run /mcp login secure")

    def test_sign_in_then_connect_with_the_token(self):
        token = mcp_oauth.login(self.auth.url + "/mcp", open_browser=_browser, timeout=10)
        self.assertEqual(token, "at-1")
        self.assertEqual(oct(mcp_oauth.store_path().stat().st_mode & 0o777), "0o600")
        self.assertTrue(self.auth.redirects[0].startswith("http://127.0.0.1:"))      # registered a loopback redirect
        clients, errors = connect_servers(self.cfg, self.home)
        self.assertEqual(errors, {})
        self.assertEqual(clients["secure"].list_tools(), ["whoami"])
        self.assertIn("Bearer at-1", self.auth.seen_auth)

    def test_a_revoked_token_is_refreshed_once_and_the_call_retried(self):
        mcp_oauth.login(self.auth.url + "/mcp", open_browser=_browser, timeout=10)
        clients, _ = connect_servers(self.cfg, self.home)
        self.auth.valid.clear()                                                        # the server revokes at-1
        self.assertEqual(clients["secure"].request("tools/list")["tools"][0]["name"], "whoami")
        self.assertEqual(self.auth.seen_auth[-1], "Bearer at-2")

    def test_a_failed_refresh_drops_the_tokens_and_asks_for_a_sign_in_again(self):
        mcp_oauth.login(self.auth.url + "/mcp", open_browser=_browser, timeout=10)
        clients, _ = connect_servers(self.cfg, self.home)
        self.auth.valid.clear()
        self.auth.refresh_ok = False
        with self.assertRaises(McpAuthRequired):
            clients["secure"].request("tools/list")
        self.assertFalse(mcp_oauth.signed_in(self.auth.url + "/mcp"))

    def test_logout_forgets_the_server(self):
        mcp_oauth.login(self.auth.url + "/mcp", open_browser=_browser, timeout=10)
        self.assertTrue(mcp_oauth.logout(self.auth.url + "/mcp"))
        self.assertFalse(mcp_oauth.signed_in(self.auth.url + "/mcp"))
        self.assertFalse(mcp_oauth.logout(self.auth.url + "/mcp"))


class TestTamperedRedirect(unittest.TestCase):
    def test_a_forged_state_is_refused(self):
        auth = _Auth(tamper_state=True)
        self.addCleanup(auth.stop)
        with patch.object(Path, "home", return_value=Path(tempfile.mkdtemp())):
            with self.assertRaisesRegex(mcp_oauth.OAuthError, "state didn't match"):
                mcp_oauth.login(auth.url + "/mcp", open_browser=_browser, timeout=10)
            self.assertFalse(mcp_oauth.signed_in(auth.url + "/mcp"))


if __name__ == "__main__":
    unittest.main()
