"""Interactive permission handling for tools.

This module provides the permission checking and interactive user consent flow
when tools require user permission before execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class PermissionBehavior(Enum):
    """Possible permission behaviors."""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class PermissionResult:
    """Result of a permission check.

    Attributes:
        behavior: The permission behavior - allow, deny, or ask.
        message: Optional message to display to the user.
        suggestion: Optional suggestion for what the user could allow.
        updated_input: Optional updated input if permission modifies the request.
    """
    behavior: PermissionBehavior
    message: Optional[str] = None
    suggestion: Optional[str] = None
    updated_input: Optional[dict[str, Any]] = None

    @staticmethod
    def allow(updated_input: Optional[dict[str, Any]] = None) -> "PermissionResult":
        """Return an allow result."""
        return PermissionResult(behavior=PermissionBehavior.ALLOW, updated_input=updated_input)

    @staticmethod
    def deny(message: str) -> "PermissionResult":
        """Return a deny result."""
        return PermissionResult(behavior=PermissionBehavior.DENY, message=message)

    @staticmethod
    def ask(message: str, suggestion: Optional[str] = None) -> "PermissionResult":
        """Return an ask result."""
        return PermissionResult(behavior=PermissionBehavior.ASK, message=message, suggestion=suggestion)

