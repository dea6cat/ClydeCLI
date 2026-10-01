"""How well a local model fits this machine: relax, balance or hard, plus a rough speed.

A model needs its weights plus working memory (KV cache at a modest context, runtime buffers).
On Apple Silicon the GPU may only wire part of the unified memory: macOS's default is about two
thirds up to 36 GB and three quarters above (`iogpu.wired_limit_mb` overrides it). Elsewhere the
budget is three quarters of RAM, leaving the rest to the OS and other apps.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ollama import _total_ram_bytes

GB = 1024 ** 3
OVERHEAD = int(1.5 * GB)   # ponytail: flat KV + runtime allowance; size it from the model's layers if ratings drift
RATINGS = (("relax", 0.5), ("balance", 0.8), ("hard", 1.0))   # share of the budget a model may use
MEANING = {
    "relax": "plenty of headroom: long context, and your other apps keep running normally",
    "balance": "comfortable, but close other heavy apps (browsers with many tabs, IDEs, Docker) while it runs",
    "hard": "barely fits: short context only, other apps will slow down, and macOS may swap or freeze "
            "the machine while it loads",
}

# Memory bandwidth (GB/s) of Apple chips; decoding speed is bound by it. Longest name match wins.
_BANDWIDTH = {
    "M1": 68, "M1 Pro": 200, "M1 Max": 400, "M1 Ultra": 800,
    "M2": 100, "M2 Pro": 200, "M2 Max": 400, "M2 Ultra": 800,
    "M3": 100, "M3 Pro": 150, "M3 Max": 400, "M3 Ultra": 819,
    "M4": 120, "M4 Pro": 273, "M4 Max": 546,
}
_EFFICIENCY = 0.6   # ponytail: real decoding reaches roughly 60% of peak bandwidth; tune against measured tok/s


@dataclass(frozen=True)
class Offer:
    """One downloadable model from a source, sized and rated for this machine."""
    name: str          # what the source calls it
    pull_tag: str      # what the downloader takes: an ollama tag, hf.co/<repo>:<quant>, or a Hugging Face URL
    size_bytes: int    # the weights' download size (exact, or estimated by the source)
    rating: str        # relax | balance | hard
    popularity: int    # pulls or downloads, for ranking
    note: str = ""     # e.g. the quantization
    source: str = ""   # the source module that offered it (ollama, hf, mlx)


def _sysctl(name: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def free_now_bytes() -> int | None:
    """Memory available right now (free + reclaimable pages), or None when it can't be read."""
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=2).stdout
            page = int(re.search(r"page size of (\d+)", out).group(1))
            pages = {k.strip(): int(v.strip(" .")) for k, v in re.findall(r"^Pages ([^:]+):\s+(\d+)\.", out, re.M)}
            return page * sum(pages.get(k, 0) for k in ("free", "inactive", "speculative", "purgeable"))
        meminfo = Path("/proc/meminfo").read_text()
        return int(re.search(r"MemAvailable:\s+(\d+) kB", meminfo).group(1)) * 1024
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        return None


def models_dir() -> Path:
    """Where Ollama stores pulled models."""
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def disk_free_bytes() -> int | None:
    """Free disk space where Ollama stores models (or the nearest existing parent)."""
    path = models_dir()
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def chip() -> str:
    """The CPU brand string ("Apple M3 Pro"), or "" when unknown."""
    return _sysctl("machdep.cpu.brand_string") if platform.system() == "Darwin" else ""


def budget_bytes(ram: int | None = None, apple: bool | None = None, wired_limit_mb: int | None = None) -> int:
    """Memory a local model may use on this machine."""
    ram = _total_ram_bytes() if ram is None else ram
    apple = chip().startswith("Apple") if apple is None else apple
    if not apple:
        return int(ram * 0.75)
    if wired_limit_mb is None:
        limit = _sysctl("iogpu.wired_limit_mb")
        wired_limit_mb = int(limit) if limit.isdigit() else 0
    if wired_limit_mb > 0:
        return wired_limit_mb * 1024 ** 2
    return int(ram * (2 / 3 if ram <= 36 * GB else 0.75))


def share(file_bytes: int, budget: int) -> float:
    """The part of the model budget a model of this size takes while loaded."""
    return (file_bytes + OVERHEAD) / budget if budget else 2.0


def rate(file_bytes: int, budget: int) -> str | None:
    """relax, balance or hard for a model file of this size; None when it won't fit."""
    used = share(file_bytes, budget)
    return next((name for name, limit in RATINGS if used <= limit), None)


_MOE = re.compile(r"(\d+(?:\.\d+)?)b-a(\d+(?:\.\d+)?)b", re.I)


def tokens_per_s(file_bytes: int, chip_name: str, model_name: str = "") -> int | None:
    """Rough decoding speed on an Apple chip, or None when the chip's bandwidth is unknown. A
    mixture-of-experts name like 30B-A3B reads only its active share of the weights per token."""
    names = [n for n in _BANDWIDTH if chip_name.removeprefix("Apple ").startswith(n)]
    if not names or not file_bytes:
        return None
    moe = _MOE.search(model_name)
    read = file_bytes * (float(moe.group(2)) / float(moe.group(1)) if moe else 1)
    return round(_BANDWIDTH[max(names, key=len)] * GB * _EFFICIENCY / read)


def pick(variants: list[tuple[str, int]], budget: int) -> tuple[str, int, str] | None:
    """(tag, bytes, rating) of the variant to offer: the largest that runs relax or balance, else
    the largest that runs at all. None when nothing fits."""
    rated = [(tag, size, r) for tag, size in variants if (r := rate(size, budget))]
    easy = [v for v in rated if v[2] != "hard"]
    return max(easy or rated, key=lambda v: v[1]) if rated else None
