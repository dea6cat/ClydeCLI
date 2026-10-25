"""/settings: one screen with four tabs, Status, Config, Usage and Stats (Overview and Models).

Left/Right switch tabs, Up/Down move, Space or Enter changes the highlighted setting, typing on Config narrows
the list, Tab flips Stats between Overview and Models, r cycles its date range, Esc closes. Where there is no
terminal /settings prints the status block instead (see ClydeREPL._show_status). The data functions are plain so
tests need no screen.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from src import config as config_mod
from src import network
from src import refine
from src.providers import omlx
from src.ui import usage_stats as stats
from src.ui.picker import scroll

Fragments = list[tuple[str, str]]

_ACCENT = "#a8a8ff"
_OK = "#4eba65"
_DIM = "#8a8a8a"
_HOT = "#e8794a"
TABS = ("Status", "Config", "Usage", "Stats")
STATS_TABS = ("Overview", "Models")
_ROWS = 14             # Config rows shown at once
_MODELS_PER_PAGE = 4   # two rows of two on Stats > Models
_CHARS_PER_TOKEN = 4
_COLUMN = 34


@dataclass(frozen=True)
class Snapshot:
    """What the running session knows: `status` rows (label, value), `usage` lines for the Usage tab's
    session section, and the plugin skill-listing `footprint` rows (plugin, skills, tokens per turn)."""
    status: list[tuple[str, str]]
    usage: list[str]
    footprint: list[tuple[str, int, int]]


@dataclass(frozen=True)
class Setting:
    label: str
    choices: tuple[Any, ...]
    read: Callable[[dict[str, Any]], Any]
    write: Callable[[Any], None]
    applies: str = "the next time ClydeCLI starts"

    def value(self) -> Any:
        return self.read(config_mod.load_config())

    def next(self) -> Any:
        """The choice after the current one, wrapping round."""
        current = self.value()
        return self.choices[(self.choices.index(current) + 1) % len(self.choices)] if current in self.choices else self.choices[0]


def _set_session(key: str) -> Callable[[Any], None]:
    def write(value: Any) -> None:
        cfg = config_mod.load_config()
        cfg.setdefault("session", {})[key] = value
        config_mod.save_config(cfg)
    return write


def settings() -> list[Setting]:
    """The options ClydeCLI keeps in ~/.clyde/config.json that a toggle can change; each applies from the next start."""
    session = lambda c: c.get("session", {})   # noqa: E731
    return [
        Setting("Auto-save sessions", (True, False), lambda c: session(c).get("auto_save", True) is not False, _set_session("auto_save")),
        Setting("Trace requests", (True, False), lambda c: session(c).get("trace", True) is not False, _set_session("trace")),
        Setting("Terse replies", (True, False), lambda c: c.get("output_style") == "terse",
                lambda on: config_mod.set_output_style("terse" if on else None)),
        Setting("Auto-refine", refine.MODES, lambda c: refine.mode(), refine.set_mode,
                applies="from your next turn; it only adds notes, each one printed, and /refine undo reverses the latest"),
        Setting("Max history", (50, 100, 200, 500), lambda c: session(c).get("max_history", 100), _set_session("max_history")),
        Setting("Tool turns", (20, 40, 60, 100), lambda c: session(c).get("max_tool_turns", 20), _set_session("max_tool_turns"),
                applies="your next turn; the tool rounds one task may use before it stops and asks you to continue"),
        Setting("Context window (local models)", (None, 4096, 8192, 16384, 32768, 65536, 131072), lambda c: config_mod.get_context_tokens(),
                config_mod.set_context_tokens, applies="your next message; oMLX serves the model with it"),
        Setting("Network proxy", network.proxy_choices(), lambda c: network.get_proxy(), network.set_proxy,
                applies="the next time Clyde starts; type a URL with /proxy <url>"),
        Setting("Company certificate", network.ca_choices(), lambda c: network.get_ca() or "off",
                lambda v: network.set_ca(None if v == "off" else v), applies="the next time Clyde starts; add one with /proxy ca <file>"),
        Setting("Update channel", config_mod.UPDATE_CHANNELS, lambda c: c.get("update_channel", "latest"), config_mod.set_update_channel),
        *([Setting("oMLX memory guard", omlx.memory_guard_choices(), lambda c: config_mod.get_omlx_memory_guard() or omlx.GUARD,
                   config_mod.set_omlx_memory_guard, applies="your next oMLX request (Clyde restarts its oMLX server with it)")]
          if omlx.supported() else []),
    ]


def visible_settings(query: str) -> list[Setting]:
    words = query.lower().split()
    return [s for s in settings() if all(w in s.label.lower() for w in words)]


def skill_footprint(enabled: list[Any]) -> list[tuple[str, int, int]]:
    """(plugin, skills, tokens per turn) for each enabled plugin: its skill names and descriptions ride in every prompt."""
    from src.skills.loader import load_skills_from_dir

    rows = []
    for plugin in enabled:
        found = load_skills_from_dir(plugin.root / "skills", loaded_from="plugin")
        rows.append((plugin.name, len(found), sum(len(s.name) + len(s.description or "") for s in found) // _CHARS_PER_TOKEN))
    return sorted((r for r in rows if r[1]), key=lambda r: r[2], reverse=True)


def session_usage(models: dict[str, dict[str, int]]) -> list[str]:
    """The session's cost and tokens per model, and how much of the input the prompt cache served."""
    from src.agent.cost_tracker import estimate_usd

    if not models:
        return ["No model requests yet in this session."]
    cost, lines, cached, fresh = 0.0, [], 0, 0
    for ref, u in models.items():
        price = estimate_usd(ref, u)
        cost += price or 0.0
        cached += u.get("cache_read_input_tokens", 0)
        fresh += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        lines.append(f"  {ref}: {stats.compact(u.get('input_tokens', 0))} in, {stats.compact(u.get('output_tokens', 0))} out, "
                     f"{stats.compact(u.get('cache_read_input_tokens', 0))} cache read" + (f" (${price:.4f})" if price else ""))
    head = [f"Total cost: ${cost:.4f}" if cost else "Total cost: free or unpriced", "Usage by model:"]
    cache = [f"Prompt cache: {100 * cached // (cached + fresh)}% of input tokens came from cache"] if cached else []
    return head + lines + cache


