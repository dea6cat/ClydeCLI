"""Cloudflare Workers AI through its OpenAI-compatible endpoint.

Chat Completions live at https://api.cloudflare.com/client/v4/accounts/<account id>/ai/v1, so the base URL
carries the account id (CLOUDFLARE_ACCOUNT_ID) and the key is an API token (CLOUDFLARE_API_TOKEN, from
`wrangler auth token` or the Workers AI dashboard). That endpoint has no /models; the catalog comes from
/ai/models/search instead, kept to text-generation models that can call tools.
"""
from __future__ import annotations

import os
import urllib.parse

from .base import get_json
from .openai_compat import OpenAICompatProvider

API = "https://api.cloudflare.com/client/v4"
ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"
_PER_PAGE = 100
_MAX_PAGES = 10


class CloudflareProvider(OpenAICompatProvider):
    def __init__(self) -> None:
        super().__init__("cloudflare", "", "CLOUDFLARE_API_TOKEN", dynamic_models=True)

    @property
    def account(self) -> str:
        return os.environ.get(ACCOUNT_ENV, "").strip()

    @property  # type: ignore[override]
    def base_url(self) -> str:
        return f"{API}/accounts/{self.account}/ai/v1"

    @base_url.setter
    def base_url(self, _value: str) -> None:
        """Fixed by the account id; the parent's constructor assigns one, which is ignored."""

    def is_available(self) -> bool:
        return bool(self.api_key and self.account)

    def _fetch_models(self) -> list[str]:
        found: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            query = urllib.parse.urlencode({"task": "Text Generation", "per_page": _PER_PAGE, "page": page})
            data = get_json(f"{API}/accounts/{self.account}/ai/models/search?{query}", headers=self._headers(), provider=self.name)
            rows = [m for m in data.get("result") or [] if isinstance(m, dict) and m.get("name")]
            found += rows
            if len(rows) < _PER_PAGE:
                break
        return sorted(m["name"] for m in found if _calls_tools(m, found))


def _calls_tools(model: dict, everything: list[dict]) -> bool:
    """Whether the catalog says `model` supports function calling. When no model in the catalog carries
    that property (the field moved), nothing is dropped on its account."""
    def flag(m: dict) -> str | None:
        return next((str(p.get("value")).lower() for p in m.get("properties") or [] if p.get("property_id") == "function_calling"), None)
    if all(flag(m) is None for m in everything):
        return True
    return flag(model) == "true"
