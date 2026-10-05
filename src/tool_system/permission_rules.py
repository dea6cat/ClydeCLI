"""Saved permission rules: `permissions` in ~/.clyde/settings.json, in Claude Code's syntax.

    {"permissions": {"allow": ["Bash(npm test)", "Bash(git commit:*)", "Edit(docs/**)",
                               "WebFetch(domain:example.com)"],
                     "deny": ["Bash(rm:*)"]}}

`Bash(cmd)` matches that exact command, `Bash(prefix:*)` any command starting with those words; Edit/Write
take a path glob relative to the workspace; a bare tool name matches every use. Deny wins over allow.
"""

from __future__ import annotations

from src.config import clyde_home

import json
import re
import shlex
import urllib.parse
from pathlib import Path, PurePath
from typing import Any

_RULE_RE = re.compile(r"^([^()]+?)\s*(?:\((.*)\))?$", re.DOTALL)
_PATH_TOOLS = ("Edit", "Write", "Read", "Grep")


# ponytail: user-level settings only; project rules need a workspace trust prompt first
def settings_path() -> Path:
    return clyde_home() / "settings.json"


def load_rules(path: Path | None = None) -> dict[str, list[str]]:
    """`permissions.allow` / `permissions.deny` from the settings file; empty lists when missing or unreadable."""
    try:
        perms = json.loads((path or settings_path()).read_text(encoding="utf-8")).get("permissions", {})
    except (OSError, ValueError, AttributeError):
        perms = {}
    if not isinstance(perms, dict):
        perms = {}
    return {key: [r for r in perms.get(key) or [] if isinstance(r, str)] for key in ("allow", "deny")}


def save_allow_rule(rule: str, path: Path | None = None) -> None:
    """Append an allow rule to the settings file, keeping every other key."""
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    if rule not in allow:
        allow.append(rule)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)  # settings may hold MCP tokens


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _bash_matches(spec: str, words: list[str]) -> bool:
    if spec.endswith(":*"):
        prefix = _words(spec[:-2])
        return words[: len(prefix)] == prefix
    return words == _words(spec)


def _file_path(tool_input: dict[str, Any], context: Any) -> Path | None:
    raw = tool_input.get("file_path") or tool_input.get("path")
    if not isinstance(raw, str):
        return None
    p = Path(raw).expanduser()
    return (p if p.is_absolute() else (context.cwd or context.workspace_root) / p).resolve()


def _domain(tool_input: dict[str, Any]) -> str | None:
    url = tool_input.get("url")
    return (urllib.parse.urlparse(url).hostname or None) if isinstance(url, str) else None


def _matches(rule: str, tool: str, tool_input: dict[str, Any], context: Any, bash_words: list[str] | None) -> bool:
    m = _RULE_RE.match(rule.strip())
    if not m or m.group(1).lower() != tool.lower():
        return False
    spec = m.group(2)
    if spec is None or spec == "*":
        return True
    if tool == "Bash":
        return bash_words is not None and _bash_matches(spec, bash_words)
    if tool in _PATH_TOOLS:
        path = _file_path(tool_input, context)
        pattern = Path(spec).expanduser()
        pattern = pattern if pattern.is_absolute() else Path(context.workspace_root) / pattern
        return path is not None and PurePath(path).full_match(str(pattern))
    if tool == "WebFetch" and spec.startswith("domain:"):
        return _domain(tool_input) == spec[len("domain:"):].lower()
    return False


def _bash_parts(command: str) -> list[list[str]] | None:
    from .tools.bash import split_command  # lazy: tools import the registry, which imports this module

    parts = split_command(command)
    return None if parts is None else [p for p in parts if p]


def check_rules(tool: str, tool_input: dict[str, Any], context: Any) -> str | None:
    """'deny' or 'allow' when the saved rules decide this call, else None (fall back to the tool's own check)."""
    rules = context.permission_rules
    if tool != "Bash":
        if any(_matches(r, tool, tool_input, context, None) for r in rules["deny"]):
            return "deny"
        return "allow" if any(_matches(r, tool, tool_input, context, None) for r in rules["allow"]) else None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    parts = _bash_parts(command)
    # Deny if the whole command or any part matches; allow only when every part is allowed.
    candidates = [_words(command)] + (parts or [])
    if any(_matches(r, tool, tool_input, context, w) for r in rules["deny"] for w in candidates):
        return "deny"
    if any(_matches(r, tool, tool_input, context, None) for r in rules["allow"]):  # bare `Bash`
        return "allow"
    if not parts or any(_part_needs_rule(p, rules["allow"], tool_input, context) for p in parts):
        return None
    return "allow"


def _part_needs_rule(words: list[str], allow: list[str], tool_input: dict[str, Any], context: Any) -> bool:
    from .tools.bash import _is_read_only_part

    return not _is_read_only_part(words) and not any(_matches(r, "Bash", tool_input, context, words) for r in allow)


def suggest_rule(tool: str, tool_input: dict[str, Any], context: Any) -> str | None:
    """The allow rule offered as "don't ask again" for this call, or None when no single rule would cover it."""
    if tool == "Bash":
        parts = _bash_parts(tool_input.get("command") or "")
        pending = [p for p in parts or [] if _part_needs_rule(p, context.permission_rules["allow"], tool_input, context)]
        if len(pending) != 1:
            return None
        # The command plus up to two sub-command words, stopping at the first flag: `npm run test:*`.
        prefix = pending[0][:1]
        for word in pending[0][1:3]:
            if word.startswith("-"):
                break
            prefix.append(word)
        return f"Bash({shlex.join(prefix)}:*)"
    if tool in _PATH_TOOLS:
        path = _file_path(tool_input, context)
        if path is None:
            return None
        try:
            return f"{tool}({path.relative_to(Path(context.workspace_root).resolve())})"
        except ValueError:
            return f"{tool}({path})"
    if tool == "WebFetch":
        domain = _domain(tool_input)
        return f"WebFetch(domain:{domain})" if domain else None
    return tool
