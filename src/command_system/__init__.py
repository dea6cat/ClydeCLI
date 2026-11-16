"""
Command system for ClydeCLI.

A complete reimplementation of Claude Code's command system.
"""

from .builtins import (
    CLEAR_COMMAND,
    COMPACT_COMMAND,
    CONTEXT_COMMAND,
    COST_COMMAND,
    EXIT_COMMAND,
    HELP_COMMAND,
    INIT_COMMAND,
    SKILLS_COMMAND,
    builtin_registry,
    run_command,
    get_builtin_commands,
    register_builtin_commands,
)
from .engine import (
    CommandContext,
    CommandResult,
    create_command_context,
)
from .registry import (
    CommandRegistry,
    get_command_registry,
)
from .types import (
    Command,
    CommandBase,
    CommandType,
    LocalCommand,
    LocalCommandResult,
    PromptCommand,
    get_command_name,
)

__all__ = [
    # Types
    "Command",
    "CommandType",
    "CommandBase",
    "PromptCommand",
    "LocalCommand",
    "LocalCommandResult",
    "get_command_name",
    # Argument substitution
    # Registry
    "CommandRegistry",
    "get_command_registry",
    # Engine
    "CommandContext",
    "CommandResult",
    "create_command_context",
    # Builtins
    "HELP_COMMAND",
    "CLEAR_COMMAND",
    "EXIT_COMMAND",
    "SKILLS_COMMAND",
    "COST_COMMAND",
    "CONTEXT_COMMAND",
    "COMPACT_COMMAND",
    "INIT_COMMAND",
    "get_builtin_commands",
    "register_builtin_commands",
    # Skills integration
]
