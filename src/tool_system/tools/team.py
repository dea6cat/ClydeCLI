"""TeamCreate / TeamDelete: run several sub-agents side by side.

TeamCreate starts each member (a name, a prompt, an optional agent type) as a background sub-agent
(see agent.py) and returns their task ids; TaskOutput collects each member's result (block: true waits)
and TeamDelete stops the ones still running. One team at a time.
"""
from __future__ import annotations

from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolRegistry, ToolSpec
from .agent import agent_types, start_background

MAX_MEMBERS = 8


class TeamCreateTool:
    def __init__(self, registry: ToolRegistry | None = None):
        self._registry = registry

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="TeamCreate",
            description=("Start a team: several sub-agents working in parallel, each on its own prompt. Returns their "
                         "task ids at once; use TaskOutput (block: true waits) to collect each member's answer and "
                         f"TeamDelete to stop the rest. At most {MAX_MEMBERS} members."),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "team_name": {"type": "string"},
                    "description": {"type": "string"},
                    "members": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "prompt": {"type": "string"},
                                "subagent_type": {"type": "string"},
                            },
                            "required": ["name", "prompt"],
                        },
                    },
                },
                "required": ["team_name", "members"],
            },
            is_destructive=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        team_name = tool_input.get("team_name")
        members = tool_input.get("members")
        if not isinstance(team_name, str) or not team_name.strip():
            raise ToolInputError("team_name must be a non-empty string")
        if not isinstance(members, list) or not members:
            raise ToolInputError("members must list at least one {name, prompt}")
        if len(members) > MAX_MEMBERS:
            raise ToolInputError(f"at most {MAX_MEMBERS} members")
        if context.team is not None:
            raise ToolInputError(f"team '{context.team['team_name']}' is still active; TeamDelete it first")
        if self._registry is None or context.provider is None or not context.model:
            return ToolResult(name="TeamCreate", output={"error": "no provider available to run a team"}, is_error=True)
        types = agent_types(context.workspace_root)
        for m in members:
            if not isinstance(m, dict) or not str(m.get("name", "")).strip() or not str(m.get("prompt", "")).strip():
                raise ToolInputError("each member needs a name and a prompt")
            if (m.get("subagent_type") or "general-purpose") not in types:
                raise ToolInputError(f"unknown subagent_type: {m.get('subagent_type')} (available: {', '.join(types)})")
        started = []
        for m in members:
            agent = types[m.get("subagent_type") or "general-purpose"]
            task_id = start_background(self._registry, context, agent, m["prompt"], f"{team_name}/{m['name']}")
            started.append({"name": m["name"], "agent": agent.name, "task_id": task_id})
        context.team = {"team_name": team_name, "description": tool_input.get("description"), "members": started}
        return ToolResult(name="TeamCreate", output={"team_name": team_name, "members": started,
                                                     "hint": "TaskOutput with each task_id (block: true waits) collects the answers"})


class TeamDeleteTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="TeamDelete",
            description="End the current team: stop members still running and report how each one ended.",
            input_schema={"type": "object", "additionalProperties": False, "properties": {}},
            is_destructive=True,
            max_result_size_chars=100_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.team is None:
            return ToolResult(name="TeamDelete", output={"success": False, "message": "No active team"})
        report = []
        for m in context.team.get("members", []):
            stopped = context.task_manager.stop(m["task_id"])
            status = (context.tasks.get(m["task_id"]) or {}).get("status")
            report.append({"name": m["name"], "task_id": m["task_id"], "status": "stopping" if stopped else status})
        name = context.team["team_name"]
        context.team = None
        return ToolResult(name="TeamDelete", output={"success": True, "team_name": name, "members": report})
