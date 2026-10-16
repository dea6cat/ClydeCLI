"""Stops an agent that keeps making the same tool call and getting the same answer.

A small model that gets an error it does not understand often sends the identical call again, sometimes until the
turn limit. After two identical results the third identical call is refused with a note to change approach, and if the
model repeats it once more the turn ends. A call whose result changed (polling a task) is never counted, and neither
are the tools that exist to be polled.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

POLLING_TOOLS = frozenset({"taskoutput", "taskget", "tasklist", "sleep", "cronlist"})
REFUSAL = ("You have made this exact {name} call {times} times in a row and got the same result each time. Do not repeat it. "
           "Change the arguments, use a different tool, or tell the user what is blocking you.")
STOPPED = ("Stopped: the model kept repeating the same {name} call without getting anywhere. "
           "Reword the request, or switch model with /model.")


class RepeatedCall(Exception):
    """Raised for a call the guard refused; its message goes back to the model as the tool result."""


def _digest(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode("utf-8", "replace")).hexdigest()


class RepeatGuard:
    def __init__(self, times: int = 3) -> None:
        self.times = times
        self.refused_in_a_row = 0
        self.last_refused = ""
        self._history: list[tuple[str, str]] = []   # (call, result), newest last

    @property
    def stuck(self) -> bool:
        return self.refused_in_a_row >= 2

    def stop_reply(self) -> str:
        return STOPPED.format(name=self.last_refused)

    def refusal(self, name: str, tool_input: Any) -> str | None:
        """The note to return instead of running this call, or None to run it."""
        if name.lower() in POLLING_TOOLS:
            return None
        call, recent = _digest([name.lower(), tool_input]), self._history[-(self.times - 1):]
        if len(recent) < self.times - 1 or any(h != recent[0] for h in recent) or recent[0][0] != call:
            return None
        self.refused_in_a_row += 1
        self.last_refused = name
        self._history.append(recent[0])   # the next identical call is still a repeat of the same result
        return REFUSAL.format(name=name, times=self.times)

    def record(self, name: str, tool_input: Any, output: Any) -> None:
        """Remember a call that ran and what it returned."""
        self.refused_in_a_row = 0
        self._history.append((_digest([name.lower(), tool_input]), _digest(output)))
