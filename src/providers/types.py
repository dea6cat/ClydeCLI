"""Canonical, provider-agnostic request types.

A data model, never a wire format: each adapter serializes these fresh into its own
native JSON on every request and normalizes responses back into them. That
re-derivation is what makes switching provider or model mid-session safe. ClydeCLI's
stored history (src/agent/conversation.py) is converted into these by convert.py.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True)
class ToolCall:
    """A tool invocation the assistant requested. `id` is always present (synthesized
    when a provider such as Ollama's native API doesn't supply one), so tool_use /
    tool_result pairing works across providers."""
    id: str
    name: str
    arguments: dict[str, Any]
    # Opaque token the producing provider requires echoed back with this call (Gemini 3's
    # thoughtSignature). Other providers ignore it.
    signature: str | None = None

    @staticmethod
    def new(name: str, arguments: dict[str, Any], id: str | None = None,
            signature: str | None = None) -> "ToolCall":
        return ToolCall(id=id or f"call_{uuid.uuid4().hex[:12]}", name=name,
                        arguments=dict(arguments or {}), signature=signature)


@dataclass(slots=True)
class ToolResult:
    """The result of executing a ToolCall, keyed back by id, flattened to text."""
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(slots=True)
class Message:
    """One turn. Kept flat (not subclassed); the role decides which fields matter."""
    role: Role
    text: str | None = None
    thinking: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)

    @staticmethod
    def user(text: str) -> "Message":
        return Message(role=Role.USER, text=text)

    @staticmethod
    def assistant(text: str | None = None, thinking: str | None = None,
                  tool_calls: list[ToolCall] | None = None) -> "Message":
        return Message(role=Role.ASSISTANT, text=text, thinking=thinking, tool_calls=tool_calls or [])

    @staticmethod
    def results(results: list[ToolResult]) -> "Message":
        # Canonically a user-role turn carrying tool results; each adapter encodes it its own
        # way (Anthropic: tool_result blocks; OpenAI/Ollama: role=tool; Gemini: functionResponse).
        return Message(role=Role.USER, tool_results=list(results))


@dataclass(slots=True)
class Conversation:
    system_prompt: str
    messages: list[Message] = field(default_factory=list)

    def append(self, message: Message) -> None:
        self.messages.append(message)
