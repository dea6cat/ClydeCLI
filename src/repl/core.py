"""Interactive REPL for ClydeCLI."""

from __future__ import annotations

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.styles import Style
    from prompt_toolkit.completion import WordCompleter
    try:
        from prompt_toolkit.completion import FuzzyCompleter
    except Exception:  # pragma: no cover
        FuzzyCompleter = None  # type: ignore
    from prompt_toolkit.key_binding import KeyBindings
except ModuleNotFoundError:  # pragma: no cover
    class FileHistory:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

    class AutoSuggestFromHistory:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

    class Style:  # type: ignore
        @staticmethod
        def from_dict(*args, **kwargs):
            return None

    class WordCompleter:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
    FuzzyCompleter = None  # type: ignore

    class KeyBindings:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

    class PromptSession:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

        def prompt(self, *args, **kwargs):
            raise EOFError()

try:
    from rich.console import Console, Group
    from rich.align import Align
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.markdown import Markdown
    from rich.columns import Columns
except ModuleNotFoundError:  # pragma: no cover
    class Console:  # type: ignore
        def print(self, *args, **kwargs):
            return None

    Group = None  # type: ignore
    Align = None  # type: ignore
    Panel = None  # type: ignore
    Table = None  # type: ignore
    Text = None  # type: ignore
    Columns = None  # type: ignore

    class Markdown:  # type: ignore
        def __init__(self, text: str):
            self.text = text
from pathlib import Path
import asyncio
import sys
import json
from datetime import datetime
from typing import Any

from src.agent import Session
from src.compact_service.service import auto_compact_threshold, compact_conversation, needs_auto_compact
from src.context_system.context_analyzer import get_context_window_for_model
from src.config import get_default_model, load_config, set_default_model
from src.output_styles import resolve_output_style
from src.providers import build_registry, keys, model_ref, pick_default_model, resolve, usable
from src.providers import catalog
from src.providers.base import ProviderError, is_auth_error
from src.providers.convert import append_response, to_canonical
from src.tool_system.context import ToolContext
from src.tool_system.hooks import load_hooks
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall
from src.tool_system.tools.cron import pop_due_jobs
from src.agent.agent_loop import ToolEvent, run_agent_loop, summarize_tool_result, summarize_tool_use

# New command system imports
from src.command_system import (
    CommandRegistry,
    CommandResult,
    create_command_context,
    execute_command_async,
    execute_command_sync,
    register_builtin_commands,
)
from src.agent.cost_tracker import CostTracker
from src.agent.history import HistoryLog

_RESUME_SHOWN = 20   # sessions listed by the /resume picker
_PREVIEW_CHARS = 80


def _message_text(message) -> str:
    """The plain text of a stored message; tool calls and results contribute nothing."""
    if isinstance(message.content, str):
        return message.content.strip()
    return " ".join(b.text for b in message.content if getattr(b, "type", None) == "text").strip()


