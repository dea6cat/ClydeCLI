"""Provider registry + model resolution.

Builds every adapter ClydeCLI knows about; `usable()` filters to those actually configured
(Ollama reachable / API key present). Resolution maps a model string to (provider, model):
explicit `provider:model`, or a bare name matched across usable providers (ambiguity
requires the explicit form).

Adding an OpenAI-compatible service is data, not code: append to _OPENAI_COMPAT. Users add
their own with `clyde login` / `/login` -> custom (saved under "providers" in settings.json).
"""
from __future__ import annotations

from . import keys, ollama
from .anthropic import AnthropicProvider
from .base import Provider
from .card_shuffle import CardShuffle
from .google import GoogleProvider
from .lmstudio import LMStudioProvider
from .openai_compat import OpenAICompatProvider

# name, base_url, key_env, dynamic_models, static models (only for dynamic_models=False; a
# dynamic provider lists live via /models and never falls back to a hardcoded guess), extra
# headers, options: reasoning_style (openai_compat.py lists each service's reasoning fields),
# max_tokens (OpenRouter defaults to a model's full output cap and pre-checks credits against
# it, rejecting low-balance accounts), stream_usage (services known to accept stream_options).
_OPENAI_COMPAT = [
    ("openai", "https://api.openai.com/v1", "OPENAI_API_KEY", True, [], {},
     {"reasoning_style": "openai", "stream_usage": True}),
    ("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", True, [],
     {"HTTP-Referer": "https://github.com/dea6cat/ClydeCLI", "X-Title": "ClydeCLI"},
     {"reasoning_style": "openrouter", "max_tokens": 16384, "stream_usage": True}),
    ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", True, [], {}, {}),
    ("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", True, [], {}, {}),
    ("deepseek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", True, [], {},
     {"reasoning_style": "deepseek", "stream_usage": True}),
    ("cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", True, [], {}, {"reasoning_style": "cerebras"}),
    ("glm", "https://open.bigmodel.cn/api/paas/v4", "GLM_API_KEY", False,
     ["glm-5", "glm-5-turbo", "glm-4.7", "glm-4.6", "glm-4.5", "glm-4-plus", "glm-4-air", "glm-4-flash"], {}, {}),
]

_MINIMAX_MODELS = ["MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed",
                   "MiniMax-M2.1", "MiniMax-M2.1-highspeed", "MiniMax-M2"]

# Preferred model per provider, used by `clyde login` and automatic selection when the
# provider actually lists it (otherwise the provider's first listed model is used).
SUGGESTED_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5.4",
    "google": "gemini-flash-latest",
    "openrouter": "~anthropic/claude-sonnet-latest",
    "deepseek": "deepseek-v4-pro",
    "mistral": "mistral-medium-latest",
    "glm": "glm-5",
    "minimax": "MiniMax-M2.7",
    "cardShuffle": "house",
}

# Order automatic selection tries connected cloud providers in, after local Ollama.
_AUTO_ORDER = ("anthropic", "openai", "google", "openrouter", "deepseek", "mistral", "glm",
               "minimax", "cerebras", "nvidia", "ollama-cloud")


def build_registry() -> dict[str, Provider]:
    reg: dict[str, Provider] = {"ollama": ollama.local(), "lmstudio": LMStudioProvider()}
    cloud = ollama.cloud()
    if cloud is not None:
        reg[cloud.name] = cloud
    for name, base, key_env, dyn, models, hdrs, opts in _OPENAI_COMPAT:
        reg[name] = OpenAICompatProvider(name, base, key_env, models=models,
                                         dynamic_models=dyn, extra_headers=hdrs, **opts)
    reg["anthropic"] = AnthropicProvider()
    reg["minimax"] = AnthropicProvider(name="minimax", base_url="https://api.minimaxi.com/anthropic",
                                       key_env="MINIMAX_API_KEY", models=_MINIMAX_MODELS)
    reg["google"] = GoogleProvider()
    for name, base in keys.custom_providers().items():
        env = keys.PROVIDER_KEY_ENV[name]
        reg[name] = (AnthropicProvider(name=name, base_url=base, key_env=env) if keys.protocol(name) == "anthropic"
                     else OpenAICompatProvider(name, base, env, dynamic_models=True))
    reg[CardShuffle.name] = CardShuffle(reg)   # deals from the providers above
    return reg


def usable(reg: dict[str, Provider]) -> dict[str, Provider]:
    return {name: p for name, p in reg.items() if p.is_available()}


def resolve(reg: dict[str, Provider], model: str) -> tuple[Provider, str] | None:
    """(provider, model) or None. Explicit 'provider:model' wins; else a bare name is matched
    across *usable* providers (ambiguity -> None). The prefix must be a known provider, so
    Ollama tags like 'qwen3:8b' still resolve as bare names."""
    if ":" in model:
        prefix, rest = model.split(":", 1)
        if prefix in reg:
            p = reg[prefix]
            return (p, rest) if p.is_available() else None
    matches = []
    for p in usable(reg).values():
        try:
            if model in p.list_models():
                matches.append(p)
        except Exception:
            continue
    if len(matches) == 1:
        return matches[0], model
    return None


def model_ref(provider: Provider, model: str) -> str:
    """The canonical `provider:model` string for a resolved pair."""
    return f"{provider.name}:{model}"


def pick_default_model(reg: dict[str, Provider]) -> str | None:
    """A model to use when none is configured, so a key in the environment is enough to start:
    the first local Ollama or LM Studio model, else the first connected cloud provider (in _AUTO_ORDER) with
    its suggested model, or its first listed one. None when nothing is usable."""
    for name in ("ollama", "lmstudio", *_AUTO_ORDER):
        provider = reg.get(name)
        if provider is None:
            continue
        try:
            if not provider.is_available():
                continue
            models = provider.list_models()
        except Exception:
            continue
        if models:
            suggested = SUGGESTED_MODELS.get(name)
            return f"{name}:{suggested if suggested in models else models[0]}"
    return None
