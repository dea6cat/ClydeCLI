"""The station's web view: only the browser that opened the launch link gets in, and what it shows is the run's own record."""
from __future__ import annotations

import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import runs, station, station_web
from src.agent.runs import Run


class StationWebCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (patch("src.agent.runs.clyde_home", return_value=Path(self.tmp.name)), patch.object(runs, "_POLL_S", 0.01),
                        patch.object(station_web, "LONG_POLL_S", 1.0)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.httpd = station_web.make_server("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.token = self.httpd.token
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, *, cookie=None, token=None, host=None, origin=None, body=None, ctype="application/json", raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if cookie:
            headers["Cookie"] = cookie
        if token:
            headers["X-Station-Token"] = token
        if origin:
            headers["Origin"] = origin
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            headers["Content-Type"] = ctype
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        text = response.read().decode(errors="replace")   # a picture is bytes, not text
        out = response.status, dict(response.getheaders()), text
        conn.close()
        return out

    def login(self) -> str:
        status, headers, _ = self.request("GET", f"/?k={self.httpd.launch_secret}")
        self.assertEqual(status, 302)
        return headers["Set-Cookie"].split(";")[0]

    def api(self, path, cookie, **kw):
        status, _, text = self.request("GET", path, cookie=cookie, token=self.token, **kw)
        return status, json.loads(text)

    def run_with_events(self) -> Run:
        run = Run.create("add login", {"master": "a:big", "advisor": None, "kinds": {"master": "provider", "worker-1": "cli"},
                                       "workers": [{"name": "worker-1", "model": "claude:haiku"}]})
        run.set_status("running")
        run.event("worker-1", "constraint", note="files only")
        run.event("worker-1", "tool_use", tool="Edit")
        return run


class TestAuth(StationWebCase):
    def test_the_page_without_the_launch_cookie_is_refused_and_leaks_no_token(self):
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 403)
        self.assertNotIn(self.token, body)

    def test_a_wrong_launch_secret_is_refused(self):
        status, headers, body = self.request("GET", "/?k=not-the-secret")
        self.assertEqual(status, 403)
        self.assertNotIn("Set-Cookie", headers)
        self.assertNotIn(self.token, body)

    def test_the_launch_secret_is_exchanged_once_for_a_strict_httponly_cookie(self):
        status, headers, _ = self.request("GET", f"/?k={self.httpd.launch_secret}")
        self.assertEqual(status, 302)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        status, page_headers, body = self.request("GET", "/", cookie=cookie.split(";")[0])
        self.assertEqual(status, 200)
        self.assertIn(self.token, body)
        self.assertIn("default-src 'self'", page_headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", f"/?k={self.httpd.launch_secret}")[0], 403)   # a replayed link is dead

    def test_a_forged_cookie_is_refused(self):
        self.assertEqual(self.request("GET", "/", cookie="station_session=guess")[0], 403)

    def test_the_api_needs_the_cookie_and_the_token_and_this_host_and_origin(self):
        cookie = self.login()
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie)[0], 403)                      # cookie alone
        self.assertEqual(self.request("GET", "/api/state", token=self.token)[0], 403)                   # token alone
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie, token="wrong")[0], 403)
        self.assertEqual(self.request("GET", "/", cookie=cookie, host="evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie, token=self.token, host="evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie, token=self.token, origin="http://evil.example")[0], 403)
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie, token=self.token, origin=f"http://127.0.0.1:{self.port}")[0], 200)

    def test_the_page_builds_its_view_with_text_nodes_only(self):
        self.assertNotIn("innerHTML", station_web.PAGE)   # event text carries paths and model output: never parsed as markup
        self.assertNotIn("eval(", station_web.PAGE)


class TestArt(StationWebCase):
    def test_a_picture_is_served_only_to_the_browser_that_opened_the_link_and_only_from_the_art_folder(self):
        cookie = self.login()
        status, headers, _ = self.request("GET", "/assets/desk.png", cookie=cookie)
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertEqual(self.request("GET", "/assets/desk.png")[0], 403)   # no cookie, no picture
        for bad in ("/assets/nothing.png", "/assets/../station_page.py", "/assets/%2e%2e/station_page.py", "/assets/desk.png/../../station_web.py", "/assets/LICENSE-cozy-space-station.txt"):
            self.assertEqual(self.request("GET", bad, cookie=cookie)[0], 404, bad)

    def test_every_picture_the_page_asks_for_exists_and_its_size_is_known(self):
        names = set(re.findall(r'(?:fit|sprite)\("([a-z\-]+)"', station_web.PAGE))
        for line in station_web.PAGE.splitlines():
            if line.startswith(("const FAMILY_SPRITE", "const PLANTS", "const CREW_FILE")):
                names |= set(re.findall(r'"([a-z]+(?:-[a-z]+)+)"', line))
        self.assertGreater(len(names), 10)
        for name in names:
            self.assertTrue((station_web.ART / f"{name}.png").is_file(), name)
        self.assertEqual(station_web.PAGE.count("__SPRITES__"), 0)   # the server filled the sizes in
        self.assertTrue((station_web.ART / "LICENSE-cozy-space-station.txt").is_file())   # the licence travels with the art


