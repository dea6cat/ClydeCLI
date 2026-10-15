"""Hugging Face as a source of local models: GGUF repos matching a search, each offered at the
largest quantization that fits this machine. Ollama pulls them as `hf.co/<repo>:<quant>`.
Stdlib only, no key; every entry point returns [] on any failure.
"""
from __future__ import annotations

import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from .base import ProviderError, get_json, get_text
from .fit import TOO_LARGE, Offer, pick, rate

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


def repo_lacks_tools(repo_id: str) -> bool:
    """True when a GGUF repo's chat template can't render a tool call; False when Hugging Face doesn't say or is unreachable."""
    try:
        info = get_json(f"{API}/{repo_id}?expand[]=gguf", provider="huggingface", timeout=10)
    except ProviderError:
        return False
    return isinstance(info, dict) and _lacks_tools(info, "gguf")


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


def gguf_offer(repo: dict, budget: int) -> Offer | None:
    """One GGUF repo ({id, downloads}) at its best-fitting quant, with every quant as an option; None when none fits."""
    repo_id = repo.get("id", "")
    quants = _quants(files(repo_id))
    best = pick(quants, budget)
    if best is None:
        return None
    quant, size, rating = best
    downloads = int(repo.get("downloads") or 0)

    def download(q: str, s: int) -> Offer:
        return Offer(repo_id, f"hf.co/{repo_id}:{q}", s, rate(s, budget) or TOO_LARGE, downloads, q, "hf")
    options = tuple(download(q, s) for q, s in sorted(quants, key=lambda v: v[1])) if len(quants) > 1 else ()
    return Offer(repo_id, f"hf.co/{repo_id}:{quant}", size, rating, downloads, quant, "hf", options=options)


def search(query: str, budget: int) -> list[Offer]:
    """GGUF repos matching `query` that fit `budget` bytes, each at its best-fitting quant."""
    return offers("gguf", query, lambda repo: gguf_offer(repo, budget))


@dataclass(frozen=True)
class Details:
    """What a model's page shows: the Hub's numbers, the README's opening paragraph, capabilities read from the
    repo, and other repos by the same author in the same format."""
    author: str
    downloads: int
    likes: int
    updated: str                  # ISO time of the last change
    params: int | None
    arch: str
    context: int | None           # tokens
    license: str
    summary: str
    tools: bool | None            # the chat template can render a tool call; None when there is no template to read
    vision: bool                  # inferred from the pipeline tag, tags or a projector file
    reasoning: bool              # inferred from tags and the name
    related: tuple[tuple[str, int, int], ...]   # (repo id, downloads, likes), most downloaded first


_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SKIP = ("#", ">", "<", "|", "!", "[!", "```", "- ", "* ", "---", "1.")
_REASON = re.compile(r"reason|think|\br1\b", re.I)


def _summary(readme: str, limit: int = 280) -> str:
    """The first real paragraph of a README (not a heading, note, badge, table or code), cut at a word."""
    body = re.sub(r"\A---\n.*?\n---\n", "", readme, flags=re.S)
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para or para.startswith(_SKIP) or "```" in para:
            continue
        text = " ".join(_MD_LINK.sub(r"\1", para).replace("**", "").replace("`", "").split())
        if len(text) >= 40:
            return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def details(repo_id: str, fmt: str = "gguf") -> Details | None:
    """A repo's page data; None when the Hub can't be reached for it. The README and the author's other repos
    are best effort: without them the page just lacks a description and a related list."""
    if os.environ.get("CLYDE_NO_MODEL_FETCH"):
        return None
    fields = ["downloads", "likes", "lastModified", "cardData", "tags", "pipeline_tag", "author", "siblings",
              "gguf" if fmt == "gguf" else "config"]
    try:
        info = get_json(f"{API}/{repo_id}?{urllib.parse.urlencode({'expand[]': fields}, doseq=True)}", provider="huggingface", timeout=10)
    except ProviderError:
        return None
    if not isinstance(info, dict):
        return None
    author = str(info.get("author") or repo_id.split("/")[0])

    def readme() -> str:
        try:
            return get_text(f"https://huggingface.co/{repo_id}/raw/main/README.md", provider="huggingface", timeout=10)
        except ProviderError:
            return ""

    def others() -> list:
        query = {"author": author, "filter": fmt, "pipeline_tag": "text-generation", "sort": "downloads", "direction": "-1", "limit": "8"}
        try:
            found = get_json(f"{API}?{urllib.parse.urlencode(query)}", provider="huggingface", timeout=10)
        except ProviderError:
            return []
        return found if isinstance(found, list) else []
    with ThreadPoolExecutor(max_workers=2) as pool:
        text, found = pool.submit(readme), pool.submit(others)
        text, found = text.result(), found.result()
    meta = info.get("gguf") if fmt == "gguf" else (info.get("config") or {}).get("tokenizer_config")
    meta = meta if isinstance(meta, dict) else {}
    template = meta.get("chat_template")
    tags = [str(t) for t in info.get("tags") or []]
    card = info.get("cardData") or {}
    license_ = card.get("license") or next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
    related = tuple((r["id"], int(r.get("downloads") or 0), int(r.get("likes") or 0)) for r in found
                    if isinstance(r, dict) and r.get("id") and r["id"] != repo_id and not _NOT_CHAT.search(r["id"]))[:5]
    return Details(
        author, int(info.get("downloads") or 0), int(info.get("likes") or 0), str(info.get("lastModified") or ""),
        meta.get("total") if isinstance(meta.get("total"), int) else None, str(meta.get("architecture") or ""),
        meta.get("context_length") if isinstance(meta.get("context_length"), int) else None,
        str(license_[0] if isinstance(license_, list) and license_ else license_),
        _summary(text), None if not template else bool(_TOOLS.search(str(template))),
        info.get("pipeline_tag") == "image-text-to-text" or any(t in ("vision", "image-text-to-text", "multimodal") for t in tags)
        or any("mmproj" in str(s.get("rfilename", "")).lower() for s in info.get("siblings") or [] if isinstance(s, dict)),
        bool(_REASON.search(" ".join(tags) + " " + repo_id)), related)
