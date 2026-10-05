"""Tests for REPL functionality."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import json
from rich.markdown import Markdown

from src.repl import ClydeREPL
from src.agent import Session, Conversation
from contextlib import contextmanager

from tests.fakes import FakeProvider, reply


@contextmanager
def _fake_provider_env(*responses, chunk_size: int = 0):
    """Patch the REPL's provider registry with a scripted `glm` provider (no network, and no
    saved keys from the real home directory)."""
    provider = FakeProvider(*responses, name="glm", models=("glm-4.5",), chunk_size=chunk_size)
    with patch("src.repl.core.build_registry", return_value={"glm": provider}), \
            patch("src.repl.core.keys.load_into_env"):
        yield provider


class TestREPL(unittest.TestCase):
    """Test REPL functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary config directory
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir) / ".clyde"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Create a test config
        test_config = {"model": "glm:glm-4.5"}

        config_file = self.config_dir / "config.json"
        with open(config_file, 'w') as f:
            json.dump(test_config, f)

    def test_repl_initialization(self):
        """Test REPL initialization."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session:
                mock_session.return_value = Mock()

                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")
                    self.assertIsNotNone(repl)
                    self.assertEqual(repl.provider_name, "glm")
                    self.assertFalse(repl.stream)
                    self.assertFalse(repl.multiline_mode)

    def test_repl_initialization_with_stream_enabled(self):
        """Test REPL can start with stream mode enabled."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session:
                mock_session.return_value = Mock()

                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5", stream=True)
                    self.assertTrue(repl.stream)

    def test_startup_header_contains_logo_and_metadata(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")

                    with patch('src.repl.core.Path.cwd', return_value=Path(self.temp_dir)):
                        # Capture stdout to verify fallback path output
                        import io
                        from contextlib import redirect_stdout

                        f = io.StringIO()
                        with redirect_stdout(f):
                            repl._print_startup_header()

                        rendered = f.getvalue()
                        self.assertIn("ClydeCLI", rendered)
                        self.assertIn("glm-4.5", rendered)
                        self.assertIn("glm", rendered)
                        # The path is shortened in the middle to fit one line; its folder name stays
                        self.assertIn(Path(self.temp_dir).name, rendered)

    def test_handle_command_exit(self):
        """Test /exit command."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")

                    with self.assertRaises(SystemExit):
                        repl.handle_command("/exit")

    def test_handle_command_clear(self):
        """Test /clear command."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session:
                mock_session_instance = Mock()
                mock_session_instance.conversation = Mock()
                mock_session.return_value = mock_session_instance

                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.handle_command("/clear")

                    mock_session_instance.conversation.clear.assert_called_once()

    def test_handle_command_multiline_toggle(self):
        """Test /multiline command."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")

                    # Initially False
                    self.assertFalse(repl.multiline_mode)

                    # Toggle to True
                    repl.handle_command("/multiline")
                    self.assertTrue(repl.multiline_mode)

                    # Toggle back to False
                    repl.handle_command("/multiline")
                    self.assertFalse(repl.multiline_mode)

    def test_handle_command_stream_toggle(self):
        """Test /stream command toggles stream mode safely."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")
                    self.assertFalse(repl.stream)

                    repl.handle_command("/stream on")
                    self.assertTrue(repl.stream)

                    repl.handle_command("/stream off")
                    self.assertFalse(repl.stream)

    def test_handle_command_render_last_renders_markdown(self):
        """Test /render-last re-renders the last assistant response."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session_factory:
                mock_session = Mock()
                mock_session.conversation = Conversation()
                mock_session.conversation.add_assistant_message("## Hello\n\n- item")
                mock_session_factory.return_value = mock_session

                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.console.print = Mock()
                    repl.handle_command("/render-last")

                    self.assertTrue(any(
                        args and isinstance(args[0], Markdown)
                        for args, _kwargs in repl.console.print.call_args_list
                    ))

    def test_handle_command_render_last_without_message(self):
        """Test /render-last handles empty history gracefully."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session_factory:
                mock_session = Mock()
                mock_session.conversation = Conversation()
                mock_session_factory.return_value = mock_session

                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.console.print = Mock()
                    repl.handle_command("/render-last")

                    self.assertTrue(any(
                        args and "No assistant response available to render." in str(args[0])
                        for args, _kwargs in repl.console.print.call_args_list
                    ))

    def test_chat_uses_true_api_stream_for_simple_prompt(self):
        """Simple prompts stream a tool-free reply directly when stream mode is enabled."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session_factory:
                mock_session = Mock()
                mock_session.conversation = Conversation()
                mock_session_factory.return_value = mock_session

                with _fake_provider_env(reply("Hello"), chunk_size=3) as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5", stream=True)
                    repl.console.print = Mock()

                    with patch('src.repl.core.run_agent_loop') as mock_agent_loop:
                        repl.chat("who are you")

                    self.assertEqual(len(mock_provider.requests), 1)
                    self.assertEqual(mock_provider.requests[0]["tools"], ())
                    mock_agent_loop.assert_not_called()
                    self.assertFalse(any(
                        args and isinstance(args[0], Markdown)
                        for args, _kwargs in repl.console.print.call_args_list
                    ))
                    self.assertEqual(len(mock_session.conversation.messages), 2)
                    self.assertEqual(mock_session.conversation.messages[1].role, "assistant")
                    self.assertEqual(mock_session.conversation.messages[1].content, "Hello")

    def test_chat_stream_falls_back_to_agent_loop_for_code_task(self):
        """Code-like prompts keep the existing agent loop path for safety."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session_factory:
                mock_session = Mock()
                mock_session.conversation = Conversation()
                mock_session_factory.return_value = mock_session

                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5", stream=True)
                    repl.console.print = Mock()

                    def run_agent_loop_side_effect(*args, **kwargs):
                        kwargs["on_text_chunk"]("**done**")
                        return Mock(response_text="**done**", usage=None, num_turns=1)

                    with patch('src.repl.core.run_agent_loop') as mock_agent_loop:
                        mock_agent_loop.side_effect = run_agent_loop_side_effect
                        repl.chat("Please read README.md and summarize it")

                    self.assertEqual(mock_provider.requests, [])
                    mock_agent_loop.assert_called_once()
                    self.assertEqual(mock_agent_loop.call_args.kwargs["model"], "glm-4.5")
                    self.assertFalse(any(
                        args and isinstance(args[0], Markdown)
                        for args, _kwargs in repl.console.print.call_args_list
                    ))

    def test_chat_stream_falls_back_to_agent_loop_on_stream_init_failure(self):
        """If real streaming fails before any chunk, fall back to the stable agent loop."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session_factory:
                mock_session = Mock()
                mock_session.conversation = Conversation()
                mock_session_factory.return_value = mock_session

                with _fake_provider_env(RuntimeError("stream unavailable")) as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5", stream=True)
                    repl.console.print = Mock()

                    with patch('src.repl.core.run_agent_loop') as mock_agent_loop:
                        mock_agent_loop.return_value = Mock(response_text="fallback", usage=None, num_turns=1)
                        repl.chat("hi there")

                    self.assertEqual(len(mock_provider.requests), 1)
                    mock_agent_loop.assert_called_once()

    def test_direct_stream_auth_error_is_not_retried_through_agent_loop(self):
        """A 401 during direct streaming surfaces (offering re-login) instead of a silent retry."""
        from src.providers.base import ProviderError
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session_factory:
                mock_session_factory.return_value = Mock(conversation=Conversation())
                auth = ProviderError("glm", "HTTP 401 — authentication failed", status=401)
                with _fake_provider_env(auth):
                    repl = ClydeREPL(model="glm:glm-4.5", stream=True)
                    repl.console.print = Mock()
                    with patch('src.repl.core.run_agent_loop') as mock_agent_loop, \
                            patch('rich.prompt.Prompt.ask', return_value="n"):
                        repl.chat("hi there")
                    mock_agent_loop.assert_not_called()

    def _relogin_repl(self, *responses):
        from src.providers.base import ProviderError
        conversation = Conversation()
        ctx = _fake_provider_env(ProviderError("glm", "HTTP 401 — authentication failed", status=401), *responses)
        return conversation, ctx

    def test_a_rejected_key_can_be_replaced_and_the_message_retried(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"), \
                patch('src.repl.core.Session.create') as mock_session_factory:
            conversation, ctx = self._relogin_repl(reply("hello again"))
            mock_session_factory.return_value = Mock(conversation=conversation)
            with ctx as provider:
                repl = ClydeREPL(model="glm:glm-4.5")
                repl.console.print = Mock()
                with patch('src.repl.core.pick', return_value="k") as ask, \
                        patch('src.cli.prompt_secret', return_value="new-key"), \
                        patch('src.repl.core.keys.connect') as connect, \
                        patch('src.repl.core.build_registry', return_value={"glm": provider}):
                    repl.chat("hi there")
                self.assertIn("New glm key", [c.label for c in ask.call_args.args[2]])
                connect.assert_called_once_with("glm", "new-key")
                self.assertEqual(len(provider.requests), 2)                       # the same message, sent again
                users = [m for m in conversation.messages if m.role == "user"]
                self.assertEqual(len(users), 1)                                  # not duplicated
                self.assertEqual(conversation.messages[-1].content, "hello again")

    def test_declining_leaves_the_message_unanswered_without_retrying(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"), \
                patch('src.repl.core.Session.create') as mock_session_factory:
            conversation, ctx = self._relogin_repl()
            mock_session_factory.return_value = Mock(conversation=conversation)
            with ctx as provider:
                repl = ClydeREPL(model="glm:glm-4.5")
                repl.console.print = Mock()
                with patch('src.repl.core.pick', return_value="n"), patch('src.cli.prompt_secret') as secret:
                    repl.chat("hi there")
                secret.assert_not_called()
                self.assertEqual(len(provider.requests), 1)

    def test_a_second_rejection_does_not_loop(self):
        from src.providers.base import ProviderError
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"), \
                patch('src.repl.core.Session.create') as mock_session_factory:
            conversation, ctx = self._relogin_repl(ProviderError("glm", "HTTP 401 — still wrong", status=401))
            mock_session_factory.return_value = Mock(conversation=conversation)
            with ctx as provider:
                repl = ClydeREPL(model="glm:glm-4.5")
                repl.console.print = Mock()
                with patch('src.repl.core.pick', return_value="k") as ask, \
                        patch('src.cli.prompt_secret', return_value="new-key"), patch('src.repl.core.keys.connect'), \
                        patch('src.repl.core.build_registry', return_value={"glm": provider}):
                    repl.chat("hi there")
                self.assertEqual(len(provider.requests), 2)    # one retry only
                self.assertEqual(ask.call_count, 2)            # it asks again, but doesn't resend by itself

    def test_provider_error_prints_one_line_without_traceback(self):
        from src.providers.base import ProviderError
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session_factory:
                mock_session_factory.return_value = Mock(conversation=Conversation())
                with _fake_provider_env():
                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.console.print = Mock()
                    with patch('src.repl.core.run_agent_loop',
                               side_effect=ProviderError("glm", "HTTP 429 — rate limited: slow down")), \
                            patch('traceback.print_exc') as print_exc:
                        repl.chat("Please fix the bug in src/app.py")
                    print_exc.assert_not_called()
                    self.assertTrue(any("rate limited" in str(a[0]) for a, _k in repl.console.print.call_args_list if a))

    def test_model_command_shows_and_switches(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env():
                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.console.print = Mock()
                    with patch('src.repl.core.pick', return_value=None) as pick:
                        repl.handle_command("/model")
                    self.assertEqual(pick.call_args.kwargs["current"], "glm:glm-4.5")   # the picker opens on the current model
                    with patch('src.repl.core.set_default_model') as save:
                        with patch('src.repl.core.pick', return_value="glm:glm-4.5-air"):
                            repl.handle_command("/model")
                    save.assert_called_once_with("glm:glm-4.5-air")
                    self.assertEqual(repl.model, "glm-4.5-air")
                    repl.handle_command("/model glm:glm-4.5")

                    with patch('src.repl.core.set_default_model') as save:
                        repl.handle_command("/model glm:glm-4.5-air")
                    save.assert_called_once_with("glm:glm-4.5-air")
                    self.assertEqual(repl.model, "glm-4.5-air")

    def test_model_command_rejects_unknown_provider(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env():
                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.console.print = Mock()
                    with patch('src.repl.core.set_default_model') as save:
                        repl.handle_command("/model nope-model")
                    save.assert_not_called()
                    self.assertEqual(repl.model, "glm-4.5")

    def test_think_command_sets_reasoning(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env():
                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.console.print = Mock()
                    repl.handle_command("/think high")
                    self.assertEqual(repl.reasoning, "high")
                    repl.handle_command("/think default")
                    self.assertIsNone(repl.reasoning)
                    repl.handle_command("/think bogus")
                    self.assertIsNone(repl.reasoning)

    def test_no_saved_model_picks_a_connected_provider(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env(), patch('src.repl.core.get_default_model', return_value=None):
                    repl = ClydeREPL()
                    self.assertEqual((repl.provider_name, repl.model), ("glm", "glm-4.5"))

    def test_unavailable_saved_model_falls_back_instead_of_exiting(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env(), patch('src.repl.core.get_default_model', return_value="openai:gpt-5.4"):
                    repl = ClydeREPL()
                    self.assertEqual(repl.provider_name, "glm")

    def test_explicit_model_must_resolve(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create'):
                with _fake_provider_env():
                    with self.assertRaises(SystemExit):
                        ClydeREPL(model="openai:gpt-5.4")

    def test_unconfigured_model_exits_with_hint(self):
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.build_registry', return_value={}), \
                    patch('src.repl.core.keys.load_into_env'), \
                    patch('src.repl.core.get_default_model', return_value=None):
                with self.assertRaises(SystemExit):
                    ClydeREPL()

    def test_handle_command_slash_shows_commands_and_skills(self):
        skills_dir = Path(self.temp_dir) / "skills"
        (skills_dir / "hello").mkdir(parents=True, exist_ok=True)
        (skills_dir / "hello" / "SKILL.md").write_text(
            "---\n"
            "description: say hello\n"
            "---\n"
            "Hello\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"CLYDE_SKILLS_DIR": str(skills_dir)}):
            with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
                with patch('src.repl.core.Session.create'):
                    with _fake_provider_env() as mock_provider:

                        repl = ClydeREPL(model="glm:glm-4.5")
                        repl.console.print = Mock()
                        repl.handle_command("/")
                        rendered = "\n".join(
                            str(args[0]) for args, _kwargs in repl.console.print.call_args_list if args
                        )
                        self.assertIn("Available commands and skills", rendered)
                        self.assertIn("/hello", rendered)

    def test_handle_command_slash_prefix_filters(self):
        skills_dir = Path(self.temp_dir) / "skills"
        (skills_dir / "hello").mkdir(parents=True, exist_ok=True)
        (skills_dir / "hello" / "SKILL.md").write_text(
            "---\n"
            "description: say hello\n"
            "---\n"
            "Hello\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"CLYDE_SKILLS_DIR": str(skills_dir)}):
            with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
                with patch('src.repl.core.Session.create'):
                    with _fake_provider_env() as mock_provider:

                        repl = ClydeREPL(model="glm:glm-4.5")
                        repl.console.print = Mock()
                        repl.handle_command("/he")
                        rendered = "\n".join(
                            str(args[0]) for args, _kwargs in repl.console.print.call_args_list if args
                        )
                        self.assertIn("/help", rendered)
                        self.assertIn("/hello", rendered)

    def test_handle_command_skill_invokes_skill_tool_and_chats_with_prompt(self):
        skills_dir = Path(self.temp_dir) / "skills"
        (skills_dir / "hello").mkdir(parents=True, exist_ok=True)
        (skills_dir / "hello" / "SKILL.md").write_text(
            "---\n"
            "description: say hello\n"
            "arguments: [name]\n"
            "---\n"
            "Hello $name\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"CLYDE_SKILLS_DIR": str(skills_dir)}):
            with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
                with patch('src.repl.core.Session.create'):
                    with _fake_provider_env() as mock_provider:

                        repl = ClydeREPL(model="glm:glm-4.5")
                        repl.chat = Mock()
                        repl.handle_command("/hello bob")
                        args, _kwargs = repl.chat.call_args
                        self.assertIn("Hello bob", args[0])

    def test_save_session(self):
        """Test session saving."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session:
                mock_session_instance = Mock()
                mock_session_instance.session_id = "test_session_123"
                mock_session.return_value = mock_session_instance

                with _fake_provider_env() as mock_provider:

                    repl = ClydeREPL(model="glm:glm-4.5")
                    repl.save_session()

                    mock_session_instance.save.assert_called_once()

    def test_load_session(self):
        """Test session loading."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session:
                mock_session_instance = Mock()
                mock_session_instance.session_id = "current_session"
                mock_session.return_value = mock_session_instance

                with _fake_provider_env() as mock_provider:

                    with patch('src.repl.core.Session.load') as mock_load:
                        loaded_session = Mock()
                        loaded_session.session_id = "loaded_session_123"
                        loaded_session.provider = "glm"
                        loaded_session.model = "glm-4.5"
                        loaded_session.conversation = Mock()
                        loaded_session.conversation.messages = []
                        mock_load.return_value = loaded_session

                        repl = ClydeREPL(model="glm:glm-4.5")
                        repl.load_session("loaded_session_123")

                        self.assertEqual(repl.session.session_id, "loaded_session_123")

    def test_load_nonexistent_session(self):
        """Test loading a session that doesn't exist."""
        with patch('src.config.get_config_path', return_value=self.config_dir / "config.json"):
            with patch('src.repl.core.Session.create') as mock_session:
                mock_session_instance = Mock()
                mock_session_instance.session_id = "current_session"
                mock_session.return_value = mock_session_instance

                with _fake_provider_env() as mock_provider:

                    with patch('src.repl.core.Session.load', return_value=None):
                        repl = ClydeREPL(model="glm:glm-4.5")
                        original_session = repl.session

                        repl.load_session("nonexistent")

                        # Session should not change
                        self.assertEqual(repl.session, original_session)


