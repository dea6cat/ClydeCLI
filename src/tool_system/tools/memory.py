from __future__ import annotations

from typing import Any

from ...memory import SCOPES, add, entries
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


class RememberTool:
    """Saves one short note that Clyde keeps between sessions (see src/memory.py). Marked destructive on purpose: it changes what every later
    turn is told, so hold mode asks first and plan mode refuses it."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Remember",
            description="Save a short note about the user or this project that is kept between sessions. Use it when the user asks you to remember something.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string", "description": "The note, one short sentence."},
                    "scope": {"type": "string", "enum": list(SCOPES), "description": "user: about the user. project: about this codebase."},
                },
                "required": ["text"],
            },
            is_destructive=True,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        scope = tool_input.get("scope", "user")
        try:
            saved = add(scope, context.workspace_root, tool_input.get("text", ""))
        except ValueError as e:
            raise ToolInputError(str(e)) from e
        return ToolResult(name="Remember", output={"saved": saved, "scope": scope, "notes": len(entries(scope, context.workspace_root))})
