from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .errors import ToolPermissionError
from .permissions import ToolPermissionContext
from .task_manager import TaskManager


@dataclass
class ToolContext:
    workspace_root: Path
    permission_context: ToolPermissionContext = field(default_factory=ToolPermissionContext)
    cwd: Path | None = None
    read_file_fingerprints: dict[Path, tuple[int, int]] = field(default_factory=dict)
    task_manager: TaskManager = field(default_factory=TaskManager)
    mcp_clients: dict[str, Any] = field(default_factory=dict)
    todos: list[dict[str, Any]] = field(default_factory=list)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan_mode: bool = False  # "reading the table": dispatch refuses tools that change things
    auto_approve: bool = False  # "all in": permission asks are approved without prompting (deny rules still apply)
    confirm_edits: bool = False  # "hold": Write, Edit and NotebookEdit ask before every change (the REPL turns this on)
    worktree_root: Path | None = None
    outbox: list[dict[str, Any]] = field(default_factory=list)
    ask_user: Callable[[list[dict[str, Any]]], dict[str, str]] | None = None
    # Called with a file's path right before Write, Edit or NotebookEdit changes it (edit checkpoints).
    before_edit: Callable[[Path], None] | None = None
    crons: dict[str, dict[str, Any]] = field(default_factory=dict)
    team: dict[str, Any] | None = None
    # Deferred tools the model has loaded (lowercase names); see deferral.py. Shared with sub-agents.
    loaded_tools: set[str] = field(default_factory=set)
    output_style_name: str | None = None
    output_style_dir: Path | None = None
    # Set by run_agent_loop so the Agent tool can run a sub-agent on the same model.
    provider: Any | None = None
    model: str | None = None
    # PreToolUse / PostToolUse hook table (see hooks.py); the REPL loads it from settings.
    hooks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Saved allow/deny rules (see permission_rules.py); the REPL loads them from settings.
    # Mutated in place so sub-agents, which get a shallow copy of this context, see new rules.
    permission_rules: dict[str, list[str]] = field(default_factory=lambda: {"allow": [], "deny": []})

    # Permission handler callback: called when a tool needs user consent.
    # Signature: (tool_name: str, message: str, suggestion: str | None)
    #           -> tuple[bool, bool] (allowed: bool, continue_without_caching: bool)
    # `suggestion` is the allow rule a "don't ask again" choice would save, or None.
    # If not set, permission errors will be raised as exceptions.
    permission_handler: Callable[[str, str, Optional[str]], tuple[bool, bool]] | None = None

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root).resolve()
        if self.cwd is None:
            self.cwd = self.workspace_root
        else:
            self.cwd = Path(self.cwd).resolve()
        if self.permission_context.workspace_root is None:
            self.permission_context = ToolPermissionContext.from_iterables(
                self.permission_context.deny_names,
                self.permission_context.deny_prefixes,
                workspace_root=self.workspace_root,
                additional_working_directories=self.permission_context.additional_working_directories,
                allow_docs=self.permission_context.allow_docs,
            )

    def mark_file_read(self, path: Path) -> None:
        stat = path.stat()
        self.read_file_fingerprints[path.resolve()] = (int(stat.st_mtime), int(stat.st_size))

    def was_file_read_and_unchanged(self, path: Path) -> bool:
        resolved = path.resolve()
        fingerprint = self.read_file_fingerprints.get(resolved)
        if fingerprint is None:
            return False
        stat = resolved.stat()
        return fingerprint == (int(stat.st_mtime), int(stat.st_size))

    def ensure_allowed_path(self, path: str | Path) -> Path:
        p = Path(path).expanduser() if isinstance(path, str) else path.expanduser()
        if not p.is_absolute():
            base = self.cwd or self.workspace_root
            p = (base / p).resolve()
        return self.permission_context.ensure_path_allowed(p)

    def ensure_tool_allowed(self, tool_name: str) -> None:
        if self.permission_context.blocks_tool(tool_name):
            raise ToolPermissionError(f"tool is blocked by permission context: {tool_name}")