def _tab_bar(tab: int) -> Fragments:
    out: Fragments = [(f"bold fg:{_ACCENT}", "Settings   ")]
    for i, name in enumerate(TABS):
        out += [("reverse bold" if i == tab else f"fg:{_DIM}", f" {name} "), ("", " ")]
    return out + [("", "\n\n")]


def _ranges(current: str) -> Fragments:
    out: Fragments = []
    for key, label in stats.RANGES:
        out += [(f"bold fg:{_HOT}" if key == current else f"fg:{_DIM}", label), (f"fg:{_DIM}", " · ")]
    return out[:-1] + [("", "\n\n")]


def render_status(snap: Snapshot) -> Fragments:
    width = max((len(k) for k, _ in snap.status), default=0) + 2
    return [part for k, v in snap.status for part in (("bold", f"{k + ':':<{width}}"), ("", v + "\n"))]


def render_config(cursor: int, top: int, query: str) -> Fragments:
    rows = visible_settings(query)
    out: Fragments = [(f"fg:{_DIM}", "Search: "), ("", (query or "type to narrow") + "\n\n")]
    if not rows:
        out.append((f"fg:{_DIM}", "  Nothing matches.\n"))
    width = max((len(s.label) for s in rows), default=0) + 4
    for offset, s in enumerate(rows[top:top + _ROWS]):
        on, value = top + offset == cursor, s.value()
        shown = "auto" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
        out += [(f"fg:{_ACCENT}", "❯ " if on else "  "), (f"bold fg:{_ACCENT}" if on else "", s.label.ljust(width)),
                (f"fg:{_OK}" if value is True else (f"fg:{_DIM}" if value is False else ""), shown + "\n")]
    return out


