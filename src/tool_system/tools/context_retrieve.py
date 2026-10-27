from __future__ import annotations

from typing import Any

from ...context_system import context_cache
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolSpec


_PAGE = 50_000
_MAX_MATCHES = 100    # blocks of matching lines in one answer
_MAX_CONTEXT = 5      # lines around a match
_LINE_CHARS = 500     # one line is cut here: a minified file is one enormous line


class RetrieveContextTool:
    """The full text of a context section the system prompt cut short (instruction file, README, git status)."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="RetrieveContext",
            description="Read the full text of a context section or tool output that was cut short. Pass the "
                        "ctx:... reference from its RetrieveContext(reference=...) note; long text comes a page at a "
                        "time, with next_offset for the next page. To find something in a big output instead of paging, "
                        "pass contains (a literal text, not a regex) and get the matching lines with their numbers.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"reference": {"type": "string", "description": "The ctx:... reference, as written."},
                               "offset": {"type": "integer", "minimum": 0,
                                          "description": "Character to start from, for text longer than one page."},
                               "contains": {"type": "string", "description": "Return only the lines holding this text (any case), with their line numbers."},
                               "lines": {"type": "integer", "minimum": 0, "maximum": 5,
                                         "description": "With contains: how many lines to show around each match (default 0)."}},
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
        if (needle := tool_input.get("contains")) is not None:
            return ToolResult(name="RetrieveContext", output=_matches(reference.strip(), text, needle, tool_input.get("lines") or 0))
        offset = tool_input.get("offset") or 0
        if not isinstance(offset, int) or offset < 0:
            raise ToolInputError("offset must be a non-negative integer")
        page = text[offset:offset + _PAGE]
        out = {"reference": reference.strip(), "text": page, "total_chars": len(text)}
        if offset + _PAGE < len(text):
            out["next_offset"] = offset + _PAGE   # a saved tool output can be megabytes: read it a page at a time
        return ToolResult(name="RetrieveContext", output=out)


def _matches(reference: str, text: str, needle: Any, around: Any) -> dict[str, Any]:
    """The lines of `text` holding `needle` (any case), each block with `around` lines either side and its first line number; blocks that touch merge."""
    if not isinstance(needle, str) or not needle.strip():
        raise ToolInputError("contains must be the text to look for")
    if not isinstance(around, int) or isinstance(around, bool) or not 0 <= around <= _MAX_CONTEXT:
        raise ToolInputError(f"lines must be an integer from 0 to {_MAX_CONTEXT}")
    lines, low = text.splitlines(), needle.lower()
    hits = [i for i, line in enumerate(lines) if low in line.lower()]
    blocks: list[list[int]] = []
    for i in hits:
        start, end = max(0, i - around), min(len(lines) - 1, i + around)
        if blocks and start <= blocks[-1][1] + 1:
            blocks[-1][1] = max(blocks[-1][1], end)
        else:
            blocks.append([start, end])
    shown = [{"line": a + 1, "text": "\n".join(ln if len(ln) <= _LINE_CHARS else ln[:_LINE_CHARS] + " …" for ln in lines[a:b + 1])} for a, b in blocks[:_MAX_MATCHES]]
    out: dict[str, Any] = {"reference": reference, "total_chars": len(text), "total_matching_lines": len(hits), "matches": shown}
    if len(blocks) > _MAX_MATCHES:
        out["more"] = f"{len(blocks) - _MAX_MATCHES} more blocks: use a more specific text"
    return out
