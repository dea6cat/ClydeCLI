"""An OS sandbox around the model's shell commands: they can read anything and use the network, but
write only inside the project (and extra working directories), temp folders and package caches.

macOS runs the command under `sandbox-exec` with a write-restricting profile; Linux under `bwrap`
(bubblewrap) when it's installed, with the filesystem read-only except those folders. Elsewhere the
command runs unsandboxed and /doctor says so. A command that has to write elsewhere (a global
install) can ask to run unsandboxed; that always asks the user first.

Settings, under "sandbox" in ~/.clyde/settings.json:
    {"sandbox": {"enabled": true, "network": true, "allow_write": ["~/.local/bin"]}}
"""
from __future__ import annotations

from src.config import clyde_home

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

# Folders tools write to on their own: package caches. Writable when they exist.
_CACHES = ("~/.cache", "~/Library/Caches", "~/.npm", "~/.pnpm-store", "~/.yarn", "~/.bun/install/cache",
           "~/.cargo/registry", "~/.cargo/git", "~/.gradle", "~/.m2/repository", "~/.pub-cache",
           "~/.dartServer", "~/go/pkg/mod")
BLOCKED_HINT = ("The sandbox blocked a write outside the project. If the command really needs it, run it again "
                "with unsandboxed: true; that asks the user first.")


def settings() -> dict[str, Any]:
    try:
        data = json.loads((clyde_home() / "settings.json").read_text(encoding="utf-8")).get("sandbox", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


def engine() -> str | None:
    """sandbox-exec, bwrap, or None when this system has neither (or the sandbox is turned off)."""
    if settings().get("enabled") is False:
        return None
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bwrap"
    return None


def writable(context: Any) -> list[Path]:
    """Every folder sandboxed commands may write to, resolved (macOS's /tmp is /private/tmp)."""
    extra = getattr(getattr(context, "permission_context", None), "additional_working_directories", ()) or ()
    temp = {tempfile.gettempdir(), "/tmp", os.environ.get("TMPDIR", "")} | ({"/private/var/folders"} if sys.platform == "darwin" else set())
    configured = settings().get("allow_write") or []
    candidates = [context.workspace_root, *extra, *temp, *_CACHES, *(configured if isinstance(configured, list) else [])]
    out: list[Path] = []
    for raw in candidates:
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if path.exists():
            resolved = path.resolve()
            if resolved not in out:
                out.append(resolved)
    return out


def _sbpl(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def macos_profile(paths: list[Path], network: bool) -> str:
    allow = " ".join(f"(subpath {_sbpl(str(p))})" for p in paths)
    rules = ["(version 1)", "(allow default)", "(deny file-write*)",
             f'(allow file-write* {allow} (subpath "/dev"))']
    if not network:
        rules += ["(deny network*)", '(allow network* (local ip "localhost:*") (remote ip "localhost:*") (remote unix-socket))']
    return "".join(rules)


def bwrap_args(paths: list[Path], network: bool) -> list[str]:
    args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--die-with-parent"]
    for p in paths:
        args += ["--bind", str(p), str(p)]
    return args + ([] if network else ["--unshare-net"]) + ["--"]


def wrap(argv: list[str], context: Any) -> tuple[list[str], bool]:
    """(the argv to run, whether it's sandboxed)."""
    kind = engine()
    if kind is None:
        return argv, False
    network = settings().get("network", True) is not False
    paths = writable(context)
    if kind == "sandbox-exec":
        return ["sandbox-exec", "-p", macos_profile(paths, network), *argv], True
    return [*bwrap_args(paths, network), *argv], True


def describe() -> str:
    """One line for /doctor."""
    kind = engine()
    if kind is None:
        return "off (turned off in settings)" if settings().get("enabled") is False else \
            "unavailable on this system: shell commands run unsandboxed (Linux: install bubblewrap)"
    network = "network allowed" if settings().get("network", True) is not False else "network blocked"
    return f"on ({kind}): shell commands write only to the project, temp and package caches; {network}"
