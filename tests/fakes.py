"""A scripted in-memory Provider for tests: records every canonical request and replays
queued replies (or raises queued exceptions) through the real stream() contract."""
from __future__ import annotations

from src.providers.base import ProviderResponse
from src.providers.types import Message, ToolCall


def reply(text: str | None = None, tool_calls=(), usage: dict | None = None,
          thinking: str | None = None) -> ProviderResponse:
    """A ProviderResponse; tool_calls are (name, input) or (name, input, id) tuples."""
    calls = [ToolCall.new(name=c[0], arguments=c[1], id=c[2] if len(c) > 2 else None) for c in tool_calls]
    return ProviderResponse(message=Message.assistant(text=text, thinking=thinking, tool_calls=calls),
                            raw={}, usage=usage)


class FakeProvider:
    def __init__(self, *responses, name: str = "fake", models=("fake-model",), chunk_size: int = 0):
        self.name = name
        self._responses = list(responses)
        self._models = list(models)
        self._chunk_size = chunk_size   # 0 -> emit each reply's text as one chunk
        self.requests: list[dict] = []

    def is_available(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return list(self._models)

    def _next(self):
        if not self._responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def send(self, conversation, model, tools):
        self.requests.append({"conversation": conversation, "model": model, "tools": tools, "reasoning": None})
        return self._next()

    def stream(self, conversation, model, tools, on_text, *, cancel=None, reasoning=None, on_thinking=None):
        self.requests.append({"conversation": conversation, "model": model, "tools": tools, "reasoning": reasoning})
        resp = self._next()
        if on_thinking and resp.message.thinking:
            on_thinking(resp.message.thinking)
        text = resp.message.text or ""
        size = self._chunk_size or len(text) or 1
        for i in range(0, len(text), size):
            on_text(text[i:i + size])
        return resp
