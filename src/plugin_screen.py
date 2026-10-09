"""/plugins: one screen with three tabs, Installed, Errors and Stats.

Left/Right switch tabs, Up/Down move, Space turns the highlighted plugin on or off (it applies the next
time ClydeCLI starts, like `clyde plugin enable`), Esc closes. Where there is no terminal /plugins prints the
plain list instead (see ClydeREPL._print_plugins). The data functions are plain so tests need no screen.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from src import plugins, skill_scan
from src.picker import scroll

_ACCENT = "#a8a8ff"
_OK = "#4eba65"
_BAD = "#d0202f"
_DIM = "#8a8a8a"
TABS = ("Installed", "Errors", "Stats")


@dataclass(frozen=True)
class Contents:
    skills: list[str]
    tools: list[str]
    hooks: int
    servers: list[str]
    problems: list[str]


def contents(plugin: plugins.Plugin) -> Contents:
    """What the plugin would add, plus anything unreadable in it."""
    problems, hooks, servers = [], 0, []
    try:
        hooks = sum(len(g["hooks"]) for groups in plugins.plugin_hooks(plugin).values() for g in groups)
    except ValueError as e:
        problems.append(f"hooks unreadable: {e}")
    try:
        servers = list(plugins.plugin_servers(plugin))
    except ValueError as e:
        problems.append(f"MCP servers unreadable: {e}")
    return Contents(plugins.skill_names(plugin), plugins.tool_files(plugin), hooks, servers, problems)


def summary(c: Contents) -> str:
    parts = [(len(c.skills), "skills"), (len(c.tools), "tools"), (c.hooks, "hooks"), (len(c.servers), "MCP servers")]
    return ", ".join(f"{n} {label}" for n, label in parts if n) or "nothing ClydeCLI can load"


def errors(loaded: list[plugins.Loaded]) -> list[str]:
    """Bad manifests, problems found at start-up, unreadable parts, and plugins SkillSpector holds back."""
    good, bad_manifests = plugins.installed()
    found = list(bad_manifests)
    found += [w for item in loaded for w in item.warnings]
    for plugin in good:
        found += [f"{plugin.name}: {p}" for p in contents(plugin).problems]
        verdict = skill_scan.cached_verdicts().get(f"plugin:{plugin.name}")
        if verdict and verdict.blocked:
            found.append(f"{plugin.name}: held back by SkillSpector ({', '.join(verdict.findings[:2]) or 'no detail'}); "
                         f"`clyde plugin enable {plugin.name}` records your approval")
    return found


def stats() -> list[str]:
    found = plugins.installed()[0]
    on = [p for p in found if plugins.is_enabled(p.name)]
    parts = {p.name: contents(p) for p in on}
    lines = [f"{len(found)} installed, {len(on)} enabled",
             f"from enabled plugins: {sum(len(c.skills) for c in parts.values())} skills, "
             f"{sum(len(c.tools) for c in parts.values())} tools, {sum(c.hooks for c in parts.values())} hooks, "
             f"{sum(len(c.servers) for c in parts.values())} MCP servers"]
    lines += [f"  {name}: {summary(c)}" for name, c in parts.items()]
    return lines


def _row(p: plugins.Plugin) -> tuple[str, str]:
    state = "enabled" if plugins.is_enabled(p.name) else "disabled"
    return f"{p.name} {p.version}".strip(), f"{state} · {summary(contents(p))}"


def render(tab: int, cursor: int, top: int, visible: int, loaded: list[plugins.Loaded], note: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = [(f"bold fg:{_ACCENT}", "Plugins   ")]
    for i, name in enumerate(TABS):
        out.append(("reverse bold" if i == tab else f"fg:{_DIM}", f" {name} "))
        out.append(("", "  "))
    out.append(("", "\n\n"))
    if tab == 0:
        found = plugins.installed()[0]
        if not found:
            out.append((f"fg:{_DIM}", "  No plugins installed. `clyde plugin install <path-or-git-url>` or `clyde plugin import`.\n"))
        for offset, p in enumerate(found[top:top + visible]):
            on = top + offset == cursor
            label, hint = _row(p)
            out.append((f"fg:{_ACCENT}", "❯ " if on else "  "))
            out.append((f"bold fg:{_OK}" if plugins.is_enabled(p.name) else ("bold" if on else ""), label))
            out.append((f"fg:{_DIM}", f"  {hint}\n"))
        if found and top + visible < len(found):
            out.append((f"fg:{_DIM}", f"  ↓ {len(found) - top - visible} more\n"))
        if found and found[cursor].description:
            out.append((f"fg:{_DIM}", f"\n  {found[cursor].description}\n"))
    else:
        lines = errors(loaded) if tab == 1 else stats()
        if not lines:
            out.append((f"fg:{_OK}", "  No errors.\n"))
        for line in lines:
            out.append((f"fg:{_BAD}" if tab == 1 else "", f"  {line}\n"))
    out.append(("", "\n"))
    out.append((f"fg:{_DIM}", (note + "\n") if note else ""))
    out.append((f"fg:{_DIM}", "←/→ tabs · ↑/↓ move · Space enable/disable · Esc close"))
    return out


def toggle(p: plugins.Plugin) -> str:
    now = not plugins.is_enabled(p.name)
    plugins.set_enabled(p.name, now)
    return f"{p.name} {'enabled' if now else 'disabled'}; this applies the next time ClydeCLI starts."


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def show(loaded: list[plugins.Loaded], *, input: Any = None, output: Any = None) -> None:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    from src.repl.esc import WATCHER

    visible = 8
    state = {"tab": 0, "cursor": 0, "top": 0, "note": ""}

    def draw() -> list[tuple[str, str]]:
        count = len(plugins.installed()[0])
        state["cursor"] = max(0, min(state["cursor"], count - 1))
        state["top"] = scroll(state["top"], state["cursor"], count, visible)
        return render(state["tab"], state["cursor"], state["top"], visible, loaded, state["note"])

    keys = KeyBindings()

    @keys.add("left", eager=True)
    def _left(event: Any) -> None:
        state["tab"], state["note"] = (state["tab"] - 1) % len(TABS), ""

    @keys.add("right", eager=True)
    def _right(event: Any) -> None:
        state["tab"], state["note"] = (state["tab"] + 1) % len(TABS), ""

    @keys.add("up", eager=True)
    def _up(event: Any) -> None:
        state["cursor"] = max(0, state["cursor"] - 1)

    @keys.add("down", eager=True)
    def _down(event: Any) -> None:
        state["cursor"] += 1

    @keys.add("space")
    def _space(event: Any) -> None:
        found = plugins.installed()[0]
        if state["tab"] == 0 and found:
            state["note"] = toggle(found[state["cursor"]])

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _close(event: Any) -> None:
        event.app.exit()

    app: Application = Application(layout=Layout(Window(FormattedTextControl(draw), dont_extend_height=True)),
                                   key_bindings=keys, erase_when_done=True, input=input, output=output)
    with WATCHER.paused():
        app.run()
