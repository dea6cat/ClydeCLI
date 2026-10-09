"""The machine's vitals that decide how a local model and a terminal process run: free memory, swap in use, CPU and GPU load."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from src.providers import fit

_TTL = 3.0           # the prompt redraws on every key; sampling spawns vm_stat, so reuse a reading for a few seconds
LOW_FREE = 2 * fit.GB
SWAP_WARN = 1 * fit.GB
LOAD_WARN = 0.9      # 1-minute load per core
GPU_WARN = 0.9       # read at an idle prompt, so a busy GPU means something else is using it


@dataclass(frozen=True)
class Vitals:
    free: int | None        # bytes available right now
    swap_used: int | None   # bytes paged out to disk
    load: float | None      # 1-minute load average per core
    gpu: float | None = None   # GPU utilization 0-1 (Apple GPU via ioreg, NVIDIA via nvidia-smi)

    @property
    def strained(self) -> bool:
        return bool((self.free is not None and self.free < LOW_FREE)
                    or (self.swap_used is not None and self.swap_used > SWAP_WARN)
                    or (self.load is not None and self.load > LOAD_WARN)
                    or (self.gpu is not None and self.gpu > GPU_WARN))


_UNITS = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
_cache: tuple[float, Vitals] | None = None


def _swap_used() -> int | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=2).stdout
            found = re.search(r"used = ([\d.]+)([KMG])", out)
            return int(float(found.group(1)) * _UNITS[found.group(2)]) if found else None
        info = {k: int(v) for k, v in re.findall(r"^(SwapTotal|SwapFree):\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M)}
        return (info["SwapTotal"] - info["SwapFree"]) * 1024
    except (OSError, subprocess.SubprocessError, KeyError, ValueError):
        return None


def _load() -> float | None:
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except OSError:
        return None


def _gpu() -> float | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["ioreg", "-r", "-d", "1", "-w0", "-c", "IOAccelerator"], capture_output=True, text=True, timeout=2).stdout
            found = re.search(r'"Device Utilization %"=(\d+)', out)
        else:
            out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2).stdout
            found = re.search(r"\d+", out)
        return int(found.group(1 if platform.system() == "Darwin" else 0)) / 100 if found else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def sample() -> Vitals:
    """A reading at most `_TTL` seconds old."""
    global _cache
    if _cache is None or time.monotonic() - _cache[0] > _TTL:
        _cache = (time.monotonic(), Vitals(fit.free_now_bytes(), _swap_used(), _load(), _gpu()))
    return _cache[1]


def line(v: Vitals) -> str:
    """`3.2G free · swap 1.4G · cpu 41% · gpu 12%`, leaving out what couldn't be read."""
    parts = [f"{v.free / fit.GB:.1f}G free" if v.free is not None else "",
             f"swap {v.swap_used / fit.GB:.1f}G" if v.swap_used else "",
             f"cpu {v.load:.0%}" if v.load is not None else "",
             f"gpu {v.gpu:.0%}" if v.gpu is not None else ""]
    return " · ".join(p for p in parts if p)
