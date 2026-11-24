"""Agent loop for multi-turn tool calling."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from src.providers.base import LOCAL_PROVIDERS, context_window
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from ..runtime import activity
from ..tool_system.checks import edit_check_for
from src import trace
from ..security import injection
from ..tool_system.registry import ToolRegistry
from ..tool_system.context import ToolContext
from ..tool_system.hooks import run_lifecycle
from ..tool_system.permission_rules import bare_denied
from ..memory import memory_prompt
from ..tool_system.plan_file import PLAN_SHAPE, plan_prompt, read_plan
from ..context_system.microcompact import trim_old_tool_results
from ..context_system.token_estimation import count_messages_tokens, request_overhead
from ..tool_system.deferral import NAMES_ONLY_UP_TO_BILLIONS, VERIFY_PROMPT, advertised, index_prompt, is_deferred, local_tools
from .cloud_review import review_reply
from .repeat_guard import RepeatedCall, RepeatGuard
from src.conversation import Conversation
from ..context_system import build_context_prompt, instruction_filter
from ..output_styles import resolve_output_style
from ..providers import model_size
from ..providers.base import Provider, stream_with_retry
from ..providers.convert import append_response, to_canonical
from ..providers.toolcall_repair import coerce_tool_args
from ..providers.toolspec import from_specs
from ..providers.types import Role


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
        loose = f" · matched loosely (ignored {output['matchedLoosely']})" if output.get("matchedLoosely") else ""
        return f"{name} · {path} · replaceAll={replace_all}{loose}"
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
    # Why the loop stopped: "done" (the model answered), "blocked" (a prompt hook refused it), "repeat" (it kept making the
    # same call), "stalled" (failing calls in a row), "budget" (the token budget ran out), "window" (the next request
    # can't fit the model's context window, so it was not sent) or "ran_out" (every tool turn used; response_text is then
    # the model's own wrap-up).
    stop_reason: str = "done"

    @property
    def ran_out(self) -> bool:
        return self.stop_reason == "ran_out"


# After N consecutive failing tool calls (different calls each time, so the repeat guard
# does not catch them) the model is burning tokens on nothing: stop and tell it to change
# approach or talk to the user.
_MAX_CONSECUTIVE_TOOL_ERRORS = 5
_STALLED_REPLY = "The tool calls keep failing (different arguments each time). Stop digging: change your approach, use a different tool, or tell me what is blocking you."


# A reply that stops at the output limit, or ends with no answer text (a reasoning model can spend its turn thinking),
# is asked for again with feedback. Mistral Vibe does this for the cut-off case, 6 times, discarding the partial reply;
# here the partial reply stays and the model continues it, so no tokens are thrown away.
# ponytail: one shared cap for both cases; split it if a model needs more continuations than retries.
_MAX_RECOVERIES = 3
# length: stopped at the output limit, however the service spells it (providers/stream.py); interrupted: the stream
# dropped mid-answer (base.py)
_CUT_OFF = ("length", "interrupted")
_CONTINUE_NUDGE = ("Your reply was cut off before it finished. Continue exactly where it stopped, without repeating "
                   "it. Keep reasoning brief, and split long file contents or edits into several smaller tool calls.")
_ANSWER_NUDGE = "Your last reply had no answer text. Answer now in plain text; keep any reasoning brief."
# A Stop hook that blocks keeps the turn going with its reason; past this many blocks in a row the turn ends anyway
# (Claude Code's override is 8), so a hook that never passes can't loop forever.
_MAX_STOP_BLOCKS = 8


def _forget_read(tool_context: ToolContext) -> Callable[[Any], None]:
    """For a cleared Read result: drop its file's fingerprint, so reading it again returns the content, not "unchanged"
    (live run: K2-Horizon re-read five trimmed files, got "unchanged" for each and decided they were empty)."""
    def forget(content: Any) -> None:
        path = (content.get("file") or {}).get("filePath") if isinstance(content, dict) else None
        if isinstance(path, str):
            tool_context.read_file_fingerprints.pop(Path(path).resolve(), None)
    return forget


# The estimate runs a little under the runtime's own count once heavy tool schemas are loaded: K2-Horizon on Ollama,
# 8,343 estimated vs 8,496 counted and 9,755 vs 9,969 (2.2% under). A request this close to the window is not sent.
_ESTIMATE_MARGIN = 1.05


def _over(estimate: int, window: int) -> bool:
    """Whether a request estimated at `estimate` tokens may not fit `window`, allowing for the estimate's error."""
    return estimate * _ESTIMATE_MARGIN > window


