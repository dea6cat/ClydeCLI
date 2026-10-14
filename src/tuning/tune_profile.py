"""What the user wants from a local model, as a few answers `clyde tune` turns into rules.

The answers are kept in ~/.clyde/tune.json so install, `clyde tune` and the offer after a model
download all start from the same profile. The profile decides how strict the quality gate is and what
the optimizer maximizes; it never names a single "category", because people mix uses.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from rich.console import Console
from rich.prompt import IntPrompt, Prompt

from src.config import clyde_home

USES = {
    "coding": "Coding and agents (tool calls must be right)",
    "chat": "Chat and writing",
    "research": "Research and fact-checking (many sources, answers must hold up)",
    "documents": "Long documents",
    "quick": "Quick answers",
}
PRIORITIES = {"speed": "Speed", "context": "Long context", "reliability": "Reliability (change nothing risky)"}
# Uses where one wrong tool call or one lost fact is a visible failure: no tolerance for a quality drop.
_STRICT = {"coding", "research"}
# Uses that can live with the more lossy 4-bit cache.
_LOSSY_OK = {"chat", "quick"}


@dataclass(frozen=True)
class Profile:
    uses: tuple[str, ...]
    priority: str
    headroom_gb: int = 4   # RAM the user wants left for other apps

    @property
    def tolerance(self) -> int:
        """Hand tasks the tuned setting may lose against the baseline, per eval run."""
        return 0 if _STRICT & set(self.uses) else 1

    @property
    def min_fidelity(self) -> float:
        """How alike the greedy answers must stay to the baseline's. Strict uses allow almost no drift."""
        return 0.95 if self.tolerance == 0 else 0.8

    @property
    def allow_q4(self) -> bool:
        return set(self.uses) <= _LOSSY_OK

    @property
    def max_slowdown(self) -> float:
        return 0.02 if self.priority == "speed" else 0.10


def _file():
    return clyde_home() / "tune.json"


def _read() -> dict:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(update: dict) -> None:
    data = {**_read(), **update}
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def load() -> Profile | None:
    raw = _read().get("profile")
    try:
        return Profile(tuple(u for u in raw["uses"] if u in USES), raw["priority"], int(raw.get("headroom_gb", 4)))
    except (KeyError, TypeError, ValueError):
        return None


def save(profile: Profile, result: dict | None = None) -> None:
    _write({"profile": {**asdict(profile), "uses": list(profile.uses)}, **({"result": result} if result else {})})


def _numbers(answer: str, limit: int) -> list[int]:
    return sorted({int(t) for t in answer.replace(",", " ").split() if t.isdigit() and 1 <= int(t) <= limit})


def ask(console: Console) -> Profile:
    """Ask what the model is for. Several uses can be picked; an empty answer means chat."""
    console.print("\n[bold]What will you mainly use your local models for?[/bold] (numbers, e.g. 1,3)")
    keys = list(USES)
    for i, key in enumerate(keys, 1):
        console.print(f"  {i}. {USES[key]}")
    picked = [keys[n - 1] for n in _numbers(Prompt.ask("Uses", default="2"), len(keys))] or ["chat"]
    console.print("\n[bold]What matters most?[/bold]")
    order = list(PRIORITIES)
    for i, key in enumerate(order, 1):
        console.print(f"  {i}. {PRIORITIES[key]}")
    priority = order[IntPrompt.ask("Most important", choices=[str(i) for i in range(1, len(order) + 1)], default=1) - 1]
    headroom = IntPrompt.ask("GB of RAM to keep free for your other apps", default=4)
    profile = Profile(tuple(picked), priority, max(0, headroom))
    save(profile)
    return profile
