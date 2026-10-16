"""The Data tool without DuckDB: the error says what to install, with which Python."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.tools.data import DUCKDB_REQUIREMENT, DataTool, _error_text


class TestMissingDuckdb(unittest.TestCase):
    def test_a_missing_duckdb_says_what_to_install_and_with_which_python(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"duckdb": None}):
            ws = Path(tmp).resolve()
            (ws / "s.csv").write_text("a\n1\n")
            result = DataTool().run({"action": "profile", "path": str(ws / "s.csv")}, ToolContext(workspace_root=ws))
        error = result.output["error"]
        self.assertTrue(result.is_error)
        self.assertIn(f"{sys.executable} -m pip install '{DUCKDB_REQUIREMENT}'", error)
        self.assertNotIn("ModuleNotFoundError", error)

    def test_any_other_error_keeps_its_type_name(self):
        self.assertEqual(_error_text(ValueError("bad")), "ValueError: bad")
        self.assertEqual(_error_text(ModuleNotFoundError("x", name="other")), "ModuleNotFoundError: x")


if __name__ == "__main__":
    unittest.main()
