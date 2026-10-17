"""The question Clyde asks before it downloads and runs LM Studio's installer: it names the command, and only a yes proceeds."""
from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from src.repl.core import ClydeREPL


class TestInstallQuestion(unittest.TestCase):
    def _ask(self, answer: str):
        printed: list[str] = []
        repl = types.SimpleNamespace(console=types.SimpleNamespace(print=lambda text, *a, **k: printed.append(str(text))))
        with patch("builtins.input", return_value=answer):
            return ClydeREPL._confirm_install_llmster(repl), printed

    def test_it_names_what_it_would_run_and_that_shell_files_are_left_alone(self):
        _, printed = self._ask("n")
        text = " ".join(printed)
        self.assertIn("curl -fsSL https://lmstudio.ai/install.sh | sh", text)
        self.assertIn("shell files are left alone", text)

    def test_only_a_yes_proceeds_and_enter_alone_is_a_no(self):
        for answer, expected in (("y", True), ("Y", True), ("yes", True), (" yes ", True), ("", False), ("n", False), ("no", False), ("sure", False)):
            self.assertEqual(self._ask(answer)[0], expected, repr(answer))


if __name__ == "__main__":
    unittest.main()
