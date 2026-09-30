"""Ollama adapter: native /api/chat, never the /v1 OpenAI-compat shim.

Handles local Ollama (default, no key) and Ollama Cloud (ollama.com with an API key).
Local models stay on Ollama's own protocol because the /v1 translation measurably
degrades their tool selection.
"""
from __future__ import annotations

import json as _json
import os
from typing import Callable

from .base import ProviderError, ProviderResponse, get_json, post_json, post_stream
from .toolcall_repair import recover_toolcalls
from .toolspec import ToolSpec, to_openai
from .types import Conversation, Message, Role, ToolCall

LOCAL_DEFAULT = "http://localhost:11434"
CLOUD_HOST = "https://ollama.com"

# Keep the model, and crucially its prompt-prefix KV cache, resident between turns. Ollama's
# default is 5m; an unload drops the cached system prompt + tool schema and forces a full
# re-encode next turn. 30m spans a normal session.
KEEP_ALIVE = "30m"

CTX_FALLBACK = 16384     # used when RAM/arch can't be read to size the window
CLOUD_CTX = 120_000      # cloud runs large windows; don't pin num_ctx there
CTX_FLOOR = 2048         # never pin below this
CTX_ROUND = 1024         # round the computed window down to a clean multiple
KV_RESERVE_BYTES = 3 * 1024 ** 3   # RAM kept free for OS + app + compute buffers
KV_USE_FRACTION = 0.75             # of the RAM left after weights+reserve, give this to KV

_THINK_STRING_MODELS = ("gpt-oss",)   # accept think:"low|medium|high"; other thinking models are boolean


def _ctx_env_key(model: str) -> str:
    """Normalize a model name into an env-var-safe key for CLYDE_MODEL_CONTEXT_*."""
    return "".join(c if c.isalnum() else "_" for c in model.upper())


def _parse_args(args):
    """Tool-call arguments as a dict. A small local model sometimes emits them as a
    (occasionally malformed) JSON string; a broken string becomes {} instead of raising."""
    if isinstance(args, str):
        try:
            args = _json.loads(args)
        except (ValueError, TypeError):
            return {}
    return args if isinstance(args, dict) else {}


def _total_ram_bytes() -> int:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")   # macOS + Linux
    except (ValueError, OSError, AttributeError):
        return 0


def _mi_int(model_info: dict, suffix: str):
    """First int field whose key ends with suffix, ignoring vision-tower keys."""
    for k, v in model_info.items():
        if ".vision." not in k and k.endswith(suffix) and isinstance(v, int):
            return v
    return None


def _kv_bytes_per_token(mi: dict) -> int:
    """f16 KV-cache bytes per token = layers × kv_heads × (k_len + v_len) × 2; 0 if unreadable."""
    layers = _mi_int(mi, ".block_count")
    heads = _mi_int(mi, ".attention.head_count")
    kv_heads = _mi_int(mi, ".attention.head_count_kv") or heads
    klen = _mi_int(mi, ".attention.key_length")
    vlen = _mi_int(mi, ".attention.value_length")
    if (klen is None or vlen is None) and heads:
        emb = _mi_int(mi, ".embedding_length")
        if emb:
            klen = vlen = emb // heads
    if not (layers and kv_heads and klen and vlen):
        return 0
    return layers * kv_heads * (klen + vlen) * 2


def _usage(obj: dict) -> dict | None:
    if obj.get("prompt_eval_count") is None and obj.get("eval_count") is None:
        return None
    return {"input_tokens": obj.get("prompt_eval_count") or 0, "output_tokens": obj.get("eval_count") or 0}


