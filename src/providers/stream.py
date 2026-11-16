"""One streamed reply as it arrives, whatever the wire format.

Each adapter parses its own events and hands the pieces to a StreamReply: text and thinking (passed on to the listeners as
they come), tool calls (whole, or as streamed fragments), why the reply stopped and what it cost. The reply then adds up
to the ProviderResponse the same way for every provider:

- why it stopped is said one way: "length" for a reply cut off at the output limit, however the service spells it
  (OpenAI `length`, Anthropic `max_tokens`, Gemini `MAX_TOKENS`), so the agent loop asks the model to continue it;
- a stream that ends before the service said it was done is an error worth retrying, never a complete answer;
- a provider that opts in (the local servers, whose small models often write a tool call as JSON text) gets those calls
  recovered from the text.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .base import ProviderError, ProviderResponse
from .toolcall_repair import recover_toolcalls
from .toolspec import ToolSpec
from .types import Message, ToolCall

CUT_OFF = "length"
_SPELLINGS = {"length": CUT_OFF, "max_tokens": CUT_OFF}   # compared lowercased: Gemini says MAX_TOKENS


def stop_reason(raw: str) -> str:
    """A service's stop reason, with every spelling of "cut off at the output limit" made "length"."""
    return _SPELLINGS.get(raw.lower(), raw.lower())


def _arguments(raw: Any) -> dict:
    """Tool-call arguments as a dict: a JSON string is parsed, and a broken one becomes {} (the tool's own validation then
    tells the model what was missing). Never repaired: a cut-off argument string could otherwise run with half its content."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


class StreamReply:
    """What one streamed reply has said so far."""

    def __init__(self, provider: str, on_text: Callable[[str], None], on_thinking: Callable[[str], None] | None = None):
        self.provider = provider
        self._on_text, self._on_thinking = on_text, on_thinking
        self._text: list[str] = []
        self._thinking: list[str] = []
        self._calls: list[ToolCall] = []
        self._parts: dict[int, dict] = {}   # streamed tool-call fragments by index
        self.stop_reason: str | None = None
        self.finished = False
        self.usage: dict | None = None
        self.prompt_tokens: int | None = None   # set when the service counts it differently from usage

    def text(self, chunk: Any) -> None:
        if isinstance(chunk, str) and chunk:
            self._text.append(chunk)
            self._on_text(chunk)

    def thinking(self, chunk: Any) -> None:
        if isinstance(chunk, str) and chunk:
            self._thinking.append(chunk)
            if self._on_thinking is not None:
                self._on_thinking(chunk)

    def tool_call(self, name: str, arguments: Any, *, id: str | None = None, signature: str | None = None) -> None:  # pylint: disable=redefined-builtin
        """A tool call that arrived whole."""
        self._calls.append(ToolCall.new(name=name, arguments=_arguments(arguments), id=id, signature=signature))

    def tool_call_part(self, index: int, *, id: str | None = None, name: str | None = None, arguments: str = "") -> None:  # pylint: disable=redefined-builtin
        """A fragment of a tool call streamed in pieces: the id and name once, the arguments as JSON text in parts."""
        slot = self._parts.setdefault(index, {"id": None, "name": "", "args": ""})
        if id:
            slot["id"] = id
        if name:
            slot["name"] = name
        slot["args"] += arguments or ""

    def note_stop(self, reason: Any) -> None:
        """Why the reply stopped, when the service says so before it is done."""
        if isinstance(reason, str) and reason:
            self.stop_reason = stop_reason(reason)

    def stop(self, reason: Any = None) -> None:
        """The service said the reply is complete (optionally with why it stopped)."""
        self.note_stop(reason)
        self.finished = True

    def response(self, tools: tuple[ToolSpec, ...] = (), *, repair_text_calls: bool = False, raw: dict | None = None) -> ProviderResponse:
        """The finished reply. Raises a retryable ProviderError when the stream ended before the service said it was done."""
        if not self.finished:
            raise ProviderError(self.provider, "stream ended before the response finished", retryable=True)
        calls = self._calls + [ToolCall.new(name=s["name"], arguments=_arguments(s["args"]), id=s["id"])
                               for _, s in sorted(self._parts.items())]
        text = "".join(self._text).strip()
        if repair_text_calls and not calls and text:
            calls = [ToolCall.new(name=n, arguments=a) for n, a in recover_toolcalls(text, [t.name for t in tools])]
        thinking = "".join(self._thinking).strip()
        prompt_tokens = self.prompt_tokens
        if prompt_tokens is None and self.usage:
            prompt_tokens = self.usage.get("input_tokens", 0) + self.usage.get("cache_read_input_tokens", 0)
        return ProviderResponse(message=Message.assistant(text=text or None, thinking=thinking or None, tool_calls=calls),
                                raw=raw or {}, done_reason=self.stop_reason, prompt_tokens=prompt_tokens, usage=self.usage)
