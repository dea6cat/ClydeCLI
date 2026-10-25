"""Benchmark score cache helpers."""

from __future__ import annotations

import json
import logging
import time

from src.vendor.whichllm.utils import _cache_dir

logger = logging.getLogger(__name__)

CACHE_DIR = _cache_dir()
BENCHMARK_CACHE = CACHE_DIR / "benchmark.json"
DEFAULT_TTL_SECONDS = 24 * 3600  # 24 hours


def load_benchmark_cache(ttl: float | None = DEFAULT_TTL_SECONDS) -> dict[str, float] | None:
    """Load cached benchmark scores. Returns None if expired or missing; `ttl=None` accepts any age."""
    if not BENCHMARK_CACHE.exists():
        return None
    try:
        data = json.loads(BENCHMARK_CACHE.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at", 0)
        if ttl is not None and time.time() - cached_at > ttl:
            logger.debug("Benchmark cache expired")
            return None
        return data.get("scores", {})
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as e:
        logger.debug(f"Benchmark cache corrupted: {e}")
        return None


def save_benchmark_cache(scores: dict[str, float]) -> None:
    """Save benchmark scores to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"cached_at": time.time(), "scores": scores}
    BENCHMARK_CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    logger.debug(f"Saved {len(scores)} benchmark scores to cache")
