from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from ...system import proc
from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionResult
from ..protocol import ToolResult
from ..registry import ToolSpec
from ..shell import DANGEROUS_PATTERNS, is_read_only_command, reaches_outside_project, removes_running_install


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
            path_field="cwd",
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
        if any(pat.search(command) for pat in DANGEROUS_PATTERNS):
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

        for pat in DANGEROUS_PATTERNS:
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
            context.grant_path(next_dir)   # for reading only: run only happens after the ask in check_permissions (reaches_outside_project)
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

