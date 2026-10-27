from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ...system import proc
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
    "rg": ("--pre", "--hostname-bin", "--search-zip", "-z"),   # run another program
    "git": ("--output",),
    "tree": ("-o", "-R", "--output"),   # -o writes a file; -R writes 00Tree.html in every folder
    "file": ("-C", "--compile"),        # writes a compiled magic file
    "date": ("-s", "--set"),            # sets the clock
}


def _has_flag(arg: str, flag: str) -> bool:
    """Whether `arg` is `flag`, `flag=value`, `flagvalue`, or (for a one-letter flag) bundled in a cluster like -aR."""
    if arg.startswith(flag):
        return True
    return len(flag) == 2 and not arg.startswith("--") and re.match(rf"-[A-Za-z]*{flag[1]}", arg) is not None


def _is_read_only_part(words: list[str]) -> bool:
    if not words:
        return True
    name, args = words[0], words[1:]
    if any(_has_flag(arg, flag) for flag in _UNSAFE_FLAGS.get(name, ()) for arg in args):
        return False
    if name in ("find", "rg"):
        return True
    if name == "git":
        # Skip harmless global options; `-c` is not one (it can point core.pager at any program).
        while args and args[0] in ("--no-pager", "-C"):
            args = args[2:] if args[0] == "-C" else args[1:]
        return bool(args) and args[0] in _READ_ONLY_GIT
    return name in _READ_ONLY_COMMANDS


# Quoting forms bash expands into code or arbitrary bytes: ANSI-C $'..', locale $"..", arithmetic $((..)).
_CAN_EVALUATE = re.compile(r"\$['\"]|\$\(\(")


def split_command(command: str) -> list[list[str]] | None:
    """Words of each part of a compound command; None if it substitutes, redirects to a file or won't parse."""
    if "$(" in command or "`" in command or _CAN_EVALUATE.search(command):
        return None
    names = re.findall(r"\$\{([^}]*)\}", command)
    if command.count("${") != len(names) or any(not re.fullmatch(r"\w+", name) for name in names):
        return None   # only a plain ${NAME} is a read; ${x@P}, ${x:=cmd}, ${!y}, ${x//a/b}, an unclosed ${ can assign or run code
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


# Commands that still ask in "all in" mode: hard to undo, or they reach outside the machine.
# ponytail: a pattern list, not a classifier; add patterns as new kinds of major commands turn up
_MAJOR_PATTERNS = [re.compile(p) for p in (
    r"\brm\s+(-\w*[rRf]|--recursive|--force)",
    r"\bgit\s+push\b", r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\s+-\w*f",
    r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", r"\bgit\s+branch\s+-D\b",
    r"\bgit\s+(rebase|filter-branch|filter-repo)\b", r"--force\b|\s-f\b.*\bpush\b",
    r"\b(npm|pnpm|yarn)\s+publish\b", r"\btwine\s+upload\b", r"\bcargo\s+publish\b", r"\bgh\s+release\b",
    r"\b(curl|wget)\b[^|]*\|\s*(ba|z)?sh\b",
    r"\bdocker\s+(rm|rmi|system\s+prune|volume\s+rm)\b", r"\bkubectl\s+delete\b",
    r"\bterraform\s+(apply|destroy)\b",
    r"\b(chmod|chown)\s+-\w*R", r"\bkill\s+-9\b|\bkillall\b|\bpkill\b",
    r"\b(shutdown|reboot|halt)\b", r"\bdd\s+if=", r"\bmkfs\b", r"\btruncate\b",
    r"\bdrop\s+(table|database)\b",
)]


def is_major_command(command: str) -> bool:
    """Whether a shell command is risky enough to ask even in all-in mode."""
    low = command.lower()
    return any(p.search(low) for p in _MAJOR_PATTERNS) or bool(re.search(r"\bbranch\s+-D\b", command))


_REMOVES = re.compile(r"\b(rm|rmdir|mv|unlink)\b|\buv\s+tool\s+uninstall\s+clyde|\bpip3?\s+uninstall\b")


