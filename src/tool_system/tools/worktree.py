from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..protocol import ToolResult
from ..registry import ToolSpec


_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def _git(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise ToolInputError("git is not installed") from exc
    if completed.returncode != 0:
        raise ToolInputError(completed.stderr.strip() or f"git {args[0]} failed")
    return completed.stdout.strip()


class EnterWorktreeTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="EnterWorktree",
            description="Create a git worktree on a new branch under .clyde/worktrees and switch the session into it.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"name": {"type": "string"}},
            },
            is_destructive=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.worktree_root is not None:
            raise ToolPermissionError("already in a worktree session")
        name = tool_input.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ToolInputError("name must be a non-empty string when provided")
            if len(name) > 64 or not _NAME_RE.match(name):
                raise ToolInputError("invalid worktree name")
            slug = name
        else:
            slug = "worktree"

        repo = Path(_git(context.workspace_root, "rev-parse", "--show-toplevel"))
        root = repo / ".clyde" / "worktrees" / slug
        branch = "worktree-" + slug.replace("/", "-")
        if not root.exists():
            _git(repo, "worktree", "add", "-b", branch, str(root), "HEAD")
        elif (root / ".git").is_file():
            branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        else:
            raise ToolInputError(f"{root} exists but is not a git worktree")
        context.worktree_root = root
        context.cwd = root
        return ToolResult(
            name="EnterWorktree",
            output={
                "worktreePath": str(root),
                "worktreeBranch": branch,
                "message": f"Worktree at {root} on branch {branch}. The session is now working in the worktree.",
            },
        )


class ExitWorktreeTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ExitWorktree",
            description=(
                "Exit the current worktree session and return to the original workspace. "
                "action 'remove' deletes the worktree (refused if it has uncommitted changes); its branch is kept."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"action": {"type": "string", "enum": ["keep", "remove"]}},
            },
            is_destructive=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.worktree_root is None:
            raise ToolPermissionError("not in a worktree session")
        action = tool_input.get("action", "keep")
        if action not in ("keep", "remove"):
            raise ToolInputError("action must be 'keep' or 'remove'")
        old = context.worktree_root
        if action == "remove":
            _git(context.workspace_root, "worktree", "remove", str(old))
        context.worktree_root = None
        context.cwd = context.workspace_root
        verb = "Removed" if action == "remove" else "Exited"
        return ToolResult(
            name="ExitWorktree",
            output={"message": f"{verb} worktree session ({old}). Returned to {context.workspace_root}."},
        )

