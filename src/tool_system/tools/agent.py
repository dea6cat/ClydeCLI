from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolRegistry, ToolSpec

_SUBAGENT_MAX_TURNS = 30


class AgentTool:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Agent",
            description=(
                "Launch a sub-agent with a fresh conversation to handle a self-contained task. "
                "It has the same tools (except Agent) and returns only its final answer."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string", "description": "A short (3-5 word) description of the task"},
                    "prompt": {"type": "string", "description": "The full task for the sub-agent to perform"},
                    "subagent_type": {"type": "string", "description": "Only 'general-purpose' is available"},
                },
                "required": ["description", "prompt"],
            },
            aliases=("Task",),
            is_destructive=True,
            max_result_size_chars=200_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        from ...agent.conversation import Conversation
        from ...agent.agent_loop import run_agent_loop

        subagent_type = tool_input.get("subagent_type") or "general-purpose"
        if subagent_type != "general-purpose":
            raise ToolInputError(f"unknown subagent_type: {subagent_type} (only 'general-purpose' is available)")
        if context.provider is None or not context.model:
            return ToolResult(name="Agent", output={"error": "no provider available to run a sub-agent"}, is_error=True)

        # Everything but Agent itself, so a sub-agent cannot spawn more sub-agents.
        tools = [self._registry.get(s.name) for s in self._registry.list_specs() if s.name != "Agent"]
        # Own read tracking and todos: the sub-agent must Read a file itself before it may Edit it.
        sub_context = replace(context, read_file_fingerprints={}, todos=[])
        conversation = Conversation()
        conversation.add_user_message(tool_input["prompt"])
        result = run_agent_loop(conversation, context.provider, context.model, ToolRegistry(tools),
                                sub_context, max_turns=_SUBAGENT_MAX_TURNS)
        return ToolResult(
            name="Agent",
            output={"content": result.response_text, "usage": result.usage, "num_turns": result.num_turns},
        )