class TestConversation(unittest.TestCase):
    """Test conversation management."""

    def test_add_message(self):
        """Test adding messages to conversation."""
        conv = Conversation()
        conv.add_message("user", "Hello")
        conv.add_message("assistant", "Hi there!")

        self.assertEqual(len(conv.messages), 2)
        self.assertEqual(conv.messages[0].role, "user")
        self.assertEqual(conv.messages[0].content, "Hello")
        self.assertEqual(conv.messages[1].role, "assistant")

    def test_max_history(self):
        """Test max history limit."""
        conv = Conversation(max_history=3)

        # Add 5 messages
        for i in range(5):
            conv.add_message("user", f"Message {i}")

        # Should only keep last 3
        self.assertEqual(len(conv.messages), 3)
        self.assertEqual(conv.messages[0].content, "Message 2")
        self.assertEqual(conv.messages[2].content, "Message 4")

    def test_get_messages(self):
        """Test getting messages in API format."""
        conv = Conversation()
        conv.add_message("user", "Test")
        conv.add_message("assistant", "Response")

        messages = conv.get_messages()

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0], {"role": "user", "content": "Test"})
        self.assertEqual(messages[1], {"role": "assistant", "content": "Response"})

    def test_clear(self):
        """Test clearing conversation."""
        conv = Conversation()
        conv.add_message("user", "Test")
        conv.clear()

        self.assertEqual(len(conv.messages), 0)

    def test_serialization(self):
        """Test conversation serialization."""
        conv = Conversation()
        conv.add_message("user", "Test")
        conv.add_message("assistant", "Response")

        # Serialize
        data = conv.to_dict()
        self.assertIn("messages", data)
        self.assertEqual(len(data["messages"]), 2)

        # Deserialize
        conv2 = Conversation.from_dict(data)
        self.assertEqual(len(conv2.messages), 2)
        self.assertEqual(conv2.messages[0].content, "Test")


