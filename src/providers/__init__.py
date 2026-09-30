"""LLM providers for ClydeCLI.

Stdlib-only adapters (no vendor SDKs): canonical types in, canonical ProviderResponse out,
each adapter owning its wire format. See registry.py for the provider list and model
resolution, keys.py for API-key storage.
"""
from .base import Provider, ProviderError, ProviderResponse, stream_with_retry
from .registry import build_registry, model_ref, pick_default_model, resolve, usable

__all__ = [
    "Provider",
    "ProviderError",
    "ProviderResponse",
    "build_registry",
    "model_ref",
    "pick_default_model",
    "resolve",
    "stream_with_retry",
    "usable",
]
