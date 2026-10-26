from __future__ import annotations

from typing import Any

from ...context_system import context_cache
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


class RetrieveContextTool:
    """The full text of a context section the system prompt cut short (instruction file, README, git status)."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="RetrieveContext",
            description="Read the full text of a section your context cut short. Pass the reference from its "
                        '"...[truncated; full text: RetrieveContext(reference=...)]" line.',
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"reference": {"type": "string", "description": "The ctx:... reference, as written."}},
                "required": ["reference"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        reference = tool_input.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise ToolInputError("reference must be a ctx:... string")
        text = context_cache.fetch(reference)
        if text is None:
            return ToolResult(name="RetrieveContext", output={"error": f"no text kept under {reference!r}: unknown, "
                                                                      "or older than 7 days. Read the file itself."},
                              is_error=True)
        return ToolResult(name="RetrieveContext", output={"reference": reference.strip(), "text": text})
