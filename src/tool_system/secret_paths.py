"""What counts as a secret: files that hold keys, and variables that carry them.

A command that reads one is not "read-only" in the sense that matters: what it prints goes to the model, and from there
into any request the model makes next. So such reads always ask, in every mode, whichever tool does the reading.
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path

from .tools.bash import split_command

# Key files, .env files (but not the committed templates), cloud and package credentials, and Clyde's own key store.
_SECRET_PATH = re.compile(
    r"(^|/)("
    r"\.env(?!\.(example|sample|template|dist)$)(\..*)?"
    r"|\.ssh/.*|\.gnupg/.*|\.aws/.*|\.kube/config|\.docker/config\.json|\.config/gh/hosts\.yml|\.config/gcloud/.*"
    r"|\.netrc|\.npmrc|\.pypirc|\.git-credentials|credentials.*|Library/Keychains/.*"
    r"|.*\.(pem|key|p12|pfx)|id_(rsa|ed25519|ecdsa|dsa).*"
    r"|\.clyde/(keys|config|settings|mcp_oauth|mcp_project_approvals)\.json[^/]*"
    r"|proc/(self|thread-self|\d+)/environ"
    r")$"
)
# Folders that hold secrets: naming one to a command that reads or copies it reads what is inside.
_SECRET_DIR = re.compile(r"(^|/)(\.ssh|\.gnupg|\.aws|\.kube|\.clyde|\.config/gcloud|Library/Keychains)$")
_NAMES_ONLY = {"ls", "cd", "pwd", "stat", "du", "test", "[", "pushd", "popd"}   # these show names, not contents
_PRINTS_ENVIRONMENT = {"env", "printenv", "set", "export", "declare", "typeset"}   # the environment holds the provider keys
_SECRET_VARIABLE = re.compile(r"\$\{?\w*(KEY|TOKEN|SECRET|PASSW(OR)?D)\w*\}?", re.IGNORECASE)
_SEARCHES = {"grep", "egrep", "fgrep", "rg", "ag", "find"}   # these go through whatever is under the folder they are given


def _resolve(path: str, base: Path | None = None) -> Path | None:
    try:
        target = Path(os.path.expandvars(path)).expanduser()
        return (target if target.is_absolute() or base is None else base / target).resolve()
    except (OSError, RuntimeError):
        return None


def is_secret_path(path: str, base: Path | None = None) -> bool:
    """Whether `path` (with ~ and $HOME expanded, relative to `base` when given, symlinks followed) names a secret file."""
    resolved = _resolve(path, base)
    return resolved is not None and bool(_SECRET_PATH.search(resolved.as_posix()))


def _broad(word: str, base: Path | None = None) -> bool:
    """The whole home folder or the whole disk: a search of it reads every secret in it."""
    resolved = _resolve(word, base)
    return resolved in (Path.home().resolve(), Path("/"))


def _braces(word: str) -> list[str]:
    """`a{b,c}d` as `abd` and `acd` (one level, as the shell expands it before a glob)."""
    match = re.search(r"\{([^{}]*,[^{}]*)\}", word)
    if not match:
        return [word]
    return [x for alt in match.group(1).split(",") for x in _braces(word[:match.start()] + alt + word[match.end():])]


def _expanded(word: str, base: Path) -> list[str]:
    """What the shell would turn a word with braces or wildcards into, for the files that exist."""
    out: list[str] = []
    for candidate in _braces(word):
        if any(c in candidate for c in "*?["):
            out += glob.glob(os.path.expanduser(os.path.expandvars(candidate)), root_dir=base)
        else:
            out.append(candidate)
    return out


def command_reads_secret(command: str) -> bool:
    """Whether a shell command names a secret file (however it is spelled: glob, braces, a name after a `cd`, a folder),
    expands a secret-looking variable, prints the environment, or searches the whole home folder."""
    parts = split_command(command)
    if parts is None:
        return False
    here = Path.cwd()
    for words in parts:
        if not words:
            continue
        name, args = words[0], words[1:]
        if name in ("cd", "pushd") and args and not args[0].startswith("-"):
            moved = _resolve(args[0], here)
            here = moved if moved is not None and moved.is_dir() else here
        if name in _PRINTS_ENVIRONMENT and all(a.startswith("-") for a in args) and (name not in ("export", "declare", "typeset") or "-p" in args):
            return True
        for word in args:
            value = word.split("=", 1)[1] if word.startswith("-") and "=" in word else word
            if value.startswith("-"):
                continue
            if _SECRET_VARIABLE.search(value):
                return True
            for item in _expanded(value, here):
                resolved = _resolve(item, here)
                if resolved is None:
                    continue
                if is_secret_path(item, here) or (name not in _NAMES_ONLY and _SECRET_DIR.search(resolved.as_posix())):
                    return True
            if name in _SEARCHES and _broad(value, here):
                return True
    return False
