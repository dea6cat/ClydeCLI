from __future__ import annotations

from typing import Any

from ...context_system import context_cache
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


_PAGE = 50_000


class RetrieveContextTool:
    """The full text of a context section the system prompt cut short (instruction file, README, git status)."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="RetrieveContext",
            description="Read the full text of a context section or tool output that was cut short. Pass the "
                        "ctx:... reference from its RetrieveContext(reference=...) note; long text comes a page at a "
                        "time, with next_offset for the next page.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"reference": {"type": "string", "description": "The ctx:... reference, as written."},
                               "offset": {"type": "integer", "minimum": 0,
                                          "description": "Character to start from, for text longer than one page."}},
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
        offset = tool_input.get("offset") or 0
        if not isinstance(offset, int) or offset < 0:
            raise ToolInputError("offset must be a non-negative integer")
        page = text[offset:offset + _PAGE]
        out = {"reference": reference.strip(), "text": page, "total_chars": len(text)}
        if offset + _PAGE < len(text):
            out["next_offset"] = offset + _PAGE   # a saved tool output can be megabytes: read it a page at a time
        return ToolResult(name="RetrieveContext", output=out)
