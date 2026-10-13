from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..permission_handler import PermissionResult
from ..protocol import ToolResult
from ..plan_file import keep_plans_out_of_git
from ..registry import ToolSpec


class EnterPlanModeTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="EnterPlanMode",
            description="Enter plan mode (exploration/planning phase).",
            input_schema={"type": "object", "additionalProperties": False, "properties": {}},
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        context.plan_mode = True
        return ToolResult(
            name="EnterPlanMode",
            output={
                "message": "Entered plan mode. Explore and design an approach before editing files.",
            },
        )


class ExitPlanModeTool:
    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        """Leaving plan mode lifts "no edits": it needs a yes (headless runs have no one to ask, so they stay in plan mode)."""
        return PermissionResult.ask(message="Leave plan mode and save this plan so edits can begin")

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ExitPlanMode",
            description="Exit plan mode after writing a plan; may persist plan to disk.",
            input_schema={
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "allowedPrompts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tool": {"type": "string", "enum": ["Bash"]},
                                "prompt": {"type": "string"},
                            },
                            "required": ["tool", "prompt"],
                        },
                    },
                    "plan": {"type": "string"},
                    "planFilePath": {"type": "string"},
                },
            },
            is_destructive=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if not context.plan_mode:
            raise ToolPermissionError("not in plan mode")

        plan = tool_input.get("plan")
        if plan is not None and not isinstance(plan, str):
            raise ToolInputError("plan must be a string when provided")
        plan_path = tool_input.get("planFilePath")
        if plan_path is not None and not isinstance(plan_path, str):
            raise ToolInputError("planFilePath must be a string when provided")

        file_path_out: str | None = None
        if plan is not None:
            # The plan goes to this session's plan file and nowhere else: a model-chosen path would be a write
            # that skips the Write/Edit gates (a hook, a skill, a build script).
            own = context.plan_file or context.workspace_root / ".clyde" / "plan.md"
            if plan_path:
                requested = Path(plan_path).expanduser()
                if not requested.is_absolute():
                    requested = (context.cwd or context.workspace_root) / requested
                if requested.resolve() != Path(own).resolve():
                    raise ToolInputError("planFilePath must be this session's plan file; leave it out to use that file")
            target = Path(own)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(plan, encoding="utf-8")
            file_path_out = str(target)
            if context.plan_file is not None and target == context.plan_file:
                keep_plans_out_of_git(context.workspace_root)

        context.plan_mode = False
        out: dict[str, Any] = {
            "plan": plan if plan is not None else None,
            "isAgent": False,
            "filePath": file_path_out,
            "hasTaskTool": True,
            "planWasEdited": False,
            "requestId": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        }
        return ToolResult(name="ExitPlanMode", output=out)