def _over_window(needed: int, overhead: int, window: int) -> str:
    """Why a request was not sent: it can't fit the model's window."""
    return (f"Stopped: the next request needs about {needed:,} tokens, more than this model's {window:,}-token window "
            f"({overhead:,} of them are Clyde's instructions and tool definitions). Run /compact, start a new "
            f"conversation, or give the model a larger window (CLYDE_CONTEXT_TOKENS).")
_HOOK_CONTEXT = "Context from a UserPromptSubmit hook:\n"
_STOP_HOOK = "A Stop hook did not let the turn end yet: "
_WRAP_UP = ("You have used every tool turn this task allows. Do not call tools. In plain text, say briefly: what is done, "
            "what remains, and what to do next.")


def _continue(cut: str, more: str) -> str:
    """A cut-off reply joined to its continuation. Asked not to, a model still restarts the line it was cut on, with the
    same opening and sometimes other words (live, ministral-8b: "- September: Gradual- September: Mild and pleasant");
    that partial line then goes and the continuation keeps its own."""
    head, _, last = cut.rpartition("\n")
    last, start = last.strip(), more.lstrip()
    same = len(os.path.commonprefix([last, start]))
    if last and same >= min(len(last), 10):   # ponytail: a 10-character shared opening means a restart; rare false match
        return (head + "\n" if head else "") + start
    # The cut line was a list item and the continuation opens the next one ("- May: sunny" then "- June: hot"):
    # the model judged the cut item done, so the next one starts its own line instead of running on.
    item = re.match(r"([-*•>|#]+|\d+[.)])\s", last)
    if item and start.startswith(item.group(1)):
        return cut.rstrip() + "\n" + start
    return cut + more


ToolEventHandler = Callable[[ToolEvent], None]
TextChunkHandler = Callable[[str], None]


def _safe_call_handler(handler: ToolEventHandler | None, event: ToolEvent) -> None:
    if handler is None:
        return
    try:
        handler(event)
    except Exception:
        return


def goal_prompt(goal: str | None) -> str:
    """The system-prompt section for the session goal (/goal); "" when none is set."""
    if not goal:
        return ""
    return f"## Session goal\nThe user set this goal for the session: {goal}\nKeep working toward it, and say when it is met."


def _build_effective_system_prompt(style_prompt: str, tool_context: ToolContext, compact: bool = False,
                                   filter_user_file: Callable[[str], str] | None = None, request: str = "") -> str:
    try:
        context_prompt = build_context_prompt(
            tool_context.workspace_root,
            cwd=tool_context.cwd,
            compact=compact,
            filter_user_file=filter_user_file,
        )
    except Exception:
        context_prompt = ""
    if tool_context.plan_mode:
        context_prompt += ("\n\n## Mode: reading the table (plan mode)\nThe user wants a plan before any change. Investigate "
                           "with read-only tools only; tools that modify files or run non-read-only commands are refused. "
                           "When you have a plan, present it with the ExitPlanMode tool.\n\n" + PLAN_SHAPE)
    elif section := plan_prompt(read_plan(getattr(tool_context, "plan_file", None))):
        context_prompt += "\n\n" + section
    if section := goal_prompt(getattr(tool_context, "goal", None)):
        context_prompt += "\n\n" + section
    context_prompt += "\n\n" + memory_prompt(tool_context.workspace_root, request, tool_context.memory_shown)
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
MAX_TOKENS_REPLY = "[Token budget reached]"
_BUDGET_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


_STEERING = "The user sent this while you were working; take it into account from here on:\n"


def _small_local(provider: Provider) -> bool:
    """A model served on this machine: models that do better with a few tools than with all of them."""
    return getattr(provider, "name", "") in LOCAL_PROVIDERS