class TestSession(unittest.TestCase):
    """Test session management."""

    def test_create_session(self):
        """Test session creation."""
        session = Session.create("glm", "glm-4.5")

        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.provider, "glm")
        self.assertEqual(session.model, "glm-4.5")
        self.assertEqual(len(session.conversation.messages), 0)

    def test_session_save_load(self):
        """Test session save and load."""
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / ".clyde" / "sessions"

            with patch('src.agent.session.Path.home', return_value=Path(temp_dir)):
                # Create and save
                session = Session.create("glm", "glm-4.5")
                session.conversation.add_message("user", "Test message")
                session.save()

                # Load
                loaded = Session.load(session.session_id)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.session_id, session.session_id)
                self.assertEqual(len(loaded.conversation.messages), 1)
                self.assertEqual(loaded.conversation.messages[0].content, "Test message")


class TestPermissionPrompt(unittest.TestCase):
    """The REPL's permission prompt, driven without starting a full REPL."""

    def setUp(self):
        from src.tool_system.context import ToolContext
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.repl = object.__new__(ClydeREPL)
        self.repl.console = Mock()
        self.repl._current_status = None
        self.repl.tool_context = ToolContext(workspace_root=self.home)

    def _answer(self, choice, suggestion="Bash(npm test:*)"):
        with patch("builtins.input", return_value=choice), patch("pathlib.Path.home", return_value=self.home):
            return self.repl._handle_permission_request("Bash", "Run shell command: npm test", suggestion)

    def test_dont_ask_again_saves_and_applies_rule(self):
        self.assertEqual(self._answer("a"), (True, False))
        self.assertIn("Bash(npm test:*)", self.repl.tool_context.permission_rules["allow"])
        saved = json.loads((self.home / ".clyde" / "settings.json").read_text())
        self.assertEqual(saved["permissions"]["allow"], ["Bash(npm test:*)"])

    def test_numbered_choices_follow_menu(self):
        self.assertEqual(self._answer("1"), (True, False))
        self.assertEqual(self._answer("3"), (False, False))
        self.assertEqual(self._answer("2", suggestion=None), (False, False))
        self.assertEqual(self.repl.tool_context.permission_rules["allow"], [])


