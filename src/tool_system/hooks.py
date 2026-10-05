"""PreToolUse / PostToolUse hooks: shell commands from ~/.clyde/settings.json or settings.toml.

The canonical shape is Claude Code's:
    {"hooks": {"PreToolUse": [{"matcher": "Bash|Write", "hooks": [{"type": "command", "command": "..."}]}]}}

Also accepted, and normalized to that shape on load:
    shorthand            {"PreToolUse": {"Bash": "cmd"}}, or a list of command strings
    Gemini CLI           BeforeTool / AfterTool, with Gemini tool names in the matcher
    Cursor               beforeShellExecution / beforeReadFile / afterFileEdit, flat {"command": ...}
    Copilot CLI          preToolUse / postToolUse, flat {"bash": ..., "timeoutSec": ...}

Each command gets the event as JSON on stdin. Exit 2 blocks the tool call (PreToolUse) or hands
stderr back to the model (PostToolUse). A JSON reply on stdout that denies or blocks does the same;
any other outcome carries on.
"""

from __future__ import annotations

from src.config import clyde_home

import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

# ponytail: user-level settings only; project .clyde/settings.json hooks need a workspace trust prompt first
def settings_paths() -> tuple[Path, Path]:
    return (clyde_home() / "settings.json", clyde_home() / "settings.toml")

DEFAULT_TIMEOUT = 60

# User-level hook settings of other agents, offered for import by `clyde hooks import` and setup.
def foreign_sources() -> tuple[tuple[str, Path], ...]:
    home = Path.home()
    return (
        ("Claude Code", home / ".claude" / "settings.json"),
        ("Gemini CLI", home / ".gemini" / "settings.json"),
        ("Cursor", home / ".cursor" / "hooks.json"),
        ("Copilot CLI", home / ".copilot" / "hooks.json"),
    )

# Event names from other agents -> (canonical event, implied matcher). Keys are lowercase.
_EVENTS = {
    "pretooluse": ("PreToolUse", ""),
    "posttooluse": ("PostToolUse", ""),
    "beforetool": ("PreToolUse", ""),
    "aftertool": ("PostToolUse", ""),
    "beforeshellexecution": ("PreToolUse", "Bash"),
    "beforereadfile": ("PreToolUse", "Read"),
    "afterfileedit": ("PostToolUse", "Write|Edit|NotebookEdit"),
}

# Gemini CLI tool names that may appear in a matcher.
_TOOL_NAMES = {
    "run_shell_command": "Bash",
    "read_file": "Read",
    "read_many_files": "Read",
    "write_file": "Write",
    "replace": "Edit",
    "glob": "Glob",
    "search_file_content": "Grep",
    "web_fetch": "WebFetch",
    "google_web_search": "WebSearch",
}


def _matcher(raw: Any, implied: str) -> str:
    raw = str(raw or "")
    if not raw or raw == "*":
        return implied
    return "|".join(_TOOL_NAMES.get(part, part) for part in raw.split("|"))


def _hook(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        return {"command": raw}
    if not isinstance(raw, dict) or raw.get("type", "command") != "command":
        return None
    command = raw.get("command") or raw.get("bash")
    if not command:
        return None
    return {"command": command, "timeout": raw.get("timeout") or raw.get("timeoutSec") or DEFAULT_TIMEOUT}


def _groups(value: Any, implied: str) -> list[dict[str, Any]]:
    """Turn any accepted form of one event's hooks into [{"matcher": str, "hooks": [...]}]."""
    if isinstance(value, dict):  # shorthand {"Bash": "cmd" | ["cmd", ...]}
        value = [{"matcher": m, "hooks": cmds if isinstance(cmds, list) else [cmds]} for m, cmds in value.items()]
    groups = []
    for entry in value if isinstance(value, list) else []:
        if isinstance(entry, dict) and "hooks" in entry:
            raw_hooks = entry["hooks"] if isinstance(entry["hooks"], list) else [entry["hooks"]]
        else:  # a bare command string, or a flat Cursor / Copilot entry
            raw_hooks = [entry]
        hooks = [h for h in map(_hook, raw_hooks) if h]
        if hooks:
            groups.append({"matcher": _matcher(entry.get("matcher") if isinstance(entry, dict) else "", implied), "hooks": hooks})
    return groups


def normalize_hooks(table: Any) -> dict[str, list[dict[str, Any]]]:
    """Map a hooks table in any supported format onto PreToolUse / PostToolUse groups."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name, value in (table.items() if isinstance(table, dict) else []):
        event = _EVENTS.get(str(name).lower())
        if event:
            out.setdefault(event[0], []).extend(_groups(value, event[1]))
    return out


def _read(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)


def load_hooks(paths: tuple[Path, ...] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Merged, normalized hooks from every settings file that exists and parses."""
    merged: dict[str, list[dict[str, Any]]] = {}
    for path in paths or settings_paths():
        try:
            data = _read(path)
        except (OSError, ValueError):
            continue
        hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
        for event, groups in normalize_hooks(hooks).items():
            merged.setdefault(event, []).extend(groups)
    return merged


def _matches(matcher: str, tool_name: str) -> bool:
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool_name) is not None
    except re.error:
        return matcher == tool_name


