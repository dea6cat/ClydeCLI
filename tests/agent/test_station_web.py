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
        status, headers, _ = self.request("GET", "/assets/furn-writer-desk-off.png", cookie=cookie)
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertEqual(self.request("GET", "/assets/furn-writer-desk-off.png")[0], 403)   # no cookie, no picture
        for bad in ("/assets/nothing.png", "/assets/../station_page.py", "/assets/%2e%2e/station_page.py", "/assets/furn-writer-desk-off.png/../../station_web.py", "/assets/LICENSE-cozy-space-station.txt"):
            self.assertEqual(self.request("GET", bad, cookie=cookie)[0], 404, bad)

    def test_every_picture_the_page_asks_for_exists_and_its_size_is_known(self):
        names = set(re.findall(r'"(tile-[a-z\-]+[a-z]|furn-[a-z\-]+-o(?:n|ff)|scene-(?:moon|stars|hedge|lamppost|tree-[a-z]+))"', station_web.PAGE)) | {f"scene-cloud-{n}" for n in range(1, 6)}
        furniture = re.search(r"const FURN = \{(.*?)\};", station_web.PAGE, re.S).group(1)
        for name in re.findall(r':\s*"([a-z\-]+)"', furniture):
            names |= {f"furn-{name}-off", f"furn-{name}-on"}   # each piece of furniture has an unlit and a lit picture
        names |= {f"tile-wall-{kind}-{side}" for kind in ("glass", "brick") for side in ("a", "b")}   # the walls are built from these names in code
        self.assertIn('"tile-wall-" + key', station_web.PAGE)
        self.assertGreater(len(names), 20)
        for name in names:
            self.assertTrue((station_web.ART / f"{name}.png").is_file(), name)
        self.assertEqual(station_web.PAGE.count("__SPRITES__") + station_web.PAGE.count("__CREW__"), 0)   # the server filled the sizes and the crew frames in
        sizes = json.loads(re.search(r"const SPR = (\{.*?\});", station_web.PAGE).group(1))
        self.assertTrue(names <= set(sizes), names - set(sizes))   # the page can fit every picture to its box


