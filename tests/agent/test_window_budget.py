"""A request that can't fit the model's window is not sent: its system prompt and tool definitions count too."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent.agent_loop import run_agent_loop
from src.agent.subagent import build_tool_registry
from src.context_system.token_estimation import count_messages_tokens
from src.conversation import Conversation
from src.tool_system.context import ToolContext
from tests.fakes import FakeProvider, reply


class _Windowed(FakeProvider):
    """A fake whose runtime pins a context window, as a local server does."""

    def __init__(self, window: int, *responses):
        super().__init__(*responses)
        self.window = window

    def context_window(self, model: str) -> int:
        return self.window


def _run(provider: FakeProvider) -> tuple:
    conversation = Conversation()
    conversation.add_user_message("go")
    context = ToolContext(workspace_root=Path(tempfile.mkdtemp()))
    result = run_agent_loop(conversation, provider, "m", build_tool_registry(include_user_tools=False), context)
    return result, context


class TestWindowBudget(unittest.TestCase):
    def test_a_window_smaller_than_the_instructions_and_tools_sends_nothing(self):
        provider = _Windowed(500, reply("never sent"))
        result, _ = _run(provider)
        self.assertEqual(result.stop_reason, "window")
        self.assertEqual(provider.requests, [])
        self.assertIn("500-token window", result.response_text)

    def test_the_runtimes_own_count_stops_the_next_round(self):
        first = reply(tool_calls=[("Glob", {"pattern": "*.nothing"}, "t1")])
        first.prompt_tokens = 199_999   # the runtime says the first request all but filled the window
        provider = _Windowed(200_000, first, reply("never sent"))
        result, _ = _run(provider)
        self.assertEqual(result.stop_reason, "window")
        self.assertEqual(len(provider.requests), 1)

    def test_old_results_are_cleared_to_fit_before_giving_up(self):
        conversation = Conversation()
        conversation.add_user_message("go")
        for i in range(4):   # four big reads, each about 2,000 tokens; the usual trim keeps all four whole
            conversation.add_tool_result_message(f"old{i}", "word " * 2_000)
        context = ToolContext(workspace_root=Path(tempfile.mkdtemp()))
        probe = _Windowed(200_000, reply("sized"))
        run_agent_loop(Conversation(), probe, "m", build_tool_registry(include_user_tools=False), context)
        window = context.prompt_overhead + 4_000   # room for one big result, not four
        provider = _Windowed(window, reply("answered"))
        result = run_agent_loop(conversation, provider, "m", build_tool_registry(include_user_tools=False), context)
        self.assertEqual(result.stop_reason, "done")
        self.assertEqual(len(provider.requests), 1)

    def test_a_cleared_read_can_be_read_in_full_again(self):
        workspace = Path(tempfile.mkdtemp())
        a, b = workspace / "a.py", workspace / "b.py"
        for path in (a, b):
            path.write_text("x = 1\n" * 2_000, encoding="utf-8")
        context = ToolContext(workspace_root=workspace)

        def read(path: Path, call_id: str):
            return reply(tool_calls=[("Read", {"file_path": str(path)}, call_id)])

        sizing = Conversation()
        sizing.add_user_message("go")
        run_agent_loop(sizing, _Windowed(200_000, read(a, "s"), reply("sized")), "m",
                       build_tool_registry(include_user_tools=False), context)   # one read, to measure what a copy costs
        one_copy = count_messages_tokens(sizing.get_messages())
        context.read_file_fingerprints.clear()
        conversation = Conversation()
        conversation.add_user_message("go")
        # Room for one copy, not two: reading b clears a, and reading a again must return its content.
        provider = _Windowed(context.prompt_overhead + one_copy + one_copy // 2,
                             read(a, "r1"), read(b, "r2"), read(a, "r3"), reply("done"))
        result = run_agent_loop(conversation, provider, "m", build_tool_registry(include_user_tools=False), context)
        self.assertEqual(result.stop_reason, "done")
        outputs = [str(c.content) for m in conversation.messages if isinstance(m.content, list) for c in m.content
                   if getattr(c, "type", "") == "tool_result"]
        self.assertNotIn("file_unchanged", outputs[-1])   # the re-read got a's content back

    def test_a_request_that_fits_is_sent_and_its_fixed_part_recorded(self):
        provider = _Windowed(200_000, reply("all set"))
        result, context = _run(provider)
        self.assertEqual(result.stop_reason, "done")
        self.assertGreater(context.prompt_overhead, 0)   # the engine's pre-turn compaction check reads it


if __name__ == "__main__":
    unittest.main()
