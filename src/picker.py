"""One way to choose between items: a list you move through with the arrow keys.

Up/Down, PageUp/PageDown and Home/End move, typing narrows the list, Enter picks, and Esc or Ctrl+C
cancels. The picker owns the keyboard while it is open, so the Esc watcher that cancels a running turn
is paused for its duration. Where there is no terminal (pipes, tests, an editor over ACP) it falls back
to a numbered question, so callers never branch on that.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from rich.prompt import Prompt
from rich.text import Text

_ACCENT = "#a8a8ff"
_OK = "#4eba65"
_DIM = "#8a8a8a"
_LABEL_MAX = 44


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    hint: str = ""


def narrow(choices: list[Choice], query: str) -> list[Choice]:
    """The choices whose label, hint or value contains every word of `query`, ignoring case."""
    words = query.lower().split()
    return [c for c in choices if all(w in f"{c.label} {c.hint} {c.value}".lower() for w in words)]


def scroll(top: int, cursor: int, rows: int, visible: int) -> int:
    """The first row to show so that `cursor` stays inside a window of `visible` rows over `rows`."""
    top = min(top, cursor)
    if cursor >= top + visible:
        top = cursor - visible + 1
    return max(0, min(top, max(0, rows - visible)))


def render(choices: list[Choice], cursor: int, top: int, visible: int, *, title: str, description: str,
           current: str | None, query: str, hint: str) -> list[tuple[str, str]]:
    """The picker as prompt_toolkit fragments (style, text)."""
    out: list[tuple[str, str]] = [(f"bold fg:{_ACCENT}", title + "\n")]
    if description:
        out.append((f"fg:{_DIM}", description + "\n"))
    out.append(("", "\n"))
    if query:
        out.append((f"fg:{_DIM}", "Filter: "))
        out.append(("", query + "\n"))
    if not choices:
        out.append((f"fg:{_DIM}", "  Nothing matches.\n"))
    width = min(_LABEL_MAX, max((len(c.label) for c in choices), default=0))
    shown = choices[top:top + visible]
    if top:
        out.append((f"fg:{_DIM}", f"  ↑ {top} more\n"))
    for offset, c in enumerate(shown):
        at = top + offset
        on = at == cursor
        label = c.label if len(c.label) <= width else c.label[:width - 1] + "…"
        style = f"bold fg:{_OK}" if c.value == current else ("bold" if on else "")
        out.append((f"fg:{_ACCENT}", "❯ " if on else "  "))
        out.append((f"fg:{_DIM}", f"{at + 1:>3}. "))
        out.append((style, label.ljust(width) + (" ✔" if c.value == current else "")))
        out.append((f"fg:{_DIM}", ("  " + c.hint if c.hint else "") + "\n"))
    below = len(choices) - top - len(shown)
    if below > 0:
        out.append((f"fg:{_DIM}", f"  ↓ {below} more\n"))
    out.append(("", "\n"))
    out.append((f"fg:{_DIM}", hint))
    return out


def _interactive() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask_numbered(console: Any, title: str, choices: list[Choice], current: str | None, allow_custom: bool) -> str | None:
    """No terminal to draw on: list the choices and ask for a number (or, when allowed, any text)."""
    console.print(Text(title, style="bold"))
    for i, c in enumerate(choices, start=1):
        console.print(Text.assemble(f"  {i:>3}. {c.label}" + (" ✔" if c.value == current else ""), (f"  {c.hint}" if c.hint else "", "dim")))
    raw = Prompt.ask("Number (Enter to cancel)", default="", show_default=False, console=console).strip()
    if raw.isdigit() and 1 <= int(raw) <= len(choices):
        return choices[int(raw) - 1].value
    return raw if raw and allow_custom else None


def pick(console: Any, title: str, choices: list[Choice], *, description: str = "", current: str | None = None,
         allow_custom: bool = False, visible: int = 8, input: Any = None, output: Any = None) -> str | None:
    """Let the user choose one of `choices`; its value, or None when they cancel. `current` is marked
    and starts selected. With `allow_custom`, Enter on a filter that matches nothing returns the typed
    text (for model ids the list doesn't know). `input`/`output` are prompt_toolkit's, for tests."""
    if not choices and not allow_custom:
        return None
    if input is None and not _interactive():
        return _ask_numbered(console, title, choices, current, allow_custom)

    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    from src.repl.esc import WATCHER

    state = {"query": "", "cursor": next((i for i, c in enumerate(choices) if c.value == current), 0), "top": 0}
    hint = "Enter to select · Esc to cancel" + (" · type to filter" if len(choices) > visible or allow_custom else "")

    def view() -> list[Choice]:
        return narrow(choices, state["query"])

    def draw() -> list[tuple[str, str]]:
        rows = view()
        state["cursor"] = max(0, min(state["cursor"], len(rows) - 1))
        state["top"] = scroll(state["top"], state["cursor"], len(rows), visible)
        return render(rows, state["cursor"], state["top"], visible, title=title, description=description,
                      current=current, query=state["query"], hint=hint)

    keys = KeyBindings()

    @keys.add("up", eager=True)
    def _up(event: Any) -> None:
        state["cursor"] = max(0, state["cursor"] - 1)

    @keys.add("down", eager=True)
    def _down(event: Any) -> None:
        state["cursor"] = min(len(view()) - 1, state["cursor"] + 1)

    @keys.add("pageup")
    def _page_up(event: Any) -> None:
        state["cursor"] = max(0, state["cursor"] - visible)

    @keys.add("pagedown")
    def _page_down(event: Any) -> None:
        state["cursor"] = min(len(view()) - 1, state["cursor"] + visible)

    @keys.add("home")
    def _home(event: Any) -> None:
        state["cursor"] = 0

    @keys.add("end")
    def _end(event: Any) -> None:
        state["cursor"] = len(view()) - 1

    @keys.add("enter")
    def _enter(event: Any) -> None:
        rows = view()
        if rows:
            event.app.exit(result=rows[state["cursor"]].value)
        elif allow_custom and state["query"].strip():
            event.app.exit(result=state["query"].strip())

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    @keys.add("backspace")
    def _back(event: Any) -> None:
        state["query"] = state["query"][:-1]
        state["cursor"] = 0

    @keys.add("<any>")
    def _type(event: Any) -> None:
        if event.data.isprintable():
            state["query"] += event.data
            state["cursor"] = 0

    app: Application = Application(layout=Layout(Window(FormattedTextControl(draw), dont_extend_height=True)),
                                   key_bindings=keys, erase_when_done=True, input=input, output=output)
    with WATCHER.paused():
        return app.run()