def _preview(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= _PREVIEW_CHARS else line[:_PREVIEW_CHARS - 1] + "…"


def _first_prompt(session) -> str:
    for message in session.conversation.messages:
        if message.role == "user" and (text := _message_text(message)):
            return _preview(text)
    return "(no prompt)"


# Returned by the prompt when the cron watcher interrupts an idle prompt to run a due job.
_CRON_WAKE = object()


class ClydeREPL:
    """Interactive REPL for ClydeCLI."""

    def __init__(self, model: str | None = None, stream: bool = False,
                 resume: str | None = None, continue_last: bool = False):
        self.console = Console()
        self.stream = stream
        self._startup_resume = resume   # "" opens the picker, an id loads that session
        self._continue_last = continue_last
        self.auto_save = load_config().get("session", {}).get("auto_save", True)
        self.multiline_mode = False
        self.reasoning: str | None = None   # /think level; None keeps each model's default

        keys.load_into_env()
        self.registry = build_registry()
        resolved = self._startup_model(model)
        if resolved is None:
            sys.exit(1)
        self.provider, self.model = resolved
        self.provider_name = self.provider.name

        # Create session
        self.session = Session.create(self.provider_name, self.model)

        self.tool_registry = build_default_registry()
        self.tool_context = ToolContext(workspace_root=Path.cwd(), hooks=load_hooks())
        self.tool_context.ask_user = self._ask_user_questions
        # Session-scoped cron: due jobs are queued here and run only between turns.
        self._cron_checked_at = datetime.now()
        self._cron_queue: list[dict[str, Any]] = []
        # Permission handler with status control for proper input handling
        self._current_status = None
        self.tool_context.permission_handler = self._handle_permission_request

        # Original built-in commands - define this FIRST!
        self._original_built_ins = [
            "/",
            "/help",
            "/exit",
            "/quit",
            "/q",
            "/clear",
            "/save",
            "/load",
            "/resume",
            "/multiline",
            "/stream",
            "/render-last",
            "/model",
            "/models",
            "/think",
            "/tools",
            "/tool",
            "/skills",
            "/init",
        ]
        self._built_in_commands = list(self._original_built_ins)

        # Initialize new command system
        self._init_command_system()

        # Prompt toolkit with tab completion
        history_file = Path.home() / ".clyde" / "history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        self.completer = WordCompleter(self._get_slash_command_words(), ignore_case=True)

        # Key bindings for multiline
        self.bindings = KeyBindings()
        if hasattr(self.bindings, "add"):
            @self.bindings.add("/")  # type: ignore[attr-defined]
            def _show_slash_completions(event):  # type: ignore[no-untyped-def]
                buf = event.current_buffer
                if buf.text == "":
                    buf.insert_text("/")
                    buf.start_completion(select_first=False)

        self.prompt_session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self.completer,
            style=Style.from_dict({
                'prompt': 'bold blue',
            }),
            key_bindings=self.bindings,
            complete_while_typing=True,
        )

    def _ask_user_questions(self, questions: list[dict]) -> dict[str, str]:
        # Stop the Rich status spinner if running, so we can get clean input
        if self._current_status is not None:
            try:
                self._current_status.stop()
            except Exception:
                pass

        answers: dict[str, str] = {}
        for q in questions:
            question_text = str(q.get("question", "")).strip()
            options = q.get("options") or []
            multi = bool(q.get("multiSelect", False))
            if not question_text or not isinstance(options, list) or len(options) < 2:
                continue

            self.console.print(f"\n[bold]{question_text}[/bold]")
            labels: list[str] = []
            for i, opt in enumerate(options, start=1):
                label = str((opt or {}).get("label", "")).strip()
                desc = str((opt or {}).get("description", "")).strip()
                labels.append(label)
                self.console.print(f"  {i}. {label}  [dim]{desc}[/dim]")
            other_idx = len(labels) + 1
            self.console.print(f"  {other_idx}. Other  [dim]Provide custom text[/dim]")

            prompt = "Select (comma-separated) > " if multi else "Select > "
            raw = input(prompt).strip()
            if not raw:
                choice_str = "1"
            else:
                choice_str = raw

            selected: list[str] = []
            parts = [p.strip() for p in choice_str.split(",") if p.strip()]
            if not parts:
                parts = ["1"]
            for part in parts:
                try:
                    idx = int(part)
                except ValueError:
                    idx = -1
                if idx == other_idx:
                    free = input("Other > ").strip()
                    if free:
                        selected.append(free)
                    continue
                if 1 <= idx <= len(labels):
                    selected.append(labels[idx - 1])
            if not selected:
                selected = [labels[0]]
            answers[question_text] = ", ".join(selected) if multi else selected[0]

        # Restart spinner after getting answers
        if self._current_status is not None:
            try:
                self._current_status.start()
            except Exception:
                pass

        return answers

    def _handle_permission_request(
        self,
        tool_name: str,
        message: str,
        suggestion: str | None,
    ) -> tuple[bool, bool]:
        """Handle interactive permission requests from tools.

        Args:
            tool_name: Name of the tool requesting permission.
            message: Message explaining what permission is needed.
            suggestion: Optional suggestion for enabling the setting.

        Returns:
            Tuple of (allowed: bool, continue_without_caching: bool).
            continue_without_caching is always False since we don't cache in REPL.
        """
        # Stop the Rich status spinner if running, so we can get clean input
        if self._current_status is not None:
            try:
                self._current_status.stop()
            except Exception:
                pass

        self.console.print("")
        self.console.print("[bold yellow]⚠ Permission Required[/bold yellow]")
        self.console.print(f"  {message}")
        self.console.print("")

        # Determine if this is a setting that can be enabled
        can_enable_setting = False
        setting_to_enable: str | None = None

        msg_lower = message.lower()
        if "allow_docs" in msg_lower or "documentation files" in msg_lower:
            pc = self.tool_context.permission_context
            if hasattr(pc, 'allow_docs') and not pc.allow_docs:
                can_enable_setting = True
                setting_to_enable = "allow_docs"

        # Build options
        options: list[tuple[str, str]] = [
            ("y", "Yes, allow this action"),
            ("n", "No, deny this action"),
        ]
        if can_enable_setting:
            options.insert(0, ("e", f"Enable {setting_to_enable} and allow"))

        self.console.print("[bold]Options:[/bold]")
        for i, (key, desc) in enumerate(options, start=1):
            self.console.print(f"  {i}. [{key}] {desc}")
        self.console.print("")

        # Get input - use standard input() which works after stopping status
        choice = input("Select option> ").strip().lower()

        # Parse choice based on the actual displayed options
        if can_enable_setting:
            # Menu: 1=Enable, 2=Yes, 3=No
            if choice in ("1", "e", "enable"):
                self._enable_permission_setting(setting_to_enable)
                return True, False
            elif choice in ("2", "y", "yes", ""):
                return True, False
            elif choice in ("3", "n", "no"):
                return False, False
        else:
            # Menu: 1=Yes, 2=No
            if choice in ("1", "y", "yes", ""):
                return True, False
            elif choice in ("2", "n", "no"):
                return False, False

        # Default to deny for invalid input
        self.console.print("[dim]Invalid choice, defaulting to deny.[/dim]")
        return False, False

    def _enable_permission_setting(self, setting_name: str | None) -> None:
        """Enable a permission setting in the tool context."""
        if not setting_name:
            return

        self.console.print(f"\n[dim]Enabling {setting_name}...[/dim]")

        if setting_name == "allow_docs":
            pc = self.tool_context.permission_context
            if hasattr(pc, 'allow_docs'):
                pc.allow_docs = True
                self.console.print(f"[green]✓ {setting_name} enabled for this session[/green]")
                return

        self.console.print(f"[dim]Could not enable {setting_name}.[/dim]")

    def _init_command_system(self):
        """Initialize the new command system."""
        # Also register to global registry so execute_command_async can find commands
        register_builtin_commands(None)  # None = use global registry

        # Create command registry and register built-ins
        self.command_registry = CommandRegistry()
        register_builtin_commands(self.command_registry)

        # Create cost tracker and history
        self.cost_tracker = CostTracker()
        self.history_log = HistoryLog()

        # Create command context
        self.command_context = create_command_context(
            workspace_root=Path.cwd(),
            conversation=self.session.conversation,
            cost_tracker=self.cost_tracker,
            history=self.history_log,
        )

        # Merge new commands with built-in list for completion
        self._update_built_in_commands_with_command_system()

    def _update_built_in_commands_with_command_system(self):
        """Update the built-in commands list with commands from the new system."""
        # Start with original built-ins
        self._built_in_commands = list(self._original_built_ins)

        # Add commands from the new command system
        try:
            for cmd in self.command_registry.list_commands():
                cmd_name = f"/{cmd.name}"
                if cmd_name not in self._built_in_commands:
                    self._built_in_commands.append(cmd_name)
                # Add aliases
                for alias in cmd.aliases:
                    alias_name = f"/{alias}"
                    if alias_name not in self._built_in_commands:
                        self._built_in_commands.append(alias_name)
        except Exception:
            pass

    def _try_execute_new_command(self, command: str, args: str) -> tuple[bool, str | None]:
        """Try to execute a command using the new command system (sync path for LocalCommand only).

        Returns:
            Tuple of (handled: bool, result_text: str | None)
        """
        try:
            success, result_text, error = execute_command_sync(
                command, args, self.command_context
            )
            if success:
                return True, result_text
            else:
                return False, error
        except Exception as e:
            return False, str(e)

    async def _try_execute_command_async(self, command: str, args: str) -> CommandResult:
        """Execute a command asynchronously, supporting both LocalCommand and PromptCommand.

        Returns:
            CommandResult with the execution result
        """
        try:
            return await execute_command_async(command, args, self.command_context)
        except Exception as e:
            return CommandResult.error(command, str(e))

    def _handle_command_result(self, result: CommandResult) -> bool:
        """Handle the result of a command execution.

        Returns True if the command was handled, False otherwise.
        """
        if not result.success:
            if result.error:
                self.console.print(f"[red]{result.error}[/red]")
            return True

        if result.result_type == "text":
            if result.text:
                self.console.print("\n" + result.text)
                self.console.print()
            return True

        elif result.result_type == "prompt":
            # For PromptCommand, extract the text content and send to LLM
            prompt_text = ""
            for item in result.prompt_content:
                if item.get("type") == "text":
                    prompt_text = item.get("text", "")
                    break

            if prompt_text:
                # Send the prompt to the LLM for interactive execution
                # Use higher max_turns for complex commands like /init
                self.console.print("[dim]Initializing workspace setup...[/dim]")
                self.chat(prompt_text, max_turns=100)
            return True

        elif result.result_type == "skip":
            # Command handled silently
            return True

        return False

    def _get_slash_command_words(self) -> list[str]:
        words = list(self._built_in_commands)
        try:
            from src.skills.loader import get_all_skills

            cwd = self.tool_context.cwd or self.tool_context.workspace_root
            for s in get_all_skills(project_root=cwd):
                words.append(f"/{s.name}")
        except Exception:
            pass
        deduped: list[str] = []
        seen: set[str] = set()
        for w in words:
            lw = w.lower()
            if lw in seen:
                continue
            seen.add(lw)
            deduped.append(w)
        return deduped

    def _refresh_completer(self) -> None:
        try:
            words = self._get_slash_command_words()
            try:
                base = WordCompleter(words, ignore_case=True, match_middle=True)
            except TypeError:
                base = WordCompleter(words, ignore_case=True)
            self.completer = FuzzyCompleter(base) if FuzzyCompleter is not None else base
            if hasattr(self, "prompt_session") and getattr(self.prompt_session, "completer", None) is not None:
                self.prompt_session.completer = self.completer
        except Exception:
            return

    def _show_slash_palette(self, query: str | None = None) -> None:
        q = (query or "").strip().lower()
        self.console.print("\n[bold]Available commands and skills:[/bold]")

        # Collect all commands
        all_commands: list[tuple[str, str, str]] = []  # (name, description, type)
        seen: set[str] = set()

        def add_command(name: str, desc: str, cmd_type: str = "command") -> None:
            if name in seen:
                return
            seen.add(name)
            if q and q not in name.lower() and q not in desc.lower():
                return
            all_commands.append((name, desc, cmd_type))

        # Add built-in commands
        for cmd in self._original_built_ins:
            if cmd == "/":
                continue
            add_command(cmd, "", "command")

        # Add commands from new command system
        try:
            for cmd in self.command_registry.list_commands():
                cmd_name = f"/{cmd.name}"
                if cmd_name in self._original_built_ins:
                    continue
                alias_str = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
                add_command(f"{cmd_name}{alias_str}", cmd.description, "command")
        except Exception:
            pass

        # Add skills
        try:
            from src.skills.loader import get_all_skills

            cwd = self.tool_context.cwd or self.tool_context.workspace_root
            skills = list(get_all_skills(project_root=cwd))
            skills.sort(key=lambda s: s.name.lower())
            for s in skills:
                desc = (s.description or "").strip()
                add_command(f"/{s.name}", desc, "skill")
        except Exception:
            pass

        # Sort and display
        all_commands.sort(key=lambda x: x[0].lower())
        for name, desc, cmd_type in all_commands:
            if cmd_type == "skill":
                self.console.print(f"  [magenta]{name}[/magenta]")
                if desc:
                    self.console.print(f"    [dim]{desc}[/dim]")
            else:
                if desc:
                    self.console.print(f"  {name}  [dim]- {desc}[/dim]")
                else:
                    self.console.print(f"  {name}")

        self.console.print()

    def _shorten_path_text(self, text: str) -> str:
        root = str(self.tool_context.workspace_root)
        cwd = str(self.tool_context.cwd or self.tool_context.workspace_root)
        for base in (cwd, root):
            prefix = base.rstrip("/") + "/"
            if text.startswith(prefix):
                return "./" + text[len(prefix):]
            text = text.replace(prefix, "")
        return text

    def _display_cwd(self) -> str:
        cwd = str(Path.cwd())
        home = str(Path.home())
        if cwd.startswith(home):
            return cwd.replace(home, "~", 1)
        return cwd

    def _truncate_middle(self, text: str, limit: int) -> str:
        if limit <= 0 or len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        head = max(1, (limit - 1) // 2)
        tail = max(1, limit - head - 1)
        return f"{text[:head]}…{text[-tail:]}"

    def _print_startup_header(self):
        from src import __version__

        display_path = self._display_cwd()
        provider_label = self.provider_name
        model_label = self.model or "Unknown model"

        mascot_ascii = "\n".join([
            "  /\\__/\\",
            " / o  o \\",
            "(  __  )",
            " \\/__/  ",
        ])

        if Panel is None or Group is None or Align is None or Table is None or Text is None or Columns is None:
            print(mascot_ascii)
            print(f"ClydeCLI v{__version__}")
            print(f"{model_label} · {provider_label}")
            print(f"{display_path}\n")
            return

        width = getattr(self.console, "width", 80)
        content_width = max(28, min(width - 12, 72))
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bright_black", justify="right", no_wrap=True)
        table.add_column(style="white", ratio=1)
        table.add_row("Version", Text.assemble(("ClydeCLI", "bold white"), ("  ", ""), (f"v{__version__}", "bold cyan")))
        table.add_row("Model", Text(model_label, style="bold magenta"))
        table.add_row("Provider", Text(provider_label, style="bold green"))
        table.add_row("Workspace", Text(self._truncate_middle(display_path, content_width - 12), style="bold blue"))

        footer = Text("/help  •  /model  •  /think  •  /stream  •  /exit", style="dim")
        mascot_block = Text(mascot_ascii, style="bold orange3", no_wrap=True)
        body = Group(
            Columns([mascot_block, table], align="center", expand=False),
            Text(""),
            Align.center(footer),
        )
        header = Panel(
            body,
            border_style="bright_black",
            title="[bold bright_cyan] CLYDE CLI [/bold bright_cyan]",
            subtitle="[dim]still here.[/dim]",
            padding=(1, 2),
        )
        self.console.print(header)
        self.console.print()

    def run(self):
        """Run the REPL."""
        self._print_startup_header()
        if self._continue_last:
            self.resume_session(latest=True)
        elif self._startup_resume is not None:
            self.resume_session(self._startup_resume)

        while True:
            try:
                if self._queue_due_cron_jobs():
                    self._run_cron_job(self._cron_queue.pop(0))
                    continue

                self._refresh_completer()
                # Dynamic prompt based on multiline mode
                # Using '❯' for a modern feel
                prompt_text = '... ' if self.multiline_mode else '❯ '
                user_input = self.prompt_session.prompt(
                    prompt_text,
                    multiline=self.multiline_mode,
                    pre_run=self._start_cron_watch,
                )
                if user_input is _CRON_WAKE:
                    continue

                if not user_input.strip():
                    self.multiline_mode = False
                    continue

                # Handle commands
                if user_input.startswith('/'):
                    self.handle_command(user_input)
                    continue

                # Send to LLM
                self.chat(user_input)
                self.multiline_mode = False

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Interrupted. Type /exit to quit.[/yellow]")
                self.multiline_mode = False
                continue
            except EOFError:
                self.console.print("\n[blue]Goodbye![/blue]")
                break

    def _queue_due_cron_jobs(self, now: datetime | None = None) -> bool:
        """Queue the scheduled jobs that came due since the last check; True if any are waiting."""
        if not self._cron_queue:
            now = now or datetime.now()
            self._cron_queue.extend(pop_due_jobs(self.tool_context.crons, self._cron_checked_at, now))
            self._cron_checked_at = now
        return bool(self._cron_queue)

    def _start_cron_watch(self) -> None:
        """While the prompt is idle and empty, wake it up when a scheduled job comes due."""
        app = self.prompt_session.app

        async def watch() -> None:
            while True:
                await asyncio.sleep(1)
                # Never clobber what the user is typing; due jobs wait until the line is empty.
                if not app.current_buffer.text and self._queue_due_cron_jobs():
                    app.exit(result=_CRON_WAKE)
                    return

        app.create_background_task(watch())

    def _run_cron_job(self, job: dict[str, Any]) -> None:
        kind = "recurring" if job.get("recurring", True) else "one-shot"
        self.console.print(f"\n⏰ Scheduled run {job['id']} ({job['cron']}, {kind}): {job['prompt']}", style="bold magenta", markup=False)
        self.chat(job["prompt"])

    def handle_command(self, command: str):
        """Handle slash commands."""
        raw = command.strip()
        if raw == "/":
            self._show_slash_palette()
            return
        if raw.startswith("/") and " " not in raw and raw.lower() not in (c.lower() for c in self._built_in_commands):
            query = raw[1:]
            if query:
                self._show_slash_palette(query=query)
                return

        # First, try the new command system
        if raw.startswith("/"):
            parts = raw[1:].split(maxsplit=1)
            cmd_name = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            # Check if this command exists in the new command system
            # but skip the ones we handle specially
            # Note: /context, /compact, /skill need special handling, don't route through new system
            # /init is handled via new command system (PromptCommand) so it's NOT in special_commands
            special_commands = {
                'exit', 'quit', 'q',
                'help', 'tools', 'tool',
                'save', 'load', 'resume', 'multiline', 'stream', 'render-last',
                'model', 'models', 'think',
                'skill',
                'context', 'compact',  # These need special handling
                ''
            }

            # Handle /init through the new command system (PromptCommand path)
            if cmd_name == 'init':
                # Use async path for PromptCommand
                try:
                    # Run async command execution in a new event loop
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            self._try_execute_command_async(cmd_name, args)
                        )
                        result = future.result()

                    if result.success:
                        self._handle_command_result(result)
                    elif result.error:
                        self.console.print(f"[red]{result.error}[/red]")
                except Exception as e:
                    self.console.print(f"[red]Error executing /init: {e}[/red]")
                return

            if cmd_name == 'doctor':
                self.command_context.config.update(provider=self.provider, model=self.model,
                                                   permission_context=self.tool_context.permission_context)

            if cmd_name not in special_commands:
                # Try to execute via new command system
                # First try sync path for LocalCommand (faster)
                try:
                    handled, result_text = self._try_execute_new_command(cmd_name, args)
                    if handled:
                        if result_text:
                            self.console.print("\n" + result_text)
                        self.console.print()
                        return
                except Exception as e:
                    # Fall through to async path
                    pass

                # Use async path for PromptCommand
                # Run in a new event loop since we're in a sync context
                try:
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            self._try_execute_command_async(cmd_name, args)
                        )
                        result = future.result()

                    if result.success:
                        if self._handle_command_result(result):
                            return
                except Exception:
                    pass

        # Fall back to original command handling
        cmd = raw.lower()

        if cmd in ['/exit', '/quit', '/q']:
            self.console.print("[blue]Goodbye![/blue]")
            sys.exit(0)

        elif cmd == '/help':
            self.show_help()

        elif cmd == '/tools':
            names = [spec.name for spec in self.tool_registry.list_specs()]
            names.sort(key=str.lower)
            self.console.print("\n[bold]Available tools:[/bold]")
            for name in names:
                self.console.print(f"  - {name}")
            self.console.print()

        elif cmd.startswith('/tool'):
            parts = command.strip().split(maxsplit=2)
            if len(parts) < 2:
                self.console.print("[red]Usage: /tool <name> <json-input>[/red]")
                return
            name = parts[1]
            payload = {}
            if len(parts) == 3:
                try:
                    payload = json.loads(parts[2])
                except json.JSONDecodeError as e:
                    self.console.print(f"[red]Invalid JSON input: {e}[/red]")
                    return
            try:
                result = self.tool_registry.dispatch(ToolCall(name=name, input=payload), self.tool_context)
            except Exception as e:
                self.console.print(f"[red]Tool error: {e}[/red]")
                return
            self.console.print("\n[bold]Tool result:[/bold]")
            self.console.print(json.dumps(result.output, indent=2, ensure_ascii=False))
            self.console.print()

        elif cmd == '/clear':
            # Try new command system first, fall back to original
            try:
                handled, result_text = self._try_execute_new_command('clear', '')
                if handled and result_text:
                    self.console.print("\n[green]" + result_text + "[/green]")
                    return
            except Exception:
                pass
            # Original implementation
            self.session.conversation.clear()
            self.console.print("[green]Conversation cleared.[/green]")

        elif cmd == '/save':
            self.save_session()

        elif cmd == '/multiline':
            self.multiline_mode = not self.multiline_mode
            status = "enabled" if self.multiline_mode else "disabled"
            self.console.print(f"[green]Multiline mode {status}.[/green]")
            if self.multiline_mode:
                self.console.print("[dim]Press Meta+Enter or Esc+Enter to submit.[/dim]")

        elif cmd == '/stream' or cmd.startswith('/stream '):
            parts = raw.split(maxsplit=1)
            if len(parts) == 1:
                status = "enabled" if self.stream else "disabled"
                self.console.print(f"[green]Stream mode {status}.[/green]")
                return

            action = parts[1].strip().lower()
            if action in {"on", "true", "1", "enable", "enabled"}:
                self.stream = True
            elif action in {"off", "false", "0", "disable", "disabled"}:
                self.stream = False
            elif action == "toggle":
                self.stream = not self.stream
            else:
                self.console.print("[red]Usage: /stream [on|off|toggle][/red]")
                return

            status = "enabled" if self.stream else "disabled"
            self.console.print(f"[green]Stream mode {status}.[/green]")

        elif cmd == '/model' or cmd.startswith('/model '):
            parts = raw.split(maxsplit=1)
            if len(parts) == 1:
                self.console.print(f"[green]Model: {model_ref(self.provider, self.model)}[/green]")
                self.console.print("[dim]Switch with /model provider:model · list with /models[/dim]")
            else:
                self._switch_model(parts[1].strip())

        elif cmd == '/models':
            self._show_models()

        elif cmd == '/think' or cmd.startswith('/think '):
            self._handle_think(raw.split(maxsplit=1)[1].strip().lower() if " " in raw else "")

        elif cmd == '/render-last':
            rendered = self._render_last_assistant_message()
            if not rendered:
                self.console.print("[yellow]No assistant response available to render.[/yellow]")

        elif cmd == '/resume' or cmd.startswith('/resume '):
            parts = raw.split(maxsplit=1)
            self.resume_session(parts[1].strip() if len(parts) > 1 else "")

        elif cmd.startswith('/load'):
            parts = command.strip().split(maxsplit=1)
            if len(parts) < 2:
                self.console.print("[red]Usage: /load <session-id>[/red]")
            else:
                session_id = parts[1]
                self.load_session(session_id)

        elif cmd == '/skill':
            self._handle_skill_command()

        elif cmd == '/context':
            # Populate command context config for context analysis
            self.command_context.config["provider"] = self.provider
            self.command_context.config["model"] = self.model
            self.command_context.config["tool_schemas"] = [
                spec.to_dict() if hasattr(spec, "to_dict") else {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": dict(spec.input_schema) if hasattr(spec.input_schema, "keys") else spec.input_schema,
                }
                for spec in self.tool_registry.list_specs()
            ]
            self.command_context.config["system_prompt"] = ""
            self.command_context.config["auto_compact_threshold"] = auto_compact_threshold(self._context_window())
            self.command_context.config["is_auto_compact_enabled"] = True
            # Try new command system
            try:
                handled, result_text = self._try_execute_new_command('context', '')
                if handled and result_text:
                    self.console.print(Markdown(result_text))
                    return
            except Exception:
                pass
            self.console.print("[yellow]/context analysis unavailable in this context.[/yellow]")

        elif cmd == '/compact':
            # Populate command context config for compact
            self.command_context.config["provider"] = self.provider
            self.command_context.config["model"] = self.model
            self.command_context.config["system_prompt"] = ""
            # Try new command system
            try:
                handled, result_text = self._try_execute_new_command('compact', '')
                if handled and result_text:
                    self.console.print("\n[green]" + result_text + "[/green]")
                    return
            except Exception:
                pass
            # Simple fallback: just clear conversation
            self.session.conversation.clear()
            self.console.print("[green]Conversation cleared.[/green]")

        else:
            if raw.startswith("/"):
                if self._try_run_skill_slash(raw):
                    return
            self.console.print(f"[red]Unknown command: {command}[/red]")

    def _try_run_skill_slash(self, raw: str) -> bool:
        text = raw.strip()
        if not text.startswith("/"):
            return False
        body = text[1:]
        if not body:
            return False
        if body.split(maxsplit=1)[0].lower() in {c.lstrip("/").lower() for c in self._built_in_commands if c != "/"}:
            return False

        parts = body.split(maxsplit=1)
        skill_name = parts[0].strip()
        args = parts[1] if len(parts) > 1 else ""
        if not skill_name:
            return False

        try:
            result = self.tool_registry.dispatch(
                ToolCall(name="Skill", input={"skill": skill_name, "args": args}),
                self.tool_context,
            )
        except Exception as e:
            self.console.print(f"[red]Skill error: {e}[/red]")
            return True

        payload = result.output if isinstance(result.output, dict) else {}
        if result.is_error or not payload.get("success"):
            err = payload.get("error") if isinstance(payload.get("error"), str) else "Unknown skill error"
            self.console.print(f"[red]{err}[/red]")
            return True

        self.console.print(f"[dim]Launching skill: {payload.get('commandName', skill_name)}[/dim]")
        meta_parts: list[str] = []
        loaded = payload.get("loadedFrom")
        if isinstance(loaded, str) and loaded:
            meta_parts.append(f"source={loaded}")
        model = payload.get("model")
        if isinstance(model, str) and model:
            meta_parts.append(f"model={model}")
        tools = payload.get("allowedTools")
        if isinstance(tools, list) and tools:
            shown = ", ".join(str(t) for t in tools[:6])
            more = f" (+{len(tools) - 6})" if len(tools) > 6 else ""
            meta_parts.append(f"tools={shown}{more}")
        if meta_parts:
            self.console.print(f"[dim]{' · '.join(meta_parts)}[/dim]")

        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            self.console.print("[red]Skill produced empty prompt[/red]")
            return True

        self.chat(prompt)
        return True

    def show_help(self):
        """Show help message."""
        help_text = """
**Available Commands:**

- `/` - Show all commands and skills
- `/help` - Show this help message
- `/exit`, `/quit`, `/q` - Exit the REPL
- `/clear`, `/reset`, `/new` - Clear conversation history
- `/save` - Save current session
- `/load <session-id>` - Load a previous session
- `/resume [session-id]` - Pick a recent session of this workspace to continue, or load one by id
- `/multiline` - Toggle multiline input mode
- `/stream [on|off|toggle]` - Toggle live response rendering
- `/render-last` - Re-render the last assistant reply as Markdown
- `/model [provider:model]` - Show or switch the model (saved as default)
- `/models` - List models from every connected provider
- `/think [off|low|medium|high|on|default]` - Set the reasoning level
- `/tools` - List available built-in tools
- `/tool <name> <json>` - Run a tool directly
- `/skills` - List all available skills
- `/init` - Create CLAUDE.md file for the project
- `/cost` - Show session cost and usage
- `/compact` - Compact conversation to save context space
- `/doctor` - Diagnose environment, config, keys and permissions

**Usage:**
- Type your message and press Enter to chat
- Use Tab for command completion
- Press Ctrl+C to interrupt current operation
- Press Ctrl+D to exit
- Use `/multiline` for multi-paragraph inputs
"""
        self.console.print(Markdown(help_text))

    def _handle_skill_command(self) -> None:
        """Handle /skill command - list all available skills."""
        try:
            from src.skills.loader import get_all_skills

            cwd = self.tool_context.cwd or self.tool_context.workspace_root
            skills = list(get_all_skills(project_root=cwd))
            skills.sort(key=lambda s: s.name.lower())

            if not skills:
                self.console.print("\n[bold]Available Skills:[/bold]")
                self.console.print("[dim]No skills found.[/dim]")
                self.console.print("[dim]Create skills in ~/.clyde/skills/ or ~/.claude/skills/ or .clyde/skills/ in your project.[/dim]")
                return

            # Group skills by source
            from collections import defaultdict
            by_source: dict[str, list] = defaultdict(list)
            for s in skills:
                loaded = getattr(s, "loaded_from", "") or "unknown"
                by_source[loaded].append(s)

            self.console.print(f"\n[bold]Available Skills ({len(skills)}):[/bold]")
            for source in sorted(by_source.keys()):
                source_skills = by_source[source]
                self.console.print(f"\n[cyan]{source.title()} Skills:[/cyan]")
                for s in source_skills:
                    desc = (getattr(s, "description", None) or "").strip()
                    user_invocable = getattr(s, "user_invocable", True)
                    inv_str = "" if user_invocable else " [dim](not user-invocable)[/dim]"
                    self.console.print(f"  [green]/{s.name}[/green]{inv_str}")
                    if desc:
                        self.console.print(f"    [dim]{desc}[/dim]")
            self.console.print()
        except Exception as e:
            self.console.print(f"[red]Error loading skills: {e}[/red]")

    def _is_recoverable_tool_error(self, tool_name: str, tool_output) -> bool:
        if not isinstance(tool_name, str):
            return False
        if not isinstance(tool_output, dict):
            return False
        name = tool_name.strip().lower()
        err = tool_output.get("error")
        if not isinstance(err, str):
            return False
        e = err.lower()
        if name == "read" and e.startswith("file not found:"):
            p = err.split(":", 2)[-1].strip()
            if "/.clyde/skills/" in p or "\\.clyde\\skills\\" in p or "/.claude/skills/" in p or "\\.claude\\skills\\" in p:
                return True
        return False

    def _should_try_direct_stream(self, user_input: str) -> bool:
        if not self.stream:
            return False
        text = user_input.strip().lower()
        if not text or text.startswith("/"):
            return False
        if len(text) > 240:
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

    def _stream_direct_response(self, on_text_chunk=None, on_thinking=None) -> str | None:
        """Stream a tool-free reply for a conversational prompt. Returns None (so the caller falls
        back to the agent loop) when streaming fails before any text arrives, unless the failure
        is an auth error, which is raised so the user can fix the key."""
        style_name = getattr(self.tool_context, "output_style_name", None)
        style_dir = getattr(self.tool_context, "output_style_dir", None)
        style_prompt = resolve_output_style(style_name, style_dir).prompt
        streamed_chunks: list[str] = []

        def emit(chunk: str) -> None:
            if not chunk:
                return
            streamed_chunks.append(chunk)
            if on_text_chunk is not None:
                on_text_chunk(chunk)

        try:
            response = self.provider.stream(
                to_canonical(self.session.conversation, style_prompt, flatten_tools=True),
                self.model,
                (),
                emit,
                reasoning=self.reasoning,
                on_thinking=on_thinking,
            )
        except Exception as e:
            if streamed_chunks or is_auth_error(e):
                raise
            return None

        if not streamed_chunks:
            return None
        append_response(self.session.conversation, response.message)
        return response.message.text or "".join(streamed_chunks)

    def _get_last_assistant_text(self) -> str | None:
        for message in reversed(self.session.conversation.messages):
            if message.role != "assistant":
                continue
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    block_type = getattr(block, "type", None)
                    if block_type == "text":
                        text = getattr(block, "text", "")
                        if isinstance(text, str) and text:
                            parts.append(text)
                joined = "".join(parts).strip()
                if joined:
                    return joined
        return None

    def _render_last_assistant_message(self) -> bool:
        text = self._get_last_assistant_text()
        if not text:
            return False
        self.console.print("\n[bold]Last Assistant Response[/bold]")
        self.console.print(Markdown(text))
        self.console.print()
        return True

    def _context_window(self) -> int:
        """The model's input window: the provider's own sizing, then the catalog, then a name heuristic."""
        provider_window = getattr(self.provider, "context_window", None)
        if callable(provider_window):
            return provider_window(self.model)
        return catalog.context_window(self.model) or get_context_window_for_model(self.model)

    def _maybe_auto_compact(self) -> None:
        """Compact the conversation before a turn when it nears the context window."""
        if not needs_auto_compact(self.session.conversation, self._context_window()):
            return
        self.console.print("[dim]Context is nearly full; compacting the conversation...[/dim]")
        try:
            result = asyncio.run(compact_conversation(self.session.conversation, self.provider, self.model, trigger="auto"))
        except Exception as e:
            self.console.print(f"[yellow]Auto-compact failed: {e}[/yellow]")
            return
        self.console.print(f"[green]{result.user_display_message}[/green]")

    def chat(self, user_input: str, max_turns: int = 20):
        """Send message to LLM and display response.

        Args:
            user_input: The user message to send.
            max_turns: Maximum number of tool call turns (default 20, higher for complex commands).
        """
        self._maybe_auto_compact()
        # Add user message
        self.session.conversation.add_user_message(user_input)

        try:
            self.console.print("\n[bold]Assistant[/bold]")

            stream_started = False

            def _stop_status_once() -> None:
                nonlocal stream_started
                if self._current_status is not None and not stream_started:
                    try:
                        self._current_status.stop()
                    except Exception:
                        pass
                stream_started = True

            def on_event(ev: ToolEvent) -> None:
                if ev.kind == "tool_use":
                    summary = summarize_tool_use(ev.tool_name, ev.tool_input or {})
                    if isinstance(summary, str) and summary:
                        summary = self._shorten_path_text(summary)
                    suffix = f" [dim]({summary})[/dim]" if summary else ""
                    self.console.print(f"[dim]•[/dim] [cyan]{ev.tool_name}[/cyan]{suffix} [dim]running...[/dim]")
                    return
                if ev.kind == "tool_result":
                    if ev.is_error:
                        if self._is_recoverable_tool_error(ev.tool_name, ev.tool_output):
                            return
                        msg = ""
                        if isinstance(ev.tool_output, dict) and isinstance(ev.tool_output.get("error"), str):
                            msg = ev.tool_output["error"]
                        self.console.print(f"[red]  ↳ {msg or 'Error'}[/red]")
                        return
                    msg = summarize_tool_result(ev.tool_name, ev.tool_output)
                    if isinstance(msg, str):
                        prefix = f"{ev.tool_name} · "
                        if msg.startswith(prefix):
                            msg = msg[len(prefix):]
                        msg = self._shorten_path_text(msg)
                    self.console.print(f"[dim]  ↳ {msg}[/dim]")
                    return
                if ev.kind == "tool_error":
                    msg = ev.error or "Error"
                    self.console.print(f"[red]  ↳ {msg}[/red]")

            thinking_open = False

            def on_thinking(chunk: str) -> None:
                nonlocal thinking_open
                if not chunk:
                    return
                _stop_status_once()
                thinking_open = True
                self.console.print(chunk, end="", style="dim italic", markup=False, highlight=False, soft_wrap=True)

            def on_text_chunk(chunk: str) -> None:
                nonlocal thinking_open
                if not chunk:
                    return
                _stop_status_once()
                if thinking_open:
                    self.console.print("\n")
                    thinking_open = False
                self.console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

            if self._should_try_direct_stream(user_input):
                self._current_status = self.console.status("[dim]Thinking...[/dim]", spinner="dots")
                with self._current_status:
                    direct_response = self._stream_direct_response(on_text_chunk=on_text_chunk,
                                                                   on_thinking=on_thinking)
                self._current_status = None
                if direct_response is not None:
                    self.console.print("\n")
                    return

            # Use agent loop with tools for any provider that supports it
            self._current_status = self.console.status("[dim]Thinking...[/dim]", spinner="dots")
            with self._current_status:
                result = run_agent_loop(
                    conversation=self.session.conversation,
                    provider=self.provider,
                    model=self.model,
                    tool_registry=self.tool_registry,
                    tool_context=self.tool_context,
                    max_turns=max_turns,
                    stream=self.stream,
                    verbose=False,
                    on_event=on_event,
                    on_text_chunk=on_text_chunk if self.stream else None,
                    reasoning=self.reasoning,
                    on_thinking=on_thinking,
                )
            self._current_status = None

            # Record usage to cost tracker
            if result.usage:
                input_tokens = result.usage.get("input_tokens", 0)
                output_tokens = result.usage.get("output_tokens", 0)
                if input_tokens > 0 or output_tokens > 0:
                    self.cost_tracker.record_usage(
                        self.provider_name, self.model, result.usage,
                        label=f"turn_{result.num_turns}_tokens",
                    )
                    # Also update command context for new commands
                    if hasattr(self, 'command_context') and self.command_context:
                        self.command_context.cost_tracker = self.cost_tracker

            if self.stream and stream_started:
                self.console.print()
                self.console.print()
            else:
                self.console.print(Markdown(result.response_text))
                self.console.print("\n")

        except Exception as e:
            self._current_status = None
            if is_auth_error(e):
                self.console.print(f"\n[red]❌ {e}[/red]")
                from rich.prompt import Prompt
                choice = Prompt.ask(
                    "\nWould you like to reconfigure your API key now?",
                    choices=["y", "n"],
                    default="y"
                )
                if choice == "y":
                    self._handle_relogin()
                else:
                    self.console.print("\n[dim]You can run [bold]clyde login[/bold] later to update your API key.[/dim]")
            elif isinstance(e, ProviderError):
                self.console.print(f"\n[red]❌ {e}[/red]")
            else:
                self.console.print(f"\n[red]Error: {e}[/red]")
                import traceback
                traceback.print_exc()
        finally:
            self._autosave_session()

    def _autosave_session(self) -> None:
        """Persist the session after each turn so /resume and --continue have something to load."""
        if not self.auto_save or not self.session.conversation.messages:
            return
        try:
            self.session.save()
        except OSError as e:
            self.console.print(f"[yellow]Couldn't auto-save the session: {e}[/yellow]")

    def _startup_model(self, requested: str | None):
        """(provider, model) to start with. An explicit --model must resolve. Otherwise the saved
        default is used when it works, and if it doesn't (or none is saved) a model is picked
        from whatever is connected, so an exported API key is enough; no login required."""
        if requested:
            return self._resolve_model(requested)
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

    def _resolve_model(self, requested: str):
        """(provider, model) for a model string, or None after explaining why it didn't resolve."""
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

    def _switch_model(self, requested: str) -> bool:
        resolved = self._resolve_model(requested)
        if resolved is None:
            return False
        self.provider, self.model = resolved
        self.provider_name = self.provider.name
        self.session.provider, self.session.model = self.provider_name, self.model
        ref = model_ref(self.provider, self.model)
        set_default_model(ref)
        self.console.print(f"[green]Model: {ref}[/green] [dim](saved as default)[/dim]")
        return True

    def _show_models(self) -> None:
        live = usable(self.registry)
        if not live:
            self.console.print("[yellow]No providers connected.[/yellow] Run [bold]clyde login[/bold], "
                               "or start Ollama for local models.")
            return
        current = model_ref(self.provider, self.model)
        with self.console.status("[dim]Fetching model lists...[/dim]", spinner="dots"):
            listings = {name: p.list_models() for name, p in live.items()}
        for name, models in listings.items():
            self.console.print(f"\n[bold cyan]{name}[/bold cyan]")
            if not models:
                self.console.print("  [dim](couldn't list models; check the key or connection)[/dim]")
                continue
            for m in models:
                ref = f"{name}:{m}"
                marker = "[green]●[/green]" if ref == current else " "
                self.console.print(f"  {marker} {ref}")
        self.console.print()

    _THINK_LEVELS = ("off", "low", "medium", "high", "on")

    def _handle_think(self, arg: str) -> None:
        if not arg:
            level = self.reasoning or "default"
            self.console.print(f"[green]Reasoning: {level}[/green]")
            self.console.print("[dim]Set with /think off|low|medium|high|on|default[/dim]")
            return
        if arg == "default":
            self.reasoning = None
        elif arg in self._THINK_LEVELS:
            self.reasoning = arg
        else:
            self.console.print("[red]Usage: /think off|low|medium|high|on|default[/red]")
            return
        self.console.print(f"[green]Reasoning: {self.reasoning or 'default'}[/green]")
        supports = getattr(self.provider, "supports_reasoning", None)
        if self.reasoning and callable(supports) and not supports(self.model):
            self.console.print(f"[dim]{self.model} doesn't expose a reasoning control; the setting is ignored.[/dim]")

    def _handle_relogin(self):
        """Handle re-authentication when an API key fails."""
        from src.cli import run_login_flow

        self.console.print("\n[bold blue]🔑 Reconfigure API Key[/bold blue]\n")
        ref = run_login_flow(self.console, self.registry, default_provider=self.provider_name)
        if ref is None:
            return
        self.registry = build_registry()   # a new key can add providers (e.g. Ollama Cloud)
        if self._switch_model(ref):
            self.console.print("[green]✓ You can continue chatting![/green]\n")

    def save_session(self):
        """Save current session."""
        self.session.save()
        self.console.print(f"[green]Session saved: {self.session.session_id}[/green]")

    def load_session(self, session_id: str):
        """Load a previous session.

        Args:
            session_id: Session ID to load
        """
        try:
            loaded_session = Session.load(session_id)
        except (OSError, ValueError, KeyError) as e:
            self.console.print(f"[red]Couldn't read session {session_id}: {e}[/red]")
            return
        if loaded_session is None:
            self.console.print(f"[red]Session not found: {session_id}[/red]")
            return
        self._switch_session(loaded_session)

    def resume_session(self, session_id: str = "", latest: bool = False) -> None:
        """Load a session by id, continue the latest one (`latest`), or pick from this workspace's recent sessions."""
        if session_id:
            self.load_session(session_id)
            return
        sessions = [s for s in Session.list_recent(str(self.tool_context.workspace_root))
                    if s.session_id != self.session.session_id]
        if not sessions:
            self.console.print("[yellow]No saved sessions for this workspace.[/yellow]")
            return
        if latest:
            self._switch_session(sessions[0])
            return

        shown = sessions[:_RESUME_SHOWN]
        self.console.print("\n[bold]Recent sessions:[/bold]")
        for i, s in enumerate(shown, start=1):
            when = s.updated_at[:16].replace("T", " ")
            self.console.print(f"  {i:>2}. {when}  {len(s.conversation.messages):>3} msgs  ", end="")
            self.console.print(_first_prompt(s), markup=False, highlight=False)
        try:
            raw = input("Resume which session? (number, Enter to cancel) > ").strip()
        except EOFError:
            raw = ""
        if not raw:
            return
        if not raw.isdigit() or not 1 <= int(raw) <= len(shown):
            self.console.print(f"[red]No session numbered {raw}.[/red]")
            return
        self._switch_session(shown[int(raw) - 1])

    def _switch_session(self, loaded_session) -> None:
        saved_model = f"{loaded_session.provider}:{loaded_session.model}"
        self.session = loaded_session
        self.command_context.conversation = loaded_session.conversation   # /clear, /compact act on it
        # Keep the model in use: the saved one may not be connected any more.
        loaded_session.provider, loaded_session.model = self.provider_name, self.model
        self._print_resume_recap(saved_model)

    def _print_resume_recap(self, saved_model: str) -> None:
        messages = self.session.conversation.messages
        tool_calls = sum(1 for m in messages if isinstance(m.content, list)
                         for b in m.content if getattr(b, "type", None) == "tool_use")
        self.console.print(f"[green]Resumed session {self.session.session_id}[/green] "
                           f"[dim]· {len(messages)} messages · {tool_calls} tool calls · was {saved_model}[/dim]")
        exchanges = [(m.role, text) for m in messages
                     if m.role in ("user", "assistant") and (text := _message_text(m))]
        for role, text in exchanges[-4:]:
            label = "You" if role == "user" else "Clyde"
            self.console.print(f"  {label}: {_preview(text)}", style="dim", markup=False, highlight=False)
        self.console.print()
