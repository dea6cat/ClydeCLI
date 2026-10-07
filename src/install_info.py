"""How this copy of Clyde was installed, what else on the machine answers to `clyde`, and whether Claude Code is there.

Shared by `clyde doctor`, `/doctor`, `clyde update` and `clyde uninstall`, so they all agree on the install method.
Read-only: nothing here changes the machine.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

PACKAGE = "clyde-cli"


@dataclass(frozen=True)
class Install:
    method: str                 # "uv-tool", "pipx", "editable" (a source checkout) or "pip"
    version: str
    location: str               # the Python environment, or the source checkout for "editable"
    commit: str | None = None   # the git commit it was installed from, when pip recorded one


def _direct_url() -> dict:
    try:
        text = metadata.distribution(PACKAGE).read_text("direct_url.json")
        data = json.loads(text) if text else {}
    except (metadata.PackageNotFoundError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def detect() -> Install:
    from src import __version__
    direct = _direct_url()
    commit = (direct.get("vcs_info") or {}).get("commit_id")
    prefix = Path(sys.prefix)
    parts = {p.lower() for p in prefix.parts}
    if (direct.get("dir_info") or {}).get("editable"):
        method, where = "editable", str(direct.get("url", "")).removeprefix("file://")
    elif "uv" in parts and "tools" in parts:
        method, where = "uv-tool", str(prefix)
    elif "pipx" in parts:
        method, where = "pipx", str(prefix)
    else:
        method, where = "pip", str(prefix)
    return Install(method=method, version=__version__, location=where, commit=commit[:7] if commit else None)


def clyde_commands(path: str | None = None) -> list[Path]:
    """Every distinct program called `clyde` on PATH (symlinks resolved), in PATH order."""
    found: dict[Path, Path] = {}
    for folder in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep):
        candidate = Path(folder) / "clyde" if folder else None
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            found.setdefault(candidate.resolve(), candidate)
    return list(found.values())


def claude_code() -> tuple[str, str] | None:
    """(path, version) of Claude Code when `claude` is on PATH; None when it is not there."""
    path = shutil.which("claude")
    if not path:
        return None
    try:
        done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return path, "unknown version"
    lines = done.stdout.strip().splitlines()
    return path, lines[0] if done.returncode == 0 and lines else "unknown version"


def uninstall_command(info: Install) -> list[str] | None:
    """The command that removes this install, or None when Clyde does not manage it (a source checkout)."""
    return {
        "uv-tool": ["uv", "tool", "uninstall", PACKAGE],
        "pipx": ["pipx", "uninstall", PACKAGE],
        "pip": [sys.executable, "-m", "pip", "uninstall", "-y", PACKAGE],
    }.get(info.method)


def purge_target() -> Path | None:
    """Clyde's own data folder (config, keys, sessions, licence record), or None when the path looks wrong enough that
    deleting it could hit something else: it must be called `.clyde` or `clyde`, exist, and not be the home folder."""
    from src.config import clyde_home
    folder = clyde_home().resolve()
    if folder.name not in (".clyde", "clyde") or folder == Path.home().resolve() or not folder.is_dir():
        return None
    return folder


def _check(ok: bool, text: str, hint: str = "") -> str:
    return f"  {'✓' if ok else '✗'} {text}" + (f" — {hint}" if hint and not ok else "")


def report_lines() -> list[str]:
    """The install section of `clyde doctor` and `/doctor`."""
    from src import license_gate
    info = detect()
    lines = [_check(True, f"ClydeCLI {info.version} installed with {info.method}"
                    + (f" from commit {info.commit}" if info.commit else "") + f" ({info.location})")]
    commands = clyde_commands()
    if not commands:
        lines.append(_check(False, "no `clyde` on PATH", "run `uv tool update-shell` and open a new terminal"))
    elif len(commands) > 1:
        lines.append(_check(False, "several programs answer to `clyde`: " + "; ".join(str(c) for c in commands),
                            "keep one and remove the others, so the version you update is the one you run"))
    else:
        lines.append(_check(True, f"`clyde` on PATH: {commands[0]}"))
    claude = claude_code()
    lines.append(_check(True, f"Claude Code: {claude[1]} at {claude[0]} (`clyde hooks import`, `clyde mcp import` and "
                        "`clyde plugin import` can bring its setup over)" if claude else "Claude Code: not found"))
    lines.append(_check(license_gate.is_accepted(), "Licence accepted on this machine", "run `clyde license accept`"))
    return lines
