from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from src import trace
from .context import ToolContext
from .hooks import run_hooks
from .permission_handler import PermissionBehavior, PermissionResult
from .permission_rules import check_rules, suggest_rule
from .protocol import ToolCall, ToolResult

_WHOLE_FILES = {"image", "pdf", "notebook"}   # Read's encoded files: never cut


def _clip_result(result: ToolResult, limit: int) -> ToolResult:
    """Hold a tool's text output to its declared max_result_size_chars: the head and tail stay, the whole output goes to
    the context cache for RetrieveContext. Before this nothing enforced the limit, and Bash kept only its first 20,000
    characters, so a failing test run lost the error at its end."""
    from src.context_cache import clip

    out = result.output
    if isinstance(out, str):
        clipped: Any = clip(out, limit)
    elif isinstance(out, dict) and out.get("type") not in _WHOLE_FILES:
        clipped = {k: clip(v, limit) if isinstance(v, str) else v for k, v in out.items()}
    else:
        return result
    return result if clipped == out else ToolResult(name=result.name, output=clipped, is_error=result.is_error,
                                                     tool_use_id=result.tool_use_id, content_type=result.content_type)
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
    path_field: str = ""            # the input that names the file or folder it works on
    writes_files: bool = False       # it changes the file at path_field
    reaches_network: bool = False    # what it sends can leave the machine, and what comes back is from outside
    plan_mode_ok: bool = False       # allowed in plan mode although it is destructive (delegating, presenting the plan)


class Tool(Protocol):
    """What every tool provides. A tool may also define the optional hook
    `check_permissions(tool_input, context) -> PermissionResult` (allow, deny or ask); the registry
    calls it when present and treats a tool without it as allowed."""

    def spec(self) -> ToolSpec: ...

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult: ...


def _changes_things(spec: ToolSpec, tool_input: dict[str, Any]) -> bool:
    """Whether a call would modify something, for plan mode ("reading the table")."""
    if spec.plan_mode_ok:
        return False
    if spec.name.lower() == "bash":
        from .shell import is_read_only_command
        return not is_read_only_command(str(tool_input.get("command", "")))
    return spec.is_destructive


def _read_target(spec: ToolSpec, tool_input: dict[str, Any]) -> str:
    """The path a tool that reads one names (Read, Grep, Glob), or "" for any other call."""
    if spec.writes_files or not spec.path_field or spec.name.lower() == "bash":
        return ""
    return str(tool_input.get(spec.path_field) or "")


def _reads_secret(spec: ToolSpec, tool_input: dict[str, Any]) -> bool:
    """A read of a key, .env, .ssh, cloud-credential or Clyde key-store file by any tool that reads a path, or a Bash
    command that names one, expands a secret-looking variable, or searches the whole home folder."""
    from .secret_paths import command_reads_secret, is_secret_path
    name = spec.name.lower()
    if name == "bash":
        return command_reads_secret(str(tool_input.get("command", "")))
    target = _read_target(spec, tool_input)
    return bool(target) and is_secret_path(target)


def _edit_target(spec: ToolSpec, tool_input: dict[str, Any], context: ToolContext):
    """The file a Write, Edit or NotebookEdit call would change, when it is inside the allowed folders (anything
    else is refused by the tool itself, so there is nothing to ask about)."""
    raw = tool_input.get(spec.path_field) if spec.writes_files else None
    if not isinstance(raw, str):
        return None
    try:
        return context.ensure_allowed_path(raw)
    except Exception:
        return None


def _outside_target(spec: ToolSpec, tool_input: dict[str, Any], context: ToolContext):
    """The file or folder this call names when it is outside the project and the user has not approved it yet."""
    raw = tool_input.get(spec.path_field) if spec.path_field else None
    return context.outside_path(raw, write=spec.writes_files) if isinstance(raw, str) and raw else None


def _shown(path, context: ToolContext) -> str:
    try:
        return str(path.relative_to(Path(context.workspace_root).resolve()))
    except ValueError:
        return str(path)


