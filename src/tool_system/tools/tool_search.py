from __future__ import annotations

from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..deferral import hint, is_deferred
from ..registry import ToolRegistry, ToolSpec


class ToolSearchTool:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="ToolSearch",
            description=("Find tools by name or keywords and load the ones that aren't loaded yet. Use `select:Name` "
                         "(or `select:A,B`) for exact names; loaded tools are ready on your next step."),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
            is_read_only=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        query = tool_input.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolInputError("query must be a non-empty string")
        max_results = tool_input.get("max_results", 5)
        if not isinstance(max_results, int) or max_results < 1 or max_results > 50:
            raise ToolInputError("max_results must be an integer between 1 and 50")

        q = query.strip()
        lowered = q.lower()
        if lowered.startswith("select:"):
            wanted = [n.strip() for n in q.split(":", 1)[1].split(",") if n.strip()]
            found = [tool.spec() for name in wanted if (tool := self._registry.get(name))]
            missing = [n for n in wanted if self._registry.get(n) is None]
            return self._result(query, found, context, missing)

        scored: list[tuple[int, ToolSpec]] = []
        for spec in self._registry.list_specs():
            hay = f"{spec.name}\n{spec.description}".lower()
            if lowered in spec.name.lower():
                scored.append((0, spec))
            elif lowered in hay:
                scored.append((1, spec))
        scored.sort(key=lambda t: (t[0], t[1].name.lower()))
        return self._result(query, [spec for _, spec in scored[:max_results]], context, [])

    def _result(self, query: str, found: list[ToolSpec], context: ToolContext, missing: list[str]) -> ToolResult:
        """The matches, with the deferred ones loaded so the model's next request carries their definitions."""
        loaded = [s.name for s in found if is_deferred(s.name)]
        context.loaded_tools.update(name.lower() for name in loaded)
        output: dict[str, Any] = {
            "matches": [s.name for s in found], "query": query, "loaded": loaded,
            "details": {s.name: hint(s) for s in found},
            "total_deferred_tools": sum(1 for s in self._registry.list_specs() if is_deferred(s.name)),
        }
        if missing:
            output["not_found"] = missing
        return ToolResult(name="ToolSearch", output=output)
