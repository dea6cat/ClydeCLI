"""A command that exits non-zero shows its exit code and last line, not a bare 'Error'."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from tests.fakes import FakeProvider, reply


class TestToolErrorLine(unittest.TestCase):
    def test_failed_command_shows_exit_code_and_output(self):
        from src.repl.core import ClydeREPL

        ws, home = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(ws)
        provider = FakeProvider(reply(tool_calls=[("Bash", {"command": "echo 'FAILED (failures=1)' >&2; exit 3"})]),
                                reply("done"), name="glm", models=("glm-4.5",))
        out = io.StringIO()
        with patch.object(Path, "home", return_value=home), patch("src.repl.core.build_registry", return_value={"glm": provider}), \
                patch("src.repl.core.keys.load_into_env"), patch.dict(os.environ, {"CLYDE_TRACE": "off"}):
            repl = ClydeREPL(model="glm:glm-4.5", console=Console(file=out, width=120))
            repl._set_mode("all_in")
            repl.chat("run the test command")
        self.assertIn("exit=3 · FAILED (failures=1)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
