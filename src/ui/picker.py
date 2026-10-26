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
           current: str | None, query: str, hint: str, header: tuple[str, str] | None = None) -> list[tuple[str, str]]:
    """The picker as prompt_toolkit fragments (style, text). `header` is the label and hint column titles, drawn over the rows."""
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
    if header and choices:
        out.append((f"bold fg:{_DIM}", " " * 7 + header[0].ljust(width) + ("  " if current is not None else "") + "  " + header[1] + "\n"))   # 7 = cursor mark + row number
    if top:
        out.append((f"fg:{_DIM}", f"  ↑ {top} more\n"))
    for offset, c in enumerate(shown):
        at = top + offset
        on = at == cursor
        label = c.label if len(c.label) <= width else c.label[:width - 1] + "…"
        style = f"bold fg:{_OK}" if c.value == current else ("bold" if on else "")
        out.append((f"fg:{_ACCENT}", "❯ " if on else "  "))
        out.append((f"fg:{_DIM}", f"{at + 1:>3}. "))
        out.append((style, label.ljust(width) + (" ✔" if c.value == current else "  " if header and current is not None else "")))   # a marked row must not shift the columns
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


def _ask_numbered(console: Any, title: str, choices: list[Choice], current: str | None, allow_custom: bool,
                  header: tuple[str, str] | None = None) -> str | None:
    """No terminal to draw on: list the choices and ask for a number (or, when allowed, any text)."""
    console.print(Text(title, style="bold"))
    width = max((len(c.label) for c in choices), default=0) if header else 0   # columns line up only when there is a header
    if header:
        console.print(Text(" " * 7 + header[0].ljust(width) + "  " + header[1], style="bold dim"))
    for i, c in enumerate(choices, start=1):
        console.print(Text.assemble(f"  {i:>3}. {c.label.ljust(width)}" + (" ✔" if c.value == current else ""), (f"  {c.hint}" if c.hint else "", "dim")))
    raw = Prompt.ask("Number (Enter to cancel)", default="", show_default=False, console=console).strip()
    if raw.isdigit() and 1 <= int(raw) <= len(choices):
        return choices[int(raw) - 1].value
    return raw if raw and allow_custom else None


def pick(console: Any, title: str, choices: list[Choice], *, description: str = "", current: str | None = None,
         allow_custom: bool = False, visible: int = 8, header: tuple[str, str] | None = None, input: Any = None,
         output: Any = None) -> str | None:
    """Let the user choose one of `choices`; its value, or None when they cancel. `current` is marked
    and starts selected. With `allow_custom`, Enter on a filter that matches nothing returns the typed
    text (for model ids the list doesn't know). `header` titles the label and hint columns when the hints
    are laid out as aligned columns. `input`/`output` are prompt_toolkit's, for tests."""
    if not choices and not allow_custom:
        return None
    if input is None and not _interactive():
        return _ask_numbered(console, title, choices, current, allow_custom, header)

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
                      current=current, query=state["query"], hint=hint, header=header)

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


CHAT = "\0chat"   # ask(): the user picked "Chat about this" instead of an answer