def removes_running_install(command: str) -> bool:
    """Whether a command deletes or moves the environment this Clyde runs from (its imports load lazily, so it fails on the next one)."""
    return bool(_REMOVES.search(command)) and sys.prefix in command.replace("~", os.path.expanduser("~"))


_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders", "/dev")


def reaches_outside_project(command: str, context: ToolContext, cwd: Any = None) -> bool:
    """Whether a shell command, or the folder it is asked to run in, is outside the project and its extra folders and not yet
    approved. The command counts when it names an absolute path, `~`, `$HOME` or `..`, or git's config or hooks; temp folders
    and /dev do not count."""
    if isinstance(cwd, str) and cwd and context.outside_path(cwd) is not None:
        return True
    roots = [*context.permission_context.allowed_roots(), *map(Path, _TEMP_ROOTS), Path(tempfile.gettempdir()).resolve()]
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        words = list(lexer)
    except ValueError:
        words = command.split()   # unbalanced quotes: the shell would not run it either; check what is there
    for word in words:
        word = re.sub(r"^\d*[<>&]+", "", word)   # a redirect glued to its target: >/etc/x, 2>>~/log
        if re.search(r"(^|/)\.git/(config|hooks)\b", word):
            return True
        if not word or not (word[0] in "/~$" or ".." in Path(word).parts):
            continue
        try:
            target = Path(os.path.expandvars(word)).expanduser()
            target = (target if target.is_absolute() else (context.cwd or context.workspace_root) / target).resolve()
        except (OSError, RuntimeError):
            return True
        if not any(target.is_relative_to(root) for root in roots):
            return True
    return False


def is_read_only_command(command: str) -> bool:
    """Whether every part of a (possibly compound) shell command only reads."""
    parts = split_command(command)
    return parts is not None and all(_is_read_only_part(part) for part in parts)




def _try_extract_cd(command: str) -> Path | None:
    stripped = command.strip()
    if not stripped.startswith("cd "):
        return None
    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError:
        return None
    # Only a bare `cd <dir>` changes the session's directory; `cd x && make` runs as a whole command.
    if len(parts) == 2 and parts[0] == "cd":
        return Path(parts[1])
    return None


class BashTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Bash",
            description=("Execute a shell command. Anything that is not read-only, and anything that names a folder "
                         "outside the project, asks the user first."),
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
            max_result_size_chars=30_000,   # per stream (stdout, stderr), as Claude Code; the rest via RetrieveContext
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        """Ask before running any command that is not clearly read-only."""
        command = tool_input.get("command")
        if not isinstance(command, str):
            return PermissionResult.allow()  # Input validation happens in run()
        if any(pat.search(command) for pat in _DANGEROUS_PATTERNS):
            return PermissionResult.deny("refusing to run potentially dangerous command")
        if removes_running_install(command):
            return PermissionResult.ask(message=f"This deletes the Clyde that is running ({sys.prefix}); it stops working as soon as it is gone: {command}")
        if reaches_outside_project(command, context, tool_input.get("cwd")):
            return PermissionResult.ask(message=f"Run shell command that reaches outside the project: {command}")
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
            context.grant_path(next_dir)   # run only happens after the ask in check_permissions (reaches_outside_project) was answered
            next_dir = context.ensure_allowed_path(next_dir)
            if not next_dir.exists() or not next_dir.is_dir():
                return ToolResult(name="Bash", output={"error": f"directory does not exist: {next_dir}"}, is_error=True)
            context.cwd = next_dir
            return ToolResult(name="Bash", output={"cwd": str(context.cwd), "stdout": "", "stderr": ""})

        timeout_s = tool_input.get("timeout_s", 60)
        if not isinstance(timeout_s, int) or timeout_s < 1 or timeout_s > 600:
            raise ToolInputError("timeout_s must be an integer between 1 and 600")

        completed = proc.run_group(
            ["bash", "-lc", command],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )

        stdout = completed.stdout or ""   # held to max_result_size_chars, head and tail, by the registry
        stderr = completed.stderr or ""
        output: dict[str, Any] = {
            "cwd": str(cwd),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        return ToolResult(name="Bash", output=output, is_error=completed.returncode != 0)

