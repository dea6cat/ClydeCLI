from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionResult
from ..protocol import ToolResult
from ..registry import ToolSpec


_DANGEROUS_PATTERNS = [
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\b\s+if=", re.IGNORECASE),
    re.compile(r"\brm\b.*\s+-rf\s+/\s*$", re.IGNORECASE),
    re.compile(r"\brm\b.*\s+-rf\s+/\s+"),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE),
]


_READ_ONLY_COMMANDS = frozenset({
    "basename", "cat", "cd", "cut", "date", "df", "diff", "dirname", "du", "echo", "egrep", "false",
    "fgrep", "file", "grep", "head", "id", "ls", "pwd", "realpath", "stat", "tail", "tr", "tree",
    "true", "uname", "wc", "which", "whoami",
})
_READ_ONLY_GIT = frozenset({"blame", "diff", "log", "ls-files", "rev-parse", "show", "status"})
# Flags that make an otherwise read-only command run programs or write files.
_UNSAFE_FLAGS = {
    "find": ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fls"),
    "rg": ("--pre",),
    "git": ("--output",),
}


def _is_read_only_part(words: list[str]) -> bool:
    if not words:
        return True
    name, args = words[0], words[1:]
    if any(arg.startswith(flag) for flag in _UNSAFE_FLAGS.get(name, ()) for arg in args):
        return False
    if name in ("find", "rg"):
        return True
    if name == "git":
        # Skip harmless global options; `-c` is not one (it can point core.pager at any program).
        while args and args[0] in ("--no-pager", "-C"):
            args = args[2:] if args[0] == "-C" else args[1:]
        return bool(args) and args[0] in _READ_ONLY_GIT
    return name in _READ_ONLY_COMMANDS


def split_command(command: str) -> list[list[str]] | None:
    """Words of each part of a compound command; None if it substitutes, redirects to a file or won't parse."""
    if "$(" in command or "`" in command:
        return None
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    parts: list[list[str]] = [[]]
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok and set(tok) <= set("|&;"):
            parts.append([])
        elif any(c in tok for c in "<>()"):
            # Only discarding output (`>/dev/null`) or merging streams (`2>&1`) stays read-only.
            if not ((tok in (">", ">>") and nxt == "/dev/null") or (tok == ">&" and nxt.isdigit())):
                return None
            i += 1
        else:
            parts[-1].append(tok)
        i += 1
    return parts


def is_read_only_command(command: str) -> bool:
    """Whether every part of a (possibly compound) shell command only reads."""
    parts = split_command(command)
    return parts is not None and all(_is_read_only_part(part) for part in parts)


def _truncate(s: str, limit: int = 20000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "\n\n... [truncated] ..."


def _try_extract_cd(command: str) -> Path | None:
    stripped = command.strip()
    if not stripped.startswith("cd "):
        return None
    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError:
        return None
    if len(parts) >= 2 and parts[0] == "cd":
        return Path(parts[1])
    return None


class BashTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Bash",
            description="Execute a shell command.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_s": {"type": "integer"},
                },
                "required": ["command"],
            },
            is_destructive=True,
            max_result_size_chars=50_000,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        """Ask before running any command that is not clearly read-only."""
        command = tool_input.get("command")
        if not isinstance(command, str):
            return PermissionResult.allow()  # Input validation happens in run()
        if any(pat.search(command) for pat in _DANGEROUS_PATTERNS):
            return PermissionResult.deny("refusing to run potentially dangerous command")
        if is_read_only_command(command):
            return PermissionResult.allow()
        return PermissionResult.ask(message=f"Run shell command: {command}")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        command = tool_input["command"]
        if not isinstance(command, str) or not command.strip():
            raise ToolInputError("command must be a non-empty string")
        if "\x00" in command:
            raise ToolInputError("command contains NUL byte")

        for pat in _DANGEROUS_PATTERNS:
            if pat.search(command):
                raise ToolPermissionError("refusing to run potentially dangerous command")

        explicit_cwd = tool_input.get("cwd")
        if explicit_cwd is not None:
            if not isinstance(explicit_cwd, str) or not explicit_cwd.startswith("/"):
                raise ToolInputError("cwd must be an absolute path when provided")
            cwd = context.ensure_allowed_path(explicit_cwd)
        else:
            cwd = context.cwd or context.workspace_root

        cd_target = _try_extract_cd(command)
        if cd_target is not None and command.strip().startswith("cd ") and len(command.strip().splitlines()) == 1:
            next_dir = (cwd / cd_target).expanduser().resolve() if not cd_target.is_absolute() else cd_target.expanduser().resolve()
            next_dir = context.ensure_allowed_path(next_dir)
            if not next_dir.exists() or not next_dir.is_dir():
                return ToolResult(name="Bash", output={"error": f"directory does not exist: {next_dir}"}, is_error=True)
            context.cwd = next_dir
            return ToolResult(name="Bash", output={"cwd": str(context.cwd), "stdout": "", "stderr": ""})

        timeout_s = tool_input.get("timeout_s", 60)
        if not isinstance(timeout_s, int) or timeout_s < 1 or timeout_s > 600:
            raise ToolInputError("timeout_s must be an integer between 1 and 600")

        completed = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

        stdout = _truncate(completed.stdout or "")
        stderr = _truncate(completed.stderr or "")
        output: dict[str, Any] = {
            "cwd": str(cwd),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        return ToolResult(name="Bash", output=output, is_error=completed.returncode != 0)

