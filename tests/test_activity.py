"""The spinner says what the turn is waiting for, with a live counter: the shared phrase, the text, the ticker and
the layers that set the phrase."""

from __future__ import annotations

import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import activity
from src.agent.agent_loop import run_agent_loop
from src.agent.conversation import Conversation
from src.providers import base
from src.providers.base import ProviderError
from src.providers.card_shuffle import LAYA_WAIT, CardShuffle, Verdict
from src.repl import core
from src.repl.core import _spin_text
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply


class TestSpinText(unittest.TestCase):
    def setUp(self):
        activity.clear()
        self.addCleanup(activity.clear)

    def test_the_word_alone_in_the_first_second(self):
        self.assertEqual(_spin_text("Dealing", 100.0, now=100.4), "[#8a8a8a]Dealing…[/#8a8a8a]".replace("#8a8a8a", core._CARD_DIM))

    def test_it_adds_the_elapsed_time_and_what_it_is_waiting_for(self):
        activity.set("waiting for nvidia:meta/muse-glimmer-30b")
        text = _spin_text("Dealing", 100.0, now=112.0)
        self.assertIn("Dealing… · 12s · waiting for nvidia:meta/muse-glimmer-30b", text)
        self.assertIn("6m 20s", _spin_text("Dealing", 0.0, now=380.0))

    def test_square_brackets_in_the_phrase_are_not_markup(self):
        activity.set("waiting for [bold]x[/bold]")
        self.assertIn(r"waiting for \[bold]x\[/bold]", _spin_text("Dealing", 0.0, now=5.0))


class _Status:
    def __init__(self):
        self.updates: list[str] = []

    def update(self, text):
        self.updates.append(text)


class TestTicker(unittest.TestCase):
    def setUp(self):
        activity.clear()
        self.addCleanup(activity.clear)
        patcher = patch.object(core, "_TICK", 0.03)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repl = core.ClydeREPL.__new__(core.ClydeREPL)

    def test_the_text_is_rewritten_while_it_waits_and_follows_the_phrase(self):
        status = _Status()
        started = time.monotonic() - 5
        with self.repl._ticking(status, "Dealing", started):
            activity.set("asking Laya how hard this is")
            time.sleep(0.2)
        self.assertGreaterEqual(len(status.updates), 3)
        self.assertTrue(all(re.search(r"· [56]\.\ds", u) for u in status.updates), status.updates)   # counting from the turn's start
        self.assertIn("asking Laya how hard this is", status.updates[-1])

    def test_it_stops_when_the_block_ends_and_pauses_while_text_streams(self):
        status = _Status()
        streaming = [True]
        with self.repl._ticking(status, "Dealing", time.monotonic(), lambda: not streaming[0]):
            time.sleep(0.15)
        self.assertEqual(status.updates, [])                                       # inactive: the stopped spinner is left alone
        before = len(status.updates)
        time.sleep(0.15)
        self.assertEqual(len(status.updates), before)                              # and no ticker thread is left running
        self.assertFalse(any(t.name == "spinner-ticker" and t.is_alive() for t in threading.enumerate()))


class TestLayersSetThePhrase(unittest.TestCase):
    def setUp(self):
        activity.clear()
        self.addCleanup(activity.clear)

    def test_a_retry_names_the_attempt_and_the_reason(self):
        seen: list[str] = []

        class Flaky:
            name = "p"
            calls = 0

            def stream(self, *args, **kwargs):
                Flaky.calls += 1
                if Flaky.calls == 1:
                    raise ProviderError("p", "HTTP 503 — provider error", retryable=True, status=503)
                return reply("ok")

        def fake_sleep(_seconds):
            seen.append(activity.get())

        with patch.object(base._time, "sleep", fake_sleep):
            base.stream_with_retry(Flaky(), Conversation(), "m", (), lambda _t: None, retries=3)
        self.assertTrue(seen and seen[0].startswith("retry 1 of 3 in 1s: HTTP 503"), seen)

    def test_cardshuffle_says_it_is_waiting_for_laya_then_asking_it_then_for_the_model(self):
        seen: list[str] = []
        evals = {"fake:m": {"passed": True, "strength": 4}}
        with patch("src.providers.card_shuffle.load_results", return_value=evals):
            fake = FakeProvider(name="fake")
            card = CardShuffle({"fake": fake}, ask=lambda *a: seen.append(activity.get()) or None,
                               wait=lambda t: seen.append(activity.get()) or True, verdict=Verdict([]))
            card.shuffle("house", "make this rhyme")
        self.assertEqual(seen, [f"waiting up to {LAYA_WAIT}s for Laya to load", "asking Laya how hard this is"])
        self.assertEqual(activity.get(), "waiting for fake:m")

    def test_the_agent_loop_names_the_model_it_waits_for_and_the_tool_it_runs(self):
        seen: list[str] = []

        class Watching(FakeProvider):
            def stream(self, *args, **kwargs):
                seen.append(activity.get())
                return super().stream(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.txt"
            target.write_text("x")
            provider = Watching(reply("", tool_calls=[("Read", {"file_path": str(target)}, "t1")]), reply("done"), name="fake")
            seen_tool: list[str] = []
            registry = build_default_registry(include_user_tools=False)
            real_dispatch = registry.dispatch

            def watching_dispatch(call, context):
                seen_tool.append(activity.get())
                return real_dispatch(call, context)

            registry.dispatch = watching_dispatch  # type: ignore[method-assign]
            conversation = Conversation()
            conversation.add_user_message("read it")
            run_agent_loop(conversation=conversation, provider=provider, model="fake-model", tool_registry=registry,
                           tool_context=ToolContext(workspace_root=Path(tmp)), verbose=False)
        self.assertEqual(seen, ["waiting for fake:fake-model", "waiting for fake:fake-model"])
        self.assertEqual(seen_tool, ["running Read"])


if __name__ == "__main__":
    unittest.main()
