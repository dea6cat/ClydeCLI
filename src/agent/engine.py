"""The session engine: one conversation with a model and its tools, with no terminal of its own.

`clyde -p`, the editor server (ACP) and Bonnie drive it directly through its public methods; the terminal REPL
(src/repl/core.py) extends it with the prompt, the spinner and the slash commands. Built with `interactive=False` (the
default) it never reads the keyboard: anything that would ask is denied until the front end installs its own
permission handler, project allow rules and .mcp.json servers nobody approved stay off, and oMLX is never installed.
Progress (tool lines, warnings, errors) goes to its console, which the front ends point at stderr.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from rich.console import Console
from rich.text import Text

from src import trace
from src.agent.agent_loop import AgentLoopResult, ToolEvent, run_agent_loop, summarize_tool_result, summarize_tool_use, \
    window_shortfall
from src.agent.checkpoints import Checkpoints
from src.agent.cost_tracker import CostTracker
from src.agent.session import Session
from src.agent.subagent import NO_NESTING, build_tool_registry
from src.compact_service.service import compact_conversation, needs_auto_compact
from src.config import get_default_model, get_output_style, load_config
from src.conversation import ImageContentBlock
from src.output_styles import resolve_output_style
from src.plugins import apply_plugins
from src.providers import build_registry, catalog, keys, model_ref, pick_default_model, resolve
from src.providers.base import (ProviderError, ProviderResponse, begin_turn, context_window, is_auth_error, retry_elsewhere,
                                served_by, turn_spend)
from src.providers.convert import append_response, to_canonical
from src.providers.types import Message
from src.runtime import activity
from src.runtime.run_control import RunControl
from src.tool_system.context import ToolContext
from src.tool_system.hooks import load_hooks
from src.tool_system.mcp_client import connect_servers, load_servers, merge_servers, register_mcp_tools
from src.tool_system.permission_rules import load_rules
from src.tool_system.plan_file import plan_file_for
from src.tool_system.registry import ToolRegistry

# The card colors the terminal uses; progress lines on stderr wear them too.
ACCENT, DIM, TEXT = "#4eba65", "#8a8a8a", "#e8e4dc"
MODES = ("hold", "plan", "all_in")
_COUNCIL_MAX_TURNS = 12   # reading turns a council member gets before it must answer

TextListener = Callable[[str], None]
EventListener = Callable[[ToolEvent], None]


def _deny(_tool: str, _message: str, _rule: str | None) -> tuple[bool, bool]:
    """Nobody to ask: anything that would ask is refused (front ends that can ask install their own handler)."""
    return False, False


def duration(seconds: float) -> str:
    """0.4s, 12s, 2m 45s, 1h 3m."""
    if seconds < 10:
        return f"{seconds:.1f}s"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _recoverable_tool_error(tool_name: Any, tool_output: Any) -> bool:
    """A failed Read of a skill file the model guessed at: it recovers on its own, so the line isn't shown."""
    if not isinstance(tool_name, str) or not isinstance(tool_output, dict):
        return False
    err = tool_output.get("error")
    if not isinstance(err, str) or tool_name.strip().lower() != "read" or not err.lower().startswith("file not found:"):
        return False
    path = err.split(":", 2)[-1].strip()
    return any(part in path for part in ("/.clyde/skills/", "\\.clyde\\skills\\", "/.claude/skills/", "\\.claude\\skills\\"))


