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

    def test_ollama_cloud_is_always_offered(self):
        self.assertEqual(_login_choices({"openai": None, "ollama": None})[-1], "ollama-cloud")


if __name__ == "__main__":
    unittest.main()
