from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from ..agent import trace
from .context import ToolContext
from .hooks import run_hooks
from .permission_handler import PermissionResult
from .permission_rules import check_rules, suggest_rule
from .protocol import ToolCall, ToolResult
from .schema_validation import validate_json_schema


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    aliases: tuple[str, ...] = ()
    is_read_only: bool = False
    is_destructive: bool = False
    strict: bool = False
    max_result_size_chars: int = 20_000


class Tool(Protocol):
    def spec(self) -> ToolSpec: ...

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult: ...

    def check_permissions(
        self, tool_input: dict[str, Any], context: ToolContext
    ) -> PermissionResult:
        """Check if this tool has permission to run.

        Args:
            tool_input: The input arguments for the tool.
            context: The tool execution context.

        Returns:
            PermissionResult indicating allow, deny, or ask.
        """
        return PermissionResult.allow()


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: list[Tool] = []
        self._by_name: dict[str, Tool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        spec = tool.spec()
        key = spec.name.lower()
        if key in self._by_name:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._tools.append(tool)
        self._by_name[key] = tool
        for alias in spec.aliases:
            alias_key = alias.lower()
            if alias_key in self._by_name:
                raise ValueError(f"duplicate tool alias: {alias}")
            self._by_name[alias_key] = tool

    def list_specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools]

    def get(self, name: str) -> Tool | None:
        return self._by_name.get(name.lower())

    def dispatch(self, call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self.get(call.name)
        if tool is None:
            return ToolResult(
                name=call.name,
                output={"error": f"unknown tool: {call.name}"},
                is_error=True,
                tool_use_id=call.tool_use_id,
            )
        spec = tool.spec()
        context.ensure_tool_allowed(spec.name)
        validate_json_schema(call.input, spec.input_schema, root_name=spec.name)

        blocked = run_hooks(context.hooks, "PreToolUse", {"tool_name": spec.name, "tool_input": call.input}, context.cwd)
        if blocked is not None:
            trace.record("hook_block", hook="PreToolUse", tool=spec.name, reason=blocked)
            return ToolResult(name=spec.name, output={"error": blocked}, is_error=True, tool_use_id=call.tool_use_id)

        # Saved deny rules block without asking; the tool's own deny wins over saved allow rules.
        ruling = check_rules(spec.name, call.input, context)
        if ruling == "deny":
            return ToolResult(
                name=spec.name,
                output={"error": f"permission denied by a deny rule in settings: {spec.name}"},
                is_error=True,
                tool_use_id=call.tool_use_id,
            )
        permission_result = tool.check_permissions(call.input, context) if hasattr(tool, 'check_permissions') else PermissionResult.allow()
        if ruling == "allow" and permission_result.behavior.value == "ask":
            permission_result = PermissionResult.allow(permission_result.updated_input)
        if permission_result.behavior.value == "deny":
            return ToolResult(
                name=spec.name,
                output={"error": permission_result.message or "permission denied"},
                is_error=True,
                tool_use_id=call.tool_use_id,
            )
        if permission_result.behavior.value == "ask":
            # Need user interaction
            if context.permission_handler is None:
                # No handler available, deny by default
                return ToolResult(
                    name=spec.name,
                    output={"error": permission_result.message or "permission required but no handler available"},
                    is_error=True,
                    tool_use_id=call.tool_use_id,
                )
            # Call the permission handler
            prompt = permission_result.message or f"Tool '{spec.name}' requires permission"
            trace.record("permission_ask", tool=spec.name, message=prompt)
            allowed, _ = context.permission_handler(spec.name, prompt, suggest_rule(spec.name, call.input, context))
            trace.record("permission_answer", tool=spec.name, allowed=allowed)
            if not allowed:
                return ToolResult(
                    name=spec.name,
                    output={"error": "permission denied by user"},
                    is_error=True,
                    tool_use_id=call.tool_use_id,
                )
            # User allowed - proceed with potentially updated input
            if permission_result.updated_input:
                call = ToolCall(
                    name=call.name,
                    input=permission_result.updated_input,
                    tool_use_id=call.tool_use_id,
                )

        result = tool.run(call.input, context)
        feedback = run_hooks(
            context.hooks, "PostToolUse",
            {"tool_name": spec.name, "tool_input": call.input, "tool_response": result.output}, context.cwd,
        )
        if feedback is not None:
            output = result.output if isinstance(result.output, dict) else {"result": result.output}
            result = ToolResult(
                name=result.name, output={**output, "hookFeedback": feedback}, is_error=result.is_error,
                tool_use_id=result.tool_use_id, content_type=result.content_type,
            )
        if result.tool_use_id is None and call.tool_use_id is not None:
            return ToolResult(
                name=result.name,
                output=result.output,
                is_error=result.is_error,
                tool_use_id=call.tool_use_id,
                content_type=result.content_type,
            )
        return result