def _is_major(spec: ToolSpec, tool_input: dict[str, Any], context: ToolContext) -> bool:
    """What "all in" mode still asks about: hard to undo, outside the project, or touching secrets."""
    name = spec.name.lower()
    if name == "bash":
        from .shell import is_major_command, is_read_only_command, reaches_outside_project
        # Changing something outside the project is always worth a yes, even when everything else plays without asking. Only
        # looking (ls, find, cat) is let through: asking for every one made all-in ask a dozen times for a search of the home folder.
        command = str(tool_input.get("command", ""))
        outside = reaches_outside_project(command, context, tool_input.get("cwd")) and not is_read_only_command(command)
        return is_major_command(command) or outside or _reads_secret(spec, tool_input)
    path = tool_input.get(spec.path_field) if spec.path_field else None
    if isinstance(path, str) and path:
        from pathlib import Path
        target = Path(path).expanduser().resolve()
        from .secret_paths import is_secret_path
        if context.outside_path(path, write=spec.writes_files) is not None:
            return True
        try:
            inside = target.relative_to(context.workspace_root)
        except ValueError:
            return is_secret_path(target.as_posix())   # outside, but the user approved it this session
        # Git runs a repository's config and hooks as the user: writing them is never routine.
        if ".git" in inside.parts[:-1] or target.name == ".git":
            return True
        return is_secret_path(target.as_posix())
    return False


def _sends_out(spec: ToolSpec, tool_input: dict[str, Any]) -> bool:
    """Whether this call can carry data off the machine: the web and MCP tools, and any Bash command that is not read-only
    (curl, git push, ssh and dig all count as not read-only)."""
    if spec.name.lower() == "bash":
        from .shell import is_read_only_command
        return not is_read_only_command(str(tool_input.get("command", "")))
    return spec.reaches_network


def _clip_input(tool_input: dict[str, Any], limit: int = 300) -> str:
    import json

    text = json.dumps(tool_input, ensure_ascii=False)
    return text if len(text) <= limit else f"{text[:limit]}… (+{len(text) - limit} more characters)"


@dataclass(frozen=True)
class _Concern:
    """One reason a call needs the user's yes, and what may answer it instead: a saved allow rule, or "all in" mode
    (which never answers for a major call: hard to undo, outside the project, or touching secrets)."""
    message: str
    by_rule: bool = True
    by_auto: bool = True
    offer_rule: bool = True   # whether "don't ask again" may save an allow rule for it


def _concerns(spec: ToolSpec, tool_input: dict[str, Any], context: ToolContext, own: PermissionResult, ruling: str | None) -> list[_Concern]:
    """Everything about this call that wants a yes, the tool's own question first."""
    found: list[_Concern] = []
    if own.behavior is PermissionBehavior.ASK:
        found.append(_Concern(own.message or f"Tool '{spec.name}' requires permission"))
    if _reads_secret(spec, tool_input):
        found.append(_Concern(f"{spec.name} wants to read a secret file: {_read_target(spec, tool_input)}"))
    outside = _outside_target(spec, tool_input, context)
    if outside is not None:
        what = "change a file" if spec.writes_files else "use a folder" if spec.name.lower() == "bash" else "read"
        found.append(_Concern(f"{spec.name} wants to {what} outside the project: {outside}"))
    target = _edit_target(spec, tool_input, context) if context.confirm_edits else None
    if target is not None:
        found.append(_Concern(f"{spec.name} wants to change {_shown(target, context)}"))   # hold mode
    if ruling == "ask":
        found.append(_Concern(f"{spec.name}: an ask rule in settings wants your yes", by_rule=False, by_auto=False))
    if context.injection_sources and _sends_out(spec, tool_input):
        # An outside result already tried to steer the model: what this sends out could carry the session's data.
        found.append(_Concern("", by_rule=False, by_auto=False, offer_rule=False))
    return found