class TestCrewArt(unittest.TestCase):
    def test_every_person_has_idle_and_walk_frames_in_all_eight_directions_and_typists_face_us(self):
        from src.agent import station_page
        crew = station_page._crew_index()
        self.assertEqual(set(crew), {"clyde", "bonnie", "master", "advisor", "newsboy", "mechanic", "clerk"})
        for person, anims in crew.items():
            for anim in ("idle", "walk", "type"):
                if anim == "type" and anim not in anims:
                    continue   # typing is shown only to people who have a typing sheet; the others stand while they work
                self.assertEqual(len(anims[anim]), 8 if anim != "type" else 3, (person, anim))   # a figure can face any way it walks; typists face us
                for direction, count in anims[anim].items():
                    for n in range(count):
                        self.assertTrue((station_web.ART / f"{person}-{anim}-{direction}-{n:02d}.png").is_file(), (person, anim, direction, n))
        self.assertIn("south", crew["clyde"]["type"])   # whoever types faces the viewer
        self.assertEqual({p for p in station_web.PAGE.split("WORKER_LOOKS = [")[1].split("]")[0].replace('"', "").replace(" ", "").split(",")}, {"newsboy", "mechanic", "clerk"})


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

    def test_the_page_can_order_a_worker_for_a_working_run_and_is_told_why_when_it_cannot(self):
        run = self.run_with_events()   # still waiting on an approval: working
        run.set_status("running")
        cookie = self.login()
        status, _, text = self.request("POST", "/api/order", cookie=cookie, token=self.token, body={"run": run.id, "task": "write c.txt"})
        self.assertEqual((status, json.loads(text)["ok"]), (200, True))
        self.assertEqual([o["task"] for o in run.pending_orders()], ["write c.txt"])
        self.assertEqual(self.request("POST", "/api/order", token=self.token, body={"run": run.id, "task": "x"})[0], 403)   # no cookie
        self.assertEqual(self.request("POST", "/api/order", cookie=cookie, token=self.token, body={"run": run.id, "task": 5})[0], 400)
        self.assertEqual(self.request("POST", "/api/order", cookie=cookie, token=self.token, body={"run": "../x", "task": "x"})[0], 400)
        status, _, text = self.request("POST", "/api/order", cookie=cookie, token=self.token, body={"run": run.id, "task": "  "})
        self.assertEqual((status, "say what" in json.loads(text)["error"]), (409, True))
        self.assertEqual(self.request("POST", "/api/order", cookie=cookie, token=self.token, body={"run": run.id, "task": "x", "worker": 3})[0], 400)
        status, _, text = self.request("POST", "/api/order", cookie=cookie, token=self.token, body={"run": run.id, "task": "x", "worker": "worker-9"})
        self.assertEqual((status, "not on this team" in json.loads(text)["error"]), (409, True))
        run.set_status("reviewing")
        status, _, text = self.request("POST", "/api/order", cookie=cookie, token=self.token, body={"run": run.id, "task": "late"})
        self.assertEqual((status, "not working" in json.loads(text)["error"]), (409, True))
        self.assertEqual(len(run.pending_orders()), 1)   # only the first was filed

    def test_the_page_can_stop_a_working_run_once_and_is_told_why_when_it_cannot(self):
        run = self.run_with_events()
        cookie = self.login()
        self.assertEqual(self.request("POST", "/api/stop", token=self.token, body={"run": run.id})[0], 403)   # no cookie
        self.assertEqual(self.request("POST", "/api/stop", cookie=cookie, token=self.token, body={"run": "../x"})[0], 400)
        status, _, text = self.request("POST", "/api/stop", cookie=cookie, token=self.token, body={"run": run.id})
        self.assertEqual((status, json.loads(text)), (200, {"ok": True}))
        self.assertTrue(run.stop_requested())
        status, _, text = self.request("POST", "/api/stop", cookie=cookie, token=self.token, body={"run": run.id})
        self.assertEqual((status, "already stopping" in json.loads(text)["error"]), (409, True))

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

    def test_the_one_look_names_every_room_object_and_hallway(self):
        found = re.findall(r'(\w+): \{ name: "[^"]+",\s*pal: \{(.*?)\},\s*words: \{(.*?)\} \}', station_web.PAGE, re.S)
        self.assertEqual([k for k, _, _ in found], ["city"])
        words = set(re.findall(r"(\w+): \"", found[0][2]))
        self.assertTrue({"deck", "bay", "outbox", "read", "write", "shell", "web", "mcp", "other", "task", "results", "review", "report", "landing", "table"} <= words)
        self.assertNotIn('id="theme"', station_web.PAGE)

    def test_the_header_shows_the_link_and_the_crew_counts_and_cinema_hides_every_panel(self):
        page = station_web.PAGE
        for needle in ('id="link"', 'id="counts"', 'id="cinemaToggle"', 'id="cinemaTab"', "body.cinema .rail", "railgrip", "station.cinema", "station.railw"):
            self.assertIn(needle, page)
        self.assertNotIn("disconnected:", page)   # the link chip says it now

    def test_the_top_left_card_lists_what_waits_on_the_user(self):
        page = station_web.PAGE
        for needle in ("function needsBox", '"Needs you"', "needsYou(", "station.dismissed", 'api("/api/answer"', "data-since" if False else "dataset.since"):
            self.assertIn(needle, page)

    def test_the_page_can_ask_for_one_more_worker_up_to_the_servers_team_size(self):
        from src.agent.runs import MAX_TEAM
        page = station_web.PAGE
        for needle in ('id="addWorker"', '"Add worker"', 'api("/api/order"', "function openAdd", f"const MAX_TEAM = {MAX_TEAM};", '"Task"', "addingFor"):
            self.assertIn(needle, page)

    def test_each_person_can_be_renamed_and_the_name_is_kept_only_in_this_browser(self):
        page = station_web.PAGE
        for needle in ("function crewItem", '"Rename"', "station.names", "withName(", "callName("):
            self.assertIn(needle, page)

    def test_the_first_steps_card_is_ticked_by_records_and_can_be_hidden(self):
        page = station_web.PAGE
        for needle in ("function questBox", '"First steps"', "station.quests", "quests(state.runs"):
            self.assertIn(needle, page)

    def test_the_page_can_stop_a_working_run_after_a_confirm(self):
        page = station_web.PAGE
        for needle in ('id="stopRun"', '"Stop run"', 'api("/api/stop"', "function openStop", "stop_requested"):
            self.assertIn(needle, page)

    def test_a_piece_the_layout_shows_from_behind_has_its_back_picture(self):
        from pathlib import Path
        art = Path(station_web.__file__).parent / "station_art"
        self.assertIn('f.back ? "-back"', station_web.PAGE)
        self.assertIn("back: true", station_web.PAGE)
        self.assertIn("if (f.back) {   // a piece that shows its back has a low glass wall behind it", station_web.PAGE)
        for name in ("file-cabinet", "writer-desk", "safe", "radio", "switchboard", "cupboard"):   # the six a workshop is furnished with
            self.assertTrue((art / f"furn-{name}-back.png").is_file(), name)

    def test_the_scene_is_built_with_svg_nodes_and_text_and_a_private_window_cannot_break_the_page(self):
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
