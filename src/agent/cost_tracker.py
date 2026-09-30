from __future__ import annotations

from dataclasses import dataclass, field

from ..providers import catalog

# Usage-dict keys (see ProviderResponse.usage) and the catalog price that bills each one.
# input_tokens is always the uncached remainder; cache reads/writes are billed separately.
_BILLED = (
    ("input_tokens", "input_per_mtok"),
    ("output_tokens", "output_per_mtok"),
    ("cache_read_input_tokens", "cache_read_per_mtok"),
    ("cache_creation_input_tokens", "cache_write_per_mtok"),
)


@dataclass
class CostTracker:
    total_units: int = 0
    events: list[str] = field(default_factory=list)
    # "provider:model" -> summed usage-dict counts
    models: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, label: str, units: int) -> None:
        self.total_units += units
        self.events.append(f'{label}:{units}')

    def record_usage(self, provider: str, model: str, usage: dict, label: str = "turn") -> None:
        totals = self.models.setdefault(f"{provider}:{model}", {})
        for key, _ in _BILLED:
            if isinstance(usage.get(key), int):
                totals[key] = totals.get(key, 0) + usage[key]
        self.record(label, usage.get("input_tokens", 0) + usage.get("output_tokens", 0))


def estimate_usd(ref: str, usage: dict[str, int]) -> float | None:
    """Estimated USD for a "provider:model" usage total; 0 for local Ollama, None if unpriced."""
    provider, _, model = ref.partition(":")
    if provider == "ollama":
        return 0.0
    info = catalog.lookup(model)
    if info is None or info.input_per_mtok is None or info.output_per_mtok is None:
        return None
    total = 0.0
    for key, price_field in _BILLED:
        # ponytail: a cache price missing from the catalog bills at the input price (upper bound).
        price = getattr(info, price_field)
        total += usage.get(key, 0) * (info.input_per_mtok if price is None else price)
    return total / 1_000_000
