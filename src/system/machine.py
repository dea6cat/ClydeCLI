"""What this machine has: total and currently free memory, and macOS sysctl values. Used by local-model sizing,
the tuner and the vitals line, so they all read memory the same way."""
from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

GB = 1024 ** 3


def total_ram_bytes() -> int:
    """Physical memory; 0 when it can't be read."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")   # macOS + Linux
    except (ValueError, OSError, AttributeError):
        return 0


def free_ram_bytes() -> int | None:
    """Memory that can be handed out right now: free, inactive, speculative and purgeable pages (macOS, from vm_stat)
    or MemAvailable (Linux). None when it can't be read."""
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


def sysctl(name: str) -> str:
    """A macOS sysctl value as text; "" when it can't be read."""
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
