"""Telemetry is opt-in, carries only what SCHEMA allows, and sends only to an endpoint someone set."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from src import telemetry
from src.agent.agent_loop import run_agent_loop
from src.agent.conversation import Conversation
from src.providers.base import ProviderError
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply

RUN = dict(surface="repl", outcome="done", turns=2, tool_calls=1, tool_errors=0, repeats_refused=0,
           first_input_tokens="1-2k", index="names", provider_kind="local", model_size="2-4B")


class _Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (patch("src.telemetry.clyde_home", return_value=Path(self.tmp.name)),
                  patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in ("CLYDE_TELEMETRY", "DO_NOT_TRACK", "CLYDE_TELEMETRY_URL")}, clear=True)):
            p.start()
            self.addCleanup(p.stop)


class TestConsent(_Home):
    def test_it_is_off_until_turned_on_and_records_nothing_while_off(self):
        self.assertFalse(telemetry.enabled())
        self.assertFalse(telemetry.record("run", **RUN))
        self.assertEqual(telemetry.queued(), [])

    def test_turning_it_on_queues_events_with_the_common_fields(self):
        telemetry.turn_on()
        self.assertTrue(telemetry.record("run", **RUN))
        event = telemetry.queued()[0]
        self.assertEqual({k: event[k] for k in RUN}, RUN)
        self.assertEqual({"event", "v", "id", "os", "arch", "py", "ram_gb", "day"} | set(RUN), set(event))

    def test_the_environment_always_wins(self):
        telemetry.turn_on()
        for name, value in (("CLYDE_TELEMETRY", "off"), ("DO_NOT_TRACK", "1")):
            with self.subTest(name), patch.dict(os.environ, {name: value}):
                self.assertFalse(telemetry.enabled())
                self.assertFalse(telemetry.record("run", **RUN))

    def test_turning_it_off_deletes_the_queue(self):
        telemetry.turn_on()
        telemetry.record("run", **RUN)
        telemetry.turn_off()
        self.assertEqual(telemetry.queued(), [])
        self.assertFalse(telemetry.enabled())

    def test_the_install_id_survives_off_and_on_and_reset_changes_it(self):
        telemetry.turn_on()
        first = telemetry._read_state()["id"]
        telemetry.turn_off(); telemetry.turn_on()
        self.assertEqual(telemetry._read_state()["id"], first)
        telemetry.reset_id()
        self.assertNotEqual(telemetry._read_state()["id"], first)


class TestSchema(_Home):
    def setUp(self):
        super().setUp()
        telemetry.turn_on()

    def test_free_text_cannot_be_recorded(self):
        for bad in ({"model_size": "/Users/me/secret"}, {"surface": "my prompt"}, {"first_input_tokens": "3141"}, {"outcome": "Error: key sk-123"}):
            with self.subTest(bad):
                self.assertFalse(telemetry.record("run", **{**RUN, **bad}))
        self.assertEqual(telemetry.queued(), [])

    def test_an_unknown_event_or_field_is_refused(self):
        self.assertFalse(telemetry.record("prompt", text="hello"))
        self.assertFalse(telemetry.record("run", **RUN, path="/tmp/x"))

    def test_counts_must_be_plain_non_negative_numbers(self):
        for bad in (-1, True, "2", 2.5, 10_000_001):
            with self.subTest(bad):
                self.assertFalse(telemetry.record("run", **{**RUN, "turns": bad}))

    def test_a_provider_error_names_only_a_known_provider_and_a_kind(self):
        telemetry.provider_error(ProviderError("openai", "x", status=429))
        telemetry.provider_error(ProviderError("my-private-llm.corp.example", "x", status=400))
        events = telemetry.queued()
        self.assertEqual([(e["provider"], e["kind"]) for e in events], [("openai", "http_429"), ("custom", "http_400")])

    def test_error_kinds(self):
        for error, kind in ((ProviderError("a", "x", status=503), "http_5xx"), (ProviderError("a", "no response for 180 s"), "stalled"),
                            (ProviderError("a", "connection failed: [SSL: CERTIFICATE_VERIFY_FAILED]"), "ssl"), (ProviderError("a", "boom"), "other")):
            with self.subTest(kind):
                self.assertEqual(telemetry.provider_error_kind(error), kind)

    def test_the_queue_is_capped(self):
        with patch.object(telemetry, "QUEUE_LIMIT", 3):
            for turns in range(6):
                telemetry.record("run", **{**RUN, "turns": turns})
        self.assertEqual([e["turns"] for e in telemetry.queued()], [3, 4, 5])

    def test_what_a_model_is_is_a_word_from_a_fixed_set(self):
        class P:
            name, api_key = "ollama", None
            parameter_billions = staticmethod(lambda model: 3.4)
        self.assertEqual(telemetry.describe(P(), "my-secret-finetune"), ("local", "2-4B"))


class TestSending(_Home):
    def setUp(self):
        super().setUp()
        telemetry.turn_on()
        telemetry.record("run", **RUN)

    def _receiver(self):
        from tools.telemetry_receiver import make_handler
        store = Path(self.tmp.name) / "received.jsonl"
        server = HTTPServer(("127.0.0.1", 0), make_handler(store))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return store, f"http://127.0.0.1:{server.server_address[1]}"

    def test_with_no_endpoint_nothing_is_sent_and_the_queue_stays(self):
        sent, why = telemetry.flush()
        self.assertFalse(sent)
        self.assertIn("nothing leaves", why)
        self.assertEqual(len(telemetry.queued()), 1)

    def test_a_batch_reaches_the_receiver_and_the_queue_is_cleared(self):
        store, url = self._receiver()
        telemetry.set_endpoint(url)
        sent, why = telemetry.flush()
        self.assertTrue(sent, why)
        self.assertEqual(telemetry.queued(), [])
        self.assertEqual(json.loads(store.read_text().splitlines()[0])["outcome"], "done")

    def test_a_failed_send_keeps_the_queue_for_next_time(self):
        telemetry.set_endpoint("http://127.0.0.1:9")   # nothing listens there
        sent, _ = telemetry.flush()
        self.assertFalse(sent)
        self.assertEqual(len(telemetry.queued()), 1)

    def test_only_https_or_this_machine_is_a_valid_endpoint(self):
        self.assertTrue(telemetry.valid_endpoint("https://t.example.com/in"))
        self.assertTrue(telemetry.valid_endpoint("http://localhost:8787"))
        for url in ("http://t.example.com/in", "ftp://x", "not a url", ""):
            self.assertFalse(telemetry.valid_endpoint(url), url)

    def test_the_receiver_refuses_an_event_that_breaks_the_schema(self):
        from tools.telemetry_receiver import acceptable
        good = telemetry.queued()[0]
        self.assertTrue(acceptable(good))
        self.assertFalse(acceptable({**good, "path": "/tmp/x"}))
        self.assertFalse(acceptable({**good, "model_size": "secret"}))


class TestFirstRunQuestion(_Home):
    def _ask(self, answer):
        asked = []
        telemetry.ask_once(type("C", (), {"print": staticmethod(lambda *a, **k: None)})(), lambda *a, **k: asked.append(k.get("default")) or answer)
        return asked

    def test_it_is_not_asked_when_there_is_nowhere_to_send(self):
        self.assertEqual(self._ask(True), [])
        self.assertFalse(telemetry.enabled())

    def test_it_is_asked_once_with_no_as_the_default_and_a_yes_turns_it_on(self):
        telemetry.set_endpoint("https://t.example.com/in")
        self.assertEqual(self._ask(True), [False])
        self.assertTrue(telemetry.enabled())
        self.assertEqual(self._ask(True), [])

    def test_a_no_leaves_it_off_and_is_not_asked_again(self):
        telemetry.set_endpoint("https://t.example.com/in")
        self.assertEqual(self._ask(False), [False])
        self.assertFalse(telemetry.enabled())
        self.assertEqual(self._ask(True), [])
        self.assertFalse(telemetry.enabled())

    def test_it_is_not_asked_when_the_environment_forces_it_off(self):
        telemetry.set_endpoint("https://t.example.com/in")
        with patch.dict(os.environ, {"DO_NOT_TRACK": "1"}):
            self.assertEqual(self._ask(True), [])


class TestAgentLoopRecordsARun(_Home):
    def test_a_finished_run_is_queued_with_its_counts_when_opted_in(self):
        telemetry.turn_on()
        provider = FakeProvider(reply(tool_calls=[("Read", {"file_path": str(Path(self.tmp.name) / "nope.txt")}, "id1")],
                                      usage={"input_tokens": 1500, "output_tokens": 5}), reply("done"), name="ollama")
        provider.context_window = lambda _m: 8192
        conversation = Conversation(); conversation.add_user_message("read nope.txt")
        run_agent_loop(conversation=conversation, provider=provider, model="qwen-3b", tool_registry=build_default_registry(),
                       tool_context=ToolContext(workspace_root=Path(self.tmp.name)), verbose=False)
        run = telemetry.queued()[0]
        self.assertEqual((run["outcome"], run["tool_calls"], run["tool_errors"], run["first_input_tokens"], run["provider_kind"], run["index"]),
                         ("done", 1, 1, "1-2k", "local", "names"))
        self.assertNotIn("qwen", json.dumps(run))   # the model's name never appears

    def test_nothing_is_queued_when_it_is_off(self):
        provider = FakeProvider(reply("hi"), name="ollama")
        provider.context_window = lambda _m: 8192
        conversation = Conversation(); conversation.add_user_message("hi")
        run_agent_loop(conversation=conversation, provider=provider, model="qwen-3b", tool_registry=build_default_registry(),
                       tool_context=ToolContext(workspace_root=Path(self.tmp.name)), verbose=False)
        self.assertEqual(telemetry.queued(), [])


if __name__ == "__main__":
    unittest.main()