def _request_frame(provider: Provider, model: str, tool_registry: ToolRegistry, tool_context: ToolContext, prompt: str,
                   system_extra: str | None = None) -> tuple[str, list, frozenset[str] | None]:
    """(system prompt, tool specs, the local core set) a request for `prompt` starts from. Changes nothing: the loop
    stores the grown core set itself, and window_shortfall builds the same request without sending it."""
    rules = getattr(tool_context, "permission_rules", None) or {"deny": []}
    # A tool denied by bare name (`Bash`, `mcp__github__*`) is not shown at all, as Claude Code does: the model can't
    # spend turns calling it, and its definition costs no prompt tokens.
    all_specs = [s for s in tool_registry.list_specs() if not bare_denied(s.name, rules)]
    style_prompt = resolve_output_style(getattr(tool_context, "output_style_name", None),
                                        getattr(tool_context, "output_style_dir", None)).prompt
    small = _small_local(provider)
    filter_user_file = instruction_filter.for_project(tool_context.workspace_root, provider, model) if small else None
    system_prompt = _build_effective_system_prompt(style_prompt, tool_context, compact=small, filter_user_file=filter_user_file,
                                                   request=prompt)
    if system_extra:   # a custom sub-agent's own instructions
        system_prompt += "\n\n" + system_extra
    # The few tools this prompt needs, grown onto the ones offered so far (see ToolContext.local_only).
    only = tool_context.local_only | local_tools(prompt) if small else None
    size = model_size.billions(provider, model) if only is not None else None
    names_only = size is not None and size <= NAMES_ONLY_UP_TO_BILLIONS
    if index := index_prompt(all_specs, only, names_only=names_only):
        system_prompt += "\n\n" + index
    if only is not None:   # a small local model checks code against the project and the docs before it presents it
        system_prompt += "\n\n" + VERIFY_PROMPT
    return system_prompt, all_specs, only


def window_shortfall(provider: Provider, model: str, tool_registry: ToolRegistry, tool_context: ToolContext,
                     system_extra: str | None = None) -> tuple[int, int] | None:
    """(fixed part, window) when `model`'s window can't hold even Clyde's instructions and tool definitions, so every
    request would be refused; None when it can. A machine short of free memory can size a local model's window below
    that: K2-Horizon got 2,048 tokens against a 4,510-token fixed part."""
    system_prompt, all_specs, only = _request_frame(provider, model, tool_registry, tool_context, "", system_extra)
    fixed = request_overhead(system_prompt, from_specs(advertised(all_specs, tool_context.loaded_tools, only)))
    window = context_window(provider, model)
    return (fixed, window) if _over(fixed, window) else None


# What Clyde itself adds as user turns; never the user's prompt (local reply review, hooks and tool routing read it).
_INJECTED = (_STEERING, _HOOK_CONTEXT, _STOP_HOOK, _CONTINUE_NUDGE, _ANSWER_NUDGE, _WRAP_UP)


