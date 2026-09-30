"""Agent loop tests against a scripted provider (real stream() contract, no network)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.conversation import Conversation, ThinkingContentBlock
from src.providers.base import ProviderError
from src.providers.types import Role
from src.agent.agent_loop import AgentLoopResult, run_agent_loop
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply


class TestAgentLoop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.registry = build_default_registry()
        self.context = ToolContext(workspace_root=self.workspace)
        self.hello = self.workspace / "hello.py"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run(self, provider, conversation, **kwargs):
        return run_agent_loop(conversation=conversation, provider=provider, model="fake-model",
                              tool_registry=self.registry, tool_context=self.context, verbose=False, **kwargs)

    def _write_then_done(self):
        return FakeProvider(
            reply("I will create the file.",
                  tool_calls=[("Write", {"file_path": str(self.hello), "content": "print('hello world')"}, "toolu_1")],
                  usage={"input_tokens": 10, "output_tokens": 20}),
            reply("File created successfully!", usage={"input_tokens": 30, "output_tokens": 10}),
        )

    def test_dispatches_tool_and_returns_final_text(self):
        conversation = Conversation()
        conversation.add_user_message("Create hello.py")
        provider = self._write_then_done()

        result = self._run(provider, conversation)

        self.assertIsInstance(result, AgentLoopResult)
        self.assertEqual(result.response_text, "File created successfully!")
        self.assertEqual(result.num_turns, 2)
        self.assertEqual(result.usage, {"input_tokens": 40, "output_tokens": 30})
        self.assertEqual(self.hello.read_text(), "print('hello world')")
        self.assertEqual(len(provider.requests), 2)

    def test_second_turn_replays_tool_call_and_result(self):
        conversation = Conversation()
        conversation.add_user_message("Create hello.py")
        provider = self._write_then_done()

        self._run(provider, conversation)

        second = provider.requests[1]["conversation"].messages
        self.assertEqual([m.role for m in second], [Role.USER, Role.ASSISTANT, Role.USER])
        self.assertEqual(second[1].tool_calls[0].id, "toolu_1")
        self.assertEqual(second[2].tool_results[0].tool_call_id, "toolu_1")
        self.assertFalse(second[2].tool_results[0].is_error)
        self.assertEqual(provider.requests[1]["model"], "fake-model")
        self.assertIn("Write", [t.name for t in provider.requests[0]["tools"]])

    def test_stream_emits_text_from_every_turn(self):
        conversation = Conversation()
        conversation.add_user_message("Create hello.py")
        chunks: list[str] = []

        result = self._run(self._write_then_done(), conversation, stream=True, on_text_chunk=chunks.append)

        self.assertEqual("".join(chunks), "I will create the file.File created successfully!")
        self.assertEqual(result.response_text, "File created successfully!")

    def test_no_stream_does_not_emit_chunks(self):
        conversation = Conversation()
        conversation.add_user_message("Say hello")
        chunks: list[str] = []

        result = self._run(FakeProvider(reply("Hello from Clyde!")), conversation, on_text_chunk=chunks.append)

        self.assertEqual(chunks, [])
        self.assertEqual(result.response_text, "Hello from Clyde!")
        self.assertEqual(conversation.messages[-1].content, "Hello from Clyde!")

    def test_tool_error_is_reported_back_to_model(self):
        conversation = Conversation()
        conversation.add_user_message("Read a missing file")
        provider = FakeProvider(
            reply(tool_calls=[("Read", {"file_path": str(self.workspace / "missing.txt")}, "toolu_x")]),
            reply("It doesn't exist."),
        )

        self._run(provider, conversation)

        result_msg = provider.requests[1]["conversation"].messages[-1]
        self.assertTrue(result_msg.tool_results[0].is_error)

    def test_wrapped_tool_arguments_are_unwrapped(self):
        target = self.workspace / "note.txt"
        target.write_text("hi")
        conversation = Conversation()
        conversation.add_user_message("Read note.txt")
        provider = FakeProvider(
            reply(tool_calls=[("Read", {"arguments": {"file_path": str(target)}}, "toolu_r")]),
            reply("done"),
        )

        self._run(provider, conversation)

        self.assertFalse(provider.requests[1]["conversation"].messages[-1].tool_results[0].is_error)

    def test_thinking_is_stored_and_replayed(self):
        conversation = Conversation()
        conversation.add_user_message("Create hello.py")
        provider = FakeProvider(
            reply(thinking="plan it", tool_calls=[("Write", {"file_path": str(self.hello), "content": "x"}, "t1")]),
            reply("ok"),
        )

        self._run(provider, conversation)

        self.assertIsInstance(conversation.messages[1].content[0], ThinkingContentBlock)
        self.assertEqual(provider.requests[1]["conversation"].messages[1].thinking, "plan it")

    def test_reasoning_level_is_forwarded(self):
        conversation = Conversation()
        conversation.add_user_message("hi")
        provider = FakeProvider(reply("hey"))

        self._run(provider, conversation, reasoning="high")

        self.assertEqual(provider.requests[0]["reasoning"], "high")

    def test_retryable_error_is_retried(self):
        conversation = Conversation()
        conversation.add_user_message("hi")
        provider = FakeProvider(ProviderError("fake", "HTTP 503", retryable=True), reply("recovered"))

        with patch("src.providers.base._time.sleep"):
            result = self._run(provider, conversation)

        self.assertEqual(result.response_text, "recovered")
        self.assertEqual(len(provider.requests), 2)

    def test_non_retryable_error_propagates(self):
        conversation = Conversation()
        conversation.add_user_message("hi")
        provider = FakeProvider(ProviderError("fake", "HTTP 401 — authentication failed", status=401))

        with self.assertRaises(ProviderError):
            self._run(provider, conversation)
        self.assertEqual(len(provider.requests), 1)


if __name__ == "__main__":
    unittest.main()


class TestBashSummary(unittest.TestCase):
    def test_bash_summary_shows_the_last_output_line(self):
        from src.agent.agent_loop import summarize_tool_result
        self.assertEqual(summarize_tool_result("Bash", {"exit_code": 0, "stdout": "a\nDetected 12 files\n\n", "stderr": ""}),
                         "Bash · exit=0 · Detected 12 files")
        self.assertEqual(summarize_tool_result("Bash", {"exit_code": 2, "stdout": "ok", "stderr": "boom\n"}), "Bash · exit=2 · boom")
        self.assertEqual(summarize_tool_result("Bash", {"exit_code": 0, "stdout": "", "stderr": ""}), "Bash · exit=0")
