"""One adapter for every OpenAI-compatible Chat Completions service.

OpenAI, OpenRouter, Mistral, NVIDIA, DeepSeek, Cerebras and GLM all speak the same
/chat/completions wire format natively. Configured per instance with base_url +
API-key env var + options; new services are added as data in registry.py, not code.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable

from .base import ProviderError, ProviderResponse, cached_model_list, get_json, post_stream
from .toolspec import ToolSpec, to_openai
from .types import Conversation, Message, Role, ToolCall

# Substrings that mark a model as NOT a chat/tool-calling model, filtered out of listings.
_NON_CHAT = (
    "embed", "embedding", "ocr", "tts", "whisper", "transcribe", "moderation",
    "rerank", "guard", "safety", "reward", "-parse", "nemoretriever", "nvclip",
    "bge-", "arctic-embed", "voxtral", "riva", "diffusion", "calibration",
    "topic-control", "detector", "-fim-", ":batch",  # OpenRouter batch variants reject chat requests
)


def _is_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    return not any(tok in low for tok in _NON_CHAT)


# Reasoning is NOT part of the shared Chat Completions surface; each service has its own
# fields, so each gets its own style (set per provider in registry.py):
#   openai     reasoning_effort, on reasoning models only (others 400 on it)
#   openrouter a `reasoning` object; models without reasoning ignore it
#   deepseek   thinking {type} + reasoning_effort (low | high | max)
#   cerebras   reasoning_effort, on its reasoning models; only some accept "none"
_OPENAI_REASONING = re.compile(r"^(o\d|gpt-5|gpt-6)")
_CEREBRAS_REASONING = ("qwen-3", "gpt-oss", "gemma-4")
_CEREBRAS_CANT_DISABLE = ("gpt-oss",)
_EFFORTS = ("low", "medium", "high")


def _usage(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    usage = {"input_tokens": raw.get("prompt_tokens") or 0, "output_tokens": raw.get("completion_tokens") or 0}
    cached = (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
    if cached:  # prompt_tokens includes the cached share; split it out the way Anthropic reports it
        usage["input_tokens"] = max(usage["input_tokens"] - cached, 0)
        usage["cache_read_input_tokens"] = cached
    return usage


class OpenAICompatProvider:
    def __init__(self, name: str, base_url: str, key_env: str,
                 models: list[str] | None = None, dynamic_models: bool = False,
                 extra_headers: dict | None = None, reasoning_style: str | None = None,
                 max_tokens: int | None = None, stream_usage: bool = False):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self._static_models = models or []
        self._dynamic = dynamic_models
        self._extra_headers = extra_headers or {}
        self._reasoning_style = reasoning_style
        self._max_tokens = max_tokens      # only where the service's default cap causes trouble
        self._stream_usage = stream_usage  # only services known to accept stream_options

    @property
    def api_key(self) -> str:
        return os.environ.get(self.key_env, "")

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}"}
        h.update(self._extra_headers)
        return h

    def is_available(self) -> bool:
        return bool(self.api_key)

    def supports_reasoning(self, model: str) -> bool:
        style, m = self._reasoning_style, model.lower()
        if style == "openai":
            return bool(_OPENAI_REASONING.match(m))
        if style == "cerebras":
            return m.startswith(_CEREBRAS_REASONING)
        return style in ("openrouter", "deepseek")

    def _reasoning_fields(self, model: str, reasoning) -> dict:
        """This service's own request fields for a /think level; {} keeps its default."""
        if reasoning is None or not self.supports_reasoning(model):
            return {}
        style = self._reasoning_style
        if style == "openrouter":
            if reasoning == "on":
                return {"reasoning": {"enabled": True}}
            return {"reasoning": {"effort": "none" if reasoning == "off" else reasoning}}
        if style == "deepseek":
            if reasoning == "off":
                return {"thinking": {"type": "disabled"}}
            effort = {} if reasoning == "on" else {"reasoning_effort": "low" if reasoning == "low" else "high"}
            return {"thinking": {"type": "enabled"}, **effort}
        if reasoning == "on":
            return {}
        if reasoning == "off":
            can_disable = style == "cerebras" and not model.lower().startswith(_CEREBRAS_CANT_DISABLE)
            return {"reasoning_effort": "none" if can_disable else "low"}
        return {"reasoning_effort": reasoning} if reasoning in _EFFORTS else {}

    def list_models(self) -> list[str]:
        if not self._dynamic:
            return list(self._static_models)
        return cached_model_list(self, self._fetch_models)

    def _fetch_models(self) -> list[str]:
        data = get_json(f"{self.base_url}/models", headers=self._headers(), provider=self.name)
        ids = [m.get("id", "") for m in data.get("data", [])]
        return sorted(i for i in ids if i and _is_chat_model(i))

    def _messages(self, conv: Conversation) -> list[dict]:
        out = [{"role": "system", "content": conv.system_prompt}]
        for m in conv.messages:
            if m.tool_results:
                for r in m.tool_results:
                    out.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content})
                continue
            if m.role == Role.ASSISTANT:
                entry: dict = {"role": "assistant", "content": m.text or ""}
                # DeepSeek 400s a tool conversation whose earlier assistant turns lack their
                # reasoning_content; other services don't take the field.
                if self._reasoning_style == "deepseek" and m.thinking:
                    entry["reasoning_content"] = m.thinking
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in m.tool_calls
                    ]
                out.append(entry)
            else:
                out.append({"role": "user", "content": m.text or ""})
        return out

    def _payload(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...], stream: bool) -> dict:
        payload: dict = {"model": model, "messages": self._messages(conversation), "stream": stream}
        if tools:   # OpenAI rejects an empty tools array
            payload["tools"] = to_openai(tools)
        return payload

    def stream(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...],
               on_text: Callable[[str], None], *, cancel=None, reasoning=None, on_thinking=None) -> ProviderResponse:
        payload = {**self._payload(conversation, model, tools, True), **self._reasoning_fields(model, reasoning)}
        if self._max_tokens:
            payload["max_tokens"] = self._max_tokens
        if self._stream_usage:
            payload["stream_options"] = {"include_usage": True}
        content: list[str] = []
        thinking: list[str] = []
        by_index: dict[int, dict] = {}   # assemble tool_calls from streamed fragments
        done_reason = None
        finished = False
        usage = None
        for line in post_stream(f"{self.base_url}/chat/completions", payload,
                                headers=self._headers(), provider=self.name, cancel=cancel):
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                err = obj["error"]
                msg = err.get("message", err) if isinstance(err, dict) else err
                raise ProviderError(self.name, f"stream error: {msg}", retryable=True)
            if obj.get("usage"):
                usage = _usage(obj["usage"])
            choices = obj.get("choices") or [{}]
            done_reason = choices[0].get("finish_reason") or done_reason
            delta = choices[0].get("delta", {})
            # Reasoning text: DeepSeek/GLM use reasoning_content; OpenRouter and Cerebras `reasoning`.
            chunk = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(chunk, str) and chunk:
                thinking.append(chunk)
                if on_thinking:
                    on_thinking(chunk)
            if delta.get("content"):
                content.append(delta["content"])
                on_text(delta["content"])
            for frag in delta.get("tool_calls") or []:
                idx = frag.get("index", 0)
                slot = by_index.setdefault(idx, {"id": None, "name": "", "args": ""})
                if frag.get("id"):
                    slot["id"] = frag["id"]
                fn = frag.get("function", {})
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]
        if not finished and done_reason is None:
            raise ProviderError(self.name, "stream ended before the response finished", retryable=True)
        calls = []
        for _, slot in sorted(by_index.items()):
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall.new(name=slot["name"], arguments=args, id=slot["id"]))
        text = "".join(content).strip()
        think = "".join(thinking).strip()
        return ProviderResponse(
            message=Message.assistant(text=text or None, thinking=think or None, tool_calls=calls),
            raw={},
            done_reason=done_reason,
            prompt_tokens=usage and usage["input_tokens"] + usage.get("cache_read_input_tokens", 0),
            usage=usage,
        )
