"""cardShuffle: a virtual provider whose models are tiers. Each user turn is dealt to a real model
that passed /eval; a failing or stuck model is swapped for the next card in the deck.

Tiers (models):
  high-roller  strongest first
  house        by mode: reading the table (plan) gets the strongest, other modes the middle card
  free         local models only (Ollama, LM Studio), strongest first
  small        weakest first, for quick and cheap turns

Strength is how many of /eval's hard tasks a model solved; ties go to the faster model.
"""
from __future__ import annotations

from typing import Callable

from .base import ProviderError, ProviderResponse, _Cancelled
from .model_eval import load_results
from .types import Conversation

NAME = "cardShuffle"
TIERS = ("high-roller", "house", "free", "small")
LOCAL = ("ollama", "lmstudio")


def by_strength(results: dict[str, dict]) -> list[str]:
    """Refs weakest to strongest; among equals the faster model ranks higher. Models evaluated
    before the hard tasks existed count as strength 0 until /eval runs again."""
    def key(ref: str) -> tuple[int, float]:
        r = results[ref]
        return r.get("strength") or 0, r.get("tokens_per_s") or 0.0
    return sorted(results, key=key)


def deck(tier: str, results: dict[str, dict], mode: str = "hold") -> list[str]:
    """The order a tier deals in: first card first, then the fallbacks."""
    ranked = by_strength(results)
    if tier == "small":
        return ranked
    if tier == "free":
        ranked = [r for r in ranked if r.partition(":")[0] in LOCAL]
    if tier == "house" and mode != "plan" and ranked:
        # The middle card, then stronger ones, then weaker ones.
        mid = len(ranked) // 2
        return ranked[mid:] + ranked[:mid][::-1]
    return ranked[::-1]


class CardShuffle:
    """Deals each user turn to a real provider from the registry it is given."""

    name = NAME

    def __init__(self, registry: dict) -> None:
        self.registry = registry
        self.mode = "hold"                      # the REPL keeps this in step with Shift+Tab
        self.on_deal: Callable[[str, str], None] | None = None
        self.dealt: str | None = None
        self.spent: list[tuple[str, dict]] = []  # (ref, usage) per real call, drained by the REPL for /cost
        self._deck: list[str] = []
        self._burned: set[str] = set()

    def is_available(self) -> bool:
        return bool(self._candidates(check=False))

    def list_models(self) -> list[str]:
        return list(TIERS)

    def _candidates(self, check: bool = True) -> dict[str, dict]:
        """Eval results of the models that passed /eval (and, with check, whose provider is connected now)."""
        out = {}
        for ref, r in load_results().items():
            if not r.get("passed") or ref.startswith(f"{NAME}:"):
                continue
            if check:
                provider = self.registry.get(ref.partition(":")[0])
                try:
                    if provider is None or not provider.is_available():
                        continue
                except Exception:
                    continue
            out[ref] = r
        return out

    def _deal(self, why: str) -> str:
        card = next((r for r in self._deck if r not in self._burned), None)
        if card is None:
            raise ProviderError(NAME, "no model left to deal: every candidate failed or none passed /eval "
                                      "(run /eval, then try again)")
        self.dealt = card
        if self.on_deal is not None:
            self.on_deal(card, why)
        return card

    def shuffle(self, tier: str) -> str:
        """Build this turn's deck and deal its first card."""
        if tier not in TIERS:
            raise ProviderError(NAME, f"unknown tier '{tier}' (one of {', '.join(TIERS)})")
        self._deck, self._burned = deck(tier, self._candidates(), self.mode), set()
        return self._deal(tier)

    def redeal(self, why: str) -> bool:
        """Burn the dealt card and deal the next one; False when the deck is spent."""
        if self.dealt is not None:
            self._burned.add(self.dealt)
        try:
            self._deal(why)
        except ProviderError:
            return False
        return True

    def stream(self, conversation: Conversation, model: str, tools, on_text, *, cancel=None,
               reasoning=None, on_thinking=None) -> ProviderResponse:
        last = conversation.messages[-1] if conversation.messages else None
        if self.dealt is None or last is None or not last.tool_results:
            self.shuffle(model)   # a fresh user message (not a tool round) opens a new turn
        while True:
            provider_name, _, real_model = self.dealt.partition(":")
            try:
                response = self.registry[provider_name].stream(
                    conversation, real_model, tools, on_text, cancel=cancel, reasoning=reasoning, on_thinking=on_thinking)
            except _Cancelled:
                raise
            except Exception as e:
                if (cancel is not None and cancel.is_set()) or not self.redeal(f"{self.dealt} failed: {str(e)[:80]}"):
                    raise
                continue
            if response.usage:
                self.spent.append((self.dealt, response.usage))
            return response
