"""Interactive REPL for ClydeCLI."""

from __future__ import annotations

from src.config import clyde_home

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.styles import Style
    from prompt_toolkit.completion import Completer, Completion, WordCompleter
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
    Completer = Completion = None  # type: ignore

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
import base64
import os
import random
import copy
import dataclasses
import threading
import time
from contextlib import contextmanager
import re
import sys
import json
from datetime import datetime
from typing import Any

from src.agent import Session, trace
from src.agent.checkpoints import Checkpoints
from src.agent.conversation import ImageContentBlock
from src.compact_service.service import auto_compact_threshold, compact_conversation, needs_auto_compact
from src.context_system.context_analyzer import get_context_window_for_model
from src.config import get_default_model, get_output_style, load_config, set_default_model, set_output_style
from src.output_styles import resolve_output_style
from src.providers import build_registry, keys, model_ref, pick_default_model, resolve, usable
from src.providers import catalog
from src.providers.model_eval import hidden_refs
from src.vitals import line, sample
from src.providers.base import ProviderError, ProviderResponse, is_auth_error
from src.providers.types import Message
from src.providers import laya_client
from src.providers.card_shuffle import CardShuffle, record_vote
from src.run_control import RunControl
from src.providers.convert import append_response, to_canonical
from src.tool_system.context import ToolContext
from src.tool_system.registry import ToolRegistry
from src.plugins import apply_plugins
from src.tool_system.hooks import load_hooks
from src import activity
from src.picker import Choice, pick
from src.tool_system.deferral import advertised
from src.repl.esc import WATCHER
from src.repl.images import IMAGE_TYPES, MAX_IMAGE_BYTES, clipboard_image, image_path, shrink
from src.tool_system.permission_rules import load_rules, save_allow_rule
from src.tool_system.tools.code_map import start_background_refresh
from src.tool_system.mcp_client import McpServerTool, connect_servers, load_servers
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall
from src.tool_system.tools.cron import pop_due_jobs
from src.agent.agent_loop import MAX_TURNS_REPLY, ToolEvent, run_agent_loop, summarize_tool_result, summarize_tool_use

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
from src.tool_system import plan_file as plans
from src.tool_system.plan_file import plan_file_for
from src.agent.history import HistoryLog

# Pastes longer than this collapse to a [Pasted text #N +X lines] marker in the prompt.
_PASTE_MAX_LINES = 2
_PASTE_MAX_CHARS = 800
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