def _taint_message(spec: ToolSpec, tool_input: dict[str, Any], context: ToolContext, left: list[_Concern]) -> str:
    what = next((c.message for c in left if c.message), f"{spec.name} {_clip_input(tool_input)}")
    return (f"{what}\n(Asking because {context.injection_sources[-1]} returned text addressed to the model this session. "
            "Check this sends nothing of yours.)")


def _mcp_alias(spec: ToolSpec, tool_input: dict[str, Any]) -> str | None:
    """The mcp__<server>__<tool> name a generic MCP call is really for, so a deny written for that name also stops this route.
    The resource tools get a name under the server's prefix, so a server-wide deny covers them too."""
    server, tool = tool_input.get("server"), tool_input.get("tool")
    if not isinstance(server, str) or not server:
        return None
    from .mcp_client import exposed_name

    if spec.name == "MCP" and isinstance(tool, str) and tool:
        return exposed_name(server, tool)
    if spec.name in ("ReadMcpResourceTool", "ListMcpResourcesTool"):
        return exposed_name(server, "resources")
    return None


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
        alias = _mcp_alias(spec, call.input)
        if alias is not None:
            context.ensure_tool_allowed(alias)
        validate_json_schema(call.input, spec.input_schema, root_name=spec.name)

        blocked = run_hooks(context.hooks, "PreToolUse", {"tool_name": spec.name, "tool_input": call.input}, context.cwd)
        if blocked is not None:
            trace.record("hook_block", hook="PreToolUse", tool=spec.name, reason=blocked)
            return ToolResult(name=spec.name, output={"error": blocked}, is_error=True, tool_use_id=call.tool_use_id)

        if context.plan_mode and _changes_things(spec, call.input):
            return ToolResult(
                name=spec.name,
                output={"error": f"Reading the table (plan mode): {spec.name} would change things. Investigate with "
                                 "read-only tools, then present your plan with ExitPlanMode."},
                is_error=True,
                tool_use_id=call.tool_use_id,
            )

        # Saved deny rules block without asking; the tool's own deny wins over saved allow rules.
        ruling = check_rules(spec.name, call.input, context)
        if alias is not None and check_rules(alias, call.input, context) == "deny":
            ruling = "deny"
        if ruling == "deny":
            return ToolResult(
                name=spec.name,
                output={"error": f"permission denied by a deny rule in settings: {spec.name}"},
                is_error=True,
                tool_use_id=call.tool_use_id,
            )
        check = getattr(tool, "check_permissions", None)   # optional hook (see Tool)
        own = check(call.input, context) if check is not None else PermissionResult.allow()
        outside = _outside_target(spec, call.input, context)   # granted below once the call goes ahead
        tainted = False
        if own.behavior is PermissionBehavior.DENY:
            permission_result = own
        else:
            concerns = _concerns(spec, call.input, context, own, ruling)
            tainted = any(not c.offer_rule for c in concerns)
            major = _is_major(spec, call.input, context)
            left = [c for c in concerns if not (ruling == "allow" and c.by_rule) and not (context.auto_approve and c.by_auto and not major)]
            if not left:
                if concerns and ruling != "allow":
                    trace.record("permission_auto", tool=spec.name, message=concerns[0].message)
                permission_result = PermissionResult.allow(own.updated_input)
            else:
                message = left[0].message if not tainted else _taint_message(spec, call.input, context, left)
                permission_result = PermissionResult.ask(message)
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
            allowed, _ = context.permission_handler(spec.name, prompt, None if tainted else suggest_rule(spec.name, call.input, context))
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

        if outside is not None:
            context.grant_path(outside, write=spec.writes_files)   # asked and answered yes (or a saved allow rule): the tool's own path check lets it through
        raw_path = call.input.get(spec.path_field) if spec.writes_files else None
        if context.before_edit is not None and isinstance(raw_path, str):
            try:
                context.before_edit(context.ensure_allowed_path(raw_path, write=True))
            except Exception:   # a checkpoint must never stop the edit; the tool reports bad paths itself
                pass
        result = tool.run(call.input, context)
        result = _clip_result(result, spec.max_result_size_chars)
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

