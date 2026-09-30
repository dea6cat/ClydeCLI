"""Bridge between ClydeCLI's stored history (src/agent/conversation.py) and the canonical
provider types. The stored history stays the single source of truth; it is re-expressed
as a canonical Conversation on every request, and each response is appended back.

to_canonical also repairs history that providers would reject: tool results for one turn
are grouped into a single message (Gemini requires it), calls left unanswered (Ctrl-C mid
turn) get an error result, orphaned results and empty turns are dropped, and the request
always starts on a user turn (the 100-message history trim can cut mid-exchange).
"""
from __future__ import annotations

import json
from typing import Any

from ..agent.conversation import (
    Conversation as History,
    TextContentBlock,
    ThinkingContentBlock,
    ToolResultContentBlock,
    ToolUseContentBlock,
)
from .types import Conversation, Message, Role, ToolCall, ToolResult

_INTERRUPTED = "Tool call was interrupted before it returned a result."


def result_text(output: Any) -> str:
    """A tool result flattened to text, as every provider receives it."""
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(output)


def _raw_messages(history: History, flatten_tools: bool) -> list[Message]:
    """Stored history -> canonical messages, one per stored message (no repair yet)."""
    out: list[Message] = []
    for msg in history.messages:
        if getattr(msg, "_is_internal", False):
            continue
        if isinstance(msg.content, str):
            role = Role.ASSISTANT if msg.role == "assistant" else Role.USER
            out.append(Message(role=role, text=msg.content))
            continue
        texts: list[str] = []
        thinking: list[str] = []
        calls: list[ToolCall] = []
        results: list[ToolResult] = []
        for block in msg.content:
            if isinstance(block, TextContentBlock):
                texts.append(block.text)
            elif isinstance(block, ThinkingContentBlock):
                thinking.append(block.thinking)
            elif isinstance(block, ToolUseContentBlock):
                if flatten_tools:
                    texts.append(f"\n[called tool {block.name} with {result_text(block.input)}]")
                else:
                    calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}),
                                          signature=block.signature))
            elif isinstance(block, ToolResultContentBlock):
                content = result_text(block.content)
                if flatten_tools:
                    texts.append(f"[tool result{' (error)' if block.is_error else ''}: {content}]")
                else:
                    results.append(ToolResult(tool_call_id=block.tool_use_id, content=content,
                                              is_error=block.is_error))
        text = "".join(texts) or None
        if msg.role == "assistant":
            out.append(Message.assistant(text=text, thinking="".join(thinking) or None, tool_calls=calls))
            continue
        if results:
            out.append(Message.results(results))
        if text:
            out.append(Message.user(text))
    return out


def _repair(messages: list[Message]) -> list[Message]:
    out: list[Message] = []
    pending: list[ToolCall] = []   # calls from the latest assistant turn still awaiting results

    def close_pending() -> None:
        """Answer any call left without a result so the pairing stays valid."""
        if pending:
            missing = [ToolResult(tc.id, _INTERRUPTED, is_error=True) for tc in pending]
            if out and out[-1].tool_results:
                out[-1] = Message.results(out[-1].tool_results + missing)
            else:
                out.append(Message.results(missing))
            pending.clear()

    for m in messages:
        if m.role == Role.ASSISTANT:
            if not (m.text and m.text.strip()) and not m.tool_calls:
                continue                      # empty turn: providers reject empty content
            close_pending()
            if not out:
                continue                      # a request must open on a user turn
            out.append(m)
            pending = list(m.tool_calls)
            continue
        if m.tool_results:
            wanted = {tc.id for tc in pending}
            results = [r for r in m.tool_results if r.tool_call_id in wanted]
            if not results:
                continue                      # orphaned results (their call was trimmed away)
            answered = {r.tool_call_id for r in results}
            pending = [tc for tc in pending if tc.id not in answered]
            if out and out[-1].tool_results:  # one turn's results travel together
                out[-1] = Message.results(out[-1].tool_results + results)
            else:
                out.append(Message.results(results))
            continue
        if not (m.text and m.text.strip()):
            continue
        close_pending()
        out.append(m)
    close_pending()
    return out


def to_canonical(history: History, system_prompt: str, *, flatten_tools: bool = False) -> Conversation:
    """The stored history as a provider-ready canonical Conversation. flatten_tools renders tool
    calls and results as plain text, for tool-free requests (compaction, quick replies), since
    providers reject tool blocks in a request that defines no tools."""
    return Conversation(system_prompt=system_prompt, messages=_repair(_raw_messages(history, flatten_tools)))


def append_response(history: History, message: Message) -> None:
    """Store an assistant turn (reasoning, text, tool calls) in ClydeCLI's history."""
    blocks: list = []
    if message.thinking:
        blocks.append(ThinkingContentBlock(thinking=message.thinking))
    if message.text:
        blocks.append(TextContentBlock(text=message.text))
    for tc in message.tool_calls:
        blocks.append(ToolUseContentBlock(id=tc.id, name=tc.name, input=tc.arguments, signature=tc.signature))
    if blocks == [] or (len(blocks) == 1 and isinstance(blocks[0], TextContentBlock)):
        history.add_assistant_message(message.text or "")
    else:
        history.add_assistant_message(blocks)
