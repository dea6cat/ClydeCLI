"""A cloud model checks weak replies from a small local model, once the user has said yes."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.agent_loop import run_agent_loop
from src.agent.cloud_review import review_reply, weak_reason
from src.agent.conversation import Conversation
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply


class TestWeakReason(unittest.TestCase):
    def test_empty_pretend_call_and_leaked_tokens_are_weak(self):
        self.assertEqual(weak_reason("  "), "empty reply")
        self.assertEqual(weak_reason("Let me look. [TOOL_SEARCH] select:Read"), "pretend tool call")
        self.assertEqual(weak_reason("word <|a|> word <|b|>"), "leaked special tokens")

    def test_a_short_refusal_to_reach_files_or_tools_is_weak(self):
        for refusal in ("Ah, sorry: the file `/tmp/x/notes.txt` doesn't exist in this folder.",
                        "I can explain the structure, but I can't guarantee access to files outside my sandboxed environment.",
                        "I'm unable to run Python here.", "I don't have access to your files.", "cat: notes.txt: No such file or directory"):
            self.assertEqual(weak_reason(refusal), "says it cannot reach files or tools", refusal)

    def test_a_correct_short_answer_and_a_plain_explanation_are_not_weak(self):
        for fine in ("391", "The third word is gamma.", "`git stash pop` applies the newest stash and drops it.",
                     "A process cannot access another process's memory without the OS allowing it.",
                     "Private members cannot be accessed from outside the class."):
            self.assertEqual(weak_reason(fine), "", fine)

    def test_a_long_answer_that_mentions_such_a_phrase_is_an_explanation_not_a_refusal(self):
        self.assertEqual(weak_reason("I can't run this in a sandboxed environment, but here is how it works. " + "Detail. " * 150), "")


class TestReviewReply(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.asked: list[str] = []
        self.answer = True
        self.ctx = ToolContext(workspace_root=Path(tmp.name))
        self.ctx.permission_handler = lambda name, message, suggestion: (self.asked.append(message) or self.answer, False)

    def _registry(self, *cloud_replies):
        return {"omlx": FakeProvider(name="omlx"), "anthropic": FakeProvider(*cloud_replies, name="anthropic", models=("m",))}

    def test_it_asks_once_then_replaces_each_weak_reply_with_the_cloud_models_correction(self):
        reg = self._registry(reply("the corrected answer"), reply("a second correction"))
        one = review_reply("q", "", self.ctx, registry=reg)
        two = review_reply("q2", "", self.ctx, registry=reg)
        self.assertIn("the corrected answer", one)
        self.assertIn("corrected by anthropic:m", one)
        self.assertIn("a second correction", two)
        self.assertEqual(len(self.asked), 1)
        self.assertIn("anthropic:m", self.asked[0])

    def test_a_no_is_remembered_and_nothing_is_sent(self):
        self.answer = False
        reg = self._registry()   # an empty script: any request to the cloud model would raise
        self.assertIsNone(review_reply("q", "", self.ctx, registry=reg))
        self.assertIsNone(review_reply("q", "", self.ctx, registry=reg))
        self.assertEqual(len(self.asked), 1)
        self.assertIs(self.ctx.cloud_review_ok, False)

    def test_an_ok_from_the_cloud_model_keeps_the_local_reply(self):
        self.assertIsNone(review_reply("q", "", self.ctx, registry=self._registry(reply("OK."))))

    def test_a_reply_that_looks_fine_is_never_sent_anywhere(self):
        self.assertIsNone(review_reply("q", "a fine answer", self.ctx, registry=self._registry()))
        self.assertEqual(self.asked, [])

    def test_with_no_cloud_model_connected_nothing_is_asked(self):
        self.assertIsNone(review_reply("q", "", self.ctx, registry={"omlx": FakeProvider(name="omlx")}))
        self.assertEqual(self.asked, [])

    def test_the_environment_switch_turns_it_off(self):
        with patch.dict(os.environ, {"CLYDE_CLOUD_REVIEW": "off"}):
            self.assertIsNone(review_reply("q", "", self.ctx, registry=self._registry(reply("x"))))
        self.assertEqual(self.asked, [])

    def test_a_cloud_error_keeps_the_local_reply(self):
        self.assertIsNone(review_reply("q", "", self.ctx, registry=self._registry(RuntimeError("boom"))))


class TestAgentLoopReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ToolContext(workspace_root=Path(self.tmp.name))

    def _run(self, provider):
        conversation = Conversation()
        conversation.add_user_message("explain this")
        chunks: list[str] = []
        result = run_agent_loop(conversation=conversation, provider=provider, model="m", tool_registry=build_default_registry(include_user_tools=False),
                                tool_context=self.ctx, verbose=False, stream=True, on_text_chunk=chunks.append)
        return conversation, result, "".join(chunks)

    def test_a_local_models_weak_reply_is_replaced_in_the_result_the_stream_and_the_history(self):
        with patch("src.agent.agent_loop.review_reply", return_value="the fix") as review:
            conversation, result, streamed = self._run(FakeProvider(reply("shaky"), name="omlx"))
        review.assert_called_once()
        self.assertEqual(review.call_args.args[:2], ("explain this", "shaky"))
        self.assertEqual(result.response_text, "the fix")
        self.assertIn("the fix", streamed)
        self.assertEqual(conversation.messages[-1].content, "the fix")

    def test_a_hosted_models_reply_is_never_reviewed(self):
        with patch("src.agent.agent_loop.review_reply") as review:
            _, result, _ = self._run(FakeProvider(reply("fine")))
        review.assert_not_called()
        self.assertEqual(result.response_text, "fine")

    def test_a_reply_that_review_leaves_alone_is_unchanged(self):
        with patch("src.agent.agent_loop.review_reply", return_value=None):
            conversation, result, streamed = self._run(FakeProvider(reply("fine"), name="omlx"))
        self.assertEqual((result.response_text, streamed, conversation.messages[-1].content), ("fine", "fine", "fine"))


if __name__ == "__main__":
    unittest.main()
