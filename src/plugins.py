"""Plugins: directories under ~/.clyde/plugins/<name>/ that bundle skills, hooks, MCP servers and tools.

The layout follows Claude Code's plugins:
    .clyde-plugin/plugin.json   (or .claude-plugin/plugin.json)  {"name", "version", "description"}
    skills/<name>/SKILL.md      skills, read by src/skills/loader.py
    commands/<name>.md|.toml    slash commands (a skill in one file), read by src/skills/loader.py
    hooks/hooks.json            a hooks table in any format normalize_hooks accepts
    .mcp.json                   {"mcpServers": {...}}
    tools/*.py                  Python tools, in the ~/.clyde/tools format

`${CLYDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_ROOT}` in hook and MCP commands expand to the plugin folder.
A plugin contributes only while ~/.clyde/settings.json has {"plugins": {"<name>": {"enabled": true}}}:
plugins run code, so installing one never enables it without an explicit yes.
"""

from __future__ import annotations

from src.config import clyde_home

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.tool_system.hooks import normalize_hooks, settings_paths

# The last entry is the older layout with plugin.json at the plugin root.
MANIFESTS = (*(Path(d) / "plugin.json" for d in (".clyde-plugin", ".claude-plugin", ".codex-plugin", ".cursor-plugin")),
             Path("plugin.json"))
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ROOT_VARS = ("${CLYDE_PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}")


@dataclass
class Plugin:
    name: str
    version: str
    description: str
    root: Path


@dataclass
class Loaded:
    """What one enabled plugin contributed at startup."""
    plugin: Plugin
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    hooks: int = 0
    mcp_servers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def plugins_dir() -> Path:
    return clyde_home() / "plugins"


def read_manifest(root: Path) -> Plugin:
    """The plugin in `root`; ValueError when its manifest is missing or invalid."""
    path = next((root / m for m in MANIFESTS if (root / m).is_file()), None)
    if path is None:
        raise ValueError(f"no plugin manifest ({', '.join(str(m) for m in MANIFESTS)}) in {root}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}") from e
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError(f"{path}: `name` must be letters, digits, '.', '_' or '-'")
    return Plugin(name, str(data.get("version") or ""), str(data.get("description") or ""), root)


def installed() -> tuple[list[Plugin], list[str]]:
    """(valid plugins, errors for folders with a bad manifest) under ~/.clyde/plugins."""
    plugins, errors = [], []
    base = plugins_dir()
    for root in sorted(base.iterdir()) if base.is_dir() else []:
        if not root.is_dir() or root.name.startswith("."):
            continue
        try:
            plugin = read_manifest(root)
        except ValueError as e:
            errors.append(str(e))
            continue
        if plugin.name != root.name:
            errors.append(f"{root}: manifest name '{plugin.name}' does not match its folder")
            continue
        plugins.append(plugin)
    return plugins, errors


# --- enable/disable state in ~/.clyde/settings.json -----------------------------------------

