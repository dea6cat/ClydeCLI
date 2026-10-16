"""How many billion parameters a model has, as far as Clyde can tell: what the provider reports, else the size in its name."""
from __future__ import annotations

import re
from typing import Any

# 3b, 3B, 1.5b, 30b-a3b (the first): not the 2.5 in qwen2.5, not 8x7b (a mixture, left unknown).
_NAME = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*b(?![a-z])", re.IGNORECASE)
_REPORTED = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([MBT])\s*$", re.IGNORECASE)   # Ollama: "3.09B", "494.03M"
_UNIT = {"M": 0.001, "B": 1.0, "T": 1000.0}


def parse_reported(text: Any) -> float | None:
    """Billions from a size a provider reports ("3.09B", "494.03M"), or None."""
    match = _REPORTED.match(text) if isinstance(text, str) else None
    return float(match.group(1)) * _UNIT[match.group(2).upper()] if match else None


def billions(provider: Any, model: str) -> float | None:
    """The model's size in billions of parameters, or None when neither the provider nor the name says."""
    reported = getattr(provider, "parameter_billions", None)
    if callable(reported) and (size := reported(model)) is not None:
        return size
    match = _NAME.search(model)
    return float(match.group(1)) if match else None
