"""Where nobody can answer at a terminal (-p, an editor over ACP, Bonnie), Clyde never asks to install oMLX."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console

from tests.fakes import FakeProvider


class TestInstallPrompt(unittest.TestCase):
    def test_a_headless_session_leaves_the_install_question_unset(self):
        from src.repl.core import ClydeREPL
        omlx = SimpleNamespace(name="omlx", confirm_install=None, is_available=lambda: False, list_models=lambda: [])
        glm = FakeProvider(name="glm", models=("glm-4.5",))
        with tempfile.TemporaryDirectory() as cwd, patch("src.repl.core.Path.cwd", return_value=Path(cwd)), \
                patch("src.repl.core.build_registry", return_value={"glm": glm, "omlx": omlx}), \
                patch("src.providers.omlx.migrate_lmstudio_refs", return_value=[]):
            ClydeREPL(model="glm:glm-4.5", console=Console(file=io.StringIO()), headless=True)
        self.assertIsNone(omlx.confirm_install)


if __name__ == "__main__":
    unittest.main()
