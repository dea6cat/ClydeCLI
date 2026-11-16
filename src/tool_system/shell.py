"""How Clyde reads a shell command: split into its parts, read-only or not, dangerous, major (hard to undo), or reaching
outside the project. Used by the Bash tool, the permission rules, the secret-file check and the dispatcher's gates, so
none of them imports the Bash tool to classify a command."""
from __future__ import annotations

import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

from .context import ToolContext


DANGEROUS_PATTERNS = [
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


def _tokens(command: str) -> list[str] | None:
    """The command's words and operators as the shell would read them; None when its quotes don't balance."""
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def split_command(command: str) -> list[list[str]] | None:
    """Words of each part of a compound command; None if it substitutes, redirects to a file or won't parse."""
    if "$(" in command or "`" in command or _CAN_EVALUATE.search(command):
        return None
    names = re.findall(r"\$\{([^}]*)\}", command)
    if command.count("${") != len(names) or any(not re.fullmatch(r"\w+", name) for name in names):
        return None   # only a plain ${NAME} is a read; ${x@P}, ${x:=cmd}, ${!y}, ${x//a/b}, an unclosed ${ can assign or run code
    tokens = _tokens(command)
    if tokens is None:
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
_MAJOR_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\brm\s+(-\w*[rRf]|--recursive|--force)",
    r"\bgit\s+push\b", r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\s+-\w*f",
    r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", r"\bgit\s+branch\s+(?-i:-D)\b",   # -d deletes only merged branches
    r"\bgit\s+(rebase|filter-branch|filter-repo)\b", r"--force\b|\s-f\b.*\bpush\b",
    r"\b(npm|pnpm|yarn)\s+publish\b", r"\btwine\s+upload\b", r"\bcargo\s+publish\b", r"\bgh\s+release\b",
    r"\b(curl|wget)\b[^|]*\|\s*(ba|z)?sh\b",
    r"\bdocker\s+(rm|rmi|system\s+prune|volume\s+rm)\b", r"\bkubectl\s+delete\b",
    r"\bterraform\s+(apply|destroy)\b",
    r"\b(chmod|chown)\s+-\w*R", r"\bkill\s+-9\b|\bkillall\b|\bpkill\b",
    r"\bhalt\b", r"\btruncate\b",   # shutdown, reboot, mkfs and dd are refused outright (DANGEROUS_PATTERNS)
    r"\bdrop\s+(table|database)\b",
)]


def is_major_command(command: str) -> bool:
    """Whether a shell command is risky enough to ask even in all-in mode."""
    return any(p.search(command) for p in _MAJOR_PATTERNS)


_REMOVES = re.compile(r"\b(rm|rmdir|mv|unlink)\b|\buv\s+tool\s+uninstall\s+clyde|\bpip3?\s+uninstall\b")


def removes_running_install(command: str) -> bool:
    """Whether a command deletes or moves the environment this Clyde runs from (its imports load lazily, so it fails on the next one)."""
    return bool(_REMOVES.search(command)) and sys.prefix in command.replace("~", os.path.expanduser("~"))


_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders", "/dev")


def reaches_outside_project(command: str, context: ToolContext, cwd: Any = None) -> bool:
    """Whether a shell command, or the folder it is asked to run in, is outside the project and its extra folders and not yet
    approved. The command counts when it runs in a folder outside, or names an absolute path, `~`, `$HOME` or `..`, or git's
    config or hooks; temp folders and /dev do not count."""
    if isinstance(cwd, str) and cwd and context.outside_path(cwd) is not None:
        return True
    roots = [*context.permission_context.allowed_roots(), *map(Path, _TEMP_ROOTS), Path(tempfile.gettempdir()).resolve()]
    here = Path(context.cwd or context.workspace_root).resolve()
    if not any(here.is_relative_to(root) for root in roots):
        return True   # moved outside with `cd`: every relative path in the command lands there
    words = _tokens(command)
    if words is None:
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
