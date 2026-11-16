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
    find_commands,
    get_command,
    get_command_registry,
    has_command,
    list_commands,
    register_command,
)
from .types import (
    Command,
    CommandBase,
    CommandType,
    LocalCommand,
    LocalCommandResult,
    PromptCommand,
    get_command_name,
    is_command_enabled,
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
    "is_command_enabled",
    # Argument substitution
    # Registry
    "CommandRegistry",
    "get_command_registry",
    "register_command",
    "get_command",
    "has_command",
    "list_commands",
    "find_commands",
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
