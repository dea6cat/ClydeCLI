"""What the running turn is waiting for, so the spinner can say so.

Whichever layer is about to wait sets a short phrase ("waiting for Laya to load", "retry 2 of 4: ..."); the REPL's spinner
reads it once a second next to the elapsed time. A turn runs one step at a time, so a single shared phrase is enough.
"""

from __future__ import annotations

_text = ""


def set(text: str) -> None:
    global _text
    _text = text


def get() -> str:
    return _text


def clear() -> None:
    set("")
