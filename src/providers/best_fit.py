"""The best models for this machine, ranked by real benchmarks: a source for /models local.

The ranking is whichllm's (github.com/Andyyyy64/whichllm, MIT; we bundle our fork, dea6cat/whichLocalLLM).
It merges LiveBench, Artificial Analysis, Aider and Arena scores and sizes each model's memory from its
architecture. Clyde replaces its machine detection with ours: the memory budget the other sources use, and
the chip's bandwidth. Every entry point returns [] on any failure, like the other sources.
"""
from __future__ import annotations

import threading
from functools import lru_cache

from src import tune_profile

from . import fit
from .fit import Offer

_TOP = 12   # ranked candidates asked for; the ones without a GGUF repo are dropped
_SOURCE = "hf"   # the offers are Hugging Face GGUF repos, pulled like any other
CREDIT = "ranked by whichllm"


def _machine(budget: int, chip: str):  # type: ignore[no-untyped-def]
    from whichllm.hardware.types import GPUInfo, HardwareInfo

    ram = fit._total_ram_bytes() or budget
    gpu = GPUInfo(chip or "GPU", "apple" if chip.startswith("Apple") else "nvidia", budget, usable_vram_bytes=budget,
                  memory_bandwidth_gbps=float(fit.bandwidth_gbps(chip) or 0) or None, shared_memory=chip.startswith("Apple"))
    return HardwareInfo(gpus=[gpu], cpu_name=chip or "CPU", ram_bytes=ram, os="darwin" if chip.startswith("Apple") else "linux")


def detail(r) -> str:  # type: ignore[no-untyped-def]
    """`quality 77 (direct benchmark) · ~37 tok/s (11-63, low confidence) · apache-2.0`."""
    parts = [f"quality {r.quality_score:.0f} ({r.benchmark_source.replace('_', ' ')} benchmark)" if r.benchmark_source != "none" else "no benchmark"]
    if r.estimated_tok_per_sec:
        low, high = r.speed_range_tok_per_sec or (None, None)
        span = f"{low:.0f}-{high:.0f}, " if low is not None else ""
        parts.append(f"~{r.estimated_tok_per_sec:.0f} tok/s ({span}{r.speed_confidence} confidence)")
    if r.model.license:
        parts.append(r.model.license)
    return " · ".join(parts)


_builder: threading.Thread | None = None


def _cache_state() -> str:
    """"fresh", "stale" or "none" for whichllm's cached model list. Building it takes about 5 minutes
    (Hugging Face and the leaderboards); a stale list still ranks well, so it is served while a new one builds."""
    from whichllm.models.cache import load_cache

    return "fresh" if load_cache() is not None else "stale" if load_cache(ttl=None) is not None else "none"


def pending() -> bool:
    """True while the model list is being built in the background."""
    return _builder is not None and _builder.is_alive()


def _build(budget: int, chip: str, profile: str) -> None:
    global _builder
    if pending():
        return

    def run() -> None:
        try:
            _ranked.cache_clear()
            _ranked(budget, chip, profile, True)
        except Exception:   # offline or rate-limited: the group stays out and the next search tries again
            pass

    _builder = threading.Thread(target=run, daemon=True, name="whichllm-build")
    _builder.start()


def _profile() -> str:
    """whichllm's ranking profile from the answers given at setup (`clyde tune`): coding when coding is one of the uses, else general."""
    saved = tune_profile.load()
    return "coding" if saved and "coding" in saved.uses else "general"


@lru_cache(maxsize=4)
def _ranked(budget: int, chip: str, profile: str, refresh: bool = False) -> tuple:
    from whichllm.api import recommend

    return tuple(recommend(_machine(budget, chip), top=_TOP, profile=profile, refresh=refresh, stale_ok=not refresh))


def search(query: str, budget: int) -> list[Offer]:
    """Top-ranked GGUF models that fit `budget`, as offers Ollama (`hf.co/<repo>:<quant>`) or LM Studio can pull."""
    chip, profile, state = fit.chip(), _profile(), _cache_state()
    if state != "fresh":
        _build(budget, chip, profile)   # never make the picker wait minutes for it
    if state == "none":
        return []
    try:
        ranked = _ranked(budget, chip, profile)
    except Exception:   # a failed fetch or an upstream change must never break /models local
        return []
    offers = []
    for r in ranked:
        repo, variant = r.artifact_model, r.artifact_variant or r.gguf_variant
        rating = fit.rate(variant.file_size_bytes, budget) if variant else None
        if repo is None or variant is None or rating is None or query.lower() not in r.model.id.lower():
            continue
        offers.append(Offer(r.model.id, f"hf.co/{repo.id}:{variant.quant_type}", variant.file_size_bytes, rating,
                            r.model.downloads, variant.quant_type, _SOURCE, detail(r)))
    return offers
