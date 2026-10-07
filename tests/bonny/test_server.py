"""clyde luv bonny: the HTTP API over a real REPL with a scripted provider (no network)."""
from __future__ import annotations

import http.client
import json
import threading
import time
import unittest
from unittest.mock import patch

from src.bonny import server
from src.bonny.server import Bonny, EventLog, make_server
from src.repl import ClydeREPL
from tests.fakes import reply
from tests.repl.test_repl import _fake_provider_env


class BonnyCase(unittest.TestCase):
    def setUp(self):
        env = _fake_provider_env(reply("hello there"), reply("second answer"))
        self.provider = env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)
        from rich.console import Console
        import io
        self.repl = ClydeREPL(model="glm:glm-4.5", console=Console(file=io.StringIO()), headless=True)
        self.bonny = Bonny(self.repl)
        self.httpd = make_server(self.bonny)
        self.port = self.httpd.server_address[1]
        self.token = self.httpd.token
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.runner = threading.Thread(target=self.bonny.run, daemon=True)
        self.runner.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.bonny.control.prompts.put(None)
        self.runner.join(2)

    def call(self, method, path, body=None, *, token=True, host=None, origin=None, raw=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        if token:
            h["X-Bonny-Token"] = self.token
        if origin:
            h["Origin"] = origin
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if method == "POST":
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(data)
        except ValueError:
            return resp.status, data.decode()

    def wait_for(self, kind, after=0, timeout=10):
        deadline = time.monotonic() + timeout
        seen = []
        while time.monotonic() < deadline:
            events, after = self.bonny.events.after(after, 0.5)
            seen += events
            if any(e["kind"] == kind for e in events):
                return seen
        self.fail(f"no {kind} event; saw {[e['kind'] for e in seen]}")


class TestGuards(BonnyCase):
    def test_the_page_is_served_with_the_token_and_safety_headers(self):
        status, body = self.call("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.token, body)

    def test_a_wrong_host_origin_or_token_is_refused(self):
        self.assertEqual(self.call("GET", "/api/state", host="evil.example")[0], 403)
        self.assertEqual(self.call("GET", "/api/state", origin="http://evil.example")[0], 403)
        self.assertEqual(self.call("GET", "/api/state", token=False)[0], 403)
        self.assertEqual(self.call("GET", "/api/state", origin=f"http://127.0.0.1:{self.port}")[0], 200)

    def test_posts_need_json_and_stay_inside_the_size_limits(self):
        self.assertEqual(self.call("POST", "/api/prompt", raw=b"text=hi", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("POST", "/api/prompt", raw=b"not json")[0], 400)
        self.assertEqual(self.call("POST", "/api/prompt", {"text": "x" * (server.MAX_PROMPT + 1)})[0], 400)
        self.assertEqual(self.call("POST", "/api/prompt", {"text": "  "})[0], 400)
        self.assertEqual(self.call("POST", "/api/prompt", raw=b"x", headers={"Content-Length": str(server.MAX_BODY + 1)})[0], 413)

    def test_unknown_routes_and_bad_session_ids_are_404(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)
        self.assertEqual(self.call("GET", "/api/sessions/..%2Fsecrets")[0], 404)
        self.assertEqual(self.call("POST", "/api/session/open", {"id": "../etc"})[0], 404)


class TestPage(BonnyCase):
    def test_the_page_has_one_token_slot_and_makes_no_outside_requests(self):
        from src.bonny.page import PAGE

        self.assertEqual(PAGE.count("__TOKEN__"), 1)
        self.assertNotIn("http://", PAGE)
        self.assertNotIn("https://", PAGE)
        self.assertNotIn("innerHTML", PAGE)   # replies reach the page as text only
        self.assertNotIn("transition: all", PAGE)

    def test_models_lists_graded_models_and_state_carries_the_latest_event_id(self):
        graded = {"a:m": {"passed": True}, "b:m": {"passed": False}, "cardShuffle:house": {"passed": True}}
        with patch("src.providers.model_eval.load_results", return_value=graded):
            self.assertEqual(self.call("GET", "/api/models")[1]["models"], ["a:m"])
        before = self.call("GET", "/api/state")[1]["event"]
        self.bonny.events.emit("x")
        self.assertEqual(self.call("GET", "/api/state")[1]["event"], before + 1)


class TestSearchAndStatus(BonnyCase):
    FOUND = [{"title": "ELIZA - Wikipedia", "url": "https://en.wikipedia.org/wiki/ELIZA", "snippet": "A 1966 chatbot."}]

    def _system_prompts(self):
        return [r["conversation"].system_prompt for r in self.provider.requests]

    def test_a_search_turn_runs_the_search_first_and_hands_the_results_to_the_model(self):
        from src.tool_system.protocol import ToolResult

        with patch.object(server.WebSearchTool, "run", return_value=ToolResult(name="WebSearch", output={"query": "q", "results": self.FOUND})):
            self.call("POST", "/api/prompt", {"text": "what is eliza", "search": True, "mode": "plan"})
            events = self.wait_for("turn_end")
        tools = [e for e in events if e["kind"] == "tool"]
        self.assertEqual([(t["phase"], t["tool"]) for t in tools], [("start", "WebSearch"), ("end", "WebSearch")])
        self.assertEqual(tools[1]["results"], [{"title": "ELIZA - Wikipedia", "url": "https://en.wikipedia.org/wiki/ELIZA"}])
        prompt = self._system_prompts()[0]
        self.assertIn("[1] ELIZA - Wikipedia", prompt)
        self.assertIn("https://en.wikipedia.org/wiki/ELIZA", prompt)
        self.assertEqual(self.repl.mode, "plan")
        self.assertIsNone(self.repl.system_extra)                       # only that turn sees the results
        history = [m["text"] for m in self.call("GET", f"/api/sessions/{self.repl.session.session_id}")[1]["messages"]]
        self.assertEqual(history[0], "what is eliza")                   # the stored message is the question, not the results

    def test_the_results_reach_the_model_on_the_agent_loop_path_too(self):
        from src.tool_system.protocol import ToolResult

        with patch.object(server.WebSearchTool, "run", return_value=ToolResult(name="WebSearch", output={"query": "q", "results": self.FOUND})):
            self.call("POST", "/api/prompt", {"text": "search the history of eliza", "search": True})   # "search" skips the direct-stream shortcut
            self.wait_for("turn_end")
        self.assertIn("[1] ELIZA - Wikipedia", self._system_prompts()[0])

    def test_a_failed_search_still_answers_and_says_it_is_unsourced(self):
        with patch.object(server.WebSearchTool, "run", side_effect=RuntimeError("blocked")):
            self.call("POST", "/api/prompt", {"text": "what is eliza", "search": True})
            events = self.wait_for("turn_end")
        end = [e for e in events if e["kind"] == "tool"][1]
        self.assertTrue(end["error"])
        self.assertIn("blocked", end["summary"])
        self.assertIn("unsourced", self._system_prompts()[0])
        self.assertTrue(events[-1]["ok"])

    def test_a_plain_turn_carries_no_search_text(self):
        self.call("POST", "/api/prompt", {"text": "hello", "mode": "hold"})
        self.wait_for("turn_end")
        self.assertNotIn("Web results", self._system_prompts()[0])
        self.assertEqual(self.repl.mode, "hold")

    def test_a_bad_prompt_mode_is_refused(self):
        self.assertEqual(self.call("POST", "/api/prompt", {"text": "hi", "mode": "yolo"})[0], 400)

    def test_state_says_what_the_turn_is_doing(self):
        from src import activity

        activity.set("waiting for Laya to load")
        self.addCleanup(activity.clear)
        self.assertEqual(self.call("GET", "/api/state")[1]["activity"], "waiting for Laya to load")

    def test_tool_events_carry_fetched_urls_and_search_result_links(self):
        from types import SimpleNamespace as NS

        start = server._tool_event(NS(kind="tool_use", tool_use_id="c1", tool_name="WebFetch", tool_input={"url": "https://a.example/x"}))
        self.assertEqual(start["url"], "https://a.example/x")
        end = server._tool_event(NS(kind="tool_result", tool_use_id="c2", tool_name="WebSearch", is_error=False,
                                    tool_output={"query": "q", "results": [{"title": "T", "url": "https://b.example/", "snippet": "s"}, {"title": "no url"}]}))
        self.assertEqual(end["results"], [{"title": "T", "url": "https://b.example/"}])


class TestTurns(BonnyCase):
    def test_a_prompt_runs_streams_events_and_is_saved_as_a_session(self):
        self.assertEqual(self.call("POST", "/api/prompt", {"text": "hi bonny"})[0], 200)
        events = self.wait_for("turn_end")
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds[0], "turn_start")
        self.assertEqual("".join(e["text"] for e in events if e["kind"] == "text"), "hello there")
        end = events[-1]
        self.assertEqual((end["ok"], end["stopped"], end["answer"]), (True, False, "hello there"))
        sid = self.call("GET", "/api/state")[1]["session"]
        titles = {s["id"]: s["title"] for s in self.call("GET", "/api/sessions")[1]["sessions"]}
        self.assertIn("hi bonny", titles[sid])
        roles = [(m["role"], m["text"]) for m in self.call("GET", f"/api/sessions/{sid}")[1]["messages"]]
        self.assertEqual(roles, [("user", "hi bonny"), ("assistant", "hello there")])

    def test_prompts_queue_and_run_one_after_another(self):
        self.call("POST", "/api/prompt", {"text": "one"})
        self.call("POST", "/api/prompt", {"text": "two"})
        deadline = time.monotonic() + 10
        ends = []
        after = 0
        while len(ends) < 2 and time.monotonic() < deadline:
            events, after = self.bonny.events.after(after, 0.5)
            ends += [e for e in events if e["kind"] == "turn_end"]
        self.assertEqual([e["answer"] for e in ends], ["hello there", "second answer"])

    def test_steer_needs_a_running_turn_and_stop_only_interrupts_one(self):
        self.assertEqual(self.call("POST", "/api/steer", {"text": "also this"})[0], 409)
        self.bonny.control.busy = True
        self.assertEqual(self.call("POST", "/api/steer", {"text": "also this"})[0], 200)
        self.assertEqual(self.bonny.control.take_steer(), "also this")
        with patch("src.run_control.interrupt_turn") as interrupt:
            self.bonny.control.busy = False
            self.call("POST", "/api/stop", {})
            interrupt.assert_not_called()
            self.bonny.control.busy = True
            self.call("POST", "/api/stop", {})
            interrupt.assert_called_once()
        self.bonny.control.busy = False

    def test_permission_cards_wait_for_the_browser_and_a_stop_denies_them(self):
        result = []
        threading.Thread(target=lambda: result.append(self.bonny.ask_permission("Bash", "run ls", None))).start()
        card = next(e for e in self.wait_for("permission") if e["kind"] == "permission")
        self.assertEqual((card["tool"], card["message"]), ("Bash", "run ls"))
        self.assertEqual(self.call("POST", "/api/permission", {"card": card["card"], "allow": True})[0], 200)
        deadline = time.monotonic() + 5
        while not result and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(result, [(True, False)])
        self.assertEqual(self.call("POST", "/api/permission", {"card": card["card"], "allow": True})[0], 404)   # answered once
        second = []
        threading.Thread(target=lambda: second.append(self.bonny.ask_permission("Write", "write x", None))).start()
        self.wait_for("permission", after=card["id"])
        with patch("src.run_control.interrupt_turn"):
            self.bonny.stop()
        deadline = time.monotonic() + 5
        while not second and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(second, [(False, False)])


class TestChanges(BonnyCase):
    def test_mode_session_and_model_changes_work_when_idle_and_are_refused_while_busy(self):
        self.assertEqual(self.call("POST", "/api/mode", {"mode": "plan"})[1]["mode"], "plan")
        self.assertEqual(self.call("POST", "/api/mode", {"mode": "nonsense"})[0], 400)
        before = self.call("GET", "/api/state")[1]["session"]
        self.assertEqual(self.call("POST", "/api/session/new", {})[0], 200)
        self.assertEqual(self.call("POST", "/api/model", {"model": "nope:nothing"})[0], 400)
        self.bonny.control.busy = True
        for path, body in (("/api/mode", {"mode": "hold"}), ("/api/session/new", {}), ("/api/model", {"model": "glm:glm-4.5"})):
            self.assertEqual(self.call("POST", path, body)[0], 409)
        self.bonny.control.busy = False
        self.assertTrue(before)

    def test_a_vote_needs_a_council_turn_and_is_recorded_locally(self):
        self.assertEqual(self.call("POST", "/api/vote", {"ref": "a:m", "vote": "up"})[0], 409)
        self.provider.last_council = {"tier": "house", "request": "hi", "answers": [{"ref": "a:m", "text": "t", "p": 0.5}]}
        with patch("src.bonny.server.record_vote") as vote:
            self.assertEqual(self.call("POST", "/api/vote", {"ref": "a:m", "vote": "down"})[0], 200)
            vote.assert_called_once_with(self.provider.last_council, "a:m", -1)
        self.assertEqual(self.call("POST", "/api/vote", {"ref": "zzz", "vote": "up"})[0], 400)
        self.assertEqual(self.call("POST", "/api/vote", {"ref": "a:m", "vote": "maybe"})[0], 400)


class TestFeedback(BonnyCase):
    def test_a_thumb_is_saved_locally_as_a_hash_never_the_text(self):
        from src.config import clyde_home

        self.assertEqual(self.call("POST", "/api/feedback", {"vote": "up", "question": "secret question text"})[0], 200)
        self.assertEqual(self.call("POST", "/api/feedback", {"vote": "down", "question": "another"})[0], 200)
        lines = [json.loads(l) for l in (clyde_home() / "answer_feedback.jsonl").read_text().splitlines()]
        self.assertEqual([l["vote"] for l in lines[-2:]], [1, -1])
        self.assertNotIn("secret question text", json.dumps(lines))
        self.assertEqual(lines[-1]["session"], self.repl.session.session_id)

    def test_bad_feedback_is_refused(self):
        self.assertEqual(self.call("POST", "/api/feedback", {"vote": "meh", "question": "q"})[0], 400)
        self.assertEqual(self.call("POST", "/api/feedback", {"vote": "up"})[0], 400)


class TestTheme(BonnyCase):
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    def setUp(self):
        super().setUp()
        from src.bonny import theme
        self.theme = theme
        theme.remove_image()
        (theme.folder() / "theme.json").unlink(missing_ok=True)
        self.addCleanup(theme.remove_image)

    def raw(self, method, path, body=b"", headers=None, token=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if token:
            h["X-Bonny-Token"] = self.token
        conn.request(method, path, body=body or None, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), data

    def test_the_theme_api_needs_the_token(self):
        self.assertEqual(self.call("GET", "/api/theme", token=False)[0], 403)
        self.assertEqual(self.call("POST", "/api/theme", {"preset": "felt"}, token=False)[0], 403)

    def test_a_saved_theme_is_cleaned_and_read_back(self):
        status, body = self.call("POST", "/api/theme", {"preset": "felt", "shape": "round", "dim": 5, "colors": {"link": "#FFAA00", "bad": "red"}})
        self.assertEqual(status, 200)
        self.assertEqual((body["theme"]["dim"], body["theme"]["shape"], body["theme"]["colors"]), (0.9, "round", {"link": "#ffaa00"}))
        self.assertEqual((body["vars"]["--bg"], body["vars"]["--link"]), ("#0b2a1c", "#ffaa00"))
        self.assertEqual(self.call("GET", "/api/theme")[1]["theme"], body["theme"])
        self.assertIn("slate", body["presets"])

    def test_the_page_is_served_with_the_saved_theme_and_the_css_cannot_break_out(self):
        self.call("POST", "/api/theme", {"preset": "night", "shape": "square", "css": "a{color:red}</style><b id=x>"})
        page = self.call("GET", "/", token=False)[1]
        self.assertIn('data-shape="square"', page)
        self.assertIn("--bg:#0f1a14", page)
        self.assertIn("a{color:red}", page)
        self.assertNotIn("</style><b", page)
        for placeholder in ("__THEME__", "__CUSTOM__", "__SHAPE__", "__TOKEN__"):
            self.assertNotIn(placeholder, page)

    def test_a_background_image_is_stored_served_with_its_real_type_and_removable(self):
        status, _, data = self.raw("POST", "/api/theme/image", self.PNG, {"Content-Type": "text/plain"})   # the header is not trusted
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertTrue(payload["image"])
        url = payload["vars"]["--bg-image"].split('"')[1]
        self.assertIn("/theme/background?t=" + self.token, url)
        status, headers, body = self.raw("GET", url, token=False)
        self.assertEqual((status, headers["Content-Type"], body), (200, "image/png", self.PNG))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.raw("GET", "/theme/background?t=wrong", token=False)[0], 403)
        self.assertEqual(self.raw("GET", "/theme/background", token=False)[0], 403)
        self.assertFalse(self.call("POST", "/api/theme/image/remove", {})[1]["image"])
        self.assertEqual(self.raw("GET", url, token=False)[0], 404)

    def test_uploads_that_are_not_images_or_are_too_big_are_refused(self):
        self.assertEqual(self.raw("POST", "/api/theme/image", b"<svg xmlns='x'><script>1</script></svg>", {"Content-Type": "image/svg+xml"})[0], 400)
        self.assertEqual(self.raw("POST", "/api/theme/image", b"", {})[0], 400)
        self.assertEqual(self.raw("POST", "/api/theme/image", b"x", {"Content-Length": str(self.theme.MAX_IMAGE + 1)})[0], 413)
        self.assertEqual(self.raw("POST", "/api/theme/image", self.PNG, token=False)[0], 403)
        self.assertIsNone(self.theme.image_path())

    def test_only_the_two_fonts_are_served_and_the_host_is_still_checked(self):
        status, headers, body = self.raw("GET", "/static/bricolage-grotesque.woff2", token=False)
        self.assertEqual((status, headers["Content-Type"], body[:4]), (200, "font/woff2", b"wOF2"))
        self.assertEqual(self.raw("GET", "/static/jetbrains-mono.woff2", token=False)[0], 200)
        self.assertEqual(self.raw("GET", "/static/../server.py", token=False)[0], 404)
        self.assertEqual(self.raw("GET", "/static/page.py", token=False)[0], 404)
        self.assertEqual(self.raw("GET", "/static/jetbrains-mono.woff2", headers={"Host": "evil.example"}, token=False)[0], 403)


class TestEventLog(unittest.TestCase):
    def test_readers_get_only_newer_events_and_a_long_poll_wakes_on_emit(self):
        log = EventLog()
        log.emit("a")
        log.emit("b")
        self.assertEqual([e["kind"] for e in log.after(1)[0]], ["b"])
        threading.Timer(0.1, log.emit, ["c"]).start()
        events, last = log.after(2, timeout=3)
        self.assertEqual(([e["kind"] for e in events], last), (["c"], 3))
        self.assertEqual(log.after(3, timeout=0.05), ([], 3))

    def test_the_log_keeps_only_the_newest_events(self):
        log = EventLog()
        with patch.object(server, "MAX_EVENTS", 3):
            for i in range(5):
                log.emit("e", n=i)
        self.assertEqual([e["n"] for e in log.after(0)[0]], [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
