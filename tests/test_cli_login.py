"""Tests for the interactive login flow (provider -> key -> live model list -> default)."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src.cli import _login_choices, run_login_flow
from src.config import get_default_model
from src.providers import keys
from tests.fakes import FakeProvider

_KEY_VARS = {env: "" for env in keys.PROVIDER_KEY_ENV.values()}


class TestRunLoginFlow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patches = [patch.object(Path, "home", return_value=Path(self._tmp.name)),
                         patch.dict(os.environ, _KEY_VARS)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def _run(self, provider_choice, key, model_answer, *, models=("gpt-5.4", "gpt-5.4-mini"), confirm=False,
             name="openai"):
        provider = FakeProvider(name=name, models=models)
        registry = {name: provider, "ollama": FakeProvider(name="ollama")}
        answers = iter([provider_choice, model_answer])
        with patch("src.cli.prompt_secret", return_value=key), \
                patch("src.cli.pick", side_effect=lambda *a, **k: next(answers)), \
                patch("src.cli.Prompt.ask", side_effect=lambda *a, **k: next(answers)), \
                patch("rich.prompt.Confirm.ask", return_value=confirm), \
                patch("src.providers.build_registry", return_value=registry):
            return run_login_flow(Console(file=io.StringIO()), registry)

    def test_saves_key_and_default_model(self):
        ref = self._run("openai", "sk-test", "gpt-5.4")
        self.assertEqual(ref, "openai:gpt-5.4")
        self.assertEqual(get_default_model(), "openai:gpt-5.4")
        self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-test")
        self.assertIn("openai", keys.saved_providers())

    def test_unknown_model_falls_back_to_suggested_when_declined(self):
        self.assertEqual(self._run("openai", "sk-test", "y", confirm=False), "openai:gpt-5.4")

    def test_unknown_model_kept_when_confirmed(self):
        self.assertEqual(self._run("openai", "sk-test", "my-model", confirm=True), "openai:my-model")

    def test_empty_key_aborts_without_saving(self):
        self.assertIsNone(self._run("openai", "", "gpt-5.4"))
        self.assertEqual(keys.saved_providers(), set())
        self.assertIsNone(get_default_model())

    def test_unlisted_models_still_accept_typed_id(self):
        self.assertEqual(self._run("openai", "sk-test", "gpt-5.4", models=()), "openai:gpt-5.4")

    def test_ollama_cloud_and_custom_are_always_offered(self):
        self.assertEqual(_login_choices({"openai": None, "ollama": None})[-2:], ["ollama-cloud", "custom"])

    def test_a_given_provider_skips_the_question(self):
        provider = FakeProvider(name="openai", models=("gpt-5.4",))
        with patch("src.cli.prompt_secret", return_value="sk-test"), \
                patch("src.cli.pick", side_effect=["gpt-5.4"]) as ask, \
                patch("src.providers.build_registry", return_value={"openai": provider}):
            ref = run_login_flow(Console(file=io.StringIO()), {"openai": provider}, provider="openai")
        self.assertEqual((ref, ask.call_count), ("openai:gpt-5.4", 1))       # only the model was asked


class TestCustomProvider(unittest.TestCase):
    """`custom` adds an OpenAI-compatible service: saved in settings.json, its key like any other."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._patches = [patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, _KEY_VARS),
                         patch.dict(keys.PROVIDER_KEY_ENV)]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_login_adds_it_saves_its_key_and_the_registry_builds_it(self):
        from src.providers import build_registry

        answers = iter(["custom", "together", "openai", "https://api.together.xyz/v1/", "meta-llama/Llama-4"])
        with patch("src.cli.prompt_secret", return_value="tg-key"), \
                patch("src.cli.pick", side_effect=lambda *a, **k: next(answers)), \
                patch("src.cli.Prompt.ask", side_effect=lambda *a, **k: next(answers)), \
                patch("src.providers.openai_compat.OpenAICompatProvider.list_models", return_value=["meta-llama/Llama-4"]):
            ref = run_login_flow(Console(file=io.StringIO()), {})
        self.assertEqual(ref, "together:meta-llama/Llama-4")
        self.assertEqual(keys.custom_providers(), {"together": "https://api.together.xyz/v1"})
        self.assertEqual(os.environ["CLYDE_TOGETHER_API_KEY"], "tg-key")
        provider = build_registry()["together"]
        self.assertEqual((provider.base_url, provider.api_key), ("https://api.together.xyz/v1", "tg-key"))

        os.environ.pop("CLYDE_TOGETHER_API_KEY")      # a new run: the saved key loads like a built-in one
        keys.load_into_env()
        self.assertEqual(os.environ["CLYDE_TOGETHER_API_KEY"], "tg-key")

    def test_logout_removes_a_custom_provider_and_its_key(self):
        from src.cli import handle_logout

        self.assertIsNone(keys.add_custom("mine", "https://x/v1"))
        keys.connect("mine", "k")
        keys.PROVIDER_KEY_ENV.pop("mine")             # a fresh process hasn't registered it yet
        keys.add_custom("other", "https://y/v1")
        with patch("src.cli.Console"):
            self.assertEqual(handle_logout("mine"), 0)
        self.assertNotIn("mine", keys.saved_providers())
        self.assertEqual(keys.custom_providers(), {"other": "https://y/v1"})   # gone from settings.json, the rest kept
        self.assertNotIn("mine", keys.PROVIDER_KEY_ENV)
        keys.remove_custom("other")
        self.assertNotIn("providers", (self.home / ".clyde" / "settings.json").read_text())   # no empty leftover

    def test_a_keyless_server_still_connects(self):
        answers = iter(["custom", "vllm", "openai", "http://localhost:8000/v1", "qwen3"])
        with patch("src.cli.prompt_secret", return_value=""), \
                patch("src.cli.pick", side_effect=lambda *a, **k: next(answers)), \
                patch("src.cli.Prompt.ask", side_effect=lambda *a, **k: next(answers)), \
                patch("src.providers.openai_compat.OpenAICompatProvider.list_models", return_value=["qwen3"]):
            self.assertEqual(run_login_flow(Console(file=io.StringIO()), {}), "vllm:qwen3")

    def test_an_anthropic_compatible_provider_gets_the_anthropic_adapter(self):
        from src.providers import build_registry
        from src.providers.anthropic import AnthropicProvider

        self.assertIsNone(keys.add_custom("work", "https://api.anthropic.com/", "anthropic"))
        provider = build_registry()["work"]
        self.assertIsInstance(provider, AnthropicProvider)
        self.assertEqual((provider.base_url, provider.key_env), ("https://api.anthropic.com", "CLYDE_WORK_API_KEY"))
        self.assertIn("protocol", keys.add_custom("odd", "https://x/v1", "grpc"))

    def test_bad_names_and_urls_are_refused_and_built_ins_cant_be_replaced(self):
        self.assertIn("built-in", keys.add_custom("openai", "https://x/v1"))
        self.assertIn("lowercase", keys.add_custom("Bad Name", "https://x/v1"))
        self.assertIn("http", keys.add_custom("mine", "ftp://x"))
        settings = self.home / ".clyde" / "settings.json"
        settings.parent.mkdir()
        settings.write_text('{"permissions": {"allow": ["Read"]}, "providers": {"openai": {"base_url": "https://evil"}}}')
        self.assertIsNone(keys.add_custom("mine", "https://x/v1"))
        self.assertEqual(keys.custom_providers(), {"mine": "https://x/v1"})           # a hand-added "openai" is ignored
        self.assertIn("permissions", settings.read_text())                            # other settings kept


class TestReplLogin(unittest.TestCase):
    def test_login_command_passes_the_provider(self):
        from src.repl.core import ClydeREPL

        repl = ClydeREPL.__new__(ClydeREPL)
        repl._built_in_commands = ["/login"]
        for line, expected in (("/login nvidia", "nvidia"), ("/login", None)):
            with patch.object(ClydeREPL, "_handle_relogin") as relogin:
                repl.handle_command(line)
            relogin.assert_called_once_with(expected, title="Connect a provider")


if __name__ == "__main__":
    unittest.main()
