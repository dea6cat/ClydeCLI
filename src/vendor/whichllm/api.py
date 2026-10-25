"""Library entry point for programs that already know their machine (ClydeCLI passes its own).

The CLI detects hardware itself; here the caller hands in a `HardwareInfo` and gets the ranked
models back, with the same fetching, caching and scoring as the command line.
"""

from __future__ import annotations

import asyncio

from src.vendor.whichllm.engine.ranker import rank_models
from src.vendor.whichllm.engine.types import CompatibilityResult
from src.vendor.whichllm.hardware.types import HardwareInfo
from src.vendor.whichllm.models.artifacts import attach_resolved_artifacts
from src.vendor.whichllm.models.benchmark import (
    fetch_benchmark_scores,
    load_benchmark_cache,
    save_benchmark_cache,
)
from src.vendor.whichllm.models.cache import DEFAULT_TTL_SECONDS, load_cache, save_cache
from src.vendor.whichllm.models.fetcher import dicts_to_models, fetch_models, models_to_dicts
from src.vendor.whichllm.models.grouper import group_models


def recommend(
    hardware: HardwareInfo,
    *,
    top: int = 5,
    context_length: int = 4096,
    profile: str = "general",
    quant: str | None = None,
    refresh: bool = False,
    stale_ok: bool = False,
) -> list[CompatibilityResult]:
    """The best models for `hardware`, best first. Raises on a failed model fetch; benchmark data is optional.

    `stale_ok` ranks from cached data of any age, so a caller can show something now and refresh in the background.
    """
    ttl = None if stale_ok else DEFAULT_TTL_SECONDS
    cached = None if refresh else load_cache(ttl)
    if cached is not None:
        models = dicts_to_models(cached)
    else:
        models = asyncio.run(fetch_models(include_vision=profile in ("vision", "any")))
        save_cache(models_to_dicts(models))

    scores = None if refresh else load_benchmark_cache(ttl)
    if scores is None:
        try:
            scores = asyncio.run(fetch_benchmark_scores())
            save_benchmark_cache(scores)
        except Exception:   # ranking still works without benchmarks, with lower confidence
            scores = {}

    candidates = [m for family in group_models(models) for m in (family.base_model, *family.variants)]
    results = rank_models(
        candidates, hardware, context_length=context_length, top_n=top, quant_filter=quant,
        benchmark_scores=scores, task_profile=profile, require_direct_top=True,
    )
    attach_resolved_artifacts(results, candidates, quant_filter=quant)
    return results
