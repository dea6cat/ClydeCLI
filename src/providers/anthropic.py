"""Anthropic Messages API adapter (also serves Anthropic-compatible endpoints like MiniMax).

Native wire format: top-level `system`, tools with `input_schema`, and tool_use /
tool_result content blocks. Foreign `thinking` (from another provider earlier in the
conversation) is dropped on serialize: you can't fabricate Anthropic's signed thinking
blocks, and every provider ignores foreign reasoning traces anyway.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable

from . import catalog
from .base import ProviderError, ProviderResponse, cached_model_list, get_json, post_stream
from .toolspec import ToolSpec, to_anthropic
from .types import Conversation, Message, Role, ToolCall

ANTHROPIC_BASE = "https://api.anthropic.com"
_DEFAULT_MAX_TOKENS = 64000   # streaming output cap when the catalog doesn't know the model

# Thinking controls differ by family (prefix-matched; always-on is checked first because
# "claude-opus-5" is also a prefix of "claude-opus-5-5"). Always-on models reject a disabled
# thinking config or a budget; effort is their only dial. Adaptive models take adaptive or
# disabled. Older models use a fixed thinking budget, which isn't enabled here.
_ALWAYS_ON = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5", "claude-mythos-5")
_ADAPTIVE = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
             "claude-sonnet-5", "claude-sonnet-4-6")
_SUMMARIZED_BY_DEFAULT = ("claude-opus-4-6", "claude-sonnet-4-6")   # newer ones default to "omitted"
_EFFORTS = ("low", "medium", "high")
_BAD_ID_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def _tool_id(raw: str) -> str:
    """Anthropic requires ^[a-zA-Z0-9_-]+$ ids; calls made by another provider earlier in the
    session may not match. Applied to tool_use and tool_result alike, so pairing survives."""
    return _BAD_ID_CHARS.sub("_", raw or "") or "call"


class AnthropicProvider:
    def __init__(self, name: str = "anthropic", base_url: str = ANTHROPIC_BASE,
                 key_env: str = "ANTHROPIC_API_KEY", models: list[str] | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self._static_models = models   # None -> list live from /v1/models

    @property
    def api_key(self) -> str:
        return os.environ.get(self.key_env, "")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def list_models(self) -> list[str]:
        if self._static_models is not None:
            return list(self._static_models)
        return cached_model_list(self, self._fetch_models)

    def _fetch_models(self) -> list[str]:
        data = get_json(f"{self.base_url}/v1/models?limit=1000", headers=self._headers(), provider=self.name)
        return sorted(m["id"] for m in data.get("data", []) if m.get("id"))

    def supports_reasoning(self, model: str) -> bool:
        return model.lower().startswith(_ALWAYS_ON + _ADAPTIVE)

    def _thinking_fields(self, model: str, reasoning) -> dict:
        """Request fields for a /think level: `thinking` and/or `output_config.effort`, per the
        model family. {} leaves the model's own default. Summarized thinking is requested so it
        can stream; "off" (also used by compaction) never shows it."""
        m = model.lower()
        effort = {"output_config": {"effort": reasoning}} if reasoning in _EFFORTS else {}
        if m.startswith(_ALWAYS_ON):
            if reasoning == "off":            # can't disable: lowest effort, reasoning not shown
                return {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}
            return {"thinking": {"type": "adaptive", "display": "summarized"}, **effort}
        if m.startswith(_ADAPTIVE):
            if reasoning is None:
                return {}
            if reasoning == "off":
                return {"thinking": {"type": "disabled"}}
            thinking = {"type": "adaptive"} if m.startswith(_SUMMARIZED_BY_DEFAULT) \
                else {"type": "adaptive", "display": "summarized"}
            return {"thinking": thinking, **effort}
        return {}

    def _payload(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...], reasoning=None) -> dict:
        # Prompt caching: mark the stable prefix (system prompt, last tool definition) with
        # cache_control so repeated requests reuse the cache instead of paying full price.
        payload = {
            "model": model,
            "max_tokens": catalog.max_tokens(model, _DEFAULT_MAX_TOKENS),
            "system": [{"type": "text", "text": conversation.system_prompt,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": self._messages(conversation),
            **self._thinking_fields(model, reasoning),
        }
        tools_json = to_anthropic(tools)
        if tools_json:
            tools_json[-1] = {**tools_json[-1], "cache_control": {"type": "ephemeral"}}
            payload["tools"] = tools_json
        return payload

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}

    def _messages(self, conv: Conversation) -> list[dict]:
        # Thinking is never replayed: a replayed block is only valid while every earlier turn is
        # byte-identical. A request with no replayed blocks is always valid; the model just
        # starts each turn without its earlier reasoning.
        out = []
        for m in conv.messages:
            if m.tool_results:
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": _tool_id(r.tool_call_id),
                     "content": r.content, "is_error": r.is_error}
                    for r in m.tool_results
                ]})
                continue
            if m.role == Role.ASSISTANT:
                blocks = []
                if m.text:
                    blocks.append({"type": "text", "text": m.text})
                for tc in m.tool_calls:
                    blocks.append({"type": "tool_use", "id": _tool_id(tc.id), "name": tc.name, "input": tc.arguments})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            else:
                out.append({"role": "user", "content": [
                    {"type": "text", "text": m.text or ""},
                    *({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}
                      for mt, data in m.images),
                ] if m.images else m.text or ""})
        return out

    def stream(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...],
               on_text: Callable[[str], None], *, cancel=None, reasoning=None, on_thinking=None) -> ProviderResponse:
        # Real SSE: emit text deltas as they arrive and assemble tool_use blocks from
        # input_json_delta fragments.
        payload = {**self._payload(conversation, model, tools, reasoning), "stream": True}
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        blocks: dict[int, dict] = {}   # index -> {"type", "name", "id", "json"}
        stop_reason = None
        finished = False
        usage: dict = {}
        for line in post_stream(f"{self.base_url}/v1/messages", payload, headers=self._headers(),
                                provider=self.name, cancel=cancel):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            try:
                evt = json.loads(data)
            except ValueError:
                continue
            etype = evt.get("type")
            if etype == "error":
                err = evt.get("error") or {}
                raise ProviderError(self.name, f"stream error: {err.get('type', '')} {err.get('message', '')}".strip(),
                                    retryable=err.get("type") in ("overloaded_error", "api_error"))
            if etype == "message_start":
                usage.update(_usage((evt.get("message") or {}).get("usage") or {}))
            elif etype == "content_block_start":
                idx = evt.get("index", 0)
                cb = evt.get("content_block") or {}
                blocks[idx] = {"type": cb.get("type"), "name": cb.get("name", ""),
                               "id": cb.get("id"), "json": ""}
            elif etype == "content_block_delta":
                idx = evt.get("index", 0)
                delta = evt.get("delta") or {}
                dtype = delta.get("type")
                if dtype == "text_delta":
                    chunk = delta.get("text", "")
                    if chunk:
                        text_parts.append(chunk)
                        on_text(chunk)
                elif dtype == "thinking_delta":
                    chunk = delta.get("thinking", "")
                    if chunk:
                        thinking_parts.append(chunk)
                        if on_thinking:
                            on_thinking(chunk)
                elif dtype == "input_json_delta":
                    slot = blocks.setdefault(idx, {"type": "tool_use", "name": "", "id": None, "json": ""})
                    slot["json"] += delta.get("partial_json", "")
            elif etype == "message_delta":
                stop_reason = (evt.get("delta") or {}).get("stop_reason", stop_reason)
                out_tokens = (evt.get("usage") or {}).get("output_tokens")
                if out_tokens is not None:
                    usage["output_tokens"] = out_tokens
            elif etype == "message_stop":
                finished = True
                break
        if not finished:
            raise ProviderError(self.name, "stream ended before the response finished", retryable=True)
        calls = []
        for idx in sorted(blocks):
            b = blocks[idx]
            if b.get("type") != "tool_use":
                continue
            try:
                args = json.loads(b["json"]) if b["json"] else {}
            except ValueError:
                args = {}
            calls.append(ToolCall.new(name=b["name"], arguments=args, id=b["id"]))
        text = "".join(text_parts).strip()
        thinking = "".join(thinking_parts).strip()
        return ProviderResponse(
            message=Message.assistant(text=text or None, thinking=thinking or None, tool_calls=calls),
            raw={},
            done_reason=stop_reason,
            prompt_tokens=usage.get("input_tokens"),
            usage=usage or None,
        )


def _usage(raw: dict) -> dict:
    """Anthropic usage -> ClydeCLI usage dict (keeps the cache fields the context analyzer reads)."""
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return {k: raw[k] for k in keys if isinstance(raw.get(k), int)}