class Engine:
    """A session: the model, the tools and their permissions, the conversation and its saving."""

    system_extra: str | None = None   # extra system-prompt text for the next turns only (Bonnie's search results); not stored
    direct_stream = True              # short chat-like prompts may skip the tools for a quicker streamed reply (needs `stream`)

    def __init__(self, model: str | None = None, console: Console | None = None, *, interactive: bool = False,
                 stream: bool = False, debug: bool = False):
        self.console = console or Console()
        self.interactive = interactive
        self.stream = stream
        self.last_result: AgentLoopResult | None = None   # the latest turn's result (None after a direct streamed reply)
        self.last_error: str | None = None
        self.control = RunControl()   # queue, steer and stop for a front end that drives turns from another thread
        self.reasoning: str | None = None   # /think level; None keeps each model's default
        session_config = load_config().get("session", {})
        self.auto_save = session_config.get("auto_save", True)
        self._trace_options = {"enabled": session_config.get("trace", True) is not False, "live": debug}

        self.registry = build_registry()
        if (omlx := self.registry.get("omlx")) is not None:
            if interactive:   # -p, an editor (ACP) and Bonnie have no terminal to answer on; there it never installs
                omlx.confirm_install = self._confirm_install_omlx
            from src.providers.omlx import migrate_lmstudio_refs
            for line in migrate_lmstudio_refs():   # LM Studio was replaced by oMLX, which serves the same folders
                self.console.print(f"[dim]Moved {line} (oMLX now runs LM Studio's models).[/dim]")
        resolved = self._startup_model(model)
        if resolved is None:
            sys.exit(1)
        self.provider, self.model = resolved
        self.provider_name = self.provider.name

        self.session = Session.create(self.provider_name, self.model)
        self.checkpoints = Checkpoints(self.session.session_id)
        trace.start(self.session.session_id, **self._trace_options)

        self.tool_registry = build_tool_registry()
        hooks, servers = load_hooks(), load_servers()
        servers = merge_servers(servers, self._project_mcp_servers(Path.cwd(), set(servers)))   # yours first: they win a clash
        self.plugins = apply_plugins(self.tool_registry, hooks, servers)
        for loaded in self.plugins:
            for warning in loaded.warnings:
                self.console.print(warning, style="yellow", markup=False)
        self.tool_context = ToolContext(workspace_root=Path.cwd(), hooks=hooks, permission_rules=self.project_rules(Path.cwd()),
                                        output_style_name=get_output_style(), confirm_edits=True)
        self._mcp_servers: dict[str, dict[str, Any]] = servers
        self._mcp_errors: dict[str, str] = {}
        self._connect_mcp_servers(servers)
        self.tool_context.permission_handler = _deny
        self.tool_context.ask_user = None
        self.tool_context.plan_file = plan_file_for(self.tool_context.workspace_root, self.session.session_id)
        self.tool_context.before_edit = lambda path: self.checkpoints.snapshot(path)   # late-bound: a switched session's checkpoints
        self.cost_tracker = CostTracker()

    # -- model ---------------------------------------------------------------------------------------
    def _confirm_install_omlx(self) -> bool:
        """Ask before downloading and building oMLX, the one download-and-build Clyde would otherwise do unasked. Wired
        only when `interactive`."""
        from src.providers.omlx import REPO, VERSION, home
        self.console.print(Text("  oMLX, the open-source server Clyde runs MLX models with, isn't installed.", style=TEXT))
        self.console.print(Text(f"  Clyde would install {VERSION} from {REPO.removesuffix('.git')} into {home()} (a few minutes; "
                                "nothing outside that folder changes).", style=DIM))
        return input("  Install it? [y/N]: ").strip().lower() in ("y", "yes")

    def _startup_model(self, requested: str | None):
        """(provider, model) to start with. An explicit --model must resolve. Otherwise the saved
        default is used when it works, and if it doesn't (or none is saved) a model is picked
        from whatever is connected, so an exported API key is enough; no login required."""
        if requested:
            return self.resolve_model(requested)
        saved = get_default_model()
        if saved:
            resolved = resolve(self.registry, saved)
            if resolved is not None:
                return resolved
            self.console.print(f"[yellow]Saved model '{saved}' isn't available right now.[/yellow]")
        with self.console.status("[dim]Looking for a connected provider...[/dim]", spinner="dots"):
            auto = pick_default_model(self.registry)
        resolved = resolve(self.registry, auto) if auto else None
        if resolved is None:
            self.console.print("[red]No provider available.[/red] Export an API key (e.g. OPENAI_API_KEY), "
                               "start Ollama, or run [bold]clyde login[/bold].")
            return None
        self.console.print(f"[dim]Using {auto}. Change it with /model provider:model.[/dim]")
        return resolved

    def resolve_model(self, requested: str):
        """(provider, model) for a model string, or None after explaining why it didn't resolve."""
        resolved = resolve(self.registry, requested)
        if resolved is None and requested.startswith("ollama:"):
            from src.tuning import tune
            if tune.start_saved_server(self.console):
                resolved = resolve(self.registry, requested)
        if resolved is not None:
            return resolved
        prefix = requested.split(":", 1)[0] if ":" in requested else ""
        provider = self.registry.get(prefix)
        if provider is not None:
            if provider.name == "ollama":
                self.console.print(f"[red]Ollama isn't reachable at {getattr(provider, 'host', '')}.[/red]")
            else:
                self.console.print(f"[red]No API key for {provider.name}.[/red] "
                                   f"Run [bold]clyde login[/bold] or set {keys.PROVIDER_KEY_ENV.get(provider.name, '')}.")
        else:
            self.console.print(f"[red]Can't resolve model '{requested}'.[/red] "
                               "Use provider:model (e.g. openai:gpt-5.4); /models lists what's available.")
        return None

    def switch_model(self, requested: str) -> bool:
        """Use `requested` for this session only (an editor or Bonnie picking a model leaves other sessions alone)."""
        resolved = self.resolve_model(requested)
        if resolved is None:
            return False
        self.provider, self.model = resolved
        self.provider_name = self.provider.name
        self.session.provider, self.session.model = self.provider_name, self.model
        self._warn_if_unlisted()
        self._warn_if_window_too_small()
        return True

    def _warn_if_window_too_small(self) -> None:
        """A local model sized below Clyde's own instructions and tools can't answer anything: say so at the pick, with
        what to do, instead of letting every message be refused."""
        if callable(refresh := getattr(self.provider, "refresh_context", None)):
            refresh(self.model)   # size it from the memory free now
        try:
            short = window_shortfall(self.provider, self.model, self.tool_registry, self.tool_context, self.system_extra)
        except Exception:   # a server that doesn't answer: the first request will say so
            return
        if short is not None:
            fixed, window = short
            self.console.print(f"[yellow]{self.model} gets a {window:,}-token window on this machine right now, but Clyde's "
                               f"instructions and tool definitions alone need about {fixed:,}: it can't answer until it has "
                               "more. Free some memory and pick it again, or set \"Context window (local models)\" in "
                               "/settings.[/yellow]")

    def _warn_if_unlisted(self) -> None:
        """A model the provider's own list doesn't contain usually fails on the first request: say so now."""
        try:
            models = self.provider.list_models()
        except Exception:
            return
        if models and self.model not in models:
            self.console.print(f"[yellow]{self.model} isn't in {self.provider_name}'s model list; if the next request "
                               "fails, pick another with /model.[/yellow]")

    def reads_images(self) -> bool | None:
        """Whether the current model takes images: Ollama asks the server, others the catalog; None when unknown."""
        ask = getattr(self.provider, "reads_images", None)
        if callable(ask):
            try:
                return ask(self.model)
            except Exception:
                return None
        info = catalog.lookup(self.model.rsplit("/", 1)[-1])
        return info.supports_images if info is not None else None

    def context_window(self) -> int:
        """The model's input window: the provider's own sizing, then the catalog, then a name heuristic."""
        return context_window(self.provider, self.model)

    # -- permission mode -----------------------------------------------------------------------------
    @property
    def mode(self) -> str:
        ctx = self.tool_context
        return "plan" if ctx.plan_mode else "all_in" if ctx.auto_approve else "hold"

    def set_mode(self, mode: str) -> None:
        """hold (asks before risky actions), plan (read-only) or all_in (asks only before major moves)."""
        self.tool_context.plan_mode = mode == "plan"
        self.tool_context.auto_approve = mode == "all_in"

    # -- sessions and workspace ------------------------------------------------------------------------
    def switch_session(self, session: Session) -> None:
        """Continue `session` with the model in use (the saved one may not be connected any more)."""
        self.session = session
        self.tool_context.plan_file = plan_file_for(self.tool_context.workspace_root, session.session_id)
        self.tool_context.goal, self.tool_context.goal_from_plan = None, False   # a goal belongs to the session that set it
        self.tool_context.todos = []   # and so does its todo list
        self.checkpoints = Checkpoints(session.session_id)   # its checkpoints, for /rewind
        trace.start(session.session_id, **self._trace_options)
        session.provider, session.model = self.provider_name, self.model

    def new_session(self) -> None:
        self.switch_session(Session.create(self.provider_name, self.model))

    def autosave(self) -> None:
        """Persist the session after each turn so /resume and --continue have something to load."""
        if not self.auto_save or not self.session.conversation.messages:
            return
        try:
            self.session.save()
        except OSError as e:
            self.console.print(f"[yellow]Couldn't auto-save the session: {e}[/yellow]")

    def set_workspace(self, path: Path) -> None:
        """Work in another folder: tools and permissions follow it. The caller checks that nothing is running."""
        # ponytail: MCP servers and hooks stay those of the folder the engine started in; restart to pick up a new project's own
        os.chdir(path)
        context = self.tool_context
        context.workspace_root = context.cwd = path
        context.permission_context.workspace_root = path
        rules = self.project_rules(path)   # the new project's own deny/ask rules, not the old one's
        context.permission_rules.clear()
        context.permission_rules.update(rules)   # in place: sub-agents share this dict

    def project_rules(self, root: Path) -> dict[str, list[str]]:
        """The user's permission rules plus this project's .clyde/settings.json ones. Its deny and ask rules apply at once;
        its allow rules come from the repository, so they apply only once you have said yes to that exact list."""
        from rich.prompt import Confirm
        from src.tool_system.permission_rules import (merge_project_rules, project_settings_path, project_trust,
                                                      set_project_trust)
        rules, path = load_rules(), project_settings_path(root)
        if not path.is_file():
            return rules
        project = load_rules(path)
        trusted = bool(project["allow"]) and project_trust(root, project["allow"])
        if project["allow"] and trusted is None and self.interactive:
            self.console.print(f"\nThis project's {path.relative_to(root)} lets these run without asking:", highlight=False)
            for rule in project["allow"]:
                self.console.print(f"  {rule}", markup=False, highlight=False)
            trusted = Confirm.ask("They come from the repository. Trust them?", default=False, console=self.console)
            set_project_trust(root, project["allow"], trusted)
        elif project["allow"] and trusted is None:
            self.console.print(f"[yellow]Not using the allow rules in this project's {path.relative_to(root)}: "
                               "start clyde here interactively once to trust them.[/yellow]")
        return merge_project_rules(rules, project, bool(trusted))

    # -- MCP -----------------------------------------------------------------------------------------
    def _project_mcp_servers(self, root: Path, taken: set[str]) -> dict[str, dict[str, Any]]:
        """The project's .mcp.json servers you've said yes to, asking about any new or changed entry."""
        from rich.prompt import Confirm
        from src.tool_system.mcp_client import (_NAME_RE, _expand_vars, describe_server, is_mixed, project_approval,
                                                project_servers, set_project_approval)

        approved = {}
        for name, cfg in project_servers(root).items():
            if name in taken:
                continue
            if _NAME_RE.sub("_", name) in {_NAME_RE.sub("_", t) for t in taken}:
                self.console.print(f"[yellow]Skipping MCP server '{name}' from this project's .mcp.json:[/yellow] "
                                   "its name clashes with one of your own servers' tool names.")
                continue
            if is_mixed(cfg):
                self.console.print(f"[yellow]Skipping MCP server '{name}' from this project's .mcp.json:[/yellow] "
                                   "it names both a command and a url.")
                continue
            allowed = project_approval(root, name, cfg)
            if allowed is None and not self.interactive:
                self.console.print(f"[yellow]Skipping MCP server '{name}' from this project's .mcp.json:[/yellow] "
                                   "it hasn't been approved; start clyde here interactively once to answer.")
                continue
            if allowed is None:
                self.console.print(f"\nThis project's .mcp.json wants to start MCP server [bold]{name}[/bold]:",
                                   highlight=False)
                self.console.print(f"  {describe_server(cfg)}", markup=False, highlight=False)
                allowed = Confirm.ask("It comes from the repository and runs on this machine. Start it?",
                                      default=False, console=self.console)
                set_project_approval(root, name, cfg, allowed)
                if not allowed:
                    self.console.print("[dim]Remembered; you won't be asked again unless that entry changes.[/dim]")
            if allowed:
                approved[name] = _expand_vars(cfg)
        return approved

    def _connect_mcp_servers(self, servers: dict[str, dict[str, Any]]) -> None:
        """Start the MCP servers from settings and plugins, registering their tools as mcp__<server>__<tool>."""
        if not servers:
            return
        clients, errors = connect_servers(servers, Path.cwd())
        self._mcp_errors = {**{k: v for k, v in self._mcp_errors.items() if k not in servers}, **errors}
        from src.security import skill_scan
        for name in list(clients):
            verdict = skill_scan.check_mcp(name, clients[name].tools)
            if verdict.blocked:
                clients.pop(name)
                self.console.print(f"[red]MCP server '{name}' held back: the security scan says {verdict.recommendation} "
                                   f"(risk {verdict.score}).[/red] /skills scan shows why; /skills allow mcp:{name} lets it in.")
            elif verdict.recommendation == skill_scan.CAUTION:
                self.console.print(f"[yellow]MCP server '{name}': the security scan says CAUTION (risk {verdict.score}); /skills scan shows why.[/yellow]")
        self.tool_context.mcp_clients = {**(self.tool_context.mcp_clients or {}), **clients}
        for warning in register_mcp_tools(self.tool_registry, clients):
            self.console.print(f"[yellow]{warning}[/yellow]", markup=True, highlight=False)
        for name, error in errors.items():
            trace.record("mcp_error", server=name, error=error)
            self.console.print(f"[yellow]MCP server '{name}' not connected: {error}[/yellow]", markup=True)

    # -- a turn --------------------------------------------------------------------------------------
    def send(self, text: str, *, images: Iterable[ImageContentBlock] = (), max_turns: int | None = None,
             max_tokens: int | None = None, on_text: TextListener | None = None, on_thinking: TextListener | None = None,
             on_event: EventListener | None = None) -> AgentLoopResult | None:
        """turn(), for a front end with no terminal: a failure is kept in `last_error` and logged to the console, an
        interrupt (KeyboardInterrupt) passes through to the caller, and the session is saved either way."""
        try:
            return self.turn(text, images=images, max_turns=max_turns, max_tokens=max_tokens, on_text=on_text,
                             on_thinking=on_thinking, on_event=on_event)
        except Exception as e:   # pylint: disable=broad-exception-caught  # any failure is the turn's error, reported to the caller
            self.last_error = str(e) or type(e).__name__
            hint = " (fix the key with clyde login)" if is_auth_error(e) and "clyde login" not in str(e) else ""
            self.console.print(f"[red]❌ {e}[/red]{hint}")
            return None
        finally:
            self.autosave()

    def turn(self, text: str, *, images: Iterable[ImageContentBlock] = (), max_turns: int | None = None,
             max_tokens: int | None = None, on_text: TextListener | None = None, on_thinking: TextListener | None = None,
             on_event: EventListener | None = None) -> AgentLoopResult | None:
        """Send one user message and run the model (and its tools) until it answers. Returns the turn's result, or None
        when a short chat-like prompt was answered by a direct streamed reply. Raises what the provider raises."""
        self.start_turn(text, images)
        return self.answer(max_turns=max_turns, max_tokens=max_tokens, on_text=on_text, on_thinking=on_thinking,
                           on_event=on_event)

    def start_turn(self, text: str, images: Iterable[ImageContentBlock] = ()) -> None:
        """Before the model runs: compact a nearly full conversation, mark the checkpoint and add the user's message."""
        self.last_result, self.last_error = None, None
        activity.clear()
        trace.record("turn", provider=self.provider_name, model=self.model, prompt_chars=len(text))
        self._maybe_auto_compact()
        self.checkpoints.begin(text, len(self.session.conversation.messages))
        images = list(images)
        if images and self.reads_images() is False:
            self.console.print(Text(f"Sent without the image{'s' if len(images) > 1 else ''}: "
                                    f"{model_ref(self.provider, self.model)} can't read images.", style=DIM))
            images = []
        self.session.conversation.add_user_message(text, images)
        begin_turn(self.provider, mode=self.mode, on_deal=self._show_deal, investigate=self._investigate)

    def answer(self, *, max_turns: int | None = None, max_tokens: int | None = None, on_text: TextListener | None = None,
               on_thinking: TextListener | None = None, on_event: EventListener | None = None) -> AgentLoopResult | None:
        """Run the model on the message start_turn() added (see turn())."""
        if max_turns is None:
            max_turns = load_config().get("session", {}).get("max_tool_turns", 20)
        messages = self.session.conversation.messages
        prompt = messages[-1].content if messages and isinstance(messages[-1].content, str) else ""
        if self._should_try_direct_stream(prompt):
            activity.set(f"waiting for {model_ref(self.provider, self.model)}")
            if self._stream_direct_response(on_text, on_thinking) is not None:
                return None
        log = _ToolLog(self.console, self.shorten_path_text)

        def events(ev: ToolEvent) -> None:
            if on_event is not None:
                on_event(ev)
            log(ev)

        def play() -> AgentLoopResult:
            return run_agent_loop(conversation=self.session.conversation, provider=self.provider, model=self.model,
                                  tool_registry=self.tool_registry, tool_context=self.tool_context, max_turns=max_turns,
                                  stream=self.stream, verbose=False, on_event=events,
                                  on_text_chunk=on_text if self.stream else None, reasoning=self.reasoning,
                                  on_thinking=on_thinking, steer=self.control.take_steer, system_extra=self.system_extra,
                                  max_tokens=max_tokens)

        result = play()
        # cardShuffle: a model stuck in its tool loop hands the turn to the next card.
        while result.ran_out and retry_elsewhere(self.provider, f"{served_by(self.provider)} hit max tool turns"):
            result = play()
        self.last_result = result
        trace.record("turn_end", ran_out=result.ran_out, rounds=result.num_turns,
                     model=served_by(self.provider) or model_ref(self.provider, self.model))
        # Spend per real model that served the turn (a router reports each one it dealt).
        for ref, usage in turn_spend(self.provider, model_ref(self.provider, self.model), result.usage):
            provider_name, _, model = ref.partition(":")
            if usage.get("input_tokens", 0) or usage.get("output_tokens", 0):
                self.cost_tracker.record_usage(provider_name, model, usage, label=f"turn_{result.num_turns}_tokens")
        return result

    def _maybe_auto_compact(self) -> None:
        """Compact the conversation before a turn when it, with the last request's fixed part, nears the context window."""
        if not needs_auto_compact(self.session.conversation, self.context_window(), self.tool_context.prompt_overhead):
            return
        self._before_compaction()
        self.console.print("[dim]Context is nearly full; compacting the conversation...[/dim]")
        activity.set("compacting the conversation")
        try:
            with self._compacting():
                result = compact_conversation(self.session.conversation, self.provider, self.model, trigger="auto")
        except Exception as e:
            self.console.print(f"[yellow]Auto-compact failed: {e}[/yellow]")
            return
        self.console.print(f"[green]{result.user_display_message}[/green]")

    def _before_compaction(self) -> None:
        """Hook: the terminal runs Auto-refine here, on the messages compaction is about to summarise away."""

    def _compacting(self) -> contextlib.AbstractContextManager:
        """Hook: what wraps the compaction call (the terminal shows a spinner)."""
        return contextlib.nullcontext()

    def _show_deal(self, ref: str, why: str) -> None:
        """cardShuffle's note on which real model plays this turn, and why."""
        self.console.print(Text.assemble(("♠ dealt ", ACCENT), (ref, TEXT), (f"  {why}", DIM)), highlight=False)

    def _investigate(self, provider: Any, model: str, cancel: threading.Event) -> ProviderResponse:
        """A council member's answer: it reads the repo on a copy of this conversation in plan mode (read-only tools, nobody to
        answer a permission prompt, so anything that would ask is denied) and its final text is the answer."""
        context = dataclasses.replace(self.tool_context, plan_mode=True, read_file_fingerprints={}, todos=[],
                                      permission_handler=_deny, ask_user=None)
        tools = ToolRegistry([self.tool_registry.get(s.name) for s in self.tool_registry.list_specs() if s.name.lower() not in NO_NESTING])
        result = run_agent_loop(copy.deepcopy(self.session.conversation), provider, model, tools, context,
                                max_turns=_COUNCIL_MAX_TURNS, cancel=cancel, reasoning=self.reasoning, system_extra=self.system_extra)
        if result.ran_out:
            raise ProviderError(provider.name, "ran out of reading turns")
        return ProviderResponse(message=Message.assistant(result.response_text), raw={}, usage=result.usage)

    def _should_try_direct_stream(self, user_input: str) -> bool:
        if not self.stream or not self.direct_stream:
            return False
        text = user_input.strip().lower()
        if not text or text.startswith("/") or len(text) > 240:
            return False
        code_task_markers = (
            "/", "\\", "src/", "tests/", ".py", ".ts", ".md",
            "file", "files", "read", "write", "edit", "modify", "change",
            "search", "grep", "glob", "bash", "shell", "command", "run",
            "test", "fix", "bug", "refactor", "repo", "repository",
            "project", "workspace", "folder", "directory", "function",
            "class", "module", "code", "implementation", "readme",
            "pyproject", "package.json", "git", "commit", "diff", "tool",
        )
        return not any(marker in text for marker in code_task_markers)

    def _stream_direct_response(self, on_text_chunk: TextListener | None = None,
                                on_thinking: TextListener | None = None) -> str | None:
        """Stream a tool-free reply for a conversational prompt. Returns None (so the caller falls
        back to the agent loop) when streaming fails before any text arrives, unless the failure
        is an auth error, which is raised so the user can fix the key."""
        style_prompt = resolve_output_style(self.tool_context.output_style_name, self.tool_context.output_style_dir).prompt
        if self.system_extra:
            style_prompt += "\n\n" + self.system_extra
        streamed_chunks: list[str] = []

        def emit(chunk: str) -> None:
            if not chunk:
                return
            streamed_chunks.append(chunk)
            if on_text_chunk is not None:
                on_text_chunk(chunk)

        try:
            request = to_canonical(self.session.conversation, style_prompt, flatten_tools=True)
            response = trace.model_call(self.provider, self.model, request, lambda: self.provider.stream(
                request, self.model, (), emit, reasoning=self.reasoning, on_thinking=on_thinking))
        except Exception as e:
            if streamed_chunks or is_auth_error(e):
                raise
            return None
        if not streamed_chunks:
            return None
        append_response(self.session.conversation, response.message)
        return response.message.text or "".join(streamed_chunks)

    def shorten_path_text(self, text: str) -> str:
        """Paths under the workspace as ./relative ones, for progress lines."""
        root = str(self.tool_context.workspace_root)
        cwd = str(self.tool_context.cwd or self.tool_context.workspace_root)
        for base in (cwd, root):
            prefix = base.rstrip("/") + "/"
            if text.startswith(prefix):
                return "./" + text[len(prefix):]
            text = text.replace(prefix, "")
        return text


