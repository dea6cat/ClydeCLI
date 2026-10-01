"""Discover installable, tool-capable local models live from ollama.com/search, filtered to
what fits the machine and ranked by popularity. Stdlib only.

ollama.com renders the model grid only inside its htmx fragment (a plain GET of /search
returns the app shell), so the HX-* headers the page itself sends are included. Two card
markups are supported: the older `<li x-test-model>` spans and the current
`<a class="group w-full">` card with chip spans. Every entry point NEVER raises and returns []
on any failure (offline, site changed, nothing parsed).
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request

from .base import _USER_AGENT
from .fit import Offer, pick

SEARCH_URL = "https://ollama.com/search?c=tools"
CODING_URL = "https://ollama.com/search?q=coding&c=tools"
_MAX_BYTES = 5_000_000

_HX_HEADERS = {
    "HX-Request": "true",
    "HX-Target": "#searchresults",
    "HX-Current-URL": "https://ollama.com/search",
}

# --- legacy markup (x-test-* markers) ---
_BLOCK = re.compile(r"<li[^>]*x-test-model")
_SLUG = re.compile(r'href="/library/([a-z0-9][a-z0-9._:-]*)"', re.I)
_CAP = re.compile(r"x-test-capability[^>]*>\s*([a-z]+)", re.I)
_SIZE = re.compile(r"x-test-size[^>]*>\s*([0-9]+(?:\.[0-9]+)?)b\b", re.I)
_PULLS = re.compile(r"x-test-pull-count[^>]*>\s*([0-9][0-9.,]*)\s*([KM]?)", re.I)

# --- current markup (a.group / chip spans) ---
_CARD = re.compile(r'<a [^>]*class="group w-full"[^>]*>.*?</a>', re.S | re.I)
_CARD_SLUG = re.compile(r'href="/library/([a-z0-9][a-z0-9._:-]*)"', re.I)
_SIZE_CHIP = re.compile(
    r'<span\s+class="[^"]*bg-\[#ddf4ff\][^"]*">\s*([0-9]+(?:\.[0-9]+)?)b\s*</span>', re.I)
_CAP_CHIP = re.compile(
    r'<span\s+class="[^"]*bg-indigo-50[^"]*">\s*([a-z]+)\s*</span>', re.I)
_PULLS_CHIP = re.compile(
    r'<span\s*>\s*([0-9][0-9.,]*)\s*([KM]?)\s*</span>\s*<span class="hidden sm:flex">', re.I)


def _fetch(url: str, headers: dict) -> str | None:
    """GET a fixed ollama.com URL; the decoded body, or None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*", **headers})
        with urllib.request.urlopen(req, timeout=6) as r:
            raw = r.read(_MAX_BYTES)
            charset = r.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")
    except Exception:
        return None


def _pulls_to_int(num: str, suffix: str) -> int:
    try:
        n = float(num.replace(",", ""))
    except ValueError:
        return 0
    return int(n * {"k": 1_000, "m": 1_000_000}.get(suffix.lower(), 1))


def est_ram(params_b: float) -> int:
    """Rough RAM (GB) a model needs: weights (~Q4) + KV/overhead ≈ params + 2, min 4."""
    return max(4, round(params_b) + 2)


def _fmt(b: float) -> str:
    return str(int(b)) if float(b).is_integer() else str(b)


def fit_variant(sizes: list[float], ram_gb: int) -> float | None:
    """The largest parameter size that fits `ram_gb`, or None if none fit."""
    fits = [b for b in sizes if est_ram(b) <= ram_gb]
    return max(fits) if fits else None


def _parse(block: str, slug_re, size_re, cap_re, pulls_re) -> dict | None:
    m = slug_re.search(block)
    if not m:
        return None
    try:
        sizes = sorted({float(s) for s in size_re.findall(block)})
        caps = {c.lower() for c in cap_re.findall(block)}
        pm = pulls_re.search(block)
        pulls = _pulls_to_int(*pm.groups()) if pm else 0
    except Exception:
        return None
    return {"slug": m.group(1), "sizes": sizes, "caps": caps, "pulls": pulls}


def parse_search(html: str) -> list[dict]:
    """Per-model dicts {slug, sizes:[float], caps:{str}, pulls:int} from the search HTML. A card
    that doesn't parse cleanly is skipped. The markup variant is detected automatically."""
    out: list[dict] = []
    if not html:
        return out
    if _BLOCK.search(html):
        for block in _BLOCK.split(html)[1:]:
            c = _parse(block.split("</li>", 1)[0], _SLUG, _SIZE, _CAP, _PULLS)
            if c:
                out.append(c)
    else:
        for card in _CARD.findall(html):
            c = _parse(card, _CARD_SLUG, _SIZE_CHIP, _CAP_CHIP, _PULLS_CHIP)
            if c:
                out.append(c)
    return out


# Ollama's default tags are Q4_K_M, about 4.85 bits per parameter.
_Q4_BYTES_PER_B = 0.6e9


def search(query: str, budget: int) -> list[Offer]:
    """Tool-capable ollama.com models matching `query` (the most pulled when empty) that fit
    `budget` bytes, each at its best-fitting size, ranked by pulls. [] on any failure."""
    if os.environ.get("CLYDE_NO_MODEL_FETCH"):
        return []
    url = f"https://ollama.com/search?q={urllib.parse.quote(query)}&c=tools" if query else SEARCH_URL
    offers = []
    for c in parse_search(_fetch(url, _HX_HEADERS) or ""):
        if "tools" not in c["caps"]:
            continue
        best = pick([(f"{c['slug']}:{_fmt(b)}b", int(b * _Q4_BYTES_PER_B)) for b in c["sizes"]], budget)
        if best:
            offers.append(Offer(c["slug"], best[0], best[1], best[2], c["pulls"], "est. Q4"))
    return sorted(offers, key=lambda o: o.popularity, reverse=True)


def discover(ram_gb: int, search_url: str = SEARCH_URL) -> list[tuple[str, int, int]]:
    """[(pull_tag, pulls, est_ram)] for tool-capable models with a variant that fits `ram_gb`,
    ranked by pulls. [] on any failure, or when CLYDE_NO_MODEL_FETCH is set."""
    if os.environ.get("CLYDE_NO_MODEL_FETCH"):
        return []
    try:
        rows = []
        for c in parse_search(_fetch(search_url, _HX_HEADERS) or ""):
            if "tools" not in c["caps"] or not c["sizes"]:
                continue
            b = fit_variant(c["sizes"], ram_gb)
            if b is None:
                continue
            rows.append((f"{c['slug']}:{_fmt(b)}b", c["pulls"], est_ram(b)))
        rows.sort(key=lambda r: r[1], reverse=True)
        return rows
    except Exception:
        return []
