"""Tests for the shared provider credential prompt."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.cli import prompt_provider_credentials


class TestPromptProviderCredentials(unittest.TestCase):
    def _run(self, key: str, model: str, confirm: bool = False):
        answers = iter(["openai", "https://api.openai.com/v1", model])
        with patch("src.cli.prompt_secret", return_value=key.strip()), \
                patch("src.cli.Prompt.ask", side_effect=lambda *a, **k: next(answers)), \
                patch("rich.prompt.Confirm.ask", return_value=confirm):
            return prompt_provider_credentials(Mock())

    def test_returns_stripped_key_and_known_model(self):
        self.assertEqual(
            self._run("  sk-test \n", "gpt-5.4"),
            ("openai", "sk-test", "https://api.openai.com/v1", "gpt-5.4"),
        )

    def test_unknown_model_falls_back_to_default_when_declined(self):
        _, _, _, model = self._run("sk-test", "y", confirm=False)
        self.assertEqual(model, "gpt-5.4")

    def test_unknown_model_kept_when_confirmed(self):
        _, _, _, model = self._run("sk-test", "my-custom-model", confirm=True)
        self.assertEqual(model, "my-custom-model")

    def test_empty_key_returns_none(self):
        self.assertIsNone(self._run("", "gpt-5.4"))


if __name__ == "__main__":
    unittest.main()
