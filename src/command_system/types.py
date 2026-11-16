"""
Command type system for ClydeCLI.

Implements the core command types inspired by Claude Code's command system:
- PromptCommand: Expands to text/prompt content sent to the model
- LocalCommand: Executes local code without rendering UI
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


class CommandType(Enum):
    """Types of commands."""
    PROMPT = "prompt"
    LOCAL = "local"


@dataclass(frozen=True)
class CompactionResult:
    """Result data from a compaction operation."""
    pre_compact_count: int = 0
    post_compact_count: int = 0
    tokens_saved: int = 0
    trigger: str = "manual"
    summary_preview: Optional[str] = None


@dataclass(frozen=True)
class LocalCommandResult:
    """Result of a local command execution."""
    type: str = "text"  # "text" | "compact" | "skip"
    value: str = ""
    compaction_result: Optional[CompactionResult] = None
    display_text: Optional[str] = None


@dataclass
class CommandContext:
    """Context passed to command execution."""
    workspace_root: Path
    cwd: Path
    conversation: Any  # Will be type hinted properly later
    cost_tracker: Any
    history: Any
    config: dict[str, Any] = field(default_factory=dict)
    provider: Any = None
    model: str | None = None


# Protocol for local command callables
LocalCommandCall = Callable[[str, CommandContext], LocalCommandResult]


@dataclass(frozen=True)
class CommandBase:
    """Base class for all commands."""
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    is_enabled: Callable[[], bool] = field(default=lambda: True)
    is_hidden: bool = False
    has_user_specified_description: bool = False
    argument_hint: Optional[str] = None
    when_to_use: Optional[str] = None
    version: Optional[str] = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    loaded_from: str = "builtin"  # "builtin" | "skills" | "plugin" | "bundled" | "mcp"
    kind: Optional[str] = None  # "workflow" or None
    immediate: bool = False
    is_sensitive: bool = False

    @property
    def command_type(self) -> CommandType:
        """Get the command type. Must be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement command_type property")

    def user_facing_name(self) -> str:
        """Get the user-facing name of the command."""
        return self.name


@dataclass(frozen=True)
class PromptCommand(CommandBase):
    """A command that expands to prompt content."""
    progress_message: str = ""
    content_length: int = 0
    arg_names: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    model: Optional[str] = None
    source: str = "builtin"
    plugin_info: Optional[dict[str, Any]] = None
    disable_non_interactive: bool = False
    hooks: dict[str, Any] = field(default_factory=dict)
    skill_root: Optional[str] = None
    context: str = "inline"  # "inline" | "fork"
    agent: Optional[str] = None
    effort: Optional[str] = None
    paths: list[str] = field(default_factory=list)
    markdown_content: str = ""

    @property
    def command_type(self) -> CommandType:
        return CommandType.PROMPT

    def prompt_for(self, args: str, context: CommandContext) -> str:
        """The prompt this command sends to the model, with its arguments filled in."""
        from src.skills.argument_substitution import substitute_arguments
        return substitute_arguments(self.markdown_content, args, argument_names=self.arg_names)


@dataclass(frozen=True)
class LocalCommand(CommandBase):
    """A command that executes local code."""
    supports_non_interactive: bool = False
    _call_impl: Optional[LocalCommandCall] = field(default=None, repr=False, compare=False)

    @property
    def command_type(self) -> CommandType:
        return CommandType.LOCAL

    def set_call(self, call: LocalCommandCall) -> None:
        """Set the call implementation."""
        object.__setattr__(self, '_call_impl', call)

    def run(self, args: str, context: CommandContext) -> LocalCommandResult:
        """Execute the local command; its errors propagate to the caller."""
        if self._call_impl is None:
            raise NotImplementedError(f"/{self.name} has no implementation")
        return self._call_impl(args, context)

    async def call(self, args: str, context: CommandContext) -> LocalCommandResult:
        return self.run(args, context)


# Type alias for any command
Command = PromptCommand | LocalCommand


def get_command_name(cmd: CommandBase) -> str:
    """Get the user-facing name of a command."""
    return cmd.user_facing_name()


def is_command_enabled(cmd: CommandBase) -> bool:
    """Check if a command is enabled."""
    return cmd.is_enabled()

