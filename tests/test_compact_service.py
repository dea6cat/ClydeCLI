"""
Tests for the compact service.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union
from unittest.mock import patch

from src.agent.conversation import (
    Conversation,
    Message,
    TextContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
)
from src.providers.base import ProviderError
from tests.fakes import FakeProvider, reply


class MockConversation:
    """Mock conversation for testing (simple list-based)."""

    def __init__(self, messages=None):
        self.messages = messages or []

    def get_messages(self):
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.messages
        ]

    def clear(self):
        self.messages.clear()


class TestCompactBoundaryMessages(unittest.TestCase):
    """Tests for compact boundary message creation."""

    def test_creates_boundary_message(self):
        """Boundary message is created with correct properties."""
        from src.compact_service.messages import create_compact_boundary_message, is_compact_boundary_message
        msg = create_compact_boundary_message(
            trigger="manual",
            pre_compact_token_count=5000,
            messages_summarized=10,
        )
        self.assertTrue(is_compact_boundary_message(msg))
        self.assertEqual(msg.role, "system")
        self.assertTrue(getattr(msg, "_is_internal", False))

    def test_non_boundary_is_not_boundary(self):
        """Regular messages are not boundary messages."""
        from src.compact_service.messages import is_compact_boundary_message
        msg = Message(role="user", content="Hello")
        self.assertFalse(is_compact_boundary_message(msg))

    def test_get_messages_after_boundary_with_no_boundary(self):
        """Returns all messages when no boundary exists."""
        from src.compact_service.messages import get_messages_after_boundary
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi"),
        ]
        result = get_messages_after_boundary(messages)
        self.assertEqual(len(result), 2)

    def test_get_messages_after_boundary_with_boundary(self):
        """Returns only messages after last boundary."""
        from src.compact_service.messages import create_compact_boundary_message, get_messages_after_boundary
        messages = [
            Message(role="user", content="Old"),
            Message(role="assistant", content="Old response"),
        ]
        boundary = create_compact_boundary_message(trigger="manual")
        messages.append(boundary)
        messages.append(Message(role="user", content="New"))
        messages.append(Message(role="assistant", content="New response"))

        result = get_messages_after_boundary(messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].content, "New")
        self.assertEqual(result[1].content, "New response")

    def test_summary_message_format(self):
        """Summary message has correct role and content."""
        from src.compact_service.messages import create_compact_summary_message
        msg = create_compact_summary_message(
            "The user was working on a Python project. "
            "They asked about implementing a feature."
        )
        self.assertEqual(msg.role, "user")
        # msg.content is a list of ContentBlock, not a single TextContentBlock
        self.assertIn("continued from a previous conversation", msg.content[0].text)


class TestCompactConversation(unittest.TestCase):
    """Tests for compact_conversation()."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        """Clean up test fixtures."""
        self.tmpdir.cleanup()

    def _make_conversation(self, messages):
        """Create a Conversation with given messages."""
        conv = Conversation()
        conv.messages = messages
        return conv

    def test_not_enough_messages_raises(self):
        """Less than 2 messages raises ValueError."""
        from src.compact_service.service import compact_conversation
        conv = self._make_conversation([
            Message(role="user", content="Hello"),
        ])

        provider = FakeProvider(reply("Summary"))

        with self.assertRaises(ValueError) as ctx:
            asyncio.run(compact_conversation(conv, provider, "fake-model"))
        self.assertIn("Not enough messages", str(ctx.exception))

    def test_text_fallback_on_llm_failure(self):
        """Falls back to text extraction when the summary call fails."""
        from src.compact_service.service import compact_conversation
        conv = self._make_conversation([
            Message(role="user", content="Hello world " * 50),
            Message(role="assistant", content="Hi there! " * 50),
            Message(role="user", content="What about the code? " * 50),
        ])

        provider = FakeProvider(ProviderError("fake", "LLM failed"))

        result = asyncio.run(compact_conversation(conv, provider, "fake-model"))
        self.assertEqual(result.trigger, "manual")
        self.assertIn("Conversation had", result.summary_text)

    def test_boundary_and_summary_inserted(self):
        """Boundary and summary messages are inserted into conversation."""
        from src.compact_service.service import compact_conversation
        conv = self._make_conversation([
            Message(role="user", content="Hello world " * 50),
            Message(role="assistant", content="Hi there! " * 50),
            Message(role="user", content="What about the code? " * 50),
            Message(role="assistant", content="Here's the code... " * 50),
        ])
        original_count = len(conv.messages)

        provider = FakeProvider(reply("User worked on Python code. Assistant helped with implementation."))

        result = asyncio.run(compact_conversation(conv, provider, "fake-model"))

        # Boundary and summary are added (2 new messages)
        self.assertEqual(len(conv.messages), result.post_compact_count)
        self.assertLess(len(conv.messages), original_count)

        # Check that internal boundary is present
        boundary = next(
            (m for m in conv.messages if getattr(m, "_is_internal", False)),
            None
        )
        self.assertIsNotNone(boundary)

    def test_custom_instructions_passed_to_llm(self):
        """Custom instructions are included in the prompt."""
        from src.compact_service.service import compact_conversation
        conv = self._make_conversation([
            Message(role="user", content="Hello " * 20),
            Message(role="assistant", content="Hi " * 20),
        ])

        provider = FakeProvider(reply("Summary"))

        asyncio.run(compact_conversation(
            conv, provider, "fake-model",
            custom_instructions="Focus on the Python code"
        ))

        request = provider.requests[0]
        self.assertIn("Focus on the Python code", request["conversation"].messages[-1].text)
        self.assertEqual(request["tools"], ())
        self.assertEqual(request["reasoning"], "off")

    def test_summary_context_never_starts_mid_tool_pair(self):
        """The recent-message slice drops a leading tool result whose call was cut off."""
        from src.agent.conversation import TextContentBlock, ToolResultContentBlock, ToolUseContentBlock
        from src.compact_service.service import compact_conversation
        messages = []
        for i in range(12):
            messages.append(Message(role="user", content=f"step {i}"))
            messages.append(Message(role="assistant", content=[
                TextContentBlock(text="running"),
                ToolUseContentBlock(id=f"t{i}", name="Read", input={"file_path": "x"})]))
            messages.append(Message(role="user", content=[ToolResultContentBlock(tool_use_id=f"t{i}", content="ok")]))
        conv = self._make_conversation(messages)
        provider = FakeProvider(reply("Summary"))

        asyncio.run(compact_conversation(conv, provider, "fake-model"))

        first = provider.requests[0]["conversation"].messages[0]
        self.assertFalse(first.tool_results)
        self.assertEqual(first.role.value, "user")


class TestCompactIntegration(unittest.TestCase):
    """Integration tests for compact with mock REPL flow."""

    def test_compact_preserves_boundary_marker_in_serialization(self):
        """Boundary markers are preserved when conversation is serialized."""
        from src.compact_service.messages import create_compact_boundary_message
        conv = Conversation()
        conv.messages.append(Message(role="user", content="Hello"))
        conv.messages.append(Message(role="assistant", content="Hi"))
        boundary = create_compact_boundary_message(trigger="manual", pre_compact_token_count=1000)
        conv.messages.append(boundary)

        # Serialize
        data = conv.to_dict()
        self.assertEqual(len(data["messages"]), 3)

        # Boundary should have _is_internal=True in serialized form
        boundary_data = data["messages"][2]
        self.assertTrue(boundary_data.get("_is_internal", False))

        # Deserialize
        restored = Conversation.from_dict(data)
        self.assertEqual(len(restored.messages), 3)

        # Boundary should still be internal
        self.assertTrue(getattr(restored.messages[2], "_is_internal", False))

        # get_messages() should skip internal messages
        api_messages = restored.get_messages()
        self.assertEqual(len(api_messages), 2)  # Only user + assistant

    def test_compact_result_dataclass(self):
        """CompactionResult dataclass has expected fields."""
        from src.command_system.types import CompactionResult
        result = CompactionResult(
            pre_compact_count=10,
            post_compact_count=2,
            tokens_saved=5000,
            trigger="manual",
            summary_preview="User worked on...",
        )
        self.assertEqual(result.pre_compact_count, 10)
        self.assertEqual(result.post_compact_count, 2)
        self.assertEqual(result.tokens_saved, 5000)
        self.assertEqual(result.trigger, "manual")
        self.assertIn("User worked on", result.summary_preview)


if __name__ == "__main__":
    unittest.main()


class TestAutoCompact(unittest.TestCase):
    """Tests for the auto-compact threshold and the REPL hook."""

    def _conversation(self, words: int) -> Conversation:
        conv = Conversation()
        conv.add_user_message("word " * words)
        conv.add_assistant_message("ok")
        return conv

    def test_below_threshold_does_not_compact(self):
        from src.compact_service.service import needs_auto_compact
        self.assertFalse(needs_auto_compact(self._conversation(10), context_window=10_000))

    def test_above_threshold_compacts(self):
        from src.compact_service.service import needs_auto_compact
        self.assertTrue(needs_auto_compact(self._conversation(9_000), context_window=10_000))

    def test_single_message_never_compacts(self):
        from src.compact_service.service import needs_auto_compact
        conv = Conversation()
        conv.add_user_message("word " * 9_000)
        self.assertFalse(needs_auto_compact(conv, context_window=10_000))

    def test_repl_compacts_before_turn_when_full(self):
        from rich.console import Console
        from src.repl.core import ClydeREPL

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.session = type("S", (), {"conversation": self._conversation(9_000)})()
        repl.provider = FakeProvider(reply("Summary of the work"))
        repl.model = "fake-model"
        repl.console = Console(file=io.StringIO())
        with patch.object(ClydeREPL, "_context_window", return_value=10_000):
            repl._maybe_auto_compact()
        messages = repl.session.conversation.messages
        self.assertEqual(len(messages), 2)
        self.assertIn("Summary of the work", str(messages[1].content))