class TestState(StationWebCase):
    def test_state_is_exactly_what_the_terminal_snapshot_shows(self):
        run = self.run_with_events()
        status, data = self.api("/api/state", self.login())
        self.assertEqual(status, 200)
        (served,) = data["runs"]
        self.assertEqual(served, json.loads(json.dumps(station.snapshot(run))))
        worker = next(m for m in served["crew"] if m["name"] == "worker-1")
        self.assertEqual((worker["kind"], worker["doing"], worker["constraint"]), ("cli", "using Edit", "files only"))
        self.assertEqual(served["clyde"], "watching the workers")

    def test_one_run_by_id_and_the_run_list_and_a_bad_id(self):
        first, second = self.run_with_events(), self.run_with_events()
        cookie = self.login()
        self.assertEqual([r["id"] for r in self.api(f"/api/state?run={first.id}", cookie)[1]["runs"]], [first.id])
        self.assertEqual({r["id"] for r in self.api("/api/runs", cookie)[1]["runs"]}, {first.id, second.id})
        self.assertEqual(self.api("/api/state?run=../x", cookie)[1]["runs"], [])


class TestStream(StationWebCase):
    def test_after_returns_only_what_is_new(self):
        run = self.run_with_events()
        cookie = self.login()
        _, data = self.api(f"/api/events?run={run.id}&after=0", cookie)
        self.assertEqual([e["kind"] for e in data["events"]], ["created", "status", "constraint", "tool_use"])
        self.assertEqual(data["next"], 4)
        run.event("worker-1", "finished")
        _, newer = self.api(f"/api/events?run={run.id}&after=4", cookie)
        self.assertEqual([e["kind"] for e in newer["events"]], ["finished"])
        self.assertEqual(newer["next"], 5)

    def test_the_poll_waits_and_answers_the_moment_something_is_recorded(self):
        run = self.run_with_events()
        cookie = self.login()
        timer = threading.Timer(0.4, lambda: run.event("worker-1", "finished"))
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        _, data = self.api(f"/api/events?run={run.id}&after=4", cookie)
        self.assertEqual([e["kind"] for e in data["events"]], ["finished"])
        self.assertTrue(0.3 < time.monotonic() - started < 0.95)   # answered on the event, not at the long-poll deadline

    def test_a_quiet_run_answers_empty_at_the_deadline(self):
        run = self.run_with_events()
        started = time.monotonic()
        _, data = self.api(f"/api/events?run={run.id}&after=4", self.login())
        self.assertEqual((data["events"], data["next"]), ([], 4))
        self.assertGreaterEqual(time.monotonic() - started, 0.9)

    def test_a_bad_cursor_or_run_is_refused(self):
        cookie = self.login()
        run = self.run_with_events()
        self.assertEqual(self.api(f"/api/events?run={run.id}&after=abc", cookie)[0], 400)
        self.assertEqual(self.api(f"/api/events?run={run.id}&after=-1", cookie)[0], 400)
        self.assertEqual(self.api("/api/events?run=../x&after=0", cookie)[0], 404)
        self.assertEqual(self.api("/api/events?run=nope&after=0", cookie)[0], 404)


