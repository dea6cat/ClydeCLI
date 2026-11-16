"""
Comprehensive tests for the command system.

Tests cover:
- Command type system
- Argument substitution
- Command registry
- Command execution engine
- Built-in commands
- Skills integration
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from src.command_system import (
    CLEAR_COMMAND,
    COMPACT_COMMAND,
    CONTEXT_COMMAND,
    COST_COMMAND,
    EXIT_COMMAND,
    HELP_COMMAND,
    INIT_COMMAND,
    SKILLS_COMMAND,
    CommandContext,
    CommandRegistry,
    CommandResult,
    CommandType,
    LocalCommand,
    LocalCommandResult,
    PromptCommand,
    create_command_context,
    builtin_registry,
    run_command,
    get_command_name,
    get_command_registry,
    register_builtin_commands,
)
from src.agent.cost_tracker import CostTracker


@dataclass
class MockConversation:
    """Mock conversation for testing."""

    messages: list = None

    def __post_init__(self):
        if self.messages is None:
            self.messages = []

    def clear(self):
        self.messages.clear()



class TestCommandTypes(unittest.TestCase):
    """Tests for the command type system."""


class TestCommandRegistry(unittest.TestCase):
    """Tests for the command registry."""

    def setUp(self):
        """Set up test fixtures."""
        self.registry = CommandRegistry()

    def tearDown(self):
        """Clean up test fixtures."""
        get_command_registry().clear()

    def test_register_and_get_command(self):
        """Test registering and getting a command."""
        cmd = PromptCommand(
            name="test",
            description="Test command",
        )
        self.registry.register(cmd)

        retrieved = self.registry.get("test")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "test")

    def test_register_with_alias(self):
        """Test registering a command with aliases."""
        cmd = PromptCommand(
            name="test",
            description="Test command",
            aliases=["t", "testing"],
        )
        self.registry.register(cmd)

        self.assertIsNotNone(self.registry.get("t"))
        self.assertIsNotNone(self.registry.get("testing"))
        self.assertEqual(self.registry.get("t").name, "test")

    def test_list_commands(self):
        """Test listing commands."""
        cmd1 = PromptCommand(name="test1", description="Test 1")
        cmd2 = PromptCommand(name="test2", description="Test 2", is_hidden=True)
        self.registry.register(cmd1)
        self.registry.register(cmd2)

        commands = self.registry.list_commands()
        self.assertEqual(len(commands), 1)

    def test_find_commands(self):
        """Test finding commands by search."""
        cmd1 = PromptCommand(name="help", description="Show help")
        cmd2 = PromptCommand(name="hello", description="Say hello")
        self.registry.register(cmd1)
        self.registry.register(cmd2)

        matches = self.registry.find_commands("he")
        self.assertEqual(len(matches), 2)


class TestBuiltinCommands(unittest.TestCase):
    """Tests for built-in commands."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.tmpdir.name).resolve()
        self.conversation = MockConversation()
        self.cost_tracker = CostTracker()
        self.history = None

        self.context = create_command_context(
            workspace_root=self.workspace_root,
            conversation=self.conversation,
            cost_tracker=self.cost_tracker,
            history=self.history,
        )

    def tearDown(self):
        """Clean up test fixtures."""
        self.tmpdir.cleanup()

    def test_register_builtin_commands(self):
        """Test registering built-in commands."""
        registry = CommandRegistry()
        register_builtin_commands(registry)

        self.assertTrue(registry.has("help"))
        self.assertTrue(registry.has("clear"))
        self.assertTrue(registry.has("exit"))
        self.assertTrue(registry.has("skills"))
        self.assertTrue(registry.has("cost"))
        self.assertTrue(registry.has("context"))
        self.assertTrue(registry.has("compact"))
        self.assertTrue(registry.has("init"))

    def test_skills_command_with_project_root(self):
        """Test that /skills command can find project skills."""
        from src.skills.create import create_skill

        # Create a skill in the temp directory
        project_skills_dir = Path(self.tmpdir.name) / ".clyde" / "skills"
        project_skills_dir.mkdir(parents=True)

        create_skill(
            directory=project_skills_dir,
            name="test-project-skill",
            description="A test skill in project",
            body="Hello from project skill",
        )

        # Create command context with the project root
        context = create_command_context(
            workspace_root=self.tmpdir.name,
            conversation=self.conversation,
            cost_tracker=self.cost_tracker,
            history=self.history,
        )

        # Execute /skills command
        outcome = run_command(builtin_registry(), "skills", "", context)
        success, result, error = outcome.success, outcome.text, outcome.error

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertIn("test-project-skill", result)




class TestInitCommand(unittest.IsolatedAsyncioTestCase):
    """Tests for the /init command implementation."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.tmpdir.name).resolve()
        self.registry = CommandRegistry()
        register_builtin_commands(self.registry)

        self.conversation = MockConversation()
        self.cost_tracker = CostTracker()
        self.history = None

        self.context = create_command_context(
            workspace_root=self.workspace_root,
            conversation=self.conversation,
            cost_tracker=self.cost_tracker,
            history=self.history,
        )


    def tearDown(self):
        """Clean up test fixtures."""
        self.tmpdir.cleanup()

    def _get_init_command(self):
        """Get the /init command from the local registry."""
        return self.registry.get("init")


    def test_init_returns_its_prompt_for_the_model(self):
        result = run_command(builtin_registry(), "init", "", self.context)
        self.assertTrue(result.success)
        self.assertEqual((result.command_name, result.result_type), ("init", "prompt"))
        self.assertTrue(result.prompt_content[0]["text"])

