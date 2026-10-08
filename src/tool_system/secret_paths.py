"""What counts as a secret: files that hold keys, and variables that carry them.

A command that reads one is not "read-only" in the sense that matters: what it prints goes to the model, and from there
into any request the model makes next. So such reads always ask, in every mode, whichever tool does the reading.
"""
from __future__ import annotations

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
    r"|\.clyde/(keys|config)\.json[^/]*"
    r")$"
)
_SECRET_VARIABLE = re.compile(r"\$\{?\w*(KEY|TOKEN|SECRET|PASSW(OR)?D)\w*\}?", re.IGNORECASE)
_SEARCHES = {"grep", "egrep", "fgrep", "rg", "ag", "find"}   # these go through whatever is under the folder they are given


def is_secret_path(path: str) -> bool:
    """Whether `path` (with ~ and $HOME expanded, symlinks followed) names a secret file."""
    try:
        resolved = Path(os.path.expandvars(path)).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return bool(_SECRET_PATH.search(resolved.as_posix()))


def _broad(word: str) -> bool:
    """The whole home folder or the whole disk: a search of it reads every secret in it."""
    try:
        resolved = Path(os.path.expandvars(word)).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return resolved in (Path.home().resolve(), Path("/"))


def command_reads_secret(command: str) -> bool:
    """Whether a shell command names a secret file, expands a secret-looking variable, or searches the whole home folder."""
    parts = split_command(command)
    if parts is None:
        return False
    for words in parts:
        for word in words[1:]:
            value = word.split("=", 1)[1] if word.startswith("-") and "=" in word else word
            if value.startswith("-"):
                continue
            if _SECRET_VARIABLE.search(value) or is_secret_path(value):
                return True
            if words and words[0] in _SEARCHES and _broad(value):
                return True
    return False
