"""Bonnie's page, and the API token inside it, go only to the browser that opened the one-time launch link."""

from __future__ import annotations

import http.client

from tests.bonnie import test_server as ts


class TestPageAuth(ts.BonnieCase):
    def _open_launch_link(self) -> str:
        return ""   # these tests do the exchange themselves, so the one-time secret must still be unused
    def _get(self, path, cookie=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if cookie:
            headers["Cookie"] = cookie
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode()
        out = resp.status, dict(resp.getheaders()), body
        conn.close()
        return out

    def test_the_page_without_the_launch_cookie_is_refused_and_leaks_no_token(self):
        status, _, body = self._get("/")
        self.assertEqual(status, 403)
        self.assertNotIn(self.token, body)

    def test_a_wrong_launch_secret_is_refused(self):
        status, headers, body = self._get("/?k=not-the-secret")
        self.assertEqual(status, 403)
        self.assertNotIn("Set-Cookie", headers)
        self.assertNotIn(self.token, body)

    def test_the_launch_secret_is_exchanged_once_for_a_strict_httponly_cookie(self):
        status, headers, _ = self._get(f"/?k={self.httpd.launch_secret}")
        self.assertEqual(status, 302)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        status, _, body = self._get("/", cookie=cookie.split(";")[0])
        self.assertEqual(status, 200)
        self.assertIn(self.token, body)
        self.assertEqual(self._get(f"/?k={self.httpd.launch_secret}")[0], 403)   # a replayed link is dead

    def test_a_forged_cookie_is_refused(self):
        self.assertEqual(self._get("/", cookie="bonnie_session=guess")[0], 403)

    def test_the_cookie_does_not_replace_the_api_token_or_the_host_check(self):
        _, headers, _ = self._get(f"/?k={self.httpd.launch_secret}")
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertEqual(self._get("/api/state", cookie=cookie)[0], 403)
        self.assertEqual(self._get("/", cookie=cookie, host="evil.example")[0], 403)