class OllamaProvider:
    def __init__(self, name: str = "ollama", host: str | None = None, api_key: str | None = None):
        self.name = name
        self.host = (host or os.environ.get("OLLAMA_API_BASE")
                     or os.environ.get("OLLAMA_HOST") or LOCAL_DEFAULT).rstrip("/")
        self.api_key = api_key
        self._ctx_cache: dict[str, int] = {}
        self._ctx_override: dict[str, int] = {}
        self._show_cache: dict[str, dict] = {}

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    # --- context window ------------------------------------------------------
    def _show(self, model: str) -> dict:
        if model not in self._show_cache:
            try:
                self._show_cache[model] = post_json(
                    f"{self.host}/api/show", {"model": model},
                    headers=self._headers(), timeout=10, provider=self.name)
            except Exception:
                self._show_cache[model] = {}
        return self._show_cache[model]

    def supports_reasoning(self, model: str) -> bool:
        """True if the model advertises the 'thinking' capability (from /api/show)."""
        return "thinking" in (self._show(model).get("capabilities") or [])

    def _think_value(self, model: str, reasoning):
        """Ollama's `think` field for a reasoning level, or None to omit it. A non-thinking model
        always omits (Ollama errors on `think`). Most thinking models take a bool; gpt-oss takes
        a native string level."""
        if reasoning is None or not self.supports_reasoning(model):
            return None
        if reasoning == "off":
            return False
        if reasoning in ("low", "medium", "high") and any(s in model.lower() for s in _THINK_STRING_MODELS):
            return reasoning
        return True

    def _weight_bytes(self, model: str) -> int:
        try:
            data = get_json(f"{self.host}/api/tags", headers=self._headers(), provider=self.name)
            for m in data.get("models", []):
                if m.get("name") == model and isinstance(m.get("size"), int):
                    return m["size"]
        except Exception:
            pass
        return 0

    def _compute_ctx(self, model: str) -> int:
        """The largest window this machine runs comfortably for this model: min(trained max,
        what fits in RAM after weights + a reserve, giving ~75% of the rest to the KV cache).
        Falls back to CTX_FALLBACK if RAM or arch can't be read."""
        mi = self._show(model).get("model_info") or {}
        trained = _mi_int(mi, ".context_length") or 0
        per_tok = _kv_bytes_per_token(mi)
        ram = _total_ram_bytes()
        weights = self._weight_bytes(model)
        if not (trained and per_tok and ram and weights):
            return min(trained, CTX_FALLBACK) if trained else CTX_FALLBACK
        avail = max(0.0, ram - weights - KV_RESERVE_BYTES) * KV_USE_FRACTION
        eff = min(trained, int(avail / per_tok))
        eff = max(CTX_FLOOR, (eff // CTX_ROUND) * CTX_ROUND)
        return min(eff, trained)

    def context_window(self, model: str) -> int:
        """The window pinned via num_ctx and budgeted for. CLYDE_CONTEXT_TOKENS overrides globally,
        CLYDE_MODEL_CONTEXT_<MODEL> per model; cloud isn't pinned; otherwise computed per
        machine + model. Cached."""
        env = os.environ.get("CLYDE_CONTEXT_TOKENS")
        if env and env.isdigit():
            return int(env)
        pm = os.environ.get(f"CLYDE_MODEL_CONTEXT_{_ctx_env_key(model)}")
        if pm and pm.isdigit():
            self._ctx_cache[model] = int(pm)
            return self._ctx_cache[model]
        if override := self._ctx_override.get(model):
            return override
        if self.api_key is not None:
            return CLOUD_CTX
        if model not in self._ctx_cache:
            self._ctx_cache[model] = self._compute_ctx(model)
        return self._ctx_cache[model]

    def set_context_window(self, model: str, tokens: int | None) -> None:
        """Override the context window for this model for this session; None/0 clears it."""
        if tokens is None or tokens <= 0:
            self._ctx_override.pop(model, None)
        else:
            self._ctx_override[model] = tokens

    def _options(self, model: str) -> dict:
        """Conservative sampling (low temperature + mild repeat penalty) steadies small-model tool
        selection. No fixed seed by default: an identical seed would make a repair retry
        regenerate the same malformed call. Locally num_ctx is pinned to context_window, since
        Ollama otherwise defaults to a small window regardless of the model's trained max."""
        opts: dict = {"temperature": 0.2, "repeat_penalty": 1.1}
        seed = os.environ.get("CLYDE_SAMPLING_SEED")
        if seed:
            try:
                opts["seed"] = int(seed)
            except ValueError:
                pass
        if self.api_key is None:
            opts["num_ctx"] = self.context_window(model)
        return opts

    def is_available(self) -> bool:
        if self.api_key is not None and not self.api_key:
            return False
        try:
            self.list_models()
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        data = get_json(f"{self.host}/api/tags", headers=self._headers(), provider=self.name)
        return [m["name"] for m in data.get("models", [])]

    def _messages(self, conv: Conversation) -> list[dict]:
        out = [{"role": "system", "content": conv.system_prompt}]
        for m in conv.messages:
            if m.tool_results:
                for r in m.tool_results:
                    out.append({"role": "tool", "content": r.content})
                continue
            if m.role == Role.ASSISTANT:
                entry: dict = {"role": "assistant", "content": m.text or ""}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {"function": {"name": tc.name, "arguments": tc.arguments}} for tc in m.tool_calls
                    ]
                out.append(entry)
            else:
                out.append({"role": "user", "content": m.text or ""})
        return out

    def _payload(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...], stream: bool) -> dict:
        payload: dict = {
            "model": model,
            "messages": self._messages(conversation),
            "stream": stream,
            "options": self._options(model),
            "keep_alive": KEEP_ALIVE,
        }
        if tools:
            payload["tools"] = to_openai(tools)
        return payload

    def send(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...]) -> ProviderResponse:
        raw = post_json(f"{self.host}/api/chat", self._payload(conversation, model, tools, False),
                        headers=self._headers(), provider=self.name)
        msg = raw.get("message", {})
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c["function"]
            calls.append(ToolCall.new(name=fn["name"], arguments=_parse_args(fn["arguments"])))
        text = (msg.get("content") or "").strip()
        if not calls and text:
            calls = [ToolCall.new(name=n, arguments=a) for n, a in recover_toolcalls(text, [t.name for t in tools])]
        thinking = (msg.get("thinking") or "").strip()
        return ProviderResponse(
            message=Message.assistant(text=text or None, thinking=thinking or None, tool_calls=calls),
            raw=raw,
            done_reason=raw.get("done_reason"),
            prompt_tokens=raw.get("prompt_eval_count"),
            usage=_usage(raw),
        )

    def stream(self, conversation: Conversation, model: str, tools: tuple[ToolSpec, ...],
               on_text: Callable[[str], None], *, cancel=None, reasoning=None, on_thinking=None) -> ProviderResponse:
        payload = self._payload(conversation, model, tools, True)
        think = self._think_value(model, reasoning)
        if think is not None:
            payload["think"] = think
        content, thinking, calls = [], [], []
        done_reason = prompt_tokens = usage = None
        for line in post_stream(f"{self.host}/api/chat", payload, headers=self._headers(),
                                provider=self.name, cancel=cancel):
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
            except ValueError:
                continue
            if obj.get("error"):
                raise ProviderError(self.name, f"stream error: {obj['error']}")
            m = obj.get("message", {})
            if m.get("content"):
                content.append(m["content"])
                on_text(m["content"])
            if m.get("thinking"):
                thinking.append(m["thinking"])
                if on_thinking:
                    on_thinking(m["thinking"])
            for c in m.get("tool_calls") or []:
                fn = c["function"]
                calls.append(ToolCall.new(name=fn["name"], arguments=_parse_args(fn["arguments"])))
            if obj.get("done"):
                done_reason = obj.get("done_reason")
                prompt_tokens = obj.get("prompt_eval_count")
                usage = _usage(obj)
                break
        text = "".join(content).strip()
        if not calls and text:
            calls = [ToolCall.new(name=n, arguments=a) for n, a in recover_toolcalls(text, [t.name for t in tools])]
        think_text = "".join(thinking).strip()
        return ProviderResponse(
            message=Message.assistant(text=text or None, thinking=think_text or None, tool_calls=calls),
            raw={},
            done_reason=done_reason,
            prompt_tokens=prompt_tokens,
            usage=usage,
        )

    def perf(self, model: str) -> str:
        """Live footprint of a loaded local model via /api/ps: total RAM and the GPU/CPU split.
        '' if the model isn't loaded yet or ps is unavailable."""
        try:
            data = get_json(f"{self.host}/api/ps", headers=self._headers(), provider=self.name)
        except Exception:
            return ""
        for m in data.get("models", []):
            if model in (m.get("name"), m.get("model")):
                total = m.get("size", 0) or 0
                vram = m.get("size_vram", 0) or 0
                if total <= 0:
                    return ""
                if vram >= total:
                    proc = "100% GPU"
                elif vram <= 0:
                    proc = "100% CPU"
                else:
                    gpu = round(vram / total * 100)
                    proc = f"{gpu}% GPU / {100 - gpu}% CPU"
                return f"{total / 1e9:.1f}GB · {proc}"
        return ""


def local() -> OllamaProvider:
    return OllamaProvider(name="ollama")


def cloud() -> OllamaProvider | None:
    key = os.environ.get("OLLAMA_API_KEY")
    if not key:
        return None
    return OllamaProvider(name="ollama-cloud", host=CLOUD_HOST, api_key=key)
