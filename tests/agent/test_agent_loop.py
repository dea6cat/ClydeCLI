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

    def test_a_local_model_is_sent_only_the_tools_the_prompt_asks_for(self):
        provider = FakeProvider(reply("done"), name="omlx")
        provider.context_window = lambda _model: 20000
        conversation = Conversation()
        conversation.add_user_message("review the login code")
        self._run(provider, conversation)
        sent = {t["name"].lower() if isinstance(t, dict) else t.name.lower() for t in provider.requests[0]["tools"]}
        self.assertEqual(sent, {"read", "grep", "glob", "toolsearch", "retrievecontext"})

    def _system_prompt_sent(self, provider_name, model):
        provider = FakeProvider(reply("done"), name=provider_name, models=(model,))
        provider.context_window = lambda _model: 20000
        conversation = Conversation()
        conversation.add_user_message("review the login code")
        run_agent_loop(conversation=conversation, provider=provider, model=model, tool_registry=self.registry,
                       tool_context=self.context, verbose=False)
        return provider.requests[0]["conversation"].system_prompt

    def test_a_small_local_model_gets_the_names_only_index_and_a_larger_one_the_full_index(self):
        small, larger, unknown = (self._system_prompt_sent("ollama", m) for m in ("qwen2.5-coder-3b", "qwen3-8b", "mystery-model"))
        self.assertIn("Not loaded, to save tokens:", small)
        self.assertNotIn("- Bash:", small)
        self.assertIn("- Bash:", larger)
        self.assertIn("- Bash:", unknown)   # an unknown size keeps the full index

    def test_a_hosted_model_never_gets_the_names_only_index(self):
        self.assertNotIn("Not loaded, to save tokens:", self._system_prompt_sent("openrouter", "tiny-1b"))

    def test_a_remote_model_still_gets_the_whole_core_set(self):
        provider = FakeProvider(reply("done"), name="openrouter")
        conversation = Conversation()
        conversation.add_user_message("review the login code")
        self._run(provider, conversation)
        sent = {t["name"].lower() if isinstance(t, dict) else t.name.lower() for t in provider.requests[0]["tools"]}
        self.assertTrue({"bash", "edit", "write"} <= sent)

    def test_a_local_model_has_its_old_tool_results_trimmed_between_rounds(self):
        provider = FakeProvider(reply("done"), name="omlx")
        provider.context_window = lambda _model: 4000
        conversation = Conversation()
        for i in range(8):
            conversation.add_user_message(f"step {i}")
            conversation.add_tool_result_message(f"id{i}", "x" * 4000)
        conversation.add_user_message("summarize")
        with patch("src.agent.agent_loop.trim_old_tool_results", wraps=__import__("src.context_system.microcompact", fromlist=["x"]).trim_old_tool_results) as trim:
            self._run(provider, conversation)
        trim.assert_called_once()
        self.assertEqual(trim.call_args.args[1], 4000)

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

    def test_steering_is_added_before_the_next_model_call_and_never_before_the_first(self):
        conversation = Conversation()
        conversation.add_user_message("Create hello.py")
        provider = self._write_then_done()
        pending = ["use double quotes", None]
        asked: list[int] = []

        def steer():
            asked.append(len(provider.requests))
            return pending.pop(0) if pending else None

        self._run(provider, conversation, steer=steer)

        self.assertEqual(asked, [1])   # not asked before the first call; asked once, before the second
        texts = [m.text for m in provider.requests[1]["conversation"].messages if m.role == Role.USER and m.text]
        self.assertTrue(texts[-1].endswith("use double quotes"))
        self.assertEqual(len([m for m in provider.requests[0]["conversation"].messages if m.role == Role.USER]), 1)

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

    def test_five_different_failing_tool_calls_in_a_row_stop_the_turn(self):
        """Different bad calls each time: the repeat guard does not fire, but the consecutive-error guard does."""
        conversation = Conversation()
        conversation.add_user_message("read some files")
        provider = FakeProvider(*[reply(tool_calls=[("Read", {"bogus_path": f"f{i}.txt"}, f"id{i}")]) for i in range(5)])

        result = self._run(provider, conversation)

        self.assertTrue(result.response_text.startswith("The tool calls keep failing"), result.response_text)
        self.assertEqual(len(provider.requests), 5)   # stopped after the fifth failing call

    def test_a_reply_cut_off_at_the_output_limit_is_continued_not_discarded(self):
        conversation = Conversation()
        conversation.add_user_message("write the essay")
        cut = reply("First half, ")
        cut.done_reason = "length"
        provider = FakeProvider(cut, reply("second half."))

        result = self._run(provider, conversation)

        self.assertEqual(result.response_text, "First half, second half.")
        self.assertIn("cut off before it finished", str(provider.requests[1]))

    def test_a_tool_denied_by_bare_name_is_not_sent_to_the_model(self):
        self.context.permission_rules = {"allow": [], "ask": [], "deny": ["WebFetch"]}
        conversation = Conversation()
        conversation.add_user_message("hi")
        provider = FakeProvider(reply("Hello."))
        with patch.dict("os.environ", {"CLYDE_ALL_TOOLS": "1"}):   # every tool sent, so only the rule can drop it
            self._run(provider, conversation)
        sent = {t["name"] if isinstance(t, dict) else t.name for t in provider.requests[0]["tools"]}
        self.assertNotIn("WebFetch", sent)
        self.assertIn("Read", sent)

    def _hooks(self, event, command):
        return {event: [{"matcher": "", "hooks": [{"command": command, "timeout": 10}]}]}

    def test_a_stop_hook_keeps_the_turn_going_until_it_passes(self):
        flag = self.workspace / "checked"
        self.context.hooks = self._hooks("Stop", f"test -f {flag} || {{ touch {flag}; echo 'run the tests first' >&2; exit 2; }}")
        conversation = Conversation()
        conversation.add_user_message("fix it")
        provider = FakeProvider(reply("Done."), reply("Tests pass. Done."))

        result = self._run(provider, conversation)

        self.assertEqual(result.response_text, "Tests pass. Done.")
        self.assertIn("run the tests first", str(provider.requests[1]))

    def test_a_stop_hook_that_never_passes_is_overridden_after_eight_blocks(self):
        self.context.hooks = self._hooks("Stop", "echo 'not yet' >&2; exit 2")
        conversation = Conversation()
        conversation.add_user_message("fix it")
        provider = FakeProvider(*[reply(f"try {i}") for i in range(12)])

        result = self._run(provider, conversation)

        self.assertEqual((result.response_text, len(provider.requests)), ("try 8", 9))

    def test_the_users_prompt_is_never_a_turn_clyde_added(self):
        from src.agent.agent_loop import _ANSWER_NUDGE, _HOOK_CONTEXT, _STOP_HOOK, _last_prompt
        conversation = Conversation()
        conversation.add_user_message("why does the build fail?")
        for injected in (_HOOK_CONTEXT + "freeze", _STOP_HOOK + "run tests", _ANSWER_NUDGE):
            conversation.add_user_message(injected)
        self.assertEqual(_last_prompt(conversation), "why does the build fail?")

    def test_the_stop_cap_counts_blocks_with_no_tool_call_between_them(self):
        self.context.hooks = self._hooks("Stop", "echo 'not yet' >&2; exit 2")
        conversation = Conversation()
        conversation.add_user_message("fix it")
        replies = [reply(f"try {i}") for i in range(7)]
        replies += [reply(tool_calls=[("Glob", {"pattern": "*.py"}, "g1")])]          # work in between: count restarts
        replies += [reply(f"again {i}") for i in range(12)]
        provider = FakeProvider(*replies)

        result = self._run(provider, conversation, max_turns=30)

        self.assertEqual((result.response_text, len(provider.requests)), ("again 8", 17))

    def test_a_user_prompt_submit_hook_adds_context_or_blocks_the_prompt(self):
        self.context.hooks = self._hooks("UserPromptSubmit", "echo 'Release freeze: no merges today.'")
        conversation = Conversation()
        conversation.add_user_message("merge it")
        provider = FakeProvider(reply("I won't merge today."))
        self._run(provider, conversation)
        self.assertIn("Release freeze: no merges today.", str(provider.requests[0]))

        self.context.hooks = self._hooks("UserPromptSubmit", "echo 'secrets in prompt' >&2; exit 2")
        conversation = Conversation()
        conversation.add_user_message("here is my key sk-123")
        provider = FakeProvider(reply("never sent"))
        result = self._run(provider, conversation)
        self.assertEqual((len(provider.requests), result.response_text),
                         (0, "Prompt blocked by a UserPromptSubmit hook: secrets in prompt"))

    def test_a_continuation_that_restarts_the_cut_line_is_not_doubled(self):
        from src.agent.agent_loop import _continue
        self.assertEqual(_continue("- May: warm\n- June:", "- June: Hot and dry.\n- July: hotter"),
                         "- May: warm\n- June: Hot and dry.\n- July: hotter")   # live, ministral-8b
        self.assertEqual(_continue("- Aug: hot\n- September: Gradual", "- September: Mild and pleasant."),
                         "- Aug: hot\n- September: Mild and pleasant.")                  # restarted with other words
        self.assertEqual(_continue("- April: mild\n- May: Pleasant and sunny", "- June: Hot and dry."),
                         "- April: mild\n- May: Pleasant and sunny\n- June: Hot and dry.")   # next item, own line
        self.assertEqual(_continue("Once upon", " a time"), "Once upon a time")

    def test_a_reply_with_no_answer_text_is_asked_for_again_a_bounded_number_of_times(self):
        conversation = Conversation()
        conversation.add_user_message("hi")
        provider = FakeProvider(reply(thinking="hmm"), reply("Hello."))
        self.assertEqual(self._run(provider, conversation).response_text, "Hello.")

        conversation = Conversation()
        conversation.add_user_message("hi")
        provider = FakeProvider(*[reply(thinking="hmm") for _ in range(6)])
        self.assertEqual(self._run(provider, conversation).response_text, "")
        self.assertEqual(len(provider.requests), 4)   # the reply, then 3 asks again

    def test_out_of_tool_turns_the_model_wraps_up_in_text_with_no_tools(self):
        conversation = Conversation()
        conversation.add_user_message("refactor everything")
        provider = FakeProvider(*[reply(tool_calls=[("Glob", {"pattern": f"*{i}.py"}, f"g{i}")]) for i in range(2)],
                                reply("Done: scanned the files. Left: the edits. Next: say continue."))

        result = self._run(provider, conversation, max_turns=2)

        self.assertTrue(result.ran_out)
        self.assertEqual(result.response_text, "Done: scanned the files. Left: the edits. Next: say continue.")
        self.assertFalse(provider.requests[-1]["tools"])   # no tools offered
        self.assertIn("used every tool turn", str(provider.requests[-1]))

    def test_out_of_tool_turns_with_no_wrap_up_still_says_so(self):
        from src.agent.agent_loop import MAX_TURNS_REPLY
        conversation = Conversation()
        conversation.add_user_message("refactor everything")
        provider = FakeProvider(*[reply(tool_calls=[("Glob", {"pattern": f"*{i}.py"}, f"g{i}")]) for i in range(2)])
        result = self._run(provider, conversation, max_turns=2)   # the provider has nothing left for the wrap-up
        self.assertEqual((result.response_text, result.ran_out), (MAX_TURNS_REPLY, True))

    def test_an_error_followed_by_a_success_resets_the_counter(self):
        conversation = Conversation()
        conversation.add_user_message("read hello.py")
        provider = FakeProvider(
            reply(tool_calls=[("Read", {"bogus_path": "nope.txt"}, "id1")]),
            reply(tool_calls=[("Write", {"file_path": str(self.hello), "content": "x"}, "id2")]),
            reply("done"),
        )

        result = self._run(provider, conversation)

        self.assertEqual(result.response_text, "done")


if __name__ == "__main__":
    unittest.main()


class TestBashSummary(unittest.TestCase):
    def test_bash_summary_shows_the_last_output_line(self):
        from src.agent.agent_loop import summarize_tool_result
        self.assertEqual(summarize_tool_result("Bash", {"exit_code": 0, "stdout": "a\nDetected 12 files\n\n", "stderr": ""}),
                         "Bash · exit=0 · Detected 12 files")
        self.assertEqual(summarize_tool_result("Bash", {"exit_code": 2, "stdout": "ok", "stderr": "boom\n"}), "Bash · exit=2 · boom")
        self.assertEqual(summarize_tool_result("Bash", {"exit_code": 0, "stdout": "", "stderr": ""}), "Bash · exit=0")