class TestAnswer(StationWebCase):
    def _waiting(self, run):
        got = []
        thread = threading.Thread(target=lambda: got.append(run.ask("worker-1", "Bash", "run: ls")), daemon=True)
        thread.start()
        for _ in range(500):
            if run.pending():
                return thread, got
            time.sleep(0.01)
        self.fail("the ask never appeared")

    def test_allow_from_the_browser_unblocks_the_waiting_worker(self):
        run = self.run_with_events()
        thread, got = self._waiting(run)
        cookie = self.login()
        _, data = self.api("/api/state", cookie)
        self.assertEqual([(a["who"], a["tool"]) for a in data["runs"][0]["asks"]], [("worker-1", "Bash")])
        self.assertEqual(data["runs"][0]["clyde"], "waiting on you for 1 request")
        ask_id = data["runs"][0]["asks"][0]["id"]
        status, _, text = self.request("POST", "/api/answer", cookie=cookie, token=self.token, body={"run": run.id, "id": ask_id, "allow": True})
        self.assertEqual((status, json.loads(text)), (200, {"ok": True}))
        thread.join(5)
        self.assertEqual(got, [True])
        again = self.request("POST", "/api/answer", cookie=cookie, token=self.token, body={"run": run.id, "id": ask_id, "allow": False})[2]
        self.assertEqual(json.loads(again), {"ok": False})   # already answered

    def test_deny_is_a_no(self):
        run = self.run_with_events()
        thread, got = self._waiting(run)
        ask_id = run.pending()[0]["id"]
        self.request("POST", "/api/answer", cookie=self.login(), token=self.token, body={"run": run.id, "id": ask_id, "allow": False})
        thread.join(5)
        self.assertEqual(got, [False])

    def test_a_post_without_the_token_or_with_the_wrong_shape_changes_nothing(self):
        run = self.run_with_events()
        thread, got = self._waiting(run)
        ask_id = run.pending()[0]["id"]
        cookie = self.login()
        body = {"run": run.id, "id": ask_id, "allow": True}
        self.assertEqual(self.request("POST", "/api/answer", cookie=cookie, body=body)[0], 403)                          # no token
        self.assertEqual(self.request("POST", "/api/answer", token=self.token, body=body)[0], 403)                       # no cookie
        self.assertEqual(self.request("POST", "/api/answer", cookie=cookie, token=self.token, raw=b"x", ctype="text/plain")[0], 415)
        self.assertEqual(self.request("POST", "/api/answer", cookie=cookie, token=self.token, raw=b"{" + b" " * 70_000 + b"}")[0], 413)
        self.assertEqual(self.request("POST", "/api/answer", cookie=cookie, token=self.token, raw=b"not json")[0], 400)
        self.assertEqual(self.request("POST", "/api/answer", cookie=cookie, token=self.token, body={**body, "allow": "yes"})[0], 400)
        self.assertEqual(self.request("POST", "/api/answer", cookie=cookie, token=self.token, body={**body, "run": "../x"})[0], 400)
        self.assertEqual(self.request("POST", "/api/other", cookie=cookie, token=self.token, body=body)[0], 404)
        self.assertEqual(len(run.pending()), 1)   # nothing above answered it
        run.answer(ask_id, False)
        thread.join(5)
        self.assertEqual(got, [False])


class TestPage(unittest.TestCase):
    """The page is one string; these check what a browser would run into without running one."""

    def _themes(self) -> dict[str, dict[str, set[str]]]:
        import re
        found = {}
        for key, pal, words in re.findall(r'(\w+): \{ name: "[^"]+",\s*pal: \{(.*?)\},\s*words: \{(.*?)\} \}', station_web.PAGE, re.S):
            found[key] = {"pal": set(re.findall(r"(\w+): \"", pal)), "words": set(re.findall(r"(\w+): \"", words))}
        return found

    def test_the_themes_give_the_same_things_different_words_and_nothing_else(self):
        themes = self._themes()
        self.assertEqual(set(themes), {"city", "steam", "cyber"})
        first = themes["city"]
        self.assertTrue({"deck", "bay", "outbox", "read", "write", "shell", "web", "mcp", "other", "task", "results", "review", "report", "landing", "table"} <= first["words"])
        self.assertEqual([themes[k] for k in ("steam", "cyber")], [first, first])   # every theme names every room, object and hallway, in a palette of the same colours

    def test_the_scene_is_built_with_svg_nodes_and_text_and_the_theme_choice_cannot_break_the_page(self):
        page = station_web.PAGE
        self.assertIn("createElementNS", page)
        self.assertNotIn("innerHTML", page)
        self.assertNotIn("insertAdjacentHTML", page)
        self.assertNotIn("document.write", page)
        self.assertNotIn("eval(", page)
        self.assertIn("try { return localStorage", page)   # a private window may not allow it
        self.assertIn("prefers-reduced-motion", page)     # reduced motion: the crew appear at their spot instead of walking
        self.assertNotIn("http://", page.replace("http://www.w3.org/2000/svg", ""))   # no outside script, font or image
        self.assertNotIn("https://", page)
        self.assertNotIn("<img", page)   # drawn in code, no picture files


if __name__ == "__main__":
    unittest.main()
