"""Per-model capability catalog for cloud models.

A small bundled JSON (`catalog.json`) maps well-known cloud model ids to their real
context window and output-token cap. Keys match by longest prefix, so
dated/suffixed variants (e.g. `gpt-4o-2024-08-06`) resolve to their base entry. Local
Ollama models are absent by design: their window is sized from num_ctx. Entries may also
carry optional USD-per-million-token list prices (input/output/cache read/cache write) used
for /cost estimates; a missing price means "unknown", never zero.

A missing or corrupt catalog degrades to "unknown" (callers use their own defaults); it
never crashes startup.
"""
from __future__ import annotations

import re

import json
from dataclasses import dataclass
from pathlib import Path

_CATALOG_PATH = Path(__file__).with_name("catalog.json")


@dataclass(frozen=True)
class ModelInfo:
    context_window: int
    default_max_tokens: int
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    cache_read_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None
    supports_images: bool | None = None   # None: the catalog doesn't say


_PRICE_FIELDS = ("input_per_mtok", "output_per_mtok", "cache_read_per_mtok", "cache_write_per_mtok")

_cache: dict[str, ModelInfo] | None = None


def _load() -> dict[str, ModelInfo]:
    global _cache
    if _cache is not None:
        return _cache
    table: dict[str, ModelInfo] = {}
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        for key, v in (data.get("models") or {}).items():
            table[key.lower()] = ModelInfo(
                context_window=int(v["context_window"]),
                default_max_tokens=int(v["default_max_tokens"]),
                **{f: float(v[f]) for f in _PRICE_FIELDS if v.get(f) is not None},
                supports_images=v["supports_images"] if isinstance(v.get("supports_images"), bool) else None,
            )
    except Exception:
        table = {}
    _cache = table
    return table


def lookup(model: str) -> ModelInfo | None:
    """The catalog entry for a model id, matched by longest key prefix, or None."""
    if not model:
        return None
    m = model.lower()
    table = _load()
    exact = table.get(m)
    if exact is not None:
        return exact
    best_key = ""
    for key in table:
        if m.startswith(key) and len(key) > len(best_key):
            best_key = key
    return table.get(best_key) if best_key else None


def context_window(model: str) -> int | None:
    info = lookup(model)
    return info.context_window if info else None


# Windows by name, for models the catalog doesn't list
_NAME_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-7": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 128_000,
    # GLM / Minimax defaults
    "glm-4": 128_000,
    "glm-4-flash": 128_000,
    "minimax": 128_000,
    "abab": 128_000,
}

DEFAULT_CONTEXT_WINDOW = 200_000


def window_from_name(model: str) -> int:
    """A guess from the model's name: a known family, a \"32k\"-style suffix, else DEFAULT_CONTEXT_WINDOW."""
    model_lower = model.lower()
    for name, window in _NAME_WINDOWS.items():
        if name in model_lower:
            return window
    # Try to extract a numeric window from model name (e.g., "gpt-4-32k")
    match = re.search(r'(\d+)k', model_lower)
    if match:
        return int(match.group(1)) * 1_000
    # Check for 1m suffix
    if '1m' in model_lower or 'million' in model_lower:
        return 1_000_000
    return DEFAULT_CONTEXT_WINDOW


def max_tokens(model: str, default: int) -> int:
    info = lookup(model)
    return info.default_max_tokens if info else default


