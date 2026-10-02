"""Agent: hand a self-contained task to a sub-agent with a fresh conversation.

Sub-agents come in types: `general-purpose` (every tool), or a custom one defined in Markdown (see
src/agent/agent_types.py) with its own instructions, an optional tool allow-list and model. A
sub-agent runs in the foreground and returns its final answer, or in the background
(run_in_background) and returns a task id at once: TaskOutput reads the result (block waits for it)
and TaskStop cancels it. Nobody can answer a background agent's permission prompt mid-turn, so
anything that would ask is denied. Sub-agents can't start agents or teams of their own.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolRegistry, ToolSpec

_SUBAGENT_MAX_TURNS = 30
_NO_NESTING = {"agent", "teamcreate", "teamdelete"}


def agent_types(root: Path) -> dict:
    from ...agent.agent_types import load
    return load(root)


def _tools_for(registry: ToolRegistry, agent: Any) -> ToolRegistry:
    allowed = {t.lower() for t in agent.tools} if agent.tools else None
    names = [s.name for s in registry.list_specs()
             if s.name.lower() not in _NO_NESTING and (allowed is None or s.name.lower() in allowed)]
    return ToolRegistry([registry.get(n) for n in names])


def _model_for(agent: Any, context: ToolContext) -> tuple[Any, str, str]:
    """(provider, model, note): the agent's own model when it names one that's usable, else the caller's."""
    if agent.model:
        from ...providers import build_registry, keys, resolve
        keys.load_into_env()
        resolved = resolve(build_registry(), agent.model)
        if resolved is not None:
            return resolved[0], resolved[1], ""
        return context.provider, context.model, f"{agent.model} isn't available; used the current model"
    return context.provider, context.model, ""


def run_agent(registry: ToolRegistry, context: ToolContext, agent: Any, prompt: str, *,
              background: bool = False, cancel: Any = None) -> tuple[Any, str]:
    """Run one sub-agent to the end; (AgentLoopResult, note about its model)."""
    from ...agent.agent_loop import run_agent_loop
    from ...agent.conversation import Conversation

    provider, model, note = _model_for(agent, context)
    # Own read tracking and todos: the sub-agent must Read a file itself before it may Edit it.
    sub_context = replace(context, read_file_fingerprints={}, todos=[])
    if background:
        sub_context.permission_handler = lambda *a: (False, False)   # nobody can answer mid-turn
        sub_context.ask_user = None
    conversation = Conversation()
    conversation.add_user_message(prompt)
    result = run_agent_loop(conversation, provider, model, _tools_for(registry, agent), sub_context,
                            max_turns=_SUBAGENT_MAX_TURNS, system_extra=agent.prompt or None, cancel=cancel)
    return result, note


def start_background(registry: ToolRegistry, context: ToolContext, agent: Any, prompt: str, description: str) -> str:
    """Start a sub-agent in the background; its record in context.tasks fills in as it finishes."""
    record: dict[str, Any] = {"status": "running", "description": description, "subject": description,
                              "agent": agent.name, "output": ""}

    def target(stop_event: Any) -> None:
        try:
            result, note = run_agent(registry, context, agent, prompt, background=True, cancel=stop_event)
            record.update(status="stopped" if stop_event.is_set() else "completed",
                          output=result.response_text + (f"\n\n({note})" if note else ""))
        except Exception as e:   # stopped mid-request, or a provider error: the record says which
            record.update(status="stopped" if stop_event.is_set() else "failed", output=f"{type(e).__name__}: {e}")

    task = context.task_manager.start(name=f"agent:{agent.name}", target=target)
    context.tasks[task.task_id] = record
    return task.task_id


class AgentTool:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def spec(self) -> ToolSpec:
        try:
            types = agent_types(Path.cwd())
        except Exception:
            types = {}
        listed = "; ".join(f"{a.name}: {a.description}" for a in types.values()) or "general-purpose"
        return ToolSpec(
            name="Agent",
            description=(
                "Launch a sub-agent with a fresh conversation to handle a self-contained task; it returns only "
                "its final answer. Set run_in_background to get a task id at once and keep working; read the "
                f"result with TaskOutput (block: true waits). Available types: {listed}"
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string", "description": "A short (3-5 word) description of the task"},
                    "prompt": {"type": "string", "description": "The full task for the sub-agent to perform"},
                    "subagent_type": {"type": "string", "description": "An agent type (default general-purpose)"},
                    "run_in_background": {"type": "boolean"},
                },
                "required": ["description", "prompt"],
            },
            aliases=("Task",),
            is_destructive=True,
            max_result_size_chars=200_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        name = tool_input.get("subagent_type") or "general-purpose"
        types = agent_types(context.workspace_root)
        agent = types.get(name)
        if agent is None:
            raise ToolInputError(f"unknown subagent_type: {name} (available: {', '.join(types)})")
        if context.provider is None or not context.model:
            return ToolResult(name="Agent", output={"error": "no provider available to run a sub-agent"}, is_error=True)
        prompt, description = tool_input["prompt"], tool_input.get("description") or name
        if tool_input.get("run_in_background"):
            task_id = start_background(self._registry, context, agent, prompt, description)
            return ToolResult(name="Agent", output={"task_id": task_id, "status": "running", "agent": agent.name,
                                                    "hint": "TaskOutput with this task_id (block: true waits) gets the result"})
        result, note = run_agent(self._registry, context, agent, prompt)
        output = {"content": result.response_text, "usage": result.usage, "num_turns": result.num_turns, "agent": agent.name}
        if note:
            output["note"] = note
        return ToolResult(name="Agent", output=output)