def _json_verdict(stdout: str) -> str | None:
    """The reason when a hook's JSON reply denies or blocks (Claude Code, Gemini, Cursor, Copilot keys)."""
    try:
        reply = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(reply, dict):
        return None
    specific = reply.get("hookSpecificOutput") if isinstance(reply.get("hookSpecificOutput"), dict) else {}
    denied = (
        reply.get("decision") in ("block", "deny")
        or "deny" in (reply.get("permission"), reply.get("permissionDecision"), specific.get("permissionDecision"))
        or reply.get("continue") is False
    )
    if not denied:
        return None
    for key in ("reason", "permissionDecisionReason", "agentMessage", "userMessage", "stopReason"):
        if reply.get(key) or specific.get(key):
            return str(reply.get(key) or specific.get(key))
    return "blocked by hook"


def run_hooks(hooks: dict[str, list[dict[str, Any]]], event: str, payload: dict[str, Any], cwd: Path) -> str | None:
    """Run the event's matching hook commands; return the message of the first one that blocks."""
    stdin = json.dumps({"hook_event_name": event, "cwd": str(cwd), **payload}, default=str)
    for group in hooks.get(event) or []:
        if not _matches(group["matcher"], payload["tool_name"]):
            continue
        for hook in group["hooks"]:
            try:
                done = subprocess.run(
                    hook["command"], shell=True, input=stdin, capture_output=True, text=True,
                    cwd=cwd, timeout=hook.get("timeout", DEFAULT_TIMEOUT),
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if done.returncode == 2:
                return done.stderr.strip() or f"blocked by {event} hook: {hook['command']}"
            if done.returncode == 0 and (verdict := _json_verdict(done.stdout.strip())):
                return verdict
    return None


def find_foreign_hooks(sources: tuple[tuple[str, Path], ...] | None = None) -> list[tuple[str, Path, dict[str, list[dict[str, Any]]]]]:
    """(agent, path, normalized hooks) for every other agent's settings file that defines hooks."""
    found = []
    for agent, path in sources or foreign_sources():
        try:
            data = _read(path)
        except (OSError, ValueError):
            continue
        hooks = normalize_hooks(data.get("hooks", {}) if isinstance(data, dict) else {})
        if hooks:
            found.append((agent, path, hooks))
    return found


def _keys(hooks: dict[str, list[dict[str, Any]]]) -> set[tuple[str, str, str]]:
    return {(event, g["matcher"], h["command"]) for event, groups in hooks.items() for g in groups for h in g["hooks"]}


def import_hooks(hooks: dict[str, list[dict[str, Any]]], dest: Path | None = None) -> int:
    """Append hooks to the JSON settings file, skipping ones already there; return how many were added."""
    dest = dest or settings_paths()[0]
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{dest} is not a JSON object")
    table = data.setdefault("hooks", {})
    existing = _keys(normalize_hooks(table))
    added = 0
    for event, groups in hooks.items():
        current = table.get(event)
        if not isinstance(current, list):  # a shorthand dict: rewrite this event in the full form
            current = normalize_hooks({event: current}).get(event, []) if current else []
        for group in groups:
            new = [h for h in group["hooks"] if (event, group["matcher"], h["command"]) not in existing]
            if not new:
                continue
            current.append({"matcher": group["matcher"], "hooks": [{"type": "command", **h} for h in new]})
            existing |= {(event, group["matcher"], h["command"]) for h in new}
            added += len(new)
        if current:
            table[event] = current
    if added:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return added