def _one_line(text: str, limit: int) -> str:
    """`text` on one line, cut to `limit` characters with an ellipsis."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _first_prompt(session) -> str:
    for message in session.conversation.messages:
        if message.role == "user" and (text := _message_text(message)):
            return _preview(text)
    return "(no prompt)"


# Returned by the prompt when the cron watcher interrupts an idle prompt to run a due job.
_CRON_WAKE = object()


# Ace of spades by ejm (artist signature left off the card).
_ACE_OF_SPADES = (
    " ______ ",
    "|A /\\  |",
    "| /  \\ |",
    "|(    )|",
    "|  )(  |",
    "|_____V|",
)


# Playing-card palette, as exact colours so every terminal theme shows the same card.
_CARD_FACE, _CARD_INK, _CARD_ACCENT, _CARD_DIM, _CARD_TEXT = "#f5f1e8", "#111111", "#4eba65", "#8a8a8a", "#e8e4dc"
_COUNCIL_MAX_TURNS = 12   # reading turns a council member gets before it must answer


def _ace_of_spades_card() -> Text:
    """The card as an ivory face with black ink, framed like a card edge."""
    card = Text(no_wrap=True)
    for i, line in enumerate(_ACE_OF_SPADES):
        if i:
            card.append("\n")
        if i == 0:
            card.append(line, style=_CARD_FACE)
            continue
        card.append(line[0], style=_CARD_FACE)
        card.append(line[1:-1], style=f"bold {_CARD_INK} on {_CARD_FACE}")
        card.append(line[-1], style=_CARD_FACE)
    return card


_HELP_TEXT = """
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
- `/model [provider:model]` - Pick a model with the arrow keys (type to filter), or switch to the one named; saved as default
- `/models [all|refresh]` - Same picker as /model (hides ones /eval showed don't work; all shows them, refresh re-fetches the lists)
- `/models local [best|ollama|hf|mlx] [words]` - Find local models on ollama.com and Hugging Face (GGUF, MLX on Apple Silicon) that fit this machine, rated relax / balance / hard, and download one
- `/tune [--ask]` - Find the best Ollama setup for how you use it, keeping quality (the same as `clyde tune`)
- `/laya` - Laya's status, and how its stuck checks and difficulty scores lined up with how traced turns ended
- `/council [up N|down N]` - Show every answer from the last cardShuffle council turn with Laya's score, or vote one up or down (votes stay on this machine)
- `/status` - Show the model, mode, directory, session, goal and token totals
- `/goal [text|plan|clear]` - Set a goal for this session (kept in the system prompt every turn), show it, or clear it; `plan` makes it "every phase of the saved plan is complete"
- `/remember [project] TEXT` - Keep a note between sessions, about you (default) or this project; `/memory` lists the notes, `/forget [project] N` drops one; the model can save one too when you ask it to remember
- `/plan [done|start|pending N|clear]` - Show the saved plan and its phases; set phase N's status; or delete the plan
- `/terse [on|off]` - Shorter replies (fewer tokens, quicker on local models); bare opens a picker; saved
- `/purge [name]` - Delete local models (Ollama and LM Studio) from disk, all of them or only those matching name; asks first
- `/eval [filter]` - Test the listed models (or those matching filter) on a tool call and a round trip
- `/think [off|low|medium|high|on|default]` - Set the reasoning level
- `/tools` - List available built-in tools
- `/tool <name> <json>` - Run a tool directly
- `/skills` - List all available skills
- `/init` - Create a CLYDE.md memory file for the project
- `/cost` - Show session cost and usage
- `/compact` - Compact conversation to save context space
- `/doctor` - Diagnose environment, config, keys and permissions
- `/mcp` - Show connected MCP servers and their tools
- `/mcp login <server>` / `/mcp logout <server>` - OAuth sign-in for a remote MCP server (opens your browser), or forget its tokens
- `/plugins` - Show loaded plugins and what each added
- `/debug [path]` - Show the last turn's model and tool calls from the trace, or the trace file path
- `/login [provider]` - Connect a provider or replace its key, or add an OpenAI-compatible one (`custom`), then switch to a model
- `/rewind` - Undo the model's file edits and/or the conversation back to before one of your messages
- `/check` - Run the project's ruff, mypy and pytest and show a summary
- `/map [question]` - Query the repo's code map: no argument lists the hubs; also `update`, `explain X`, `affected X`, `path A B`

**Usage:**
- Type your message and press Enter to chat
- Use Tab for command completion
- Press Esc (or Ctrl+C) to interrupt the current reply or command
- Press Shift+Tab to cycle modes: hold, reading the table (plan only), all in (asks only before major moves)
- Press Ctrl+D to exit
- Use `/multiline` for multi-paragraph inputs
"""

# Rotating spinner words while the model works (in the spirit of Claude Code and Gemini CLI), with
# the past tense used in the line that closes the turn.
_THINKING_WORDS = (
    ("Thinking", "Thought"), ("Pondering", "Pondered"), ("Shuffling the deck", "Shuffled"),
    ("Reading the table", "Read the table"), ("Counting cards", "Counted cards"), ("Dealing", "Dealt"),
    ("Calculating odds", "Calculated"), ("Bluffing", "Bluffed"), ("Cutting the deck", "Cut the deck"),
    ("Stacking the deck", "Stacked the deck"), ("Tinkering", "Tinkered"), ("Noodling", "Noodled"),
    ("Scheming", "Schemed"), ("Mulling it over", "Mulled it over"), ("Connecting dots", "Connected the dots"),
)


def _clock(when: datetime | None = None) -> str:
    """Machine time as 5:47 PM."""
    return (when or datetime.now()).strftime("%I:%M %p").lstrip("0")


def _tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _usage_note(usage: dict, ref: str) -> str:
    """' · 4.1k in, 388 out · $0.012 · 812 requests left' for the turn footer; parts that aren't known are left out."""
    from src.agent.cost_tracker import estimate_usd
    from src.providers.base import remaining_quota

    parts = [f"{_tokens(usage.get('input_tokens', 0))} in, {_tokens(usage.get('output_tokens', 0))} out"]
    cost = estimate_usd(ref, usage) if ref else None
    if cost:
        parts.append(f"${cost:.3f}" if cost >= 0.001 else "<$0.001")
    if quota := remaining_quota(ref.partition(":")[0]):
        parts.append(quota)
    return " · " + " · ".join(parts)


def _duration(seconds: float) -> str:
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


def _thinking_label(word: str | None = None) -> str:
    import random
    return f"[{_CARD_DIM}]{word or random.choice(_THINKING_WORDS)[0]}…[/{_CARD_DIM}]"


_TICK = 1.0   # seconds between spinner rewrites


def _spin_text(word: str, started: float, now: float | None = None) -> str:
    """The spinner's line: the word, how long the turn has been going, and what it is waiting for, e.g.
    `Dealing… · 12s · waiting up to 30s for Laya to load`."""
    from rich.markup import escape

    elapsed = (time.monotonic() if now is None else now) - started
    parts = [f"{word}…"]
    if elapsed >= 1:
        parts.append(_duration(elapsed))
    if waiting := activity.get():
        parts.append(waiting)
    return f"[{_CARD_DIM}]{escape(' · '.join(parts))}[/{_CARD_DIM}]"


def _help_descriptions() -> dict[str, str]:
    """`/cmd` -> description, read from the /help text (every alias gets the same text)."""
    out: dict[str, str] = {}
    for line in _HELP_TEXT.splitlines():
        if not line.startswith("- `/") or " - " not in line:
            continue
        names, desc = line[2:].split(" - ", 1)
        for name in re.findall(r"`(/[\w-]+)", names):
            out[name] = desc.strip()
    return out


if Completer is not None:
    class SlashCompleter(Completer):
        """Offer commands and skills only while the line is a single word that starts with '/'."""

        def __init__(self, entries: list[tuple[str, str]]) -> None:
            self.entries = entries

        def get_completions(self, document, complete_event):  # type: ignore[no-untyped-def]
            text = document.text_before_cursor
            if not text.startswith("/") or any(c.isspace() for c in text):
                return
            needle = text.lower()
            starts = [e for e in self.entries if e[0].lower().startswith(needle)]
            inside = [e for e in self.entries if needle[1:] and needle[1:] in e[0].lower() and e not in starts]
            for name, desc in starts + inside:
                yield Completion(name, start_position=-len(text), display=name, display_meta=desc)


class ClydeREPL:
    """Interactive REPL for ClydeCLI."""

    # Listeners for a turn's streamed text and tool events (used by --acp); None in the terminal.
    on_text_hook = None
    on_event_hook = None
    system_extra: str | None = None   # extra system-prompt text for the next turns only (Bonnie's search results); not stored
    direct_stream = True              # short chat-like prompts may skip the tools for a quicker streamed reply; Bonnie's Computer mode turns this off

    # Esc cancels a running turn or command; prompts pause it (see src/repl/esc.py).
    _esc = WATCHER

    def __init__(self, model: str | None = None, stream: bool = False,
                 resume: str | None = None, continue_last: bool = False, debug: bool = False,
                 console: Console | None = None, headless: bool = False):
        # headless: `clyde -p`, one turn and no terminal prompts (see src/repl/headless.py).
        self.console = console or Console()
        self.headless = headless
        self.last_result: Any = None   # the latest turn's AgentLoopResult
        self.last_error: str | None = None
        self.control = RunControl()   # queue, steer and stop for a front end that drives turns from another thread
        self.stream = stream
        self._startup_resume = resume   # "" opens the picker, an id loads that session
        self._continue_last = continue_last
        session_config = load_config().get("session", {})
        self.auto_save = session_config.get("auto_save", True)
        self._trace_options = {"enabled": session_config.get("trace", True) is not False, "live": debug}
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
        self.checkpoints = Checkpoints(self.session.session_id)
        trace.start(self.session.session_id, **self._trace_options)

        self.tool_registry = build_default_registry()
        hooks, servers = load_hooks(), load_servers()
        servers = {**self._project_mcp_servers(Path.cwd(), set(servers)), **servers}   # yours win a clash
        self.plugins = apply_plugins(self.tool_registry, hooks, servers)
        for loaded in self.plugins:
            for warning in loaded.warnings:
                self.console.print(warning, style="yellow", markup=False)
        self.tool_context = ToolContext(workspace_root=Path.cwd(), hooks=hooks, permission_rules=load_rules(),
                                        output_style_name=get_output_style(), confirm_edits=True)
        self._mcp_servers, self._mcp_errors = servers, {}
        self._connect_mcp_servers(servers)
        self.tool_context.ask_user = self._ask_user_questions
        self.tool_context.plan_file = plan_file_for(self.tool_context.workspace_root, self.session.session_id)
        self.tool_context.before_edit = lambda path: self.checkpoints.snapshot(path)
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
            "/mcp",
            "/plugins",
            "/debug",
            "/rewind",
            "/login",
            "/laya",
            "/tune",
            "/council",
            "/multiline",
            "/stream",
            "/render-last",
            "/model",
            "/models",
            "/purge",
            "/terse",
            "/status",
            "/goal",
            "/plan",
            "/remember",
            "/memory",
            "/forget",
            "/eval",
            "/think",
            "/tools",
            "/tool",
            "/skills",
            "/init",
            "/review",
        ]
        self._built_in_commands = list(self._original_built_ins)

        # Initialize new command system
        self._init_command_system()

        # Pasted images and long pasted texts, numbered together by their [Image #N] / [Pasted text #N ...] markers.
        self._pastes: dict[int, ImageContentBlock | str] = {}
        if not self.headless:
            self._setup_prompt()

    def _setup_prompt(self) -> None:
        """The interactive prompt: history, completion, key bindings (paste, Shift+Tab) and the frame."""
        # Prompt toolkit with tab completion
        history_file = clyde_home() / "history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        self.completer = self._make_completer()

        # Key bindings for multiline
        self.bindings = KeyBindings()
        if hasattr(self.bindings, "add"):
            from prompt_toolkit.keys import Keys

            @self.bindings.add("s-tab")  # type: ignore[attr-defined]
            def _cycle_mode(event):  # type: ignore[no-untyped-def]
                self._cycle_mode()
                event.app.invalidate()

            # Ctrl+V reaches us raw (the terminal doesn't paste images), so read the clipboard image.
            @self.bindings.add("c-v")  # type: ignore[attr-defined]
            def _paste_image(event):  # type: ignore[no-untyped-def]
                self._insert_image(event.current_buffer, clipboard_image(), "image/png")

            # Cmd+V is the terminal's paste: a copied image file path becomes the image itself.
            @self.bindings.add(Keys.BracketedPaste)  # type: ignore[attr-defined]
            def _paste(event):  # type: ignore[no-untyped-def]
                data = event.data.replace("\r\n", "\n").replace("\r", "\n")
                path = image_path(data)
                if path is None:
                    event.current_buffer.insert_text(self._collapse_text(data))
                    return
                self._insert_image(event.current_buffer, path.read_bytes(), IMAGE_TYPES[path.suffix.lower()])

        self.prompt_session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self.completer,
            style=Style.from_dict({
                'prompt': 'bold #ffffff',
                'rule': '#5a5a5a',
                'mode': f'bold {_CARD_ACCENT}',
                'mode-note': _CARD_DIM,
                'model': _CARD_DIM,
                'vitals': _CARD_DIM,
                'vitals-strained': '#d0202f',
                'model-dealt': _CARD_ACCENT,
                # A plain list like Claude Code's: no grey block, green for the selected row.
                'completion-menu': 'bg:default',
                'completion-menu.completion': 'bg:default #d8d4cc',
                'completion-menu.completion.current': f'bg:default bold {_CARD_ACCENT}',
                'completion-menu.meta.completion': f'bg:default {_CARD_DIM}',
                'completion-menu.meta.completion.current': f'bg:default {_CARD_ACCENT}',
                'scrollbar.background': 'bg:default',
                'scrollbar.button': 'bg:#5a5a5a',
            }),
            reserve_space_for_menu=0,
            # The framed prompt is erased on Enter and the input echoed plainly (see run()).
            erase_when_done=True,
            key_bindings=self.bindings,
            complete_while_typing=True,
        )
        self._add_rule_under_input()

    def _insert_image(self, buffer, data: bytes | None, media_type: str) -> None:  # type: ignore[no-untyped-def]
        """Keep a pasted image and type its [Image #N] marker at the cursor, or say why there is none.
        An image over the size cap is shrunk when it can be; a model that can't read images is named."""
        from prompt_toolkit.application import run_in_terminal

        notes = []
        if data and len(data) > MAX_IMAGE_BYTES:
            small = shrink(data)
            if small is None:
                data = None
                notes.append(f"Image is over {MAX_IMAGE_BYTES // 2**20} MB and couldn't be shrunk, not attached.")
            else:
                notes.append(f"Image was over {MAX_IMAGE_BYTES // 2**20} MB; shrank it to {len(small) / 2**20:.1f} MB.")
                data, media_type = small, "image/jpeg"
        elif not data:
            notes.append("No image on the clipboard.")
        if data:
            number = len(self._pastes) + 1
            self._pastes[number] = ImageContentBlock(media_type=media_type, data=base64.b64encode(data).decode("ascii"))
            buffer.insert_text(f"[Image #{number}]")
            if self._reads_images() is False:
                notes.append(f"{model_ref(self.provider, self.model)} can't read images: it would get the text only. "
                             "Switch with /model before sending to include it.")
        for note in notes:
            run_in_terminal(lambda note=note: self.console.print(Text(note, style=_CARD_DIM)))

    def _reads_images(self) -> bool | None:
        """Whether the current model takes images: Ollama asks the server, others the catalog; None when unknown."""
        if isinstance(self.provider, CardShuffle):
            return None
        ask = getattr(self.provider, "reads_images", None)
        if callable(ask):
            try:
                return ask(self.model)
            except Exception:
                return None
        info = catalog.lookup(self.model.rsplit("/", 1)[-1])
        return info.supports_images if info is not None else None

    def _collapse_text(self, text: str) -> str:
        """A long paste as a [Pasted text #N +X lines] marker (kept, expanded on send); short ones as is."""
        lines = text.count("\n")
        if lines <= _PASTE_MAX_LINES and len(text) <= _PASTE_MAX_CHARS:
            return text
        number = len(self._pastes) + 1
        self._pastes[number] = text
        return f"[Pasted text #{number} +{lines} lines]"

    def _expand_pastes(self, text: str) -> str:
        """The input with each [Pasted text #N ...] marker replaced by the text it stands for."""
        def full(match: re.Match) -> str:
            pasted = self._pastes.get(int(match.group(1)))
            return pasted if isinstance(pasted, str) else match.group(0)
        return re.sub(r"\[Pasted text #(\d+) \+\d+ lines\]", full, text)

    def _investigate(self, provider: Any, model: str, cancel: threading.Event) -> ProviderResponse:
        """A council member's answer: it reads the repo on a copy of this conversation in plan mode (read-only tools, nobody to
        answer a permission prompt, so anything that would ask is denied) and its final text is the answer."""
        from src.tool_system.tools.agent import _NO_NESTING
        context = dataclasses.replace(self.tool_context, plan_mode=True, read_file_fingerprints={}, todos=[],
                                      permission_handler=lambda *a: (False, False), ask_user=None)
        tools = ToolRegistry([self.tool_registry.get(s.name) for s in self.tool_registry.list_specs() if s.name.lower() not in _NO_NESTING])
        result = run_agent_loop(copy.deepcopy(self.session.conversation), provider, model, tools, context,
                                max_turns=_COUNCIL_MAX_TURNS, cancel=cancel, reasoning=self.reasoning, system_extra=self.system_extra)
        if result.response_text == MAX_TURNS_REPLY:
            raise ProviderError(provider.name, "ran out of reading turns")
        return ProviderResponse(message=Message.assistant(result.response_text), raw={}, usage=result.usage)

    def _show_deal(self, ref: str, why: str) -> None:
        """cardShuffle's note on which real model plays this turn, and why."""
        self.console.print(Text.assemble(("♠ dealt ", _CARD_ACCENT), (ref, _CARD_TEXT), (f"  {why}", _CARD_DIM)), highlight=False)

    def _attached_images(self, text: str) -> list[ImageContentBlock]:
        """The pasted images a message refers to, in the order its [Image #N] markers appear."""
        numbers = dict.fromkeys(int(n) for n in re.findall(r"\[Image #(\d+)\]", text))
        return [p for n in numbers if isinstance(p := self._pastes.get(n), ImageContentBlock)]

    def _add_rule_under_input(self) -> None:
        """Draw a line right under the input, hidden while the completion menu is open so the menu
        sits directly below the prompt. Best effort: it relies on PromptSession's layout shape."""
        try:
            from prompt_toolkit.filters import has_completions
            from prompt_toolkit.layout.containers import ConditionalContainer, FloatContainer, Window
            from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
            from prompt_toolkit.layout.dimension import D

            top = self.prompt_session.layout.container.children[0]
            main = next((c for c in (getattr(top, "alternative_content", None), getattr(top, "content", None))
                         if isinstance(c, FloatContainer)), None)
            if main is None:
                return
            rows = main.content.children
            at = next(i for i, c in enumerate(rows) if isinstance(getattr(c.content, "content", None), BufferControl))
            from prompt_toolkit.filters import to_filter

            rows[at].content.dont_extend_height = to_filter(True)  # keep the line hugging the input
            rule = Window(FormattedTextControl(self._prompt_rule), height=1, dont_extend_height=True)
            buffer = self.prompt_session.default_buffer

            def menu_room():  # type: ignore[no-untyped-def]
                # Blank rows where the rule was, so the menu opens downward instead of flipping up.
                state = buffer.complete_state
                return D.exact(min(16, len(state.completions)) if state else 0)

            mode = Window(FormattedTextControl(self._mode_line), height=1, dont_extend_height=True)
            rows.insert(at + 1, ConditionalContainer(rule, filter=~has_completions))
            rows.insert(at + 2, ConditionalContainer(mode, filter=~has_completions))
            rows.insert(at + 3, ConditionalContainer(Window(height=menu_room), filter=has_completions))
        except Exception:
            return

    # Shift+Tab cycles: hold (asks before risky actions) -> reading the table (plan only) -> all in.
    _MODES = ("hold", "plan", "all_in")
    _MODE_LABELS = {
        "hold": ("♠ hold", ""),
        "plan": ("♠ reading the table", " · plans only, no edits"),
        "all_in": ("♠♠ all in", " · asks only before major moves"),
    }

    @property
    def mode(self) -> str:
        ctx = self.tool_context
        return "plan" if ctx.plan_mode else "all_in" if ctx.auto_approve else "hold"

    def _set_mode(self, mode: str) -> None:
        self.tool_context.plan_mode = mode == "plan"
        self.tool_context.auto_approve = mode == "all_in"

    def _cycle_mode(self) -> None:
        self._set_mode(self._MODES[(self._MODES.index(self.mode) + 1) % len(self._MODES)])

    def _model_parts(self) -> tuple[str, str]:
        """The model in use for the corner of the status line: (`provider:model`, `→ dealt` when it is
        cardShuffle, which says which real model got the latest turn)."""
        dealt = self.provider.dealt if isinstance(self.provider, CardShuffle) else None
        return model_ref(self.provider, self.model), f" → {dealt}" if dealt else ""

    def _mode_line(self):  # type: ignore[no-untyped-def]
        label, note = self._MODE_LABELS[self.mode]
        left = [("class:mode", f"  {label}"), ("class:mode-note", note), ("class:rule", "  (shift+tab to cycle)")]
        room = self._rule_width() - 1 - sum(len(text) for _, text in left) - 2   # a column of margin, two before the model
        ref, dealt = self._model_parts()
        vitals = sample()
        pulse = f"{line(vitals)}   "
        if room - len(ref + dealt) > len(pulse) + 2:   # only when the model keeps its full name
            room -= len(pulse) + 1
            left = [*left, ("", " "), ("class:vitals-strained" if vitals.strained else "class:vitals", pulse)]
        if dealt and len(ref + dealt) > room and isinstance(self.provider, CardShuffle):
            ref = self.model   # too long: the tier alone ("high-roller") says as much as "cardShuffle:high-roller"
        shown = (ref + dealt)[-room:] if room > 8 else ""
        if not shown:
            return left
        if len(shown) < len(ref + dealt):
            shown = "…" + shown[1:]   # too long for the row: keep the end, which names the model
        cut = max(0, len(shown) - len(dealt)) if dealt else len(shown)
        return [*left, ("", " " * (room - len(shown) + 2)), ("class:model", shown[:cut]), ("class:model-dealt", shown[cut:])]

    @staticmethod
    def _rule_width() -> int:
        import shutil
        return max(10, shutil.get_terminal_size((80, 24)).columns)

    def _prompt_rule(self):  # type: ignore[no-untyped-def]
        """The line under the input."""
        return [("class:rule", "─" * self._rule_width())]

    def _prompt_message(self):  # type: ignore[no-untyped-def]
        """The line above the input, then the chevron."""
        return [("class:rule", "─" * self._rule_width() + "\n"), ("class:prompt", "... " if self.multiline_mode else "❯ ")]

    @contextmanager
    def _prompting(self):  # type: ignore[no-untyped-def]
        """Hand the terminal to a prompt mid-turn: pause the spinner and the Esc watcher, then resume
        both, so the rest of the turn still shows it's working."""
        status = self._current_status
        if status is not None:
            try:
                status.stop()
            except Exception:
                pass
        try:
            with self._esc.paused():
                yield
        finally:
            if status is not None and status is self._current_status:
                try:
                    status.start()
                except Exception:
                    pass

    def _ask_user_questions(self, questions: list[dict]) -> dict[str, str]:
        with self._prompting():
            return self._ask_user_questions_unpaused(questions)

    def _ask_user_questions_unpaused(self, questions: list[dict]) -> dict[str, str]:

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
            suggestion: Allow rule offered as "don't ask again", or None.

        Returns:
            Tuple of (allowed: bool, continue_without_caching: bool).
            continue_without_caching is always False since we don't cache in REPL.
        """
        with self._prompting():
            return self._ask_permission(message, suggestion)

    def _ask_permission(self, message: str, suggestion: str | None) -> tuple[bool, bool]:
        self.console.print()
        self.console.print(Text.assemble(("♠ ", _CARD_ACCENT), ("Permission required", f"bold {_CARD_TEXT}")))
        self.console.print(Text(f"  {message}", style=_CARD_TEXT))

        # Determine if this is a setting that can be enabled
        can_enable_setting = False
        setting_to_enable: str | None = None

        msg_lower = message.lower()
        if "allow_docs" in msg_lower or "documentation files" in msg_lower:
            pc = self.tool_context.permission_context
            if hasattr(pc, 'allow_docs') and not pc.allow_docs:
                can_enable_setting = True
                setting_to_enable = "allow_docs"

        # Build options: (key, description, allowed)
        options: list[tuple[str, str, bool]] = [("y", "yes", True)]
        if suggestion:
            options.append(("a", f"yes, and don't ask again for {suggestion}", True))
        options.append(("n", "no", False))
        if can_enable_setting:
            options.insert(0, ("e", f"enable {setting_to_enable} and allow", True))

        # Plain Text, not markup: "[y]" in a markup string is read as a style tag and vanishes.
        for key, desc, _ in options:
            self.console.print(Text.assemble(("    ", ""), (key, f"bold {_CARD_ACCENT}"), ("  ", ""), (desc, _CARD_TEXT)))
        keys = "/".join(k for k, _, _ in options)

        choice = input(f"  Allow? [{keys}] (y): ").strip().lower()
        if choice in ("", "yes", "no", "enable", "always"):
            choice = {"": "y", "always": "a"}.get(choice, choice[:1])
        key = next((k for i, (k, _, _) in enumerate(options, start=1) if choice in (k, str(i))), None)
        if key is None:
            self.console.print(Text("  Not an option; denied.", style=_CARD_DIM))
            return False, False
        if key == "e":
            self._enable_permission_setting(setting_to_enable)
        elif key == "a" and suggestion:
            self._save_permission_rule(suggestion)
        return next(allowed for k, _, allowed in options if k == key), False

    def _save_permission_rule(self, rule: str) -> None:
        """Apply an allow rule now and save it to the user settings for later sessions."""
        self.tool_context.permission_rules["allow"].append(rule)
        try:
            save_allow_rule(rule)
        except (OSError, ValueError) as e:
            self.console.print(f"[yellow]Allowed {rule} for this session only; could not save it: {e}[/yellow]")
            return
        self.console.print(f"[green]✓ Saved allow rule {rule} to ~/.clyde/settings.json[/green]")

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

    def _slash_entries(self) -> list[tuple[str, str]]:
        """(command, description) for the completion menu: built-ins, registered commands, then skills."""
        descriptions = _help_descriptions()
        try:
            for cmd in self.command_registry.list_commands():
                descriptions.setdefault(f"/{cmd.name}", cmd.description or "")
        except Exception:
            pass
        try:
            from src.skills.loader import get_all_skills

            cwd = self.tool_context.cwd or self.tool_context.workspace_root
            for skill in get_all_skills(project_root=cwd):
                descriptions.setdefault(f"/{skill.name}", " ".join((skill.description or "").split()))
        except Exception:
            pass
        return [(w, descriptions.get(w, "")) for w in self._get_slash_command_words() if w != "/"]

    def _make_completer(self):  # type: ignore[no-untyped-def]
        if Completer is None:
            return WordCompleter(self._get_slash_command_words(), ignore_case=True)
        return SlashCompleter(self._slash_entries())

    def _refresh_completer(self) -> None:
        try:
            self.completer = self._make_completer()
            if hasattr(self, "prompt_session") and getattr(self.prompt_session, "completer", None) is not None:
                self.prompt_session.completer = self.completer
        except Exception:
            return

    def _names_a_command(self, name: str) -> bool:
        """Whether `/name` typed alone is a command or a user-invocable skill that exists, so it runs."""
        if self.command_registry.has(name):
            return True
        try:
            from src.skills.loader import get_all_skills

            cwd = self.tool_context.cwd or self.tool_context.workspace_root
            return any(s.name.lower() == name.lower() and getattr(s, "user_invocable", True)
                       for s in get_all_skills(project_root=cwd))
        except Exception:
            return False

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
                self.console.print(Text(f"  {name}", style=_CARD_ACCENT))
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

        info = f"ClydeCLI v{__version__} · {model_label} · {provider_label} · {display_path}"
        if Text is None:
            print("\n".join(_ACE_OF_SPADES[:-1] + (f"{_ACE_OF_SPADES[-1]}  {info}",)) + "\n")
            return

        width = getattr(self.console, "width", 80)
        path_room = max(12, width - len(_ACE_OF_SPADES[0]) - len(info) + len(display_path) - 2)
        header = _ace_of_spades_card()
        header.append("  ")
        header.append(Text.assemble(
            ("ClydeCLI ", f"bold {_CARD_TEXT}"), (f"v{__version__}", f"bold {_CARD_ACCENT}"),
            ("  ·  ", _CARD_DIM), (model_label, f"bold {_CARD_TEXT}"),
            ("  ·  ", _CARD_DIM), (provider_label, _CARD_ACCENT),
            ("  ·  ", _CARD_DIM), (self._truncate_middle(display_path, path_room), _CARD_DIM),
        ))
        self.console.print(header)
        self.console.print()

    def run(self):
        """Run the REPL."""
        self._print_startup_header()
        from src import updates
        if note := updates.cached_note():
            self.console.print(f"[{_CARD_DIM}]{note}[/{_CARD_DIM}]")
            self.console.print()
        self._warn_if_no_tool_training()
        updates.start_background_check()     # a thread: the answer shows on the next start
        start_background_refresh(self.tool_context.workspace_root)
        if isinstance(self.provider, CardShuffle):
            laya_client.warm()   # ~17 s cold load in the background, ready before the first turn needs it
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
                prefill, self._prefill = getattr(self, "_prefill", ""), ""
                user_input = self.prompt_session.prompt(
                    self._prompt_message,
                    multiline=self.multiline_mode,
                    pre_run=self._start_cron_watch,
                    default=prefill,   # /rewind puts the rewound message back for editing
                )
                if user_input is _CRON_WAKE:
                    continue
                if user_input.strip():
                    self.console.print(Text.assemble((f"{_clock()}  ", _CARD_DIM), (user_input, _CARD_TEXT)), highlight=False)

                if not user_input.strip():
                    self.multiline_mode = False
                    continue
                user_input = self._expand_pastes(user_input)

                # Handle commands
                if user_input.startswith('/'):
                    with self._esc.active():
                        self.handle_command(user_input)
                    continue

                # Send to LLM; Esc (like Ctrl+C) cancels the turn
                with self._esc.active():
                    self.chat(user_input)
                self.multiline_mode = False

            except KeyboardInterrupt:
                self.console.print(Text("\nInterrupted. Type /exit to quit.", style=_CARD_DIM))
                self.multiline_mode = False
                continue
            except EOFError:
                self.console.print(); self._say_goodbye()
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
        self.console.print(f"\n⏰ Scheduled run {job['id']} ({job['cron']}, {kind}): {job['prompt']}", style=f"bold {_CARD_ACCENT}", markup=False)
        self.chat(job["prompt"])

    def handle_command(self, command: str):
        """Handle slash commands."""
        raw = command.strip()
        if raw == "/":
            self._show_slash_palette()
            return
        if raw.startswith("/") and " " not in raw and raw.lower() not in (c.lower() for c in self._built_in_commands):
            query = raw[1:]
            if query and not self._names_a_command(query):   # a real name runs; a partial one lists what matches
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
                'model', 'models', 'think', 'eval',
                'skill', 'skills', 'mcp', 'debug', 'laya', 'council',
                'context', 'compact',  # These need special handling
                'clear', 'reset', 'new',  # also clears the screen and redraws the banner
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
            self._say_goodbye()
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

        elif cmd in ('/clear', '/reset', '/new'):
            # Try new command system first, fall back to original
            try:
                handled, result_text = self._try_execute_new_command('clear', '')
            except Exception:
                handled, result_text = False, None
            if not handled:
                self.session.conversation.clear()
            # Clear the screen as well, then redraw the banner
            self.console.clear()
            self._print_startup_header()
            self.console.print(Text(result_text or "Conversation cleared.", style=_CARD_DIM))

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
                self._pick_model()
            else:
                self._switch_model(parts[1].strip())

        elif cmd == '/models' or cmd.startswith('/models '):
            self._show_models(raw.split(maxsplit=1)[1].strip().lower() if " " in raw.strip() else "")

        elif cmd == '/status':
            self._show_status()

        elif cmd == '/goal' or cmd.startswith('/goal '):
            self._handle_goal(raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else "")

        elif cmd == '/memory':
            self._show_memory()

        elif cmd == '/remember' or cmd.startswith('/remember '):
            self._handle_remember(raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else "")

        elif cmd == '/forget' or cmd.startswith('/forget '):
            self._handle_forget(raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else "")

        elif cmd == '/plan' or cmd.startswith('/plan '):
            self._handle_plan(raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else "")

        elif cmd == '/terse' or cmd.startswith('/terse '):
            self._handle_terse(cmd[len('/terse'):].strip())

        elif cmd == '/purge' or cmd.startswith('/purge '):
            from src.repl import local_models
            local_models.purge(self, raw.split(maxsplit=1)[1] if " " in raw.strip() else "")

        elif cmd == '/eval' or cmd.startswith('/eval '):
            self._eval_models(raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else "")

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

        elif cmd == '/mcp':
            self._print_mcp_status()
        elif raw.strip().startswith(('/mcp login', '/mcp logout')):
            self._mcp_auth(*raw.strip().split()[1:3])

        elif cmd == '/plugins':
            self._print_plugins()
        elif cmd == '/rewind':
            self._rewind()
        elif cmd == '/login' or cmd.startswith('/login '):
            self._handle_relogin(raw.split(maxsplit=1)[1].strip() if " " in raw.strip() else None, title="Connect a provider")
        elif cmd == '/laya':
            self._show_laya()
        elif cmd == '/tune' or cmd.startswith('/tune '):
            from src import tune
            tune.run(self.console, reask='--ask' in raw.split())

        elif cmd == '/council' or cmd.startswith('/council '):
            self._show_council(raw.split(maxsplit=1)[1].strip().lower() if " " in raw.strip() else "")
        elif cmd == '/debug' or cmd.startswith('/debug '):
            self._show_debug(raw.split(maxsplit=1)[1].strip().lower() if " " in raw else "")

        elif raw.strip().startswith(('/skills scan', '/skills allow')):
            self._skills_security(raw.strip().split(maxsplit=2)[1:])
        elif cmd in ('/skill', '/skills') or cmd.startswith('/skills '):
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
                for spec in advertised(self.tool_registry.list_specs(), self.tool_context.loaded_tools)   # what a request carries
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
        help_text = _HELP_TEXT
        self.console.print(Markdown(help_text))

    def _skills_security(self, args: list[str]) -> None:
        """/skills scan rescans every skill ClydeCLI loads from a folder (user, other agents', plugins',
        the project's), with the LLM review when the current model allows it, and shows every verdict,
        MCP servers' and plugins' included; /skills allow <kind:name> lets a held-back item in."""
        from src import skill_scan
        from src.skills.loader import get_all_skills, load_commands_from_dir, load_skills_from_dir
        from src.skills.loader import _candidate_user_skills_dirs

        if args[0] == "allow":
            target = args[1] if len(args) > 1 else ""
            kind, _, name = target.partition(":") if ":" in target else ("skill", "", target)
            ok = skill_scan.approve(kind, name)
            self.console.print(f"Allowed {kind}:{name}; it loads from the next prompt (until its content changes)." if ok
                               else f"No scan result for {kind}:{name}. Run /skills scan first.")
            if ok and kind == "skill":
                get_all_skills(project_root=self.tool_context.cwd or self.tool_context.workspace_root)
            return
        env = skill_scan.llm_env(self.provider, self.model)
        self.console.print("LLM review: " + (f"on, with {model_ref(self.provider, self.model)} (this can take minutes; Ctrl+C stops it)"
                                             if env else "off (no connected model SkillSpector can use), static scan only"))
        from src.plugins import command_dirs, skill_dirs

        root = Path(self.tool_context.cwd or self.tool_context.workspace_root)
        folders = [*_candidate_user_skills_dirs(), *skill_dirs(), root / ".clyde" / "skills", root / ".claude" / "skills"]
        try:
            for folder in command_dirs():
                for s in load_commands_from_dir(folder, loaded_from="plugin"):
                    skill_scan.check("skill", s.name, Path(s.skill_root), env=env, rescan=True)
            for folder in folders:
                for s in load_skills_from_dir(folder, loaded_from="user"):
                    if s.skill_root:
                        skill_scan.check("skill", s.name, Path(s.skill_root), env=env, rescan=True)
        except KeyboardInterrupt:
            self.console.print("Stopped; the static verdicts already cached stay in force.")
        rows = sorted(skill_scan.cached_verdicts().items())
        table = Table(box=None, pad_edge=False, header_style=_CARD_DIM, show_edge=False)
        for col in ("item", "verdict", "risk", "llm", "findings"):
            table.add_column(col, overflow="fold" if col == "findings" else "ellipsis")
        style = {skill_scan.SAFE: _CARD_ACCENT, skill_scan.CAUTION: "#e0b341", skill_scan.BLOCK: "#d0202f"}
        for key, v in rows:
            label = v.recommendation + (" (allowed)" if v.approved and v.recommendation == skill_scan.BLOCK else "")
            table.add_row(key, Text(label, style=style.get(v.recommendation, _CARD_DIM)), str(v.score), "yes" if v.llm else "-",
                          "; ".join(v.findings[:3]) + (f" (+{len(v.findings) - 3} more)" if len(v.findings) > 3 else ""))
        self.console.print(table if rows else "Nothing scanned yet.")

    def _handle_skill_command(self) -> None:
        """/skills and /skill: choose a skill with the arrow keys; Enter runs it (as typing /<name> would)."""
        from src.skills.loader import get_all_skills

        try:
            skills = sorted(get_all_skills(project_root=self.tool_context.cwd or self.tool_context.workspace_root),
                            key=lambda s: s.name.lower())
        except Exception as e:
            self.console.print(f"[red]Error loading skills: {e}[/red]")
            return
        runnable = [s for s in skills if getattr(s, "user_invocable", True)]
        if not runnable:
            self.console.print("[dim]No skills found. Create them in ~/.clyde/skills/, ~/.claude/skills/ or .clyde/skills/ in your project.[/dim]")
            return
        choices = [Choice(s.name, s.name, _one_line(getattr(s, "description", None) or "", 110)) for s in runnable]
        note = f" {len(skills) - len(runnable)} more are for the model only." if len(skills) > len(runnable) else ""
        name = pick(self.console, "Run a skill", choices, description="Enter runs it; type to filter, Esc cancels." + note)
        if name:
            self.handle_command(f"/{name}")

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
        if not self.stream or not self.direct_stream:
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
                request,
                self.model,
                (),
                emit,
                reasoning=self.reasoning,
                on_thinking=on_thinking,
            ))
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

    def _project_mcp_servers(self, root: Path, taken: set[str]) -> dict[str, dict[str, Any]]:
        """The project's .mcp.json servers you've said yes to, asking about any new or changed entry."""
        from rich.prompt import Confirm
        from src.tool_system.mcp_client import (_expand_vars, describe_server, project_approval, project_servers,
                                                set_project_approval)

        approved = {}
        for name, cfg in project_servers(root).items():
            if name in taken:
                continue
            allowed = project_approval(root, name, cfg)
            if allowed is None and self.headless:
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
        self._mcp_errors = {**{k: v for k, v in getattr(self, "_mcp_errors", {}).items() if k not in servers}, **errors}
        from src import skill_scan
        for name in list(clients):
            verdict = skill_scan.check_mcp(name, clients[name].tools)
            if verdict.blocked:
                clients.pop(name)
                self.console.print(f"[red]MCP server '{name}' held back: SkillSpector says {verdict.recommendation} "
                                   f"(risk {verdict.score}).[/red] /skills scan shows why; /skills allow mcp:{name} lets it in.")
            elif verdict.recommendation == skill_scan.CAUTION:
                self.console.print(f"[yellow]MCP server '{name}': SkillSpector says CAUTION (risk {verdict.score}); /skills scan shows why.[/yellow]")
        self.tool_context.mcp_clients = {**(self.tool_context.mcp_clients or {}), **clients}
        for client in clients.values():
            for tool in client.tools:
                try:
                    self.tool_registry.register(McpServerTool(client, tool))
                except ValueError:  # two tools that sanitize to the same name: keep the first
                    pass
        for name, error in errors.items():
            trace.record("mcp_error", server=name, error=error)
            self.console.print(f"[yellow]MCP server '{name}' not connected: {error}[/yellow]", markup=True)

    def _rewind(self) -> None:
        """Pick a checkpoint and put files and/or the conversation back to before that message."""
        cps = self.checkpoints.list()[-15:]
        if not cps:
            self.console.print("Nothing to rewind yet: checkpoints start with your next message.")
            return
        picked = pick(self.console, "Rewind to before which message?",
                      [Choice(str(c.number), f"#{c.number}  {c.at[11:16]}  {len(c.files)} file(s)", c.prompt.replace("\n", " ")[:90])
                       for c in reversed(cps)], description="Files edited since then are put back; you choose what else next.")
        cp = next((c for c in cps if str(c.number) == picked), None)
        if cp is None:
            self.console.print("Nothing rewound.")
            return
        messages = self.session.conversation.messages
        first = messages[cp.message_index] if cp.message_index < len(messages) else None
        first_text = first.content if first is not None and isinstance(first.content, str) else \
            next((b.text for b in (first.content if first is not None else []) if getattr(b, "type", "") == "text"), "")
        talk_ok = first is not None and first.role == "user" and first_text.startswith(cp.prompt[:100])
        modes = [Choice("c", "Code and conversation", "restore the files and cut the chat back to that message"),
                 Choice("f", "Files only", "keep the conversation"),
                 Choice("m", "Conversation only", "keep the files as they are")]
        if not talk_ok:
            self.console.print("[dim]The conversation was compacted or cleared since, so only files can be restored.[/dim]")
        what = pick(self.console, "Rewind what?", modes if talk_ok else modes[1:2])
        if what is None:
            self.console.print("Nothing rewound.")
            return
        if what in ("c", "f"):
            restored, problems = self.checkpoints.restore(cp.number)
            for line in restored:
                self.console.print(f"  [green]↺[/green] {line}", highlight=False)
            for line in problems:
                self.console.print(f"  [yellow]✗ {line}[/yellow]", highlight=False)
            if not restored and not problems:
                self.console.print("  No files had been edited since then.")
        if what in ("c", "m"):
            del messages[cp.message_index:]
            self._prefill = first_text
            self.console.print("  Conversation rewound; your message is back in the prompt to edit or resend.")
        self.console.print(Text("Changes made by shell commands (rm, mv, scripts) aren't covered by /rewind.", style=_CARD_DIM))
        self._autosave_session()

    def _show_council(self, arg: str) -> None:
        """The last council turn's answers with Laya's scores, or `up N` / `down N` to vote on one."""
        council = getattr(self.provider, "last_council", None)
        if council is None:
            self.console.print("No council turn yet. Try /model cardShuffle:high-roller council", markup=False)
            return
        answers = council["answers"]
        if arg:
            way, _, number = arg.partition(" ")
            if way not in ("up", "down") or not number.isdigit() or not 1 <= int(number) <= len(answers):
                self.console.print(f"Use /council up N or /council down N, N from 1 to {len(answers)}.", markup=False)
                return
            ref = answers[int(number) - 1]["ref"]
            try:
                record_vote(council, ref, 1 if way == "up" else -1)
            except OSError as e:
                self.console.print(f"Couldn't save the vote: {e}", markup=False)
                return
            self.console.print(f"Voted {way} on {ref}. Votes stay on this machine.", markup=False)
            return
        for n, a in enumerate(answers, 1):
            chance = "unranked" if a["p"] is None else f"{a['p']:.0%} best"
            self.console.print(Text(f"{n}. {a['ref']}  {chance}", style=_CARD_ACCENT), highlight=False)
            self.console.print(a["text"], markup=False, highlight=False)
        for ref, why in council["failed"].items():
            self.console.print(Text(f"  {ref}: {why}", style=_CARD_DIM), highlight=False)
        self.console.print(Text("Vote with /council up N or /council down N.", style=_CARD_DIM), highlight=False)

    def _show_laya(self) -> None:
        """Laya's status, and how its judgments lined up with how traced turns ended."""
        from src.providers.card_shuffle import laya_report

        files = sorted(trace.traces_dir().glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        lines = [line for path in files for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
        self.console.print(f"Laya: {laya_client.status()} · from {len(files)} traced session(s)\n", markup=False)
        self.console.print(laya_report(lines), markup=False, highlight=False)

    def _show_debug(self, arg: str) -> None:
        path = trace.trace_path()
        if arg == "path":
            self.console.print(str(path), markup=False, highlight=False)
            return
        if arg:
            self.console.print("[red]Usage: /debug [path][/red]")
            return
        if path is None or not path.exists():
            self.console.print("[yellow]No trace for this session yet[/yellow] "
                               "[dim](tracing is off with CLYDE_TRACE=off or session.trace=false)[/dim]")
            return
        self.console.print(trace.last_turn_report(), markup=False, highlight=False)

    def _mcp_auth(self, action: str, name: str = "") -> None:
        """/mcp login <server> signs in with OAuth (browser) and connects it; /mcp logout <server> forgets the tokens."""
        from src.tool_system import mcp_oauth
        from src.tool_system.mcp_client import remote_spec

        cfg = self._mcp_servers.get(name)
        spec = remote_spec(cfg) if cfg else None
        if spec is None:
            remote = [n for n, c in self._mcp_servers.items() if remote_spec(c)]
            self.console.print(f"Usage: /mcp {action} <server>. Remote servers: {', '.join(remote) or 'none configured'}.")
            return
        url = spec[1]
        if action == "logout":
            gone = mcp_oauth.logout(url)
            self.console.print(f"Signed out of {name}." if gone else f"{name} had no saved sign-in.")
            return
        self.console.print(f"Opening your browser to sign in to {name}. Waiting up to {mcp_oauth.LOGIN_TIMEOUT // 60} minutes "
                           "(Ctrl+C cancels).", markup=False)
        try:
            with self._esc.paused():
                mcp_oauth.login(url, on_url=lambda u: self.console.print(f"If it didn't open: {u}", style=_CARD_DIM,
                                                                          markup=False, soft_wrap=True))
        except mcp_oauth.OAuthError as e:
            self.console.print(f"[red]Sign-in failed:[/red] {e}")
            return
        except KeyboardInterrupt:
            self.console.print("Sign-in cancelled.")
            return
        old = self.tool_context.mcp_clients.pop(name, None) if self.tool_context.mcp_clients else None
        if old is not None:
            old.close()
        self._connect_mcp_servers({name: cfg})
        client = self.tool_context.mcp_clients.get(name)
        self.console.print(f"[green]✓ Signed in to {name}[/green]: {len(client.tools)} tool(s) connected." if client
                           else f"Signed in, but {name} didn't connect: {self._mcp_errors.get(name, 'unknown error')}")

    def _print_mcp_status(self) -> None:
        clients, errors = self.tool_context.mcp_clients, getattr(self, "_mcp_errors", {})
        if not clients and not errors:
            self.console.print("No MCP servers configured. Add them under `mcpServers` in ~/.clyde/settings.json.")
            return
        for name, client in clients.items():
            self.console.print(f"[green]✓[/green] {name}: {len(client.tools)} tool(s)")
            for tool in client.tools:
                self.console.print(f"    mcp__{name}__{tool['name']}", markup=False)
        for name, error in errors.items():
            self.console.print(f"[red]✗[/red] {name}: {error}")

    def _print_plugins(self) -> None:
        if not self.plugins:
            self.console.print("No plugins loaded. Install one with `clyde plugin install <path-or-git-url>`.")
            return
        for loaded in self.plugins:
            p = loaded.plugin
            self.console.print(f"[green]✓[/green] {p.name} {p.version}", markup=True)
            if p.description:
                self.console.print(f"    {p.description}", markup=False)
            for label, items in (("tools", loaded.tools), ("skills", loaded.skills), ("commands", loaded.commands), ("MCP servers", loaded.mcp_servers)):
                if items:
                    self.console.print(f"    {label}: {', '.join(items)}", markup=False)
            if loaded.hooks:
                self.console.print(f"    hooks: {loaded.hooks}", markup=False)
            for warning in loaded.warnings:
                self.console.print(f"    {warning}", style="yellow", markup=False)

    def _context_window(self) -> int:
        """The model's input window: the provider's own sizing, then the catalog, then a name heuristic."""
        provider_window = getattr(self.provider, "context_window", None)
        if callable(provider_window):
            return provider_window(self.model)
        return catalog.context_window(self.model) or get_context_window_for_model(self.model)

    @contextmanager
    def _ticking(self, status, word: str, started: float, active=lambda: True):  # type: ignore[no-untyped-def]
        """Rewrite the spinner's text every second while `active()` (the status is stopped while text streams), so the
        counter runs through the whole wait and the phrase follows what the turn is waiting for."""
        stop = threading.Event()

        def tick() -> None:
            while not stop.wait(_TICK):
                if not active():
                    continue
                try:
                    status.update(_spin_text(word, started))
                except Exception:
                    return

        thread = threading.Thread(target=tick, name="spinner-ticker", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()

    def _maybe_auto_compact(self) -> None:
        """Compact the conversation before a turn when it nears the context window."""
        if not needs_auto_compact(self.session.conversation, self._context_window()):
            return
        self.console.print("[dim]Context is nearly full; compacting the conversation...[/dim]")
        started = time.monotonic()
        activity.set("compacting the conversation")
        try:
            status = self.console.status(_spin_text("Compacting", started), spinner="dots", spinner_style=_CARD_ACCENT)
            with status, self._ticking(status, "Compacting", started):
                result = asyncio.run(compact_conversation(self.session.conversation, self.provider, self.model, trigger="auto"))
        except Exception as e:
            self.console.print(f"[yellow]Auto-compact failed: {e}[/yellow]")
            return
        self.console.print(f"[green]{result.user_display_message}[/green]")

    def chat(self, user_input: str, max_turns: int = 20, _auth_retry: bool = False):
        """Send message to LLM and display response.

        Args:
            user_input: The user message to send.
            max_turns: Maximum number of tool call turns (default 20, higher for complex commands).
        """
        self.last_result, self.last_error = None, None
        activity.clear()
        trace.record("turn", provider=self.provider_name, model=self.model, prompt_chars=len(user_input))
        self._maybe_auto_compact()
        # Add user message
        self.checkpoints.begin(user_input, len(self.session.conversation.messages))
        images = self._attached_images(user_input)
        if images and self._reads_images() is False:
            self.console.print(Text(f"Sent without the image{'s' if len(images) > 1 else ''}: "
                                    f"{model_ref(self.provider, self.model)} can't read images.", style=_CARD_DIM))
            images = []
        self.session.conversation.add_user_message(user_input, images)
        if isinstance(self.provider, CardShuffle):
            self.provider.mode, self.provider.on_deal, self.provider.investigate = self.mode, self._show_deal, self._investigate
            laya_client.warm()

        turn_started = time.monotonic()
        word, past = random.choice(_THINKING_WORDS)
        tool_started: dict[str, float] = {}
        try:
            self.console.print()

            stream_started = False

            def _stop_status_once() -> None:
                nonlocal stream_started
                if self._current_status is not None and not stream_started:
                    try:
                        self._current_status.stop()
                    except Exception:
                        pass
                stream_started = True

            def _resume_status() -> None:
                # Streamed text stopped the spinner; bring it back while a tool and the next model call run.
                nonlocal stream_started
                if stream_started and self._current_status is not None:
                    self.console.print()
                    try:
                        self._current_status.start()
                    except Exception:
                        pass
                    stream_started = False

            def on_event(ev: ToolEvent) -> None:
                if self.on_event_hook is not None:
                    self.on_event_hook(ev)
                if ev.kind == "tool_use":
                    _resume_status()
                    tool_started[ev.tool_use_id or ev.tool_name] = time.monotonic()
                    summary = summarize_tool_use(ev.tool_name, ev.tool_input or {})
                    if isinstance(summary, str) and summary:
                        summary = self._shorten_path_text(summary)
                    suffix = f" [dim]({summary})[/dim]" if summary else ""
                    self.console.print(f"[dim]•[/dim] [{_CARD_ACCENT}]{ev.tool_name}[/{_CARD_ACCENT}]{suffix} [dim]running...[/dim]")
                    return
                if ev.kind == "tool_result":
                    began = tool_started.pop(ev.tool_use_id or ev.tool_name, None)
                    took = f" · {_duration(time.monotonic() - began)}" if began is not None else ""
                    if ev.is_error:
                        if self._is_recoverable_tool_error(ev.tool_name, ev.tool_output):
                            return
                        msg = ""
                        if isinstance(ev.tool_output, dict) and isinstance(ev.tool_output.get("error"), str):
                            msg = ev.tool_output["error"]
                        if not msg:   # e.g. a command that exited non-zero: show its exit code and last line
                            msg = str(summarize_tool_result(ev.tool_name, ev.tool_output) or "").removeprefix(f"{ev.tool_name} · ")
                        self.console.print(Text(f"  ↳ {msg or 'Error'}{took}", style="#d0202f"))
                        return
                    msg = summarize_tool_result(ev.tool_name, ev.tool_output)
                    if isinstance(msg, str):
                        prefix = f"{ev.tool_name} · "
                        if msg.startswith(prefix):
                            msg = msg[len(prefix):]
                        msg = self._shorten_path_text(msg)
                    self.console.print(Text(f"  ↳ {msg}{took}", style=_CARD_DIM))
                    problems = ev.tool_output.get("newProblems") if isinstance(ev.tool_output, dict) else None
                    if isinstance(problems, str):
                        self.console.print("  ↳ " + problems.replace("\n", "\n    "), style="yellow", markup=False)
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
                if self.on_text_hook is not None:
                    self.on_text_hook(chunk)
                _stop_status_once()
                if thinking_open:
                    self.console.print("\n")
                    thinking_open = False
                self.console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

            if self._should_try_direct_stream(user_input):
                self._current_status = self.console.status(_spin_text(word, turn_started), spinner="dots", spinner_style=_CARD_ACCENT)
                with self._current_status, self._ticking(self._current_status, word, turn_started, lambda: not stream_started):
                    activity.set(f"waiting for {model_ref(self.provider, self.model)}")
                    direct_response = self._stream_direct_response(on_text_chunk=on_text_chunk,
                                                                   on_thinking=on_thinking)
                self._current_status = None
                if direct_response is not None:
                    self.console.print()
                    self.console.print()
                    self._turn_footer(past, turn_started)
                    return

            # Use agent loop with tools for any provider that supports it
            def play():  # type: ignore[no-untyped-def]
                return run_agent_loop(
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
                    steer=self.control.take_steer,
                    system_extra=self.system_extra,
                )

            self._current_status = self.console.status(_spin_text(word, turn_started), spinner="dots", spinner_style=_CARD_ACCENT)
            with self._current_status, self._ticking(self._current_status, word, turn_started, lambda: not stream_started):
                result = play()
                # cardShuffle: a model stuck in its tool loop hands the turn to the next card.
                while (result.response_text == MAX_TURNS_REPLY and isinstance(self.provider, CardShuffle)
                       and self.provider.redeal(f"{self.provider.dealt} hit max tool turns")):
                    result = play()
            self._current_status = None
            self.last_result = result
            trace.record("turn_end", ran_out=result.response_text == MAX_TURNS_REPLY, rounds=result.num_turns,
                         model=self.provider.dealt if isinstance(self.provider, CardShuffle) else model_ref(self.provider, self.model))

            # Record usage to cost tracker; cardShuffle reports each real model it dealt.
            if isinstance(self.provider, CardShuffle):
                for ref, usage in self.provider.spent:
                    provider_name, _, model = ref.partition(":")
                    self.cost_tracker.record_usage(provider_name, model, usage, label=f"turn_{result.num_turns}_tokens")
                self.provider.spent.clear()
            elif result.usage:
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

            if self.headless:
                pass   # `clyde -p` prints the answer itself, on stdout
            elif self.stream and stream_started:
                self.console.print()
                self.console.print()
            elif not result.response_text.strip():
                self._print_no_answer(result)
            else:
                self.console.print(Markdown(result.response_text))
                self.console.print()
            dealt = self.provider.dealt if isinstance(self.provider, CardShuffle) else None
            self._turn_footer(past, turn_started, result.usage, dealt or model_ref(self.provider, self.model))

        except Exception as e:
            self._current_status = None
            self.last_error = str(e) or type(e).__name__
            if self.headless:
                hint = " (fix the key with clyde login)" if is_auth_error(e) and "clyde login" not in str(e) else ""
                self.console.print(f"[red]❌ {e}[/red]{hint}")
            elif is_auth_error(e):
                self.console.print(f"\n[red]❌ {e}[/red]")
                if self._recover_auth() and not _auth_retry:
                    self._retry_last(user_input, max_turns)
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
        self._warn_if_unlisted()
        self._warn_if_no_tool_training()
        return True

    def _warn_if_no_tool_training(self) -> None:
        """LM Studio knows which models were trained for tool calls. One that wasn't tends to write the call as
        plain text and then not do the task: say so before the first turn."""
        lacks = getattr(self.provider, "lacks_tool_training", None)
        if lacks is not None and lacks(self.model):
            self.console.print(f"[yellow]LM Studio says {self.model} wasn't trained for tool use.[/yellow] [dim]It may write tool calls "
                               f"as text instead of running them. /eval {model_ref(self.provider, self.model)} tests it, or pick another with /model.[/dim]")

    def _warn_if_unlisted(self) -> None:
        """A model the provider's own list doesn't contain usually fails on the first request: say so now."""
        try:
            models = self.provider.list_models()
        except Exception:
            return
        if models and self.model not in models:
            self.console.print(f"[yellow]{self.model} isn't in {self.provider_name}'s model list; if the next request "
                               "fails, pick another with /model.[/yellow]")

    def _print_no_answer(self, result) -> None:  # type: ignore[no-untyped-def]
        """A turn that ended with no answer text (a reasoning model can spend all of it thinking): say so, with what is
        known, instead of showing only the footer."""
        tokens = (result.usage or {}).get("output_tokens", 0)
        spent = f" after {tokens} output tokens" if tokens else ""
        self.console.print(f"[yellow]The model ended its turn{spent} without any answer text.[/yellow] "
                           "[dim]It may have used them on reasoning or reached its output limit. Ask again, try /think off, "
                           "or pick another model with /model.[/dim]")
        self.console.print()

    def _turn_footer(self, past: str, started: float, usage: dict | None = None, ref: str = "") -> None:
        """Close a reply with how long it took, the machine time and, when known, what the turn used,
        e.g. ♠ Shuffled for 2m 45s · 5:47 PM · 4.1k in, 388 out · $0.012 · 812 requests left."""
        line = f"{past} for {_duration(time.monotonic() - started)} · {_clock()}" + (_usage_note(usage, ref) if usage else "")
        self.console.print(Text.assemble(("♠ ", _CARD_ACCENT), (line, _CARD_DIM)))
        self.console.print()
        self._check_goal_met()

    def _say_goodbye(self) -> None:
        self.console.print(Text.assemble(("♠ ", _CARD_ACCENT), ("Goodbye!", f"bold {_CARD_TEXT}")))

    def _eval_models(self, query: str = "") -> None:
        """Grade every listed model (or those matching `query`) on a tool call and a round trip."""
        from rich.prompt import Confirm
        from src.providers.model_eval import HAND, evaluate_all, save_results
        from src.repl.local_models import installed, loaded_bytes, short_on_memory, stop_eval

        live = usable(self.registry)
        if not live:
            self.console.print("[yellow]No providers connected.[/yellow] Run [bold]clyde login[/bold], or start Ollama.")
            return
        with self.console.status(f"[{_CARD_DIM}]Fetching model lists…[/{_CARD_DIM}]", spinner="dots", spinner_style=_CARD_ACCENT):
            listings = {name: p.list_models() for name, p in live.items()}
        q = query.lower()
        targets = [(live[name], m, f"{name}:{m}") for name, models in listings.items() for m in models
                   if name != CardShuffle.name and (not q or q in f"{name}:{m}".lower())]
        if not targets:
            self.console.print(f"No models match '{query}'." if query else "No models listed.")
            return
        self.console.print(f"{len(targets)} model(s) to test on your own keys: two short requests, then a hand of {len(HAND)} harder tasks for each that passes"
                           + ("" if query else " (narrow it with /eval <provider or name>)") + ".")
        sizes = {m.ref: m.size for m in installed(self)}
        biggest = max((loaded_bytes(p, m, sizes[ref]) for p, m, ref in targets if ref in sizes), default=0)
        short = biggest > 0 and short_on_memory(self.console, biggest, "/eval")
        with self._esc.paused():
            if not Confirm.ask("Run the evaluation?", default=len(targets) <= 20 and not short, console=self.console):
                return
        done = [0]
        try:
            with self.console.status("", spinner="dots", spinner_style=_CARD_ACCENT) as status:
                def progress(score) -> None:  # type: ignore[no-untyped-def]
                    done[0] += 1
                    status.update(f"[{_CARD_DIM}]Tested {done[0]}/{len(targets)} · {score.ref}[/{_CARD_DIM}]")
                scores = evaluate_all(targets, on_done=progress)
        except KeyboardInterrupt:
            stop_eval(self.console, [(p, m) for p, m, _ref in targets])
            return
        drops = save_results(scores)
        width = getattr(self.console, "width", 100)
        table = Table(box=None, pad_edge=False, header_style=_CARD_DIM, show_edge=False)
        table.add_column("", no_wrap=True, width=1)
        table.add_column("model", no_wrap=True, overflow="ellipsis", max_width=max(20, width - 64))
        for col in ("tool", "trip", "hand", "secs", "tok/s"):
            table.add_column(col, no_wrap=True, justify="right", min_width=len(col))
        table.add_column("note", no_wrap=True, overflow="ellipsis", min_width=12, max_width=30)
        current = model_ref(self.provider, self.model)
        mark = lambda ok: Text("✓", style=_CARD_ACCENT) if ok else Text("✗", style="#d0202f")  # noqa: E731
        for sc in scores:
            table.add_row(
                Text("●", style=_CARD_ACCENT) if sc.ref == current else "",
                Text(sc.ref, style=f"bold {_CARD_TEXT}" if sc.passed else _CARD_DIM),
                mark(sc.tool_call), mark(sc.round_trip),
                f"{sc.strength}/{len(HAND)}" if sc.strength is not None else "-",
                f"{sc.latency_s:.1f}" if sc.latency_s is not None else "-",
                f"{sc.tokens_per_s:.0f}" if sc.tokens_per_s else "-",
                Text(sc.short_note, style=_CARD_DIM),
            )
        self.console.print(table)
        for line in drops:   # a model that got worse since its last grade; cardShuffle now ranks it lower
            self.console.print(Text(f"↓ {line}", style="#d0202f"))
        kinds = {k: sum(sc.kind == k for sc in scores) for k in ("ok", "tools", "unavailable", "answer", "transient")}
        parts = [(f"{kinds['ok']}/{len(scores)} passed", f"bold {_CARD_ACCENT}")]
        for key, label in (("tools", "no tool calling"), ("unavailable", "not available"), ("answer", "wrong answer"),
                           ("transient", "credits or rate limits (kept, retry later)")):
            if kinds[key]:
                parts += [("  ·  ", _CARD_DIM), (f"{kinds[key]} {label}", _CARD_DIM)]
        self.console.print(Text.assemble(*parts))
        hidden = kinds["tools"] + kinds["unavailable"] + kinds["answer"]
        if hidden:
            self.console.print(Text(f"/models now hides the {hidden} that don't work · /models all shows them", style=_CARD_DIM))

    def _show_status(self) -> None:
        """/status: what this session is set to."""
        from src import __version__
        from src.repl.status import status_lines
        totals = {"input_tokens": 0, "output_tokens": 0}
        for usage in getattr(self.cost_tracker, "models", {}).values():
            for key in totals:
                totals[key] += usage.get(key, 0)
        label, _ = self._MODE_LABELS[self.mode]
        for line in status_lines(version=__version__, model=model_ref(self.provider, self.model), mode=label.lstrip("♠ "),
                                 cwd=self.tool_context.cwd or self.tool_context.workspace_root, session_id=self.session.session_id,
                                 goal=self.tool_context.goal, terse=self.tool_context.output_style_name == "terse", usage=totals):
            self.console.print(line, markup=False)
        if note := plans.status_note(plans.read_plan(self.tool_context.plan_file)):
            self.console.print(f"  plan:      {note}", markup=False)

    def _show_memory(self) -> None:
        """/memory: the notes Clyde keeps between sessions, numbered per scope for /forget."""
        from src import memory
        root = self.tool_context.workspace_root
        shown = False
        for scope, label in (("user", "About you"), ("project", "About this project")):
            notes = memory.entries(scope, root)
            if notes:
                shown = True
                self.console.print(f"{label} ({memory.path_for(scope, root)}):", markup=False)
                for i, note in enumerate(notes, 1):
                    self.console.print(f"  {i}. {note}", markup=False, highlight=False)
        if not shown:
            self.console.print("No notes yet. Save one with /remember TEXT, or ask me to remember something.", markup=False)

    def _handle_remember(self, arg: str) -> None:
        """/remember [project] TEXT: save a note, about the user unless the first word is `project`."""
        from src import memory
        scope, _, rest = arg.partition(" ") if arg.split(" ", 1)[0] in ("project", "user") else ("user", "", arg)
        try:
            saved = memory.add(scope, self.tool_context.workspace_root, rest)
        except ValueError as e:
            self.console.print(f"[red]{e}[/red]")
            return
        self.console.print(f"[green]Remembered ({scope}):[/green] {saved}")

    def _handle_forget(self, arg: str) -> None:
        """/forget [project] N: drop note N of the user's notes, or of the project's."""
        from src import memory
        words = arg.split()
        scope = words.pop(0) if words and words[0] in ("project", "user") else "user"
        if len(words) != 1 or not words[0].isdigit():
            self.console.print("[red]Usage: /forget [project] N  (numbers are in /memory)[/red]")
            return
        try:
            gone = memory.forget(scope, self.tool_context.workspace_root, int(words[0]))
        except ValueError as e:
            self.console.print(f"[red]{e}[/red]")
            return
        self.console.print(f"[green]Forgot ({scope}):[/green] {gone}")

    def _handle_plan(self, arg: str) -> None:
        """/plan [done|start|pending N|clear]: show the saved plan, set one phase's status, or delete the plan."""
        path = self.tool_context.plan_file
        text = plans.read_plan(path)
        if not text:
            self.console.print("No saved plan. Press Shift+Tab to plan mode and ask for one; it is saved when you approve it.", markup=False)
            return
        words = arg.split()
        if words and words[0] == "clear":
            path.unlink(missing_ok=True)
            self.console.print("[green]Plan deleted.[/green]")
            return
        if words:
            status = {"done": "complete", "start": "in_progress", "pending": "pending"}.get(words[0])
            if status is None or len(words) != 2 or not words[1].isdigit():
                self.console.print("[red]Usage: /plan [done|start|pending N | clear][/red]")
                return
            try:
                text = plans.set_phase_status(text, int(words[1]), status)
            except ValueError as e:
                self.console.print(f"[red]{e}[/red]")
                return
            path.write_text(text, encoding="utf-8")
        self.console.print(plans.plan_head(text), markup=False, highlight=False)
        self.console.print(plans.status_note(text), markup=False, highlight=False)
        self._check_goal_met()

    def _check_goal_met(self) -> None:
        """A goal made with /goal plan ends when every phase of the saved plan is complete."""
        ctx = self.tool_context
        done, total = plans.progress(plans.read_plan(ctx.plan_file))
        if ctx.goal_from_plan and total and done == total:
            ctx.goal, ctx.goal_from_plan = None, False
            self.console.print("[green]Plan complete: the goal is met and cleared.[/green]")

    def _handle_goal(self, arg: str) -> None:
        """/goal [text|clear]: set, show or clear the session goal."""
        from src.repl.status import MAX_GOAL_CHARS, clamp_goal
        if not arg:
            self.console.print(f"Goal: {self.tool_context.goal}" if self.tool_context.goal else "No goal set. Set one with /goal TEXT.", markup=False)
            return
        if arg.lower() == "clear":
            self.tool_context.goal, self.tool_context.goal_from_plan = None, False
            self.console.print("[green]Goal cleared.[/green]")
            return
        if arg.lower() == "plan":
            goal = plans.goal_from_plan(plans.read_plan(self.tool_context.plan_file))
            if not goal:
                self.console.print("[yellow]No saved plan with phases yet.[/yellow] Present one in plan mode (Shift+Tab).")
                return
            self.tool_context.goal, self.tool_context.goal_from_plan = clamp_goal(goal)[0], True
            self.console.print("[green]Goal set from the plan.[/green] [dim]It ends when every phase is complete.[/dim]")
            return
        goal, cut = clamp_goal(arg)
        self.tool_context.goal_from_plan = False
        self.tool_context.goal = goal
        self.console.print(f"[green]Goal set.[/green] [dim](applies from your next message)[/dim]")
        if cut:
            self.console.print(f"[yellow]Cut to {MAX_GOAL_CHARS} characters; it is sent every turn.[/yellow]")

    def _handle_terse(self, arg: str) -> None:
        """/terse [on|off]: shorter replies. Bare opens a picker. Saved, and in effect from the next message."""
        on = self.tool_context.output_style_name == "terse"
        if arg not in ("", "on", "off"):
            self.console.print("[red]Usage: /terse [on|off][/red]")
            return
        choice = arg or pick(self.console, "Terse replies", [
            Choice("on", "On", "short answers: fewer tokens, quicker on local models"),
            Choice("off", "Off", "Clyde's usual replies")], current="on" if on else "off")
        if choice is None:
            return
        self.tool_context.output_style_name = "terse" if choice == "on" else None
        set_output_style(self.tool_context.output_style_name)
        self.console.print(f"[green]Terse replies: {choice}[/green] [dim](saved; applies from your next message)[/dim]")

    def _pick_model(self, show_all: bool = False, refresh: bool = False) -> None:
        """/model and /models: choose from every connected provider's models with the arrow keys; Enter
        switches. Models /eval showed don't work are left out unless `show_all`; `refresh` fetches
        fresh lists first."""
        live = usable(self.registry)
        if not live:
            self.console.print("[yellow]No providers connected.[/yellow] Run [bold]clyde login[/bold], "
                               "or start Ollama or LM Studio for local models.")
            return
        if refresh:
            for p in live.values():
                p.__dict__.pop("_models_cache", None)
        current, hide = model_ref(self.provider, self.model), set() if show_all else hidden_refs()
        with self.console.status(f"[{_CARD_DIM}]Fetching model lists…[/{_CARD_DIM}]", spinner="dots", spinner_style=_CARD_ACCENT):
            listings = {name: p.list_models() for name, p in live.items()}
        for name in (n for n, models in listings.items() if not models):
            self.console.print(Text(f"{name}: couldn't list models; check the key or connection.", style=_CARD_DIM))
        refs = [f"{name}:{m}" for name, models in listings.items() for m in models]
        shown = [ref for ref in refs if ref not in hide or ref == current]
        description = "Your pick becomes the default. Type to filter." + (
            f" {len(refs) - len(shown)} hidden because /eval showed they don't work; /models all lists them."
            if len(shown) < len(refs) else "")
        chosen = pick(self.console, "Select model", [Choice(ref, ref) for ref in shown], current=current, description=description)
        if chosen and chosen != current:
            self._switch_model(chosen)

    def _show_models(self, arg: str = "") -> None:
        """/models [all|refresh]: the model picker; `/models local ...` finds downloadable local models
        that fit this machine."""
        if arg.split(" ", 1)[0] == "local":
            from src.repl import local_models
            local_models.show(self, arg[len("local"):])
            return
        self._pick_model(show_all=arg == "all", refresh=arg == "refresh")

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

    def _recover_auth(self) -> bool:
        """After a rejected key: re-enter just this provider's key (k), switch provider or model (s), or
        leave it (n). True when a new key or model is in place."""
        key_name = "ollama" if self.provider_name == "ollama-cloud" else self.provider_name
        can_rekey = key_name in keys.PROVIDER_KEY_ENV
        options = ([Choice("k", f"New {self.provider_name} key", "enter a replacement key")] if can_rekey else []) + [
            Choice("s", "Switch provider or model", "pick another one"), Choice("n", "Not now", "fix it later with clyde login or /model")]
        self._esc.stop()
        choice = pick(self.console, "Fix it now?", options) or "n"
        if choice == "n":
            self.console.print("\n[dim]Run [bold]clyde login[/bold] or /model later to fix it.[/dim]")
            return False
        if choice == "s":
            before = (self.provider_name, self.model)
            self._handle_relogin()
            return (self.provider_name, self.model) != before
        return self._rekey(key_name)

    def _rekey(self, key_name: str) -> bool:
        """Ask for the current provider's key only, save it, and keep the same model."""
        from src.cli import prompt_secret

        env = keys.PROVIDER_KEY_ENV[key_name]
        try:
            saved = keys._load().get(key_name)
        except keys.KeysFileError:
            saved = None
        from_shell = bool(os.environ.get(env)) and os.environ.get(env) != saved
        key = prompt_secret(f"New {self.provider_name} API key")
        if not key:
            self.console.print("[dim]No key entered; nothing changed.[/dim]")
            return False
        keys.connect(key_name, key)
        ref = model_ref(self.provider, self.model)
        self.registry = build_registry()
        resolved = resolve(self.registry, ref)
        if resolved is None:
            self.console.print(f"[yellow]Saved the key, but {ref} isn't available with it.[/yellow] Pick another with /model.")
            return False
        self.provider, self.model = resolved
        self.provider_name = self.provider.name
        self.console.print(f"[green]✓ New {self.provider_name} key saved.[/green]")
        if from_shell:
            self.console.print(f"[yellow]Your shell exports {env} with the old key, and it overrides the saved one when "
                               f"ClydeCLI starts.[/yellow] Update or remove it in your shell profile.")
        return True

    def _retry_last(self, user_input: str, max_turns: int) -> None:
        """Send the message that hit the rejected key once more, with the fixed key or model."""
        messages = self.session.conversation.messages
        last = messages[-1] if messages else None
        text = last.content if last is not None and isinstance(last.content, str) else \
            next((b.text for b in (last.content if last is not None else []) if getattr(b, "type", "") == "text"), None)
        if last is None or last.role != "user" or text != user_input:
            self.console.print("[dim]Fixed. Send your message again to continue.[/dim]")
            return
        messages.pop()   # chat() adds it again
        self.console.print(Text("Retrying your message…", style=_CARD_DIM))
        self.chat(user_input, max_turns, _auth_retry=True)

    def _handle_relogin(self, provider: str | None = None, title: str = "Reconfigure API key"):
        """Connect a provider (or re-enter a failed key) and switch to the model picked."""
        from src.cli import run_login_flow

        self.console.print(Text.assemble(("\n♠ ", _CARD_ACCENT), (title, f"bold {_CARD_TEXT}"), "\n"))
        with self._esc.paused():   # the flow reads the keyboard: pickers, key entry, questions
            ref = run_login_flow(self.console, self.registry, default_provider=self.provider_name, provider=provider)
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
        chosen = pick(self.console, "Resume a session",
                      [Choice(str(i), f"{s.updated_at[:16].replace('T', ' ')}  {len(s.conversation.messages):>3} msgs",
                              _first_prompt(s)) for i, s in enumerate(shown)])
        if chosen is not None:
            self._switch_session(shown[int(chosen)])

    def _switch_session(self, loaded_session) -> None:
        saved_model = f"{loaded_session.provider}:{loaded_session.model}"
        self.session = loaded_session
        self.tool_context.plan_file = plan_file_for(self.tool_context.workspace_root, loaded_session.session_id)
        self.tool_context.goal, self.tool_context.goal_from_plan = None, False   # a goal belongs to the session that set it
        self.checkpoints = Checkpoints(loaded_session.session_id)   # its checkpoints, for /rewind
        trace.start(loaded_session.session_id, **self._trace_options)
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