if __name__ == '__main__':
    unittest.main()


class TestSlashCompleter(unittest.TestCase):
    def _names(self, text):
        from prompt_toolkit.document import Document
        from src.repl.core import SlashCompleter

        completer = SlashCompleter([("/help", "Show help"), ("/exit", "Exit"), ("/check", "Run checks")])
        return [(c.text, c.display_meta_text) for c in completer.get_completions(Document(text), None)]

    def test_plain_text_gets_no_menu(self):
        self.assertEqual(self._names("so hi how you"), [])
        self.assertEqual(self._names("/help me"), [])

    def test_slash_prefix_first_then_substring(self):
        self.assertEqual(self._names("/he"), [("/help", "Show help"), ("/check", "Run checks")])
        self.assertEqual([n for n, _ in self._names("/")], ["/help", "/exit", "/check"])

    def test_descriptions_come_from_help_text(self):
        from src.repl.core import _help_descriptions

        desc = _help_descriptions()
        self.assertEqual(desc["/help"], "Show this help message")
        self.assertEqual(desc["/quit"], desc["/exit"])


class TestTimesAndClear(unittest.TestCase):
    def test_clock_and_duration_formats(self):
        from datetime import datetime
        from src.repl.core import _clock, _duration

        self.assertEqual(_clock(datetime(2026, 1, 1, 17, 47)), "5:47 PM")
        self.assertEqual(_clock(datetime(2026, 1, 1, 0, 5)), "12:05 AM")
        self.assertEqual([_duration(x) for x in (0.42, 12, 165, 3725)], ["0.4s", "12s", "2m 45s", "1h 2m"])

    def test_clear_wipes_the_conversation_and_the_screen(self):
        import io
        from unittest.mock import MagicMock
        from rich.console import Console
        from src.repl.core import ClydeREPL

        repl = ClydeREPL.__new__(ClydeREPL)
        repl.console = Console(file=io.StringIO(), width=100)
        repl.console.clear = MagicMock()
        repl._print_startup_header = MagicMock()
        repl._try_execute_new_command = MagicMock(return_value=(False, None))
        repl._built_in_commands = ["/clear"]
        repl.session = MagicMock()
        repl.handle_command("/clear")
        repl.session.conversation.clear.assert_called_once()
        repl.console.clear.assert_called_once()
        repl._print_startup_header.assert_called_once()
        self.assertIn("Conversation cleared.", repl.console.file.getvalue())