def render_usage(snap: Snapshot) -> Fragments:
    out: Fragments = [("bold", "Session\n")] + [("", f"{line}\n") for line in snap.usage]
    out += [("", "\n"), ("bold", "Plugin skill-listing footprint\n"),
            (f"fg:{_DIM}", "What each plugin's skill descriptions add to the prompt on every turn.\n\n")]
    if not snap.footprint:
        out.append((f"fg:{_DIM}", "No enabled plugin adds skills.\n"))
    for name, count, tokens in snap.footprint:
        out.append(("", f"{name:<18}{count:>4} skills · ~{tokens} tok/turn\n"))
    if snap.footprint:
        out.append(("", f"\n{'Total':<22}~{sum(t for _, _, t in snap.footprint)} tok/turn\n"))
    return out


def _pair(left: tuple[str, str], right: tuple[str, str]) -> Fragments:
    """`Label: value` twice on one line, the values highlighted."""
    pad = " " * max(1, _COLUMN - len(left[0]) - len(left[1]))
    return [("", left[0]), (f"bold fg:{_HOT}", left[1]), ("", pad), ("", right[0]), (f"bold fg:{_HOT}", right[1] + "\n")]


def render_overview(requests: list[stats.Request], sessions: list[stats.Session], range_key: str, today: date) -> Fragments:
    o = stats.overview(requests, sessions, stats.first_day(range_key, today, requests), today)
    t = o.totals
    out = stats.heatmap(requests, today) + [("", "\n")] + _ranges(range_key)
    out += _pair(("Favorite model: ", o.favorite), ("Total tokens: ", stats.compact(t.total)))
    out += _pair(("Sessions: ", str(o.sessions)), ("Longest session: ", stats.duration(o.longest_session)))
    out += _pair(("Active days: ", f"{o.active_days}/{o.span_days}"), ("Longest streak: ", f"{o.longest_streak} days"))
    out += _pair(("", ""), ("Current streak: ", f"{o.current_streak} days"))
    out.append((f"fg:{_DIM}", f"\nInput {stats.compact(t.input)} · Output {stats.compact(t.output)} · "
                              f"Cache read {stats.compact(t.cache_read)} · Cache write {stats.compact(t.cache_write)}\n"))
    return out


def render_models(requests: list[stats.Request], range_key: str, top: int, today: date) -> Fragments:
    since = stats.first_day(range_key, today, requests)
    models = stats.by_model(requests, since)
    if not models:
        return [(f"fg:{_DIM}", "No traced model requests in this range yet.\n\n")] + _ranges(range_key)
    out = stats.chart([(ref, stats.daily(requests, ref, since, today)) for ref, _ in models[:6]], since, today)
    out += [("", "\n")] + _ranges(range_key)
    total = sum(t.total for _, t in models) or 1
    page = models[top:top + _MODELS_PER_PAGE]
    for i in range(0, len(page), 2):
        row = page[i:i + 2]
        out += [("", f"● {ref} ".ljust(_COLUMN)) if k == 0 else ("", f"● {ref} ") for k, (ref, _) in enumerate(row)] + [("", "\n")]
        out += [(f"fg:{_DIM}", f"  {100 * t.total / total:.1f}% · In {stats.compact(t.input)} · Out {stats.compact(t.output)}".ljust(_COLUMN)) for _, t in row]
        out += [("", "\n")]
        out += [(f"fg:{_DIM}", f"  Cache {stats.compact(t.cache_read)} read · {stats.compact(t.cache_write)} write".ljust(_COLUMN)) for _, t in row]
        out += [("", "\n\n")]
    out.append((f"fg:{_DIM}", f"↓ {top + 1}-{top + len(page)} of {len(models)} models (↑/↓ to scroll)\n"))
    return out


_HINTS = ("←/→ tabs · Esc close",
          "←/→ tabs · ↑/↓ move · Space/Enter change · type to search · Esc close",
          "←/→ tabs · Esc close",
          "←/→ tabs · Tab Overview/Models · r date range · ↑/↓ scroll models · Esc close")


