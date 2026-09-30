"""Session trace: JSONL events from a real agent-loop turn, redaction, opt-out, pruning and /debug."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.agent import trace
from src.agent.agent_loop import run_agent_loop
from src.agent.conversation import Conversation
from src.providers.base import ProviderError
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply

SECRET = "sk-live-abcdefghijklmnopqrstuvwxyz0123"


class TraceTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        for p in (patch("pathlib.Path.home", return_value=self.home),
                  patch.dict(os.environ, {"CLYDE_TRACE": "on", "OPENAI_API_KEY": SECRET})):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(trace.start, "", enabled=False)   # leave the module inactive for other tests

    def trace_file(self, session_id="s1") -> Path:
        return self.home / ".clyde" / "traces" / f"{session_id}.jsonl"

    def events(self, session_id="s1"):
        return [json.loads(line) for line in self.trace_file(session_id).read_text().splitlines()]


class TestTraceAgentLoop(TraceTestCase):
    def _run(self, *responses):
        workspace = self.home / "ws"
        workspace.mkdir(exist_ok=True)
        conversation = Conversation()
        conversation.add_user_message("go")
        run_agent_loop(conversation, FakeProvider(*responses), "fake-model", build_default_registry(),
                       ToolContext(workspace_root=workspace), verbose=False)

    def test_turn_with_tool_call_writes_model_and_tool_events(self):
        trace.start("s1")
        target = self.home / "ws" / "a.txt"
        self._run(reply("writing", tool_calls=[("Write", {"file_path": str(target), "content": "hi"}, "t1")],
                        usage={"input_tokens": 10, "output_tokens": 5}),
                  reply("done", usage={"input_tokens": 20, "output_tokens": 3}))

        events = self.events()
        self.assertEqual([e["event"] for e in events], ["model_request", "tool_call", "model_request"])
        first, tool, second = events
        self.assertEqual((first["provider"], first["model"], first["messages"]), ("fake", "fake-model", 1))
        self.assertEqual(first["usage"], {"input_tokens": 10, "output_tokens": 5})
        self.assertEqual(first["tool_calls"], 1)
        self.assertGreater(first["est_input_tokens"], 0)
        self.assertIsInstance(first["duration_ms"], int)
        self.assertEqual(second["messages"], 3)
        self.assertEqual(tool["name"], "Write")
        self.assertFalse(tool["is_error"])
        self.assertGreater(tool["result_chars"], 0)
        self.assertIn("a.txt", tool["input"])

    def test_secrets_are_redacted_and_long_strings_truncated(self):
        trace.start("s1")
        target = self.home / "ws" / "a.txt"
        content = f"key={SECRET} " + "x" * 2000
        self._run(reply(tool_calls=[("Write", {"file_path": str(target), "content": content, "api_key": "hunter2"}, "t1")]),
                  reply("done"))

        raw = self.trace_file().read_text()
        self.assertNotIn(SECRET, raw)
        self.assertNotIn("hunter2", raw)
        tool = self.events()[1]
        self.assertLessEqual(len(tool["input"]), trace.MAX_CHARS + 30)
        self.assertIn("[redacted]", tool["input"])

    def test_model_error_is_recorded_and_propagates(self):
        trace.start("s1")
        with self.assertRaises(ProviderError):
            self._run(ProviderError("fake", "bad request"))
        event = self.events()[0]
        self.assertEqual(event["event"], "model_request")
        self.assertIn("bad request", event["error"])

    def test_opt_out_writes_nothing(self):
        with patch.dict(os.environ, {"CLYDE_TRACE": "off"}):
            trace.start("s1")
            self._run(reply("done"))
        trace.start("s2", enabled=False)
        trace.record("turn")
        self.assertFalse((self.home / ".clyde" / "traces").exists())

    def test_live_prints_to_stderr(self):
        trace.start("s1", live=True)
        with patch("sys.stderr") as err:
            self._run(reply("done", usage={"input_tokens": 7, "output_tokens": 2}))
        printed = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertIn("[trace] model fake:fake-model msgs=1 in=7 out=2", printed)


class _AskTool:
    def spec(self):
        from src.tool_system.registry import ToolSpec
        return ToolSpec(name="Ask", description="", input_schema={"type": "object"})

    def check_permissions(self, tool_input, context):
        from src.tool_system.permission_handler import PermissionResult
        return PermissionResult.ask("may I?")

    def run(self, tool_input, context):
        from src.tool_system.protocol import ToolResult
        return ToolResult(name="Ask", output="ran")


class TestTraceDispatchAndCompact(TraceTestCase):
    def test_permission_ask_answer_and_hook_block(self):
        from src.tool_system.protocol import ToolCall
        from src.tool_system.registry import ToolRegistry

        trace.start("s1")
        registry = ToolRegistry([_AskTool()])
        context = ToolContext(workspace_root=self.home)
        context.permission_handler = lambda name, message, suggestion: (False, False)
        registry.dispatch(ToolCall(name="Ask", input={}), context)
        context.hooks = {"PreToolUse": [{"matcher": "*", "hooks": [{"command": "echo nope >&2; exit 2"}]}]}
        registry.dispatch(ToolCall(name="Ask", input={}), context)

        events = self.events()
        self.assertEqual([e["event"] for e in events], ["permission_ask", "permission_answer", "hook_block"])
        self.assertEqual(events[0]["message"], "may I?")
        self.assertFalse(events[1]["allowed"])
        self.assertEqual(events[2]["reason"], "nope")

    def test_compaction_is_recorded(self):
        import asyncio
        from src.compact_service.service import compact_conversation

        trace.start("s1")
        conversation = Conversation()
        conversation.add_user_message("hello")
        conversation.add_assistant_message("hi")
        asyncio.run(compact_conversation(conversation, FakeProvider(reply("summary")), "fake-model"))

        kinds = [e["event"] for e in self.events()]
        self.assertEqual(kinds, ["model_request", "compact"])
        compact = self.events()[1]
        self.assertEqual((compact["trigger"], compact["fallback_summary"]), ("manual", False))


class TestTraceFile(TraceTestCase):
    def test_unwritable_trace_file_is_ignored(self):
        trace.start("s1")
        (self.home / ".clyde").mkdir()
        (self.home / ".clyde" / "traces").write_text("not a dir")
        trace.record("turn")   # must not raise

    def test_start_prunes_to_newest_files(self):
        folder = self.home / ".clyde" / "traces"
        folder.mkdir(parents=True)
        for i in range(trace.KEEP_FILES + 5):
            path = folder / f"old{i}.jsonl"
            path.write_text("")
            os.utime(path, (i, i))
        trace.start("s1")
        left = {p.name for p in folder.glob("*.jsonl")}
        self.assertEqual(len(left), trace.KEEP_FILES)
        self.assertNotIn("old0.jsonl", left)
        self.assertIn(f"old{trace.KEEP_FILES + 4}.jsonl", left)


class TestDebugCommand(TraceTestCase):
    def _printed(self, repl, command: str) -> str:
        repl.console.print.reset_mock()
        repl.handle_command(command)
        return "\n".join(str(c.args[0]) for c in repl.console.print.call_args_list if c.args)

    def test_debug_shows_last_turn_and_path(self):
        from src.repl import ClydeREPL

        provider = FakeProvider(reply(tool_calls=[("NoSuchTool", {}, "t1")], usage={"input_tokens": 4, "output_tokens": 1}),
                                reply("ok", usage={"input_tokens": 6, "output_tokens": 2}),
                                reply("again", usage={"input_tokens": 9, "output_tokens": 1}),
                                name="glm", models=("glm-4.5",))
        with patch("src.repl.core.build_registry", return_value={"glm": provider}), \
                patch("src.repl.core.keys.load_into_env"):
            repl = ClydeREPL(model="glm:glm-4.5")
            repl.console.print = Mock()
            repl.chat("first")
            first = self._printed(repl, "/debug")
            repl.chat("second")
            second = self._printed(repl, "/debug")
            path_out = self._printed(repl, "/debug path")

        self.assertIn("model glm:glm-4.5 msgs=1 in=4 out=1", first)
        self.assertIn("tool NoSuchTool", first)
        self.assertIn("ERROR", first)
        self.assertIn("Totals: 2 model call(s)", first)
        self.assertIn("in=10 out=3 · 1 tool call(s)", first)
        self.assertIn("1 error(s)", first)
        self.assertIn("Totals: 1 model call(s)", second)
        self.assertIn("in=9 out=1 · 0 tool call(s)", second)
        self.assertEqual(path_out, str(self.trace_file(repl.session.session_id)))


if __name__ == "__main__":
    unittest.main()