def render_question(header: str, question: str, options: list[dict], cursor: int, *, multi: bool, chosen: set[int],
                    typed: str) -> list[tuple[str, str]]:
    """One AskUserQuestion as prompt_toolkit fragments: the header chip, the question, each option with its
    description, a row to type an answer, then "Chat about this", and the focused option's preview."""
    n = len(options)
    out: list[tuple[str, str]] = [(f"reverse fg:{_ACCENT}", f" ☐ {header} " if header else ""), ("", "\n\n")]
    out += [(f"fg:{_ACCENT}", "▌ "), ("bold", question + "\n\n")]
    for i, opt in enumerate(options):
        on = i == cursor
        out.append((f"fg:{_ACCENT}", "❯ " if on else "  "))
        out.append((f"fg:{_ACCENT}" if on else f"fg:{_DIM}", f"{i + 1}. "))
        if multi:
            out.append(("", "[x] " if i in chosen else "[ ] "))
        out.append((f"bold fg:{_ACCENT}" if on else "bold", str(opt.get("label", "")) + "\n"))
        if opt.get("description"):
            out.append((f"fg:{_DIM}", "     " + str(opt["description"]) + "\n"))
    on = cursor == n
    out.append((f"fg:{_ACCENT}", "❯ " if on else "  "))
    out.append((f"fg:{_DIM}", f"{n + 1}. "))
    if typed:
        out.append(("", typed + ("█" if on else "")))
    else:
        out.append(("", "█") if on else (f"fg:{_DIM}", "Type something."))
    out.append(("", "\n"))
    out.append((f"fg:{_DIM}", "─" * 60 + "\n"))
    on = cursor == n + 1
    out.append((f"fg:{_ACCENT}", "❯ " if on else "  "))
    out.append((f"fg:{_DIM}", f"{n + 2}. "))
    out.append((f"bold fg:{_ACCENT}" if on else "", "Chat about this\n"))
    preview = options[cursor].get("preview") if cursor < n else None
    if preview:
        out.append((f"fg:{_DIM}", "\n" + "\n".join("  │ " + line for line in str(preview).splitlines()) + "\n"))
    out.append((f"fg:{_DIM}", "\n" + ("Space to tick · " if multi else "") +
                "Enter to select · ↑/↓ to navigate · type to answer · Esc to cancel"))   # fits 80 columns
    return out


def ask(header: str, question: str, options: list[dict], *, multi: bool = False, input: Any = None,
        output: Any = None) -> str | None:
    """Put one AskUserQuestion to the user, the way Claude Code draws it. The picked label (several, comma-separated,
    with `multi`), their own typed answer, CHAT when they would rather talk it over, or None on Esc."""
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    from src.repl.esc import WATCHER

    n = len(options)
    labels = [str(o.get("label", "")) for o in options]
    state: dict[str, Any] = {"cursor": 0, "typed": "", "chosen": set()}
    keys = KeyBindings()

    def draw() -> list[tuple[str, str]]:
        return render_question(header, question, options, state["cursor"], multi=multi, chosen=state["chosen"],
                               typed=state["typed"])

    @keys.add("up", eager=True)
    def _up(event: Any) -> None:
        state["cursor"] = max(0, state["cursor"] - 1)

    @keys.add("down", eager=True)
    def _down(event: Any) -> None:
        state["cursor"] = min(n + 1, state["cursor"] + 1)

    @keys.add("enter")
    def _enter(event: Any) -> None:
        at, typed = state["cursor"], state["typed"].strip()
        if at == n + 1:
            event.app.exit(result=CHAT)
        elif multi:
            picked = [labels[i] for i in sorted(state["chosen"])] or ([labels[at]] if at < n else [])
            if picked or typed:
                event.app.exit(result=", ".join(picked + ([typed] if typed else [])))
        elif at < n:
            event.app.exit(result=labels[at])
        elif typed:
            event.app.exit(result=typed)

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    @keys.add("backspace")
    def _back(event: Any) -> None:
        if state["cursor"] == n:
            state["typed"] = state["typed"][:-1]

    @keys.add("<any>")
    def _type(event: Any) -> None:
        ch = event.data
        if not ch.isprintable():
            return
        if state["cursor"] == n:                       # on the answer row: it all goes into the answer
            state["typed"] += ch
        elif ch == " " and multi and state["cursor"] < n:
            state["chosen"] ^= {state["cursor"]}
        elif ch.isdigit() and 1 <= int(ch) <= n + 2:   # a row number jumps to that row
            state["cursor"] = int(ch) - 1
        elif ch.strip():                               # any other key starts an answer in the user's own words
            state["cursor"], state["typed"] = n, state["typed"] + ch

    app: Application = Application(layout=Layout(Window(FormattedTextControl(draw), dont_extend_height=True)),
                                   key_bindings=keys, erase_when_done=True, input=input, output=output)
    with WATCHER.paused():
        return app.run()
