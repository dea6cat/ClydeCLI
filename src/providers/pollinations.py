"""Pollinations (gen.pollinations.ai) through its OpenAI-compatible endpoint.

One key (POLLINATIONS_API_KEY, `sk_...` from enter.pollinations.ai/keys) covers text, image, video and audio, but
Clyde only chats, so /v1/models is asked for tool-capable text models. Community models are left out: they run on
their owners' servers, which would see every prompt. Model ids are `publisher/model`; the old short names still
work in requests as aliases.
"""
from __future__ import annotations

from .base import get_json
from .openai_compat import OpenAICompatProvider, _is_chat_model

BASE_URL = "https://gen.pollinations.ai/v1"
_QUERY = "capabilities=tool_calling&source=official&limit=500"


class PollinationsProvider(OpenAICompatProvider):
    def __init__(self) -> None:
        super().__init__("pollinations", BASE_URL, "POLLINATIONS_API_KEY", dynamic_models=True)

    def _fetch_models(self) -> list[str]:
        data = get_json(f"{self.base_url}/models?{_QUERY}", headers=self._headers(), provider=self.name)
        rows = data.get("data") or []
        return sorted(m["id"] for m in rows if isinstance(m, dict) and m.get("id") and m.get("category") == "text"
                      and _is_chat_model(m["id"]))