def _last_prompt(conversation: Conversation) -> str:
    """What the user last typed (not a tool result, not a steering note). Reads the agent's own history (`content`)
    as well as canonical turns (`text`): the loop passes the first, and matching only the second left the prompt empty."""
    for message in reversed(conversation.messages):
        text = getattr(message, "text", None) or getattr(message, "content", None)
        if message.role == Role.USER and isinstance(text, str) and text and not text.startswith(_INJECTED):
            return text
    return ""


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
    steer: Callable[[], str | None] | None = None,
    max_tokens: int | None = None,
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
        steer: Optional callback returning text the user sent while the turn runs; it is added as a user
            message before the next model call (never before the first).
        max_tokens: Optional token budget over the run (prompt, cached prompt and output); past it the loop stops after
            that turn's tools with MAX_TOKENS_REPLY.

    Returns:
        AgentLoopResult with final text response, usage info, and turn count
    """
    tool_context.provider, tool_context.model = provider, model
    system_prompt, all_specs, only = _request_frame(provider, model, tool_registry, tool_context, _last_prompt(conversation),
                                                    system_extra)
    if only is not None:   # grow-only: see ToolContext.local_only; a changed tool list re-prefills the server's cache
        tool_context.local_only = only
    known_tools = tuple(s.name for s in all_specs)   # every tool runs when called; only some are sent (deferral.py)
    text_handler = on_text_chunk if (stream and on_text_chunk is not None) else _discard

    last_user_visible_message: str | None = None
    repeat_guard = RepeatGuard()
    consecutive_errors = 0
    recoveries, carried = 0, ""   # carried: a cut-off reply's text, which the next reply continues

    total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    spent = 0   # max_tokens: what the provider reports, cached prompt included; an estimate when it reports nothing
    turn_count = 0

    def _usage_or_none() -> dict[str, int] | None:
        return total_usage if total_usage["input_tokens"] > 0 or total_usage["output_tokens"] > 0 else None

    hooks = getattr(tool_context, "hooks", None) or {}
    stop_blocks = 0
    if hooks.get("UserPromptSubmit"):
        blocked, added = run_lifecycle(hooks, "UserPromptSubmit", {"prompt": _last_prompt(conversation)}, tool_context.cwd)
        if blocked:
            return AgentLoopResult(response_text=f"Prompt blocked by a UserPromptSubmit hook: {blocked}", usage=None, num_turns=0,
                                   stop_reason="blocked")
        if added:
            conversation.add_user_message(_HOOK_CONTEXT + added)

    # The fixed part as the runtime measured it this run; only grows, since a cached prompt may report fewer tokens.
    overhead_seen = 0
    for _turn in range(max_turns):
        if _turn and steer is not None and (steering := steer()):
            conversation.add_user_message(f"{_STEERING}{steering}")
        specs = from_specs(advertised(all_specs, tool_context.loaded_tools, only))   # again each turn: ToolSearch may have loaded more
        window = context_window(provider, model)
        # Every round, not only before the turn: the system prompt and tool definitions are most of a small window, so
        # one tool result can push the next request past it.
        overhead = tool_context.prompt_overhead = max(request_overhead(system_prompt, specs), overhead_seen)
        forget = _forget_read(tool_context)
        if only is not None:   # a local window fills with old file dumps long before auto-compact
            trim_old_tool_results(conversation, window, overhead=overhead, forget=forget)
        sent = count_messages_tokens(conversation.get_messages())
        # Past the window even after that: clear all but the newest result (the model can read a file again), and only
        # then refuse. The usual four kept whole filled a 12k window with K2-Horizon after four reads.
        if _over(sent + overhead, window) and trim_old_tool_results(conversation, window, keep=1, overhead=overhead, forget=forget):
            sent = count_messages_tokens(conversation.get_messages())
        if _over(sent + overhead, window):   # the server would refuse it: say why instead
            return AgentLoopResult(response_text=_over_window(sent + overhead, overhead, window), usage=_usage_or_none(),
                                   num_turns=turn_count, stop_reason="window")
        activity.set(f"waiting for {getattr(provider, 'name', '')}:{model}")
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
        if measured := getattr(response, "prompt_tokens", None):   # the runtime's own count, in its own tokenizer
            overhead_seen = max(overhead_seen, measured - sent)
        _add_usage(total_usage, response.usage)
        if max_tokens:
            spent += sum(response.usage.get(k) or 0 for k in _BUDGET_KEYS) if response.usage else \
                trace.estimate_tokens(request) + trace.estimate_tokens(SimpleNamespace(messages=[response.message]))
        append_response(conversation, response.message)

        final_assistant_content = response.message.text or ""
        tool_calls = response.message.tool_calls

        if not tool_calls:
            cut_off = response.done_reason in _CUT_OFF
            empty = not final_assistant_content.strip() and last_user_visible_message is None
            if (cut_off or empty) and recoveries < _MAX_RECOVERIES:
                recoveries += 1
                carried = _continue(carried, final_assistant_content)
                # Where it stopped, quoted: told only to continue, ministral-8b skipped the line it was cut on 2 runs in 3.
                stopped = f' It stopped at: "…{final_assistant_content[-80:]}"' if final_assistant_content.strip() else ""
                conversation.add_user_message(_CONTINUE_NUDGE + stopped if cut_off else _ANSWER_NUDGE)
                continue
            final_assistant_content = _continue(carried, final_assistant_content)
            if final_assistant_content.strip() == "" and last_user_visible_message is not None:
                final_assistant_content = last_user_visible_message
            if only is not None and (fixed := review_reply(_last_prompt(conversation), final_assistant_content, tool_context)):
                text_handler("\n\n" + fixed)   # a weak local reply already streamed; the cloud model's correction follows it
                conversation.messages[-1].content = fixed
                final_assistant_content = fixed
            if hooks.get("Stop") and stop_blocks < _MAX_STOP_BLOCKS:
                blocked, _ = run_lifecycle(hooks, "Stop", {"stop_hook_active": stop_blocks > 0,
                                                           "last_assistant_message": final_assistant_content},
                                           tool_context.cwd)
                if blocked:
                    stop_blocks += 1
                    conversation.add_user_message(_STOP_HOOK + blocked)
                    continue
            return AgentLoopResult(
                response_text=final_assistant_content,
                usage=_usage_or_none(),
                num_turns=turn_count,
            )

        stop_blocks = 0   # as Claude Code: the Stop cap counts blocks with no tool call between them
        for tc in tool_calls:
            tool_id = tc.id
            tool_name, tool_input = coerce_tool_args(tc.name, tc.arguments, known_tools)
            if is_deferred(tool_name, only):
                tool_context.loaded_tools.add(tool_name.lower())   # called by name: send its definition from now on
            started = time.monotonic()
            activity.set(f"running {tool_name}")

            try:
                _safe_call_handler(
                    on_event,
                    ToolEvent(kind="tool_use", tool_name=tool_name, tool_input=tool_input, tool_use_id=tool_id),
                )
                from ..tool_system.protocol import ToolCall
                if (refusal := repeat_guard.refusal(tool_name, tool_input)) is not None:
                    raise RepeatedCall(refusal)
                edit_check = edit_check_for(tool_name, tool_input, tool_context.workspace_root)
                result = tool_registry.dispatch(ToolCall(name=tool_name, input=tool_input, tool_use_id=tool_id),
                                                tool_context)
                tool = tool_registry.get(tool_name)
                result_output, flagged = injection.guard(tool_name, result.output, tool is not None and tool.spec().reaches_network)   # an outside tool's answer that addresses the model gets a notice
                if flagged:
                    trace.record("injection_flag", tool=tool_name, findings=flagged)
                    summary = summarize_tool_use(tool_name, tool_input)
                    tool_context.injection_sources.append(f"{tool_name} ({summary})" if summary else tool_name)
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
                repeat_guard.record(tool_name, tool_input, result_output)
                consecutive_errors = consecutive_errors + 1 if result.is_error else 0
            except Exception as e:
                error_str = f"Error: {e}"
                consecutive_errors += 1
                if not isinstance(e, RepeatedCall):
                    repeat_guard.record(tool_name, tool_input, error_str)
                _trace_tool(tool_name, tool_input, started, True, error_str)
                if verbose:
                    print(f"[Tool Error] {error_str}")
                _safe_call_handler(
                    on_event,
                    ToolEvent(kind="tool_error", tool_name=tool_name, tool_input=tool_input,
                              tool_use_id=tool_id, is_error=True, error=error_str),
                )
                conversation.add_tool_result_message(tool_id, error_str, is_error=True)

        if repeat_guard.stuck:
            return AgentLoopResult(response_text=repeat_guard.stop_reply(), usage=_usage_or_none(), num_turns=turn_count, stop_reason="repeat")
        if consecutive_errors >= _MAX_CONSECUTIVE_TOOL_ERRORS:
            return AgentLoopResult(response_text=_STALLED_REPLY, usage=_usage_or_none(), num_turns=turn_count, stop_reason="stalled")
        # Checked once the turn's tool results are in, so the saved session has no call without its result. A stop the
        # caller asked for, like an interrupt.
        if max_tokens and spent > max_tokens:
            return AgentLoopResult(response_text=MAX_TOKENS_REPLY, usage=_usage_or_none(), num_turns=turn_count, stop_reason="budget")

    # Out of tool turns: one more request, with no tools, for the model to say where the task stands (Kilo does the
    # same); a fixed "[Max tool turns reached]" told the user nothing. It stays as the fallback if this fails.
    conversation.add_user_message(_WRAP_UP)
    wrap_up = ""
    try:
        request = to_canonical(conversation, system_prompt, flatten_tools=True)
        response = trace.model_call(provider, model, request, lambda: stream_with_retry(
            provider, request, model, (), text_handler, cancel=cancel, reasoning=reasoning))
        _add_usage(total_usage, response.usage)
        append_response(conversation, response.message)
        wrap_up = (response.message.text or "").strip()
    except Exception:   # the turns are spent either way; say so plainly
        pass
    return AgentLoopResult(
        response_text=wrap_up or MAX_TURNS_REPLY,
        usage=_usage_or_none(),
        num_turns=turn_count,
        stop_reason="ran_out",
    )
