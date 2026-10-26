"""Saved permission rules: `permissions` in ~/.clyde/settings.json, in Claude Code's syntax.

    {"permissions": {"allow": ["Bash(npm test)", "Bash(git commit:*)", "Edit(docs/**)",
                               "WebFetch(domain:example.com)"],
                     "deny": ["Bash(rm:*)"]}}

`Bash(cmd)` matches that exact command, `Bash(prefix:*)` any command starting with those words; Edit/Write
take a path glob relative to the workspace; a bare tool name matches every use. Deny wins over allow.
"""

from __future__ import annotations

from src.config import clyde_home

import fnmatch
import hashlib
import json
import re
import shlex
import urllib.parse
from functools import lru_cache
from pathlib import Path, PurePath
from typing import Any

_RULE_RE = re.compile(r"^([^()]+?)\s*(?:\((.*)\))?$", re.DOTALL)
_PATH_TOOLS = ("Edit", "Write", "Read", "Grep")


def settings_path() -> Path:
    return clyde_home() / "settings.json"


def load_rules(path: Path | None = None) -> dict[str, list[str]]:
    """`permissions.allow` / `.ask` / `.deny` from a settings file; empty lists when missing or unreadable."""
    try:
        perms = json.loads((path or settings_path()).read_text(encoding="utf-8")).get("permissions", {})
    except (OSError, ValueError, AttributeError):
        perms = {}
    if not isinstance(perms, dict):
        perms = {}
    return {key: [r for r in perms.get(key) or [] if isinstance(r, str)] for key in ("allow", "ask", "deny")}


def project_settings_path(root: Path) -> Path:
    return Path(root) / ".clyde" / "settings.json"


def _approvals_path() -> Path:
    return clyde_home() / "project_rule_approvals.json"


def _approval_key(root: Path, allow: list[str]) -> str:
    return f"{Path(root).resolve()}::{hashlib.sha256(json.dumps(sorted(allow)).encode()).hexdigest()[:16]}"


def project_trust(root: Path, allow: list[str]) -> bool | None:
    """True or False when this project's exact allow list was answered before; None when it is new or changed."""
    try:
        answers = json.loads(_approvals_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = answers.get(_approval_key(root, allow)) if isinstance(answers, dict) else None
    return value if isinstance(value, bool) else None


def set_project_trust(root: Path, allow: list[str], trusted: bool) -> None:
    path = _approvals_path()
    try:
        answers = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        answers = {}
    answers = answers if isinstance(answers, dict) else {}
    answers[_approval_key(root, allow)] = trusted
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answers, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def merge_project_rules(rules: dict[str, list[str]], project: dict[str, list[str]], trusted: bool) -> dict[str, list[str]]:
    """A project's .clyde/settings.json rules on top of the user's, as Claude Code applies a shared settings file: its
    deny and ask rules only take permission away, so they apply at once; its allow rules come from the repository and
    could let a command run unasked, so they apply only once the user has trusted that exact list."""
    return {"allow": rules["allow"] + (project["allow"] if trusted else []),
            "ask": rules.get("ask", []) + project["ask"], "deny": rules["deny"] + project["deny"]}


def bare_denied(tool: str, rules: dict[str, list[str]]) -> bool:
    """A deny rule naming the tool alone (`Bash`, `WebFetch`, `mcp__github__*`): the model is not even shown it."""
    return any("(" not in r and fnmatch.fnmatchcase(tool.lower(), r.strip().lower()) for r in rules["deny"])


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


def _segment_regex(segment: str) -> str:
    """One path segment of a glob as a regex: `*` and `?` stay inside the segment, `[abc]` and `[!abc]` are classes."""
    out, i = [], 0
    while i < len(segment):
        c = segment[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1 + (segment[i + 1:i + 2] == "!")
            j += segment[j:j + 1] == "]"      # a ] right after the opening is a member, not the end
            j = segment.find("]", j)
            if j == -1:
                out.append(r"\[")
            else:
                body = segment[i + 1:j]
                negate, body = (True, body[1:]) if body.startswith("!") else (False, body)
                out.append("[" + ("^" if negate else "") + re.sub(r"([\\\[&~|^])", r"\\\1", body) + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    segments = pattern.split("/")
    out = []
    for i, segment in enumerate(segments):
        last = i == len(segments) - 1
        if segment == "**":   # whole-segment ** is any number of segments; as the last one it needs at least one
            out.append("(?:[^/]+/)*[^/]+" if last else "(?:[^/]+/)*")
        else:
            out.append(_segment_regex(segment) + ("" if last else "/"))
    return re.compile("".join(out), re.S)


def _full_match(path: PurePath, pattern: str) -> bool:
    """PurePath.full_match (Python 3.13+) on any supported Python: the whole path against a glob. Where full_match exists it is used;
    the fallback copies its rules (tests/tool_system/test_permission_rules.py compares the two on every combination they try)."""
    if hasattr(path, "full_match"):
        return path.full_match(pattern)
    return _glob_regex(pattern).fullmatch(path.as_posix()) is not None


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
        return path is not None and _full_match(PurePath(path), str(pattern))
    if tool == "WebFetch" and spec.startswith("domain:"):
        return _domain(tool_input) == spec[len("domain:"):].lower()
    return False


def _bash_parts(command: str) -> list[list[str]] | None:
    from .tools.bash import split_command  # lazy: tools import the registry, which imports this module

    parts = split_command(command)
    return None if parts is None else [p for p in parts if p]


def check_rules(tool: str, tool_input: dict[str, Any], context: Any) -> str | None:
    """'deny', 'ask' or 'allow' when the saved rules decide this call, else None (fall back to the tool's own check).
    As Claude Code: deny, then ask, then allow; an ask rule prompts even where an allow rule or read-only would not."""
    rules = context.permission_rules
    ask = rules.get("ask", [])
    if tool != "Bash":
        if any(_matches(r, tool, tool_input, context, None) for r in rules["deny"]):
            return "deny"
        if any(_matches(r, tool, tool_input, context, None) for r in ask):
            return "ask"
        return "allow" if any(_matches(r, tool, tool_input, context, None) for r in rules["allow"]) else None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    from .secret_paths import command_reads_secret
    parts = _bash_parts(command)
    # Deny if the whole command or any part matches; allow only when every part is allowed.
    candidates = [_words(command)] + (parts or [])
    if any(_matches(r, tool, tool_input, context, w) for r in rules["deny"] for w in candidates):
        return "deny"
    if any(_matches(r, tool, tool_input, context, w) for r in ask for w in candidates):
        return "ask"
    if any(_matches(r, tool, tool_input, context, None) for r in rules["allow"]):  # bare `Bash`
        return "allow"
    if not parts or any(_part_needs_rule(p, rules["allow"], tool_input, context) for p in parts):
        return None
    from .tools.bash import reaches_outside_project
    if (command_reads_secret(command) or reaches_outside_project(command, context, tool_input.get("cwd"))) \
            and not all(any(_matches(r, tool, tool_input, context, w) for r in rules["allow"]) for w in parts):
        return None   # read-only is not a yes to printing a key or reading another folder: only a rule the user wrote covers that
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
