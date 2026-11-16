"""A slash command that fails says why, and a failed /compact leaves the conversation alone."""

from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from rich.console import Console

from src.command_system import builtin_registry
from src.repl.core import ClydeREPL


def _repl() -> ClydeREPL:
    repl = ClydeREPL.__new__(ClydeREPL)
    repl.console = Console(file=io.StringIO(), width=120)
    repl.command_registry = builtin_registry()
    repl.command_context = MagicMock()
    repl._built_in_commands = []
    return repl


class TestCommandErrors(unittest.TestCase):
    def test_a_failing_command_shows_its_error_not_unknown_command(self):
        repl = _repl()
        with patch("src.repl.core.run_command", side_effect=RuntimeError("tracker broke")):
            repl.handle_command("/cost")
        out = repl.console.file.getvalue()
        self.assertIn("tracker broke", out)
        self.assertNotIn("Unknown command", out)

    def test_a_failed_compact_keeps_the_conversation(self):
        repl = _repl()
        repl.session = MagicMock()
        repl.provider, repl.model = MagicMock(), "m"
        repl._refine_before_compaction = MagicMock()
        with patch.object(repl, "_run_command", return_value=MagicMock(success=False, error="/compact failed: down")):
            repl.handle_command("/compact")
        repl.session.conversation.clear.assert_not_called()
        self.assertIn("down", repl.console.file.getvalue())


if __name__ == "__main__":
    unittest.main()
