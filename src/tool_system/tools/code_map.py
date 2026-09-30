"""Map: a structural map of the repo (symbols, calls, imports) as a tool any model can call.

The map is built by graphify (`uv tool install graphifyy`) from the code's syntax tree with no LLM,
into graphify-out/graph.json. This tool runs its deterministic queries: what relates to a question,
how two symbols connect, what a symbol is, and what a change to it would affect.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec

INSTALL_HINT = "the code map needs graphify: run `uv tool install graphifyy` (or `pip install graphifyy`)"
MAP_FILE = Path("graphify-out") / "graph.json"
TIMEOUT = 120
_MAX_CHARS = 20_000

# action -> (required fields, graphify argv builder)
_ACTIONS = {
    "query": (("question",), lambda i: ["query", i["question"], "--budget", str(i.get("budget", 2000))]),
    "path": (("source", "target"), lambda i: ["path", i["source"], i["target"]]),
    "explain": (("target",), lambda i: ["explain", i["target"]]),
    "affected": (("target",), lambda i: ["affected", i["target"], "--depth", str(i.get("depth", 2))]),
    "god_nodes": ((), lambda i: ["god-nodes", "--top", str(i.get("top", 10))]),
}


def map_path(root: Path) -> Path:
    return root / MAP_FILE


def refresh_map(root: Path, timeout: float = 600) -> str:
    """Rebuild the code map from source (syntax tree only, incremental); return the builder's summary line."""
    exe = shutil.which("graphify")
    if exe is None:
        raise ToolInputError(INSTALL_HINT)
    done = subprocess.run([exe, "update", "."], cwd=root, capture_output=True, text=True, timeout=timeout)
    lines = (done.stdout + done.stderr).strip().splitlines()
    if done.returncode != 0:
        raise ToolInputError("updating the code map failed: " + (lines[-1] if lines else f"exit {done.returncode}"))
    return lines[-2] if len(lines) > 1 else (lines[-1] if lines else "map updated")


class MapTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Map",
            description=(
                "Query this repository's code map (symbols, calls, imports, clusters) instead of "
                "grepping blindly. Actions: query (what relates to a question), path (how source reaches target), "
                "explain (a symbol and its neighbours), affected (what depends on target, for impact before "
                "an edit), god_nodes (the most connected hubs), update (rebuild after large edits). Results cite "
                "file and line; read the file before relying on a detail."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": [*_ACTIONS, "update"]},
                    "question": {"type": "string"},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 6},
                    "top": {"type": "integer", "minimum": 1, "maximum": 50},
                    "budget": {"type": "integer", "minimum": 200, "maximum": 8000},
                },
                "required": ["action"],
            },
            is_read_only=True,
            max_result_size_chars=_MAX_CHARS,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = tool_input["action"]
        root = context.workspace_root
        if action == "update":
            return ToolResult(name="Map", output=refresh_map(root), content_type="text")
        required, argv = _ACTIONS[action]
        missing = [f for f in required if not str(tool_input.get(f, "")).strip()]
        if missing:
            raise ToolInputError(f"{action} needs: {', '.join(missing)}")
        exe = shutil.which("graphify")
        if exe is None:
            raise ToolInputError(INSTALL_HINT)
        if not map_path(root).exists():
            refresh_map(root)
        done = subprocess.run([exe, *argv(tool_input), "--graph", str(map_path(root))], cwd=root,
                              capture_output=True, text=True, timeout=TIMEOUT)
        out = (done.stdout or done.stderr).strip() or "(no result)"
        return ToolResult(name="Map", output=out[:_MAX_CHARS], is_error=done.returncode != 0, content_type="text")


def _exclude_from_git(root: Path, pattern: str) -> None:
    """Keep graphify-out/ out of `git status` without touching the tracked .gitignore."""
    try:
        rel = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=root,
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return
    if not rel:
        return
    exclude = (root / rel).resolve()
    try:
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if pattern not in current.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(current + ("" if current.endswith("\n") or not current else "\n") + pattern + "\n", encoding="utf-8")
    except OSError:
        pass


def start_background_refresh(root: Path) -> threading.Thread | None:
    """Refresh the repo's code map off the main thread when graphify is installed (opt out: CLYDE_MAP=off)."""
    # ponytail: rebuilds the whole-repo map each session start; incremental in graphify, but huge monorepos may want a size cap
    if os.environ.get("CLYDE_MAP", "").lower() == "off" or shutil.which("graphify") is None:
        return None
    if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True).returncode != 0:
        return None
    _exclude_from_git(root, "graphify-out/")

    def _refresh() -> None:
        try:
            refresh_map(root)
        except (ToolInputError, OSError, subprocess.TimeoutExpired):
            pass  # the Map tool reports the problem if the model actually asks

    thread = threading.Thread(target=_refresh, daemon=True, name="code-map-refresh")
    thread.start()
    return thread