class _ToolLog:
    """The progress lines a turn prints for its tool calls: `• Bash (ls) running...` then `↳ result · 0.4s`."""

    def __init__(self, console: Console, shorten: Callable[[str], str]) -> None:
        self.console, self.shorten = console, shorten
        self.started: dict[str, float] = {}

    def __call__(self, ev: ToolEvent) -> None:
        if ev.kind == "tool_use":
            self.started[ev.tool_use_id or ev.tool_name] = time.monotonic()
            summary = summarize_tool_use(ev.tool_name, ev.tool_input or {})
            summary = self.shorten(summary) if isinstance(summary, str) and summary else summary
            suffix = f" [dim]({summary})[/dim]" if summary else ""
            self.console.print(f"[dim]•[/dim] [{ACCENT}]{ev.tool_name}[/{ACCENT}]{suffix} [dim]running...[/dim]")
        elif ev.kind == "tool_result":
            began = self.started.pop(ev.tool_use_id or ev.tool_name, None)
            took = f" · {duration(time.monotonic() - began)}" if began is not None else ""
            if ev.is_error:
                if _recoverable_tool_error(ev.tool_name, ev.tool_output):
                    return
                output = ev.tool_output
                msg = output["error"] if isinstance(output, dict) and isinstance(output.get("error"), str) else ""
                if not msg:   # e.g. a command that exited non-zero: show its exit code and last line
                    msg = str(summarize_tool_result(ev.tool_name, output) or "").removeprefix(f"{ev.tool_name} · ")
                self.console.print(Text(f"  ↳ {msg or 'Error'}{took}", style="#d0202f"))
                return
            msg = summarize_tool_result(ev.tool_name, ev.tool_output)
            if isinstance(msg, str):
                msg = self.shorten(msg.removeprefix(f"{ev.tool_name} · "))
            self.console.print(Text(f"  ↳ {msg}{took}", style=DIM))
            problems = ev.tool_output.get("newProblems") if isinstance(ev.tool_output, dict) else None
            if isinstance(problems, str):
                self.console.print("  ↳ " + problems.replace("\n", "\n    "), style="yellow", markup=False)
        elif ev.kind == "tool_error":
            self.console.print(f"[red]  ↳ {ev.error or 'Error'}[/red]")
