"""Agent loop for multi-turn tool calling."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..tool_system.checks import edit_check_for
from . import trace
from ..tool_system.registry import ToolRegistry
from ..tool_system.context import ToolContext
from ..tool_system.deferral import advertised, index_prompt, is_deferred
from .conversation import Conversation
from ..context_system import build_context_prompt
from ..output_styles import resolve_output_style
from ..providers.base import Provider, stream_with_retry
from ..providers.convert import append_response, to_canonical
from ..providers.toolcall_repair import coerce_tool_args
from ..providers.toolspec import from_specs


def summarize_tool_result(name: str, output: Any) -> str:
    """Create a concise, single-line summary for tool result output."""
    if not isinstance(output, dict):
        return str(output)
    if name.lower() == "write":
        path = output.get("filePath") or output.get("file_path")
        op = output.get("type")
        return f"{name} · {path} · {op}"
    if name.lower() == "edit":
        path = output.get("filePath") or output.get("file_path")
        replace_all = output.get("replaceAll")
        return f"{name} · {path} · replaceAll={replace_all}"
    if name.lower() == "read":
        if output.get("type") == "text" and isinstance(output.get("file"), dict):
            f = output["file"]
            path = f.get("filePath")
            num = f.get("numLines")
            total = f.get("totalLines")
            start = f.get("startLine")
            return f"{name} · {path} · lines={start}-{(start or 1) + (num or 0) - 1}/{total}"
        if output.get("type") == "file_unchanged" and isinstance(output.get("file"), dict):
            return f"{name} · {output['file'].get('filePath')} · unchanged"
        if output.get("type") in {"image", "pdf", "notebook"} and isinstance(output.get("file"), dict):
            return f"{name} · {output['file'].get('filePath')} · {output.get('type')}"
        return f"{name}"
    if name.lower() == "glob":
        n = output.get("numFiles")
        return f"{name} · matches={n}"
    if name.lower() == "grep":
        n = output.get("numFiles")
        mode = output.get("mode")
        return f"{name} · mode={mode} · files={n}"
    if name.lower() == "bash":
        code = output.get("exit_code")
        # The last line the command printed (its error output on failure), so the result isn't just a code.
        text = str(output.get("stderr") if code and output.get("stderr") else output.get("stdout") or "")
        last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
        if len(last) > 80:
            last = last[:79] + "…"
        return f"{name} · exit={code}" + (f" · {last}" if last else "")
    if name.lower() == "webfetch":
        url = output.get("url")
        ct = output.get("content_type")
        return f"{name} · {url} · {ct}"
    if name.lower() == "websearch":
        q = output.get("query")
        results = output.get("results")
        n = len(results) if isinstance(results, list) else None
        return f"{name} · \"{q}\" · results={n}"
    if name.lower() == "config":
        op = output.get("operation")
        setting = output.get("setting")
        return f"{name} · {op} · {setting}"
    if name.lower() == "taskstop":
        tid = output.get("task_id")
        stopped = output.get("stopped")
        return f"{name} · {tid} · stopped={stopped}"
    if name.lower() == "sendusermessage":
        n = 0
        atts = output.get("attachments")
        if isinstance(atts, list):
            n = len(atts)
        return f"{name} · attachments={n}"
    # default: truncate dict keys for brevity
    keys = ", ".join(list(output.keys())[:3])
    return f"{name} · {keys}"


@dataclass(frozen=True)
class ToolEvent:
    kind: str
    tool_name: str
    tool_input: dict[str, Any] | None = None
    tool_output: Any | None = None
    tool_use_id: str | None = None
    is_error: bool = False
    error: str | None = None


@dataclass(frozen=True)
class AgentLoopResult:
    """Result of running the agent loop."""
    response_text: str
    usage: dict[str, Any] | None = None  # {"input_tokens": int, "output_tokens": int}
    num_turns: int = 0


ToolEventHandler = Callable[[ToolEvent], None]
TextChunkHandler = Callable[[str], None]


def _safe_call_handler(handler: ToolEventHandler | None, event: ToolEvent) -> None:
    if handler is None:
        return
    try:
        handler(event)
    except Exception:
        return


def _build_effective_system_prompt(style_prompt: str, tool_context: ToolContext) -> str:
    try:
        context_prompt = build_context_prompt(
            tool_context.workspace_root,
            cwd=tool_context.cwd,
        )
    except Exception:
        context_prompt = ""
    if tool_context.plan_mode:
        context_prompt += ("\n\n## Mode: reading the table (plan mode)\nThe user wants a plan before any change. Investigate "
                           "with read-only tools only; tools that modify files or run non-read-only commands are refused. "
                           "When you have a plan, present it with the ExitPlanMode tool.")
    if not context_prompt.strip():
        return style_prompt
    return f"{style_prompt}\n\n{context_prompt}"


def summarize_tool_use(name: str, tool_input: dict[str, Any]) -> str:
    lowered = name.lower()
    if lowered == "bash":
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            s = cmd.strip().replace("\n", " ")
            return s if len(s) <= 80 else s[:77] + "..."
        return ""
    if lowered in {"read", "write", "edit"}:
        p = tool_input.get("file_path") or tool_input.get("filePath") or tool_input.get("path")
        if isinstance(p, str):
            extra = ""
            if lowered == "read":
                off = tool_input.get("offset")
                lim = tool_input.get("limit")
                if isinstance(off, int) or isinstance(lim, int):
                    start = off if isinstance(off, int) else 1
                    if isinstance(lim, int):
                        extra = f" · lines {start}-{start + lim - 1}"
            return f"{p}{extra}"
        return ""
    if lowered == "glob":
        pat = tool_input.get("pattern")
        base = tool_input.get("path")
        if isinstance(pat, str) and isinstance(base, str):
            return f"{pat} · {base}"
        if isinstance(pat, str):
            return pat
        return ""
    if lowered == "grep":
        pat = tool_input.get("pattern")
        base = tool_input.get("path")
        if isinstance(pat, str) and isinstance(base, str):
            return f"{pat} · {base}"
        if isinstance(pat, str):
            return pat
        return ""
    if lowered == "webfetch":
        url = tool_input.get("url")
        return url if isinstance(url, str) else ""
    if lowered == "websearch":
        q = tool_input.get("query")
        return q if isinstance(q, str) else ""
    if lowered == "toolsearch":
        q = tool_input.get("query")
        return q if isinstance(q, str) else ""
    if lowered == "askuserquestion":
        qs = tool_input.get("questions")
        if isinstance(qs, list):
            return f"{len(qs)} question(s)"
        return ""
    if lowered == "sendusermessage":
        status = tool_input.get("status")
        return status if isinstance(status, str) else ""
    return ""



def _discard(_chunk: str) -> None:
    return None


def _add_usage(total: dict[str, int], usage: dict | None) -> None:
    for key, value in (usage or {}).items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value


def _trace_tool(name: str, tool_input: dict, started: float, is_error: bool, output: Any) -> None:
    if not trace.active():
        return
    trace.record("tool_call", name=name, input=json.dumps(trace.redact(tool_input), ensure_ascii=False),
                 duration_ms=int((time.monotonic() - started) * 1000), is_error=is_error,
                 result_chars=len(output if isinstance(output, str) else str(output)))


MAX_TURNS_REPLY = "[Max tool turns reached]"


def run_agent_loop(
    conversation: Conversation,
    provider: Provider,
    model: str,
    tool_registry: ToolRegistry,
    tool_context: ToolContext,
    max_turns: int = 20,
    stream: bool = False,
    verbose: bool = False,
    on_event: ToolEventHandler | None = None,
    on_text_chunk: TextChunkHandler | None = None,
    *,
    reasoning: str | None = None,
    on_thinking: TextChunkHandler | None = None,
    cancel: threading.Event | None = None,
    system_extra: str | None = None,
) -> AgentLoopResult:
    """Run agent loop: LLM -> tools -> LLM until no more tools or max turns.

    Every turn re-expresses the stored conversation in the provider's own wire format, so the
    same history works with any provider. Retryable provider errors (429/5xx/connection) are
    retried with backoff; anything else propagates as a ProviderError.

    Args:
        conversation: Conversation with the initial user message; replies and tool results are
            appended to it.
        provider: A provider from src.providers.registry.
        model: Model id for that provider.
        tool_registry: Tool registry to use.
        tool_context: Tool context.
        max_turns: Maximum model turns before stopping.
        stream: Whether to forward text (and reasoning) chunks as they arrive.
        verbose: Whether to print tool calls/results.
        on_event: Optional callback for tool events.
        on_text_chunk: Optional callback for incremental user-visible text chunks.
        reasoning: Optional reasoning level (off | low | medium | high | on).
        on_thinking: Optional callback for streamed reasoning chunks.
        cancel: Optional event; setting it aborts the in-flight request.

    Returns:
        AgentLoopResult with final text response, usage info, and turn count
    """
    tool_context.provider, tool_context.model = provider, model
    all_specs = tool_registry.list_specs()
    known_tools = tuple(s.name for s in all_specs)   # every tool runs when called; only some are sent (deferral.py)
    style_name = getattr(tool_context, "output_style_name", None)
    style_dir = getattr(tool_context, "output_style_dir", None)
    style_prompt = resolve_output_style(style_name, style_dir).prompt
    system_prompt = _build_effective_system_prompt(style_prompt, tool_context)
    if system_extra:   # a custom sub-agent's own instructions
        system_prompt += "\n\n" + system_extra
    if index := index_prompt(all_specs):
        system_prompt += "\n\n" + index
    text_handler = on_text_chunk if (stream and on_text_chunk is not None) else _discard

    last_user_visible_message: str | None = None
    total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    turn_count = 0

    def _usage_or_none() -> dict[str, int] | None:
        return total_usage if total_usage["input_tokens"] > 0 or total_usage["output_tokens"] > 0 else None

    for _turn in range(max_turns):
        specs = from_specs(advertised(all_specs, tool_context.loaded_tools))   # again each turn: ToolSearch may have loaded more
        request = to_canonical(conversation, system_prompt)
        response = trace.model_call(provider, model, request, lambda: stream_with_retry(
            provider,
            request,
            model,
            specs,
            text_handler,
            cancel=cancel,
            reasoning=reasoning,
            on_thinking=on_thinking if stream else None,
        ))
        turn_count += 1
        _add_usage(total_usage, response.usage)
        append_response(conversation, response.message)

        final_assistant_content = response.message.text or ""
        tool_calls = response.message.tool_calls

        if not tool_calls:
            if final_assistant_content.strip() == "" and last_user_visible_message is not None:
                final_assistant_content = last_user_visible_message
            return AgentLoopResult(
                response_text=final_assistant_content,
                usage=_usage_or_none(),
                num_turns=turn_count,
            )

        for tc in tool_calls:
            tool_id = tc.id
            tool_name, tool_input = coerce_tool_args(tc.name, tc.arguments, known_tools)
            if is_deferred(tool_name):
                tool_context.loaded_tools.add(tool_name.lower())   # called by name: send its definition from now on
            started = time.monotonic()

            try:
                _safe_call_handler(
                    on_event,
                    ToolEvent(kind="tool_use", tool_name=tool_name, tool_input=tool_input, tool_use_id=tool_id),
                )
                from ..tool_system.protocol import ToolCall
                edit_check = edit_check_for(tool_name, tool_input, tool_context.workspace_root)
                result = tool_registry.dispatch(ToolCall(name=tool_name, input=tool_input, tool_use_id=tool_id),
                                                tool_context)
                result_output = result.output
                # New lint/type problems ride on the edit's own result (like hook feedback), so the
                # model sees them on its next turn without breaking tool_use/tool_result pairing.
                problems = edit_check.report() if edit_check and not result.is_error else None
                if problems and isinstance(result_output, dict):
                    result_output = {**result_output, "newProblems": problems}
                _trace_tool(tool_name, tool_input, started, result.is_error, result_output)
                if tool_name.lower() == "sendusermessage" and isinstance(result_output, dict):
                    msg = result_output.get("message")
                    if isinstance(msg, str):
                        last_user_visible_message = msg
                if tool_name.lower() == "structuredoutput" and isinstance(result_output, dict):
                    payload = result_output.get("structured_output")
                    try:
                        last_user_visible_message = json.dumps(payload, ensure_ascii=False, indent=2)
                    except Exception:
                        last_user_visible_message = str(payload)

                if verbose:
                    use_summary = summarize_tool_use(tool_name, tool_input)
                    if use_summary:
                        print(f"{tool_name} · {use_summary}")
                    print(summarize_tool_result(tool_name, result_output))

                _safe_call_handler(
                    on_event,
                    ToolEvent(kind="tool_result", tool_name=tool_name, tool_output=result_output,
                              tool_use_id=tool_id, is_error=result.is_error),
                )
                conversation.add_tool_result_message(tool_id, result_output, is_error=result.is_error)
            except Exception as e:
                error_str = f"Error: {e}"
                _trace_tool(tool_name, tool_input, started, True, error_str)
                if verbose:
                    print(f"[Tool Error] {error_str}")
                _safe_call_handler(
                    on_event,
                    ToolEvent(kind="tool_error", tool_name=tool_name, tool_input=tool_input,
                              tool_use_id=tool_id, is_error=True, error=error_str),
                )
                conversation.add_tool_result_message(tool_id, error_str, is_error=True)

    return AgentLoopResult(
        response_text=MAX_TURNS_REPLY,
        usage=_usage_or_none(),
        num_turns=turn_count,
    )
