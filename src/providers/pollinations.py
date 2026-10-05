"""Pollinations (gen.pollinations.ai) through its OpenAI-compatible endpoint.

One key (POLLINATIONS_API_KEY, `sk_...` from enter.pollinations.ai/keys) covers text, image, video and audio, but
Clyde only chats, so /v1/models is asked for tool-capable text models. Community models are left out: they run on
their owners' servers, which would see every prompt. Model ids are `publisher/model`; the old short names still
work in requests as aliases.
"""
from __future__ import annotations

import json

from .base import ProviderError, get_json, http_error_message
from .openai_compat import OpenAICompatProvider, _is_chat_model

BASE_URL = "https://gen.pollinations.ai/v1"
_QUERY = "capabilities=tool_calling&source=official&limit=500"
# Out of credits, Pollinations answers 200 with a chat message instead of a 402. Its links carry this stable
# tracking marker (ref=agent_low_balance_topup / _quests), which is what gives the notice away.
_LOW_BALANCE = "agent_low_balance"
_OUT_OF_CREDITS = "top up at https://enter.pollinations.ai/top-up or complete a quest at https://enter.pollinations.ai/quests"


class PollinationsProvider(OpenAICompatProvider):
    def __init__(self) -> None:
        super().__init__("pollinations", BASE_URL, "POLLINATIONS_API_KEY", dynamic_models=True)

    def _fetch_models(self) -> list[str]:
        data = get_json(f"{self.base_url}/models?{_QUERY}", headers=self._headers(), provider=self.name)
        rows = data.get("data") or []
        return sorted(m["id"] for m in rows if isinstance(m, dict) and m.get("id") and m.get("category") == "text"
                      and _is_chat_model(m["id"]))

    def stream(self, conversation, model, tools, on_text, **kwargs):  # type: ignore[no-untyped-def]
        response = super().stream(conversation, model, tools, on_text, **kwargs)
        if not response.message.tool_calls and _LOW_BALANCE in (response.message.text or ""):
            # A real error, so the notice isn't kept in the conversation as if the model had said it,
            # and /eval counts it as transient instead of marking the model as failing.
            raise ProviderError(self.name, http_error_message(402, json.dumps({"error": {"message": _OUT_OF_CREDITS}}), ""),
                                status=402)
        return response