def _settings() -> dict[str, Any]:
    try:
        data = json.loads(settings_paths()[0].read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{settings_paths()[0]} is not a JSON object")
    return data


def is_enabled(name: str) -> bool:
    try:
        entry = (_settings().get("plugins") or {}).get(name)
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(entry, dict) and entry.get("enabled") is True


def set_enabled(name: str, enabled: bool | None) -> None:
    """Record the plugin's state; None drops its entry (on remove)."""
    data = _settings()   # a malformed file raises rather than being overwritten
    table = data.setdefault("plugins", {})
    if enabled is None:
        table.pop(name, None)
    else:
        table.setdefault(name, {})["enabled"] = enabled
    path = settings_paths()[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def enabled_plugins() -> list[Plugin]:
    return [p for p in installed()[0] if is_enabled(p.name)]


def skill_dirs() -> list[Path]:
    """skills/ folders of enabled plugins, for get_all_skills."""
    return [p.root / "skills" for p in enabled_plugins()]


def command_dirs() -> list[Path]:
    """commands/ folders of enabled plugins, for get_all_skills."""
    return [p.root / "commands" for p in enabled_plugins()]


# --- what a plugin contains ------------------------------------------------------------------

def _expand(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        for var in _ROOT_VARS:
            value = value.replace(var, str(root))
    return value


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: {e}") from e


def plugin_hooks(plugin: Plugin) -> dict[str, list[dict[str, Any]]]:
    data = _read_json(plugin.root / "hooks" / "hooks.json")
    table = data.get("hooks", data) if isinstance(data, dict) else {}
    hooks = normalize_hooks(table)
    for groups in hooks.values():
        for group in groups:
            for hook in group["hooks"]:
                hook["command"] = _expand(hook["command"], plugin.root)
    return hooks


def plugin_servers(plugin: Plugin) -> dict[str, dict[str, Any]]:
    data = _read_json(plugin.root / ".mcp.json")
    table = data.get("mcpServers", data) if isinstance(data, dict) else {}
    servers = {}
    for name, cfg in (table.items() if isinstance(table, dict) else []):
        if isinstance(cfg, dict):
            cfg = {**cfg, "command": _expand(cfg.get("command"), plugin.root),
                   "args": [_expand(a, plugin.root) for a in cfg.get("args") or []]}
            if isinstance(cfg.get("env"), dict):
                cfg["env"] = {k: _expand(v, plugin.root) for k, v in cfg["env"].items()}
            servers[name] = cfg
    return servers


def skill_names(plugin: Plugin) -> list[str]:
    skills = plugin.root / "skills"
    return sorted(d.name for d in skills.iterdir() if (d / "SKILL.md").is_file()) if skills.is_dir() else []


def command_names(plugin: Plugin) -> list[str]:
    commands = plugin.root / "commands"
    return sorted(p.stem for p in commands.iterdir() if p.suffix in (".md", ".toml")) if commands.is_dir() else []


def tool_files(plugin: Plugin) -> list[str]:
    """Tool file names only: loading a tool runs its code, so previews never import them."""
    return sorted(p.name for p in (plugin.root / "tools").glob("*.py"))


def describe(plugin: Plugin) -> list[str]:
    """Human-readable lines for everything the plugin would add; env values are never shown."""
    lines = []
    if tools := tool_files(plugin):
        lines.append(f"tools (Python code): {', '.join(tools)}")
    if skills := skill_names(plugin):
        lines.append(f"skills: {', '.join(skills)}")
    try:
        for event, groups in plugin_hooks(plugin).items():
            for group in groups:
                for hook in group["hooks"]:
                    lines.append(f"hook {event} [{group['matcher'] or '*'}]: {hook['command']}")
    except ValueError as e:
        lines.append(f"hooks: unreadable ({e})")
    try:
        for name, cfg in plugin_servers(plugin).items():
            env = f"  (env: {', '.join(cfg['env'])})" if cfg.get("env") else ""
            lines.append(f"MCP server {name}: {' '.join(map(str, [cfg.get('command') or '', *cfg['args']]))}{env}")
    except ValueError as e:
        lines.append(f"MCP servers: unreadable ({e})")
    if commands := command_names(plugin):
        lines.append(f"commands: {', '.join('/' + c for c in commands)}")
    return lines


# --- startup ---------------------------------------------------------------------------------

def _register_tools(registry: Any, plugin: Plugin, loaded: Loaded) -> None:
    from src.tool_system.loader import load_tools_from_dir

    try:
        tools = load_tools_from_dir(plugin.root / "tools")
    except Exception as e:  # a broken tool file must not take the REPL down
        loaded.warnings.append(f"plugin '{plugin.name}': tools not loaded: {e}")
        return
    for tool in tools:
        spec = tool.spec()
        taken = [n for n in (spec.name, *spec.aliases) if registry.get(n) is not None]
        if taken:
            loaded.warnings.append(f"plugin '{plugin.name}': tool {spec.name} skipped, {', '.join(taken)} already exists")
            continue
        registry.register(tool)
        loaded.tools.append(spec.name)


def apply_plugins(registry: Any, hooks: dict[str, list[dict[str, Any]]], servers: dict[str, dict[str, Any]]) -> list[Loaded]:
    """Add enabled plugins' tools to `registry` and their hooks / MCP servers to `hooks` / `servers`.
    Built-in tools and servers from settings.json keep their names; clashes become warnings.
    Skills and commands reach get_all_skills through skill_dirs() / command_dirs()."""
    result = []
    for plugin in enabled_plugins():
        loaded = Loaded(plugin, skills=skill_names(plugin), commands=command_names(plugin))
        _register_tools(registry, plugin, loaded)
        try:
            for event, groups in plugin_hooks(plugin).items():
                hooks.setdefault(event, []).extend(groups)
                loaded.hooks += sum(len(g["hooks"]) for g in groups)
        except ValueError as e:
            loaded.warnings.append(f"plugin '{plugin.name}': hooks not loaded: {e}")
        try:
            for name, cfg in plugin_servers(plugin).items():
                if name in servers:
                    loaded.warnings.append(f"plugin '{plugin.name}': MCP server {name} skipped, one with that name exists")
                    continue
                servers[name] = cfg
                loaded.mcp_servers.append(name)
        except ValueError as e:
            loaded.warnings.append(f"plugin '{plugin.name}': MCP servers not loaded: {e}")
        result.append(loaded)
    return result


# --- other agents' plugins ----------------------------------------------------------------

@dataclass
class Foreign:
    """A plugin another agent has installed, as offered by `clyde plugin import`."""
    agent: str
    source: Path
    plugin: Plugin | None       # None when it has no manifest ClydeCLI can read
    enabled_there: bool
    reason: str = ""            # why it cannot be imported


def _claude_code_plugins() -> list[tuple[Path, bool]]:
    """(install path, enabled in Claude Code) from ~/.claude/plugins/installed_plugins.json."""
    home = Path.home() / ".claude"
    try:
        index = json.loads((home / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    try:
        enabled = json.loads((home / "settings.json").read_text(encoding="utf-8")).get("enabledPlugins") or {}
    except (OSError, ValueError, AttributeError):
        enabled = {}
    found = []
    for key, entries in (index.get("plugins") or {}).items() if isinstance(index, dict) else []:
        entry = entries[0] if isinstance(entries, list) and entries else entries
        path = entry.get("installPath") if isinstance(entry, dict) else None
        if path:
            found.append((Path(path), bool(enabled.get(key, True))))
    return found


def find_foreign() -> list[Foreign]:
    """Plugins installed for Claude Code, Codex or Cursor, excluding names ClydeCLI already has."""
    have = {p.name for p in installed()[0]}
    candidates = [("Claude Code", path, on) for path, on in _claude_code_plugins()]
    for agent, base in (("Codex", Path.home() / ".codex" / "plugins"), ("Cursor", Path.home() / ".cursor" / "plugins")):
        for root in sorted(base.glob("*")) + sorted(base.glob("*/*")) if base.is_dir() else []:
            if root.is_dir() and any((root / m).is_file() for m in MANIFESTS):
                candidates.append((agent, root, True))
    found = []
    for agent, root, on in candidates:
        try:
            plugin = read_manifest(root)
        except ValueError:
            found.append(Foreign(agent, root, None, on, "no plugin manifest"))
            continue
        if plugin.name in have:
            continue
        loadable = describe(plugin)
        reason = "" if loadable else "nothing ClydeCLI can load (no skills, commands, hooks, MCP servers or tools)"
        found.append(Foreign(agent, root, plugin, on, reason))
    return found


# --- install / remove ------------------------------------------------------------------------

def _is_git_url(source: str) -> bool:
    return "://" in source or source.startswith("git@")


def install(source: str) -> Plugin:
    """Copy a local plugin folder, or shallow-clone a git URL, into ~/.clyde/plugins/<name>.
    The plugin is not enabled; ValueError when the source is not a valid plugin or is already installed."""
    base = plugins_dir()
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base, prefix=".install-") as tmp:
        staged = Path(tmp) / "plugin"
        if _is_git_url(source) and not Path(source).exists():
            done = subprocess.run(["git", "clone", "--depth", "1", "--", source, str(staged)],
                                  capture_output=True, text=True, check=False)
            if done.returncode != 0:
                raise ValueError(f"git clone failed: {done.stderr.strip()}")
        else:
            src = Path(source).expanduser()
            if not src.is_dir():
                raise ValueError(f"{source} is not a folder or a git URL")
            shutil.copytree(src, staged, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        plugin = read_manifest(staged)
        dest = base / plugin.name
        if dest.exists():
            raise ValueError(f"plugin '{plugin.name}' is already installed; remove it first")
        staged.rename(dest)
    return Plugin(plugin.name, plugin.version, plugin.description, dest)


def remove(name: str) -> None:
    if not _NAME_RE.fullmatch(name) or not (plugins_dir() / name).is_dir():
        raise ValueError(f"no plugin named '{name}' is installed")
    shutil.rmtree(plugins_dir() / name)
    set_enabled(name, None)
