"""Hugging Face as a source of local models: GGUF repos matching a search, each offered at the
largest quantization that fits this machine. Ollama pulls them as `hf.co/<repo>:<quant>`.
Stdlib only, no key; every entry point returns [] on any failure.
"""
from __future__ import annotations

import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from .base import ProviderError, get_json
from .fit import Offer, pick

API = "https://huggingface.co/api/models"
_REPOS = 15     # repos looked at per search
_QUANT = re.compile(r"[-_.]((?:I?Q\d(?:_[A-Z0-9]+)*)|F16|BF16|F32)\.gguf$", re.I)
_SPLIT = re.compile(r"-\d{5}-of-\d{5}\.gguf$")


def _quants(files: list[dict]) -> list[tuple[str, int]]:
    """(quant, bytes) for each single-file GGUF at the repo root. Split files and vision
    projectors (mmproj) are skipped: ollama pulls one file per tag."""
    out = []
    for f in files:
        path, size = str(f.get("path", "")), f.get("size")
        m = _QUANT.search(path)
        if f.get("type") != "file" or not m or not isinstance(size, int) or "mmproj" in path.lower() or _SPLIT.search(path):
            continue
        out.append((m.group(1).upper(), size))
    return out


def _offer(repo: dict, budget: int) -> Offer | None:
    repo_id = repo.get("id", "")
    try:
        files = get_json(f"{API}/{repo_id}/tree/main", provider="huggingface", timeout=10)
    except ProviderError:
        return None
    best = pick(_quants(files if isinstance(files, list) else []), budget)
    if best is None:
        return None
    quant, size, rating = best
    return Offer(repo_id, f"hf.co/{repo_id}:{quant}", size, rating, int(repo.get("downloads") or 0), quant)


def search(query: str, budget: int) -> list[Offer]:
    """GGUF repos matching `query` (the most downloaded when empty) that fit `budget` bytes,
    ranked by downloads."""
    if os.environ.get("CLYDE_NO_MODEL_FETCH"):
        return []
    params = {"filter": "gguf", "sort": "downloads", "direction": "-1", "limit": str(_REPOS)}
    if query:
        params["search"] = query
    try:
        repos = get_json(f"{API}?{urllib.parse.urlencode(params)}", provider="huggingface", timeout=10)
    except ProviderError:
        return []
    if not isinstance(repos, list):
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        offers = [o for o in pool.map(lambda r: _offer(r, budget), repos) if o is not None]
    return sorted(offers, key=lambda o: o.popularity, reverse=True)
