"""
Command execution engine for ClydeCLI.

Handles execution of commands and integration with the REPL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .types import (
    Command,
    CommandContext,
    CommandType,
    LocalCommand,
    LocalCommandResult,
    PromptCommand,
)


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    command_name: str
    result_type: str = "text"  # "text" | "prompt" | "skip"
    text: str = ""
    prompt_content: list[dict[str, Any]] = field(default_factory=list)
    should_query: bool = False
    display: str = "system"  # "skip" | "system" | "user"
    meta_messages: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @classmethod
    def success_text(cls, command_name: str, text: str) -> "CommandResult":
        """Create a successful text result."""
        return cls(
            success=True,
            command_name=command_name,
            result_type="text",
            text=text,
            display="system",
        )

    @classmethod
    def success_prompt(
        cls,
        command_name: str,
        prompt_content: list[dict[str, Any]],
        should_query: bool = True,
    ) -> "CommandResult":
        """Create a successful prompt result."""
        return cls(
            success=True,
            command_name=command_name,
            result_type="prompt",
            prompt_content=prompt_content,
            should_query=should_query,
            display="user",
        )

    @classmethod
    def failed(cls, command_name: str, error: str) -> "CommandResult":
        """Create an error result."""
        return cls(
            success=False,
            command_name=command_name,
            result_type="text",
            text=f"Error: {error}",
            error=error,
            display="system",
        )

    @classmethod
    def skip(cls, command_name: str) -> "CommandResult":
        """Create a skip result."""
        return cls(
            success=True,
            command_name=command_name,
            result_type="skip",
            display="skip",
        )


def create_command_context(
    workspace_root: str | Path,
    conversation: Any = None,
    cost_tracker: Any = None,
    history: Any = None,
    cwd: str | Path | None = None,
    config: dict[str, Any] | None = None,
    provider: Any = None,
    model: str | None = None,
) -> CommandContext:
    """
    Create a command context.

    Args:
        workspace_root: Root directory of the workspace
        conversation: Conversation object
        cost_tracker: Cost tracker object
        history: History log object
        cwd: Current working directory (defaults to workspace_root)
        config: Optional configuration dict
        provider: Optional provider instance for model calls
        model: Optional model name for model calls

    Returns:
        CommandContext instance
    """
    root = Path(workspace_root).expanduser().resolve()
    current = Path(cwd).expanduser().resolve() if cwd is not None else root

    return CommandContext(
        workspace_root=root,
        cwd=current,
        conversation=conversation,
        cost_tracker=cost_tracker,
        history=history,
        config=config or {},
        provider=provider,
        model=model,
    )
