"""PreToolUse / PostToolUse hooks: shell commands from ~/.clyde/settings.json.

Shape (same as Claude Code):
    {"hooks": {"PreToolUse": [{"matcher": "Bash|Write", "hooks": [{"type": "command", "command": "..."}]}]}}

Each command gets the event as JSON on stdin. Exit 0 continues; exit 2 blocks the tool call
(PreToolUse) or hands stderr back to the model (PostToolUse); any other exit is ignored.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

# ponytail: user-level settings only; project .clyde/settings.json hooks need a workspace trust prompt first
SETTINGS_PATH = Path.home() / ".clyde" / "settings.json"
DEFAULT_TIMEOUT = 60


def load_hooks(path: Path = SETTINGS_PATH) -> dict[str, list[dict[str, Any]]]:
    """The `hooks` table from the settings file, or {} when it is missing or unreadable."""
    try:
        hooks = json.loads(path.read_text(encoding="utf-8")).get("hooks", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return hooks if isinstance(hooks, dict) else {}


def _matches(matcher: str, tool_name: str) -> bool:
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool_name) is not None
    except re.error:
        return matcher == tool_name


def run_hooks(hooks: dict[str, list[dict[str, Any]]], event: str, payload: dict[str, Any], cwd: Path) -> str | None:
    """Run the event's matching hook commands; return the stderr of the first one that exits 2."""
    stdin = json.dumps({"hook_event_name": event, "cwd": str(cwd), **payload}, default=str)
    for group in hooks.get(event) or []:
        if not isinstance(group, dict) or not _matches(str(group.get("matcher", "")), payload["tool_name"]):
            continue
        for hook in group.get("hooks") or []:
            if not isinstance(hook, dict) or hook.get("type", "command") != "command" or not hook.get("command"):
                continue
            try:
                done = subprocess.run(
                    hook["command"], shell=True, input=stdin, capture_output=True, text=True,
                    cwd=cwd, timeout=hook.get("timeout", DEFAULT_TIMEOUT),
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if done.returncode == 2:
                return done.stderr.strip() or f"blocked by {event} hook: {hook['command']}"
    return None
