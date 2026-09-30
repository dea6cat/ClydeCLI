"""Per-model capability catalog for cloud models.

A small bundled JSON (`catalog.json`) maps well-known cloud model ids to their real
context window and output-token cap. Keys match by longest prefix, so
dated/suffixed variants (e.g. `gpt-4o-2024-08-06`) resolve to their base entry. Local
Ollama models are absent by design: their window is sized from num_ctx.

A missing or corrupt catalog degrades to "unknown" (callers use their own defaults); it
never crashes startup.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_CATALOG_PATH = Path(__file__).with_name("catalog.json")


@dataclass(frozen=True)
class ModelInfo:
    context_window: int
    default_max_tokens: int


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


def max_tokens(model: str, default: int) -> int:
    info = lookup(model)
    return info.default_max_tokens if info else default