def render(state: dict[str, Any], snap: Snapshot, requests: list[stats.Request], sessions: list[stats.Session], today: date) -> Fragments:
    tab = state["tab"]
    out = _tab_bar(tab)
    if tab == 3:
        out += [("reverse bold" if i == state["sub"] else f"fg:{_DIM}", f" {name} ") for i, name in enumerate(STATS_TABS)] + [("", "\n\n")]
    if tab == 0:
        out += render_status(snap)
    elif tab == 1:
        out += render_config(state["cursor"], state["top"], state["query"])
    elif tab == 2:
        out += render_usage(snap)
    elif state["sub"] == 0:
        out += render_overview(requests, sessions, state["range"], today)
    else:
        out += render_models(requests, state["range"], state["top"], today)
    return out + [("", "\n"), (f"fg:{_DIM}", (state["note"] + "\n") if state["note"] else ""), (f"fg:{_DIM}", _HINTS[tab])]


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def show(snap: Snapshot, *, input: Any = None, output: Any = None, today: date | None = None) -> None:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    from src.repl.esc import WATCHER

    today = today or date.today()
    requests, sessions = stats.load_requests(), stats.load_sessions()
    state: dict[str, Any] = {"tab": 0, "sub": 0, "range": "all", "cursor": 0, "top": 0, "query": "", "note": ""}

    def models_on_screen() -> int:
        return len(stats.by_model(requests, stats.first_day(state["range"], today, requests)))

    def draw() -> Fragments:
        if state["tab"] == 1:
            rows = len(visible_settings(state["query"]))
            state["cursor"] = max(0, min(state["cursor"], rows - 1))
            state["top"] = scroll(state["top"], state["cursor"], rows, _ROWS)
        return render(state, snap, requests, sessions, today)

    def reset(**changes: Any) -> None:
        state.update({"cursor": 0, "top": 0, "note": "", **changes})

    keys = KeyBindings()

    @keys.add("left", eager=True)
    def _left(event: Any) -> None:
        reset(tab=(state["tab"] - 1) % len(TABS), query="")

    @keys.add("right", eager=True)
    def _right(event: Any) -> None:
        reset(tab=(state["tab"] + 1) % len(TABS), query="")

    @keys.add("up", eager=True)
    def _up(event: Any) -> None:
        state["cursor"] = max(0, state["cursor"] - 1)
        if state["tab"] == 3:
            state["top"] = max(0, state["top"] - 2)

    @keys.add("down", eager=True)
    def _down(event: Any) -> None:
        state["cursor"] += 1
        if state["tab"] == 3:
            state["top"] = min((max(1, models_on_screen()) - 1) // 2 * 2, state["top"] + 2)

    @keys.add("tab")
    def _tab(event: Any) -> None:
        if state["tab"] == 3:
            reset(sub=(state["sub"] + 1) % len(STATS_TABS), range=state["range"])

    @keys.add("space")
    @keys.add("enter")
    def _change(event: Any) -> None:
        rows = visible_settings(state["query"])
        if state["tab"] == 1 and rows:
            row = rows[state["cursor"]]
            row.write(row.next())
            state["note"] = f"{row.label}: {'auto' if row.value() is None else str(row.value()).lower()} (applies {row.applies})"

    @keys.add("backspace")
    def _back(event: Any) -> None:
        state["query"], state["cursor"] = state["query"][:-1], 0

    @keys.add("<any>")
    def _type(event: Any) -> None:
        if state["tab"] == 3 and event.data == "r":
            order = [key for key, _ in stats.RANGES]
            reset(range=order[(order.index(state["range"]) + 1) % len(order)], sub=state["sub"])
        elif state["tab"] == 1 and event.data.isprintable():
            state["query"] += event.data
            state["cursor"] = 0

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _close(event: Any) -> None:
        event.app.exit()

    app: Application = Application(layout=Layout(Window(FormattedTextControl(draw), dont_extend_height=True)),
                                   key_bindings=keys, erase_when_done=True, input=input, output=output)
    with WATCHER.paused():
        app.run()
