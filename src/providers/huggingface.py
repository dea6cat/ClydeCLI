"""Hugging Face as a source of local models: GGUF repos matching a search, each offered at the
largest quantization that fits this machine. Ollama pulls them as `hf.co/<repo>:<quant>`.
Stdlib only, no key; every entry point returns [] on any failure.
"""
from __future__ import annotations

import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .base import ProviderError, get_json
from .fit import Offer, pick

API = "https://huggingface.co/api/models"
_REPOS = 15     # repos looked at per search
_QUANT = re.compile(r"[-_.]((?:I?Q\d(?:_[A-Z0-9]+)*)|F16|BF16)\.gguf$", re.I)
_SPLIT = re.compile(r"-\d{5}-of-\d{5}\.gguf$")
# Repos tagged text-generation that can't chat: embedding and reranker models (seen live: Qwen3-Embedding).
_NOT_CHAT = re.compile(r"embed|rerank", re.I)


# A chat template that never mentions tools can't render a tool call. No template at all (it can live in a
# separate file) proves nothing, so only a template that is present and silent drops the repo.
_TOOLS = re.compile(r"\btools?\b|tool_call", re.I)
_EXPAND = {"gguf": ["gguf", "downloads", "cardData"], "mlx": ["config", "downloads", "cardData"]}
_CHAT_NAME = re.compile(r"instruct|chat|[-_]it\b|assistant|thinking|\bsft\b|dpo", re.I)


def _lacks_tools(repo: dict, fmt: str) -> bool:
    meta = repo.get("gguf") if fmt == "gguf" else (repo.get("config") or {}).get("tokenizer_config")
    template = meta.get("chat_template") if isinstance(meta, dict) else None
    return bool(template) and not _TOOLS.search(str(template))


def _is_base(repo: dict) -> bool:
    """A quant of a base (pretrained, not chat-tuned) model: it writes tool calls as prose and ignores tool
    results. Its card names the base model; that model is a base when an `-Instruct` sibling is published
    (Qwen2.5-Coder-7B has one, a hybrid like Qwen3-8B doesn't). HF answers 200 only for repos that exist,
    so any other reply keeps the repo. ponytail: only the `-Instruct` suffix is probed, not `-it` or `-Chat`."""
    base = (repo.get("cardData") or {}).get("base_model")
    base = base[0] if isinstance(base, list) and base else base
    if not isinstance(base, str) or "/" not in base or _CHAT_NAME.search(base) or _CHAT_NAME.search(str(repo.get("id", ""))):
        return False
    try:
        return isinstance(get_json(f"{API}/{base}-Instruct", provider="huggingface", timeout=10), dict)
    except ProviderError:
        return False


def _quants(files: list[dict]) -> list[tuple[str, int]]:
    """(quant, bytes) for the single-file GGUFs at the repo root. Split files, vision projectors
    (mmproj) and speculative-decoding drafts are skipped. When several files share a quant (a
    `noMTP-Q4_K_M` beside `Q4_K_M`), Ollama's `:Q4_K_M` tag may fetch any of them, so the largest
    size is the one reported: a rating must never understate the download."""
    sizes: dict[str, int] = {}
    for f in files:
        path, size = str(f.get("path", "")), f.get("size")
        m = _QUANT.search(path)
        lower = path.lower()
        if f.get("type") != "file" or not m or not isinstance(size, int) or _SPLIT.search(path) \
                or "mmproj" in lower or "draft" in lower:
            continue
        quant = m.group(1).upper()
        sizes[quant] = max(size, sizes.get(quant, 0))
    return list(sizes.items())


def files(repo_id: str) -> list[dict]:
    """The files at a repo's root ({type, path, size}); [] on any failure."""
    try:
        listing = get_json(f"{API}/{repo_id}/tree/main", provider="huggingface", timeout=10)
    except ProviderError:
        return []
    return listing if isinstance(listing, list) else []


def offers(fmt: str, query: str, offer: Callable[[dict], Offer | None]) -> list[Offer]:
    """Text-generation repos in format `fmt` (gguf, mlx) matching `query` (the most downloaded when
    empty) whose chat template can call tools, each turned into an Offer by `offer` (None drops it), ranked by downloads."""
    if os.environ.get("CLYDE_NO_MODEL_FETCH"):
        return []
    params = {"filter": fmt, "pipeline_tag": "text-generation", "sort": "downloads", "direction": "-1",
              "limit": str(_REPOS), "expand[]": _EXPAND[fmt]}
    if query:
        params["search"] = query
    try:
        repos = get_json(f"{API}?{urllib.parse.urlencode(params, doseq=True)}", provider="huggingface", timeout=10)
    except ProviderError:
        return []
    if not isinstance(repos, list):
        return []
    repos = [r for r in repos if isinstance(r, dict) and not _NOT_CHAT.search(str(r.get("id", ""))) and not _lacks_tools(r, fmt)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        repos = [r for r, base in zip(repos, pool.map(_is_base, repos)) if not base]
        found = [o for o in pool.map(offer, repos) if o is not None]
    return sorted(found, key=lambda o: o.popularity, reverse=True)


def search(query: str, budget: int) -> list[Offer]:
    """GGUF repos matching `query` that fit `budget` bytes, each at its best-fitting quant."""
    def offer(repo: dict) -> Offer | None:
        repo_id = repo.get("id", "")
        best = pick(_quants(files(repo_id)), budget)
        if best is None:
            return None
        quant, size, rating = best
        return Offer(repo_id, f"hf.co/{repo_id}:{quant}", size, rating, int(repo.get("downloads") or 0), quant, "hf")
    return offers("gguf", query, offer)
