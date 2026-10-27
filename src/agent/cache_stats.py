"""Where the prompt cache was missed, and what it cost: read from a session's traced model requests.

A provider that caches the start of a prompt bills those tokens at a fraction of the input price on the next request. When the cache
does not hold (it expired while you were away, or the start of the prompt changed) the same tokens are billed again at the full
price, and nothing in the answer says so. This compares each request with the one before it on the same model and says how many
tokens were read again, what that cost extra, and whether you had been idle longer than the cache lives.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.providers import catalog

CACHE_TTL_S = 5 * 60   # how long the usual provider cache entry lives
NOISE_FLOOR = 1024     # a smaller miss is cache-block granularity, not a miss


@dataclass(frozen=True)
class Miss:
    ts: str
    ref: str
    missed: int                 # tokens billed again at the full price
    extra_usd: float | None     # None when the model has no price
    idle_s: float | None        # how long the session sat quiet before this request


@dataclass(frozen=True)
class CacheReport:
    requests: int               # requests that took part in caching
    read: int                   # prompt tokens served from the cache
    prompt: int                 # prompt tokens in those requests
    misses: list[Miss]

    @property
    def hit_rate(self) -> float | None:
        return self.read / self.prompt if self.prompt else None

    @property
    def extra_usd(self) -> float | None:
        priced = [m.extra_usd for m in self.misses if m.extra_usd is not None]
        return sum(priced) if priced else None


def _count(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _extra_usd(model: str, missed: int, wrote: bool) -> float | None:
    info = catalog.lookup(model)
    if info is None or info.input_per_mtok is None or info.cache_read_per_mtok is None:
        return None
    paid = info.cache_write_per_mtok if wrote and info.cache_write_per_mtok is not None else info.input_per_mtok
    return missed * (paid - info.cache_read_per_mtok) / 1_000_000


def analyze(events: list[dict[str, Any]]) -> CacheReport:
    """The cache's record over a session's traced events. A request is compared with the one before it on the same model, only while the
    conversation grows (a shorter one is another conversation or a compaction, and starts over)."""
    previous: dict[str, tuple[int, int, datetime, bool]] = {}   # per model: prompt tokens, messages, when it ended, whether caching was reported
    requests = read = prompt_total = 0
    misses: list[Miss] = []
    for e in events:
        usage = e.get("usage")
        if e.get("event") != "model_request" or not isinstance(usage, dict) or e.get("error"):
            continue
        try:
            ended = datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError, TypeError):
            continue
        ref = f"{e.get('provider')}:{e.get('model')}"
        fresh, cached, wrote = _count(usage.get("input_tokens")), _count(usage.get("cache_read_input_tokens")), _count(usage.get("cache_creation_input_tokens"))
        prompt, count = fresh + cached + wrote, e.get("messages") if isinstance(e.get("messages"), int) else 0
        before = previous.get(ref)
        if before and count < before[1]:
            before = None
        reported = cached + wrote > 0 or bool(before and before[3])
        if reported and prompt > 0:
            requests += 1
            read += cached
            prompt_total += prompt
        if before and reported and prompt > 0:
            missed = min(before[0], prompt) - cached
            if missed > NOISE_FLOOR:
                started = ended.timestamp() - _count(e.get("duration_ms")) / 1000
                misses.append(Miss(e["ts"], ref, missed, _extra_usd(str(e.get("model")), missed, wrote > 0), max(0.0, started - before[2].timestamp())))
        previous[ref] = (prompt, count, ended, reported)
    return CacheReport(requests, read, prompt_total, misses)


def _span(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes} min" if minutes >= 1 else f"{int(seconds)} s"


def describe(report: CacheReport) -> list[str]:
    """The lines /cost shows, or none when nothing used a prompt cache."""
    if not report.requests:
        return []
    lines = ["  Prompt cache:", f"    - {report.read:,} of {report.prompt:,} prompt tokens came from the cache ({report.hit_rate:.0%}) over {report.requests} requests"]
    if not report.misses:
        return lines + ["    - no misses worth naming"]
    extra = f", about ${report.extra_usd:.4f} more than a hit" if report.extra_usd is not None else ""
    after_idle = sum(1 for m in report.misses if m.idle_s is not None and m.idle_s > CACHE_TTL_S)
    lines.append(f"    - {len(report.misses)} miss{'es' if len(report.misses) != 1 else ''}{extra}; {after_idle} after you were away longer than {_span(CACHE_TTL_S)} (the cache had expired)")
    for m in sorted(report.misses, key=lambda m: m.missed, reverse=True)[:3]:
        why = f"after {_span(m.idle_s)} quiet" if m.idle_s is not None and m.idle_s > CACHE_TTL_S else "with no long pause: the start of the prompt changed"
        lines.append(f"      {m.ts[11:19]} {m.ref}: {m.missed:,} tokens billed again, {why}")
    return lines
