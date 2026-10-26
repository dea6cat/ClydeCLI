"""tmux panes for a run: one window with the live station on top and a pane for each team member.

A pane is a view, not a second copy of the work: it runs `clyde station watch <run> --who <name>`, which streams that
member's recorded events, so what a pane shows is what the run recorded. The workers themselves keep running as
subprocesses of the run, so closing the window stops nothing. The window stays after the run ends
(`remain-on-exit`), so the last lines can be read.

Inside tmux the window joins your session; outside it, a detached session is made and the attach command is printed.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from src.agent.runs import Run


def tmux_path() -> str | None:
    return shutil.which("tmux")


def _clyde() -> list[str]:
    found = shutil.which("clyde")
    return [found] if found else [sys.executable, "-m", "src.cli"]


def pane_commands(run: Run) -> list[tuple[str, str]]:
    """(title, shell command) for each pane: the live overview, then the advisor and each worker."""
    clyde = _clyde()
    roles = run.state().get("roles") or {}
    members = (["advisor"] if roles.get("advisor") else []) + [w["name"] for w in roles.get("workers", [])]
    panes = [("overview", shlex.join([*clyde, "station", "show", run.id]))]
    panes += [(name, shlex.join([*clyde, "station", "watch", run.id, "--who", name])) for name in members]
    return panes


def _tmux(tmux: str, *args: str) -> str:
    done = subprocess.run([tmux, *args], capture_output=True, text=True, timeout=30, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"tmux {args[0]} failed")
    return done.stdout.strip()


def open_panes(run: Run, tmux: str | None = None) -> str:
    """Open the run's panes; the message says where they are (or why they could not be opened)."""
    tmux = tmux or tmux_path()
    if not tmux:
        return "tmux is not installed, so there are no panes. `clyde station` shows the run in this terminal."
    panes = pane_commands(run)
    name = f"clyde-{run.id}"
    try:
        if os.environ.get("TMUX"):
            target = _tmux(tmux, "new-window", "-d", "-P", "-F", "#{window_id}", "-n", name[:24], panes[0][1])
            where = f"a new window ({name[:24]}) in this tmux session; Ctrl-b n and Ctrl-b p switch windows"
        else:
            _tmux(tmux, "new-session", "-d", "-s", name, "-n", "run", "-x", "200", "-y", "50", panes[0][1])
            target = f"{name}:run"
            where = f"a detached tmux session; attach with: tmux attach -t {name}"
        _tmux(tmux, "set-option", "-w", "-t", target, "remain-on-exit", "on")
        for _title, command in panes[1:]:
            _tmux(tmux, "split-window", "-d", "-t", target, command)
            _tmux(tmux, "select-layout", "-t", target, "tiled")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        return f"Could not open the tmux panes: {e}"
    return f"{len(panes)} panes in {where}."
